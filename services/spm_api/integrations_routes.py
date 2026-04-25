"""
SPM API — Integrations module routes.

Kept in a separate module (rather than appended to app.py) because the
Integrations surface area (8 tables, 15+ endpoints) is large enough that
co-locating it with model-registry code would bloat the single-file pattern.
The top-level FastAPI app imports `router` and includes it verbatim.

Endpoint summary:

    GET    /integrations                          — list (optional ?category, ?status, ?q)
    GET    /integrations/metrics                  — connected / healthy / needs_attention / failed_syncs_24h
    POST   /integrations                          — create
    GET    /integrations/{id}                     — full detail (all nested tabs)
    PATCH  /integrations/{id}                     — update top-level fields
    DELETE /integrations/{id}                     — hard delete

    GET    /integrations/{id}/overview            — overview tab
    GET    /integrations/{id}/connection          — connection tab
    GET    /integrations/{id}/auth                — auth tab
    GET    /integrations/{id}/coverage            — coverage tab
    GET    /integrations/{id}/activity            — activity tab
    GET    /integrations/{id}/workflows           — workflows tab
    GET    /integrations/{id}/logs                — logs tab

    POST   /integrations/{id}/configure           — write api_key / model / …
    POST   /integrations/{id}/test                — health check
    POST   /integrations/{id}/disable             — toggle off
    POST   /integrations/{id}/enable              — toggle on
    POST   /integrations/{id}/rotate-credentials  — issue new secret
    POST   /integrations/{id}/sync                — trigger manual sync
    GET    /integrations/{id}/docs                — returns vendor docs URL
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from spm.db.models import (
    Integration,
    IntegrationActivity,
    IntegrationActivityResult,
    IntegrationAuth,
    IntegrationAuthMethod,
    IntegrationConnection,
    IntegrationCoverage,
    IntegrationCredential,
    IntegrationLog,
    IntegrationStatus,
    IntegrationWorkflow,
)
from spm.db.session import get_db

# Live-credential cache invalidation. Imported at module scope so a missing
# platform_shared package fails loud at boot rather than silently swallowing
# rotation events at runtime.
from platform_shared.credentials import invalidate_credential_cache

log = logging.getLogger("spm-api.integrations")

router = APIRouter(prefix="/integrations", tags=["integrations"])


# ─── Secret at-rest encoding ────────────────────────────────────────────────────
# Placeholder for KMS/Vault.  Today we base64-encode so the raw key isn't
# readable as-is in psql, but any real deployment must swap in envelope
# encryption keyed to SPM_KMS_KEY / spm-api's workload identity.

def _encode_secret(raw: str) -> str:
    if not raw:
        return ""
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_secret(enc: Optional[str]) -> str:
    if not enc:
        return ""
    try:
        return base64.b64decode(enc.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def _mask(raw: str) -> str:
    if not raw:
        return ""
    if len(raw) <= 8:
        return "****"
    return f"{raw[:4]}…{raw[-4:]}"


# ─── Vendor liveness probes ─────────────────────────────────────────────────────
# Each probe returns (ok, message, latency_ms).  They are deliberately
# short-timeout, read-only calls against a stable listing endpoint — no
# completions are issued, so the user is not charged for a Test click.
# Probes never raise; they catch httpx/network errors and convert them
# into an (ok=False, message=…) tuple so the route can always respond.

_PROBE_TIMEOUT_S = 6.0


async def _probe_anthropic(api_key: str, base_url: Optional[str]) -> Tuple[bool, str, Optional[int]]:
    url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/models"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            })
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            return True, "Anthropic /v1/models responded 200", latency
        if r.status_code in (401, 403):
            return False, f"Anthropic rejected the API key ({r.status_code})", latency
        return False, f"Anthropic returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Anthropic probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Anthropic probe failed: {e}", None


async def _probe_openai_compatible(
    api_key: str, base_url: str, vendor_label: str
) -> Tuple[bool, str, Optional[int]]:
    """Shared probe for any vendor that exposes an OpenAI-compatible
    /v1/models endpoint behind Bearer-token auth (OpenAI, Groq, Mistral,
    Together, Fireworks, …)."""
    url = base_url.rstrip("/") + "/models"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, headers={"Authorization": f"Bearer {api_key}"})
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            return True, f"{vendor_label} /v1/models responded 200", latency
        if r.status_code in (401, 403):
            return False, f"{vendor_label} rejected the API key ({r.status_code})", latency
        return False, f"{vendor_label} returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"{vendor_label} probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"{vendor_label} probe failed: {e}", None


async def _probe_kafka(bootstrap_servers: Optional[str]) -> Tuple[bool, str, Optional[int]]:
    """
    Kafka liveness = "is the first bootstrap broker accepting TCP
    connections".  We parse the comma-separated host:port list, grab
    the first entry, and do an ``asyncio.open_connection`` against it.
    That confirms the broker is up and network-reachable — it does NOT
    verify auth (which would need a full KafkaAdminClient with the
    uploaded cert); that's a future upgrade.  For now "reachable" is
    exactly the signal the Test button was missing.
    """
    if not bootstrap_servers or not bootstrap_servers.strip():
        return False, "Test failed — no bootstrap servers configured", None

    first = bootstrap_servers.split(",")[0].strip()
    if ":" not in first:
        return False, f"Invalid bootstrap server '{first}' (expected host:port)", None
    host, _, port_s = first.rpartition(":")
    try:
        port = int(port_s)
    except ValueError:
        return False, f"Invalid port in '{first}' — must be an integer", None

    started = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_PROBE_TIMEOUT_S,
        )
        # Close cleanly but don't fail the probe if the close races.
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        latency = int((time.monotonic() - started) * 1000)
        return True, f"Kafka broker {host}:{port} is reachable (TCP)", latency
    except asyncio.TimeoutError:
        return False, f"Kafka broker {host}:{port} timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except (OSError, ConnectionRefusedError) as e:
        return False, f"Kafka broker {host}:{port} unreachable: {e}", None


async def _probe_flink(jobmanager_url: Optional[str]) -> Tuple[bool, str, Optional[int]]:
    """
    Flink liveness = "does the JobManager's REST overview endpoint
    respond 200".  ``GET /overview`` is the canonical cluster-summary
    endpoint (it's what the Flink web UI polls every few seconds) and
    returns taskmanager + slot + running-job counts.  We don't auth the
    call — in the AI-SPM deployment the JobManager REST port is
    network-isolated inside the docker-compose cluster, and a reachable
    JobManager is the actual signal the Test button needs.
    """
    if not jobmanager_url or not jobmanager_url.strip():
        return False, "Test failed — no jobmanager_url configured", None

    url = jobmanager_url.rstrip("/") + "/overview"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url)
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            # Best-effort extraction of the task-slot summary so the
            # success message carries a real signal, not just "200 OK".
            try:
                j = r.json()
                tm = j.get("taskmanagers")
                slots_total = j.get("slots-total")
                slots_available = j.get("slots-available")
                return True, (
                    f"Flink JobManager reachable — "
                    f"{tm} taskmanager(s), {slots_available}/{slots_total} slots free"
                ), latency
            except Exception:  # noqa: BLE001
                return True, "Flink JobManager /overview responded 200", latency
        return False, f"Flink JobManager returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Flink probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Flink probe failed: {e}", None


async def _probe_ollama(base_url: Optional[str]) -> Tuple[bool, str, Optional[int]]:
    # Ollama's native listing endpoint lives at /api/tags at the ROOT —
    # not under /v1/.  But the stored base_url is often the OpenAI-
    # compatible surface "http://host.docker.internal:11434/v1" (that's
    # the shape guard-model talks to), so hitting base_url + "/api/tags"
    # straight would give us /v1/api/tags and a 404.  Strip a trailing
    # /v1 (and /v1/) before appending the native path.
    root = (base_url or "http://host.docker.internal:11434").rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    url = root + "/api/tags"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url)
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            tags = (r.json().get("models") or [])
            return True, f"Ollama reachable at {root} — {len(tags)} models pulled", latency
        return False, f"Ollama at {root} returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Ollama at {root} timed out after {_PROBE_TIMEOUT_S:.0f}s — is ollama running?", None
    except httpx.HTTPError as e:
        return False, f"Ollama probe failed ({root}): {e}", None


async def _probe_vendor(
    row: "Integration", api_key: Optional[str]
) -> Tuple[bool, str, Optional[int]]:
    """
    Dispatch Test clicks to the right probe.

    Primary path: ``row.connector_type`` is a registry key
    (``"postgres"``, ``"kafka"``, …).  We look up the connector in
    :mod:`connector_registry`, decrypt every secret credential the
    registry declared, and hand the probe a ``(config, credentials)``
    pair.  This is the path every new vendor uses; it covers all 21
    catalog entries.

    Legacy path: if ``connector_type`` is NULL (rows created before
    migration 004, or operator-added custom rows), we fall back to the
    old name-based dispatch.  Back-compat only — do NOT extend.
    """
    # ── Primary path — registry-driven dispatch ──────────────────────────────
    ctype = getattr(row, "connector_type", None)
    if ctype:
        try:
            from connector_registry import get_connector  # type: ignore
        except ModuleNotFoundError:
            from services.spm_api.connector_registry import get_connector  # type: ignore
        ct = get_connector(ctype)
        if ct is not None:
            cfg = dict(row.config or {})
            # Decode every secret the registry declared, keyed by field.key
            # (e.g. "api_key", "password", "hec_token", "bot_token", …).
            # Match credentials by credential_type, which is the same
            # string as the secret field.key per the schema-driven path.
            creds: Dict[str, Any] = {}
            for f in ct["fields"]:
                if not f.get("secret"):
                    continue
                key = f["key"]
                c = next(
                    (c for c in (row.credentials or [])
                     if c.credential_type == key and c.is_configured),
                    None,
                )
                if c:
                    creds[key] = _decode_secret(c.value_enc)
            # One-off: the old api-key probe fed api_key in via function
            # arg.  If the credentials dict didn't find an api_key
            # row (unusual for seed rows bootstrapped pre-004) but the
            # legacy decoder did, fold it in so nothing regresses.
            if api_key and "api_key" in {f["key"] for f in ct["fields"] if f.get("secret")}:
                creds.setdefault("api_key", api_key)
            try:
                return await ct["probe"](cfg, creds)
            except Exception as e:  # noqa: BLE001
                # Probes are supposed to never raise, but belt-and-braces:
                # convert any leaked exception to a clean (False, msg) tuple
                # so the HTTP route still responds 200 with ok=False.
                log.exception("probe for %r raised", ctype)
                return False, f"Probe for {ctype} errored: {e}", None
        # Unknown key — log and fall through to legacy dispatch.
        log.warning("row %s has unknown connector_type=%r; falling back", row.id, ctype)

    # ── Legacy name-based dispatch (pre-004 rows only) ───────────────────────
    name = (row.name or "").strip().lower()
    cfg = row.config or {}
    base_url = cfg.get("base_url") if isinstance(cfg, dict) else None

    API_KEY_PROBE_VENDORS = {"anthropic", "openai", "groq", "mistral"}
    if name in API_KEY_PROBE_VENDORS and not api_key:
        return False, "Test failed — no API key configured", None

    if name == "anthropic":
        return await _probe_anthropic(api_key, base_url)
    if name == "openai":
        return await _probe_openai_compatible(api_key, base_url or "https://api.openai.com/v1", "OpenAI")
    if name == "groq":
        return await _probe_openai_compatible(api_key, base_url or "https://api.groq.com/openai/v1", "Groq")
    if name == "mistral":
        return await _probe_openai_compatible(api_key, base_url or "https://api.mistral.ai/v1", "Mistral")
    if name == "ollama":
        return await _probe_ollama(base_url)
    if name == "kafka":
        bootstrap = cfg.get("bootstrap_servers") if isinstance(cfg, dict) else None
        return await _probe_kafka(bootstrap)
    if name == "flink":
        jobmanager = cfg.get("jobmanager_url") if isinstance(cfg, dict) else None
        return await _probe_flink(jobmanager or "http://flink-jobmanager:8081")

    has_cred = any(c.is_configured for c in (row.credentials or []))
    if has_cred and row.enabled:
        return True, "Credentials present (no live probe implemented for this vendor yet)", None
    if not row.enabled:
        return False, "Test failed — integration is disabled", None
    return False, "Test failed — credentials not configured", None


# ─── Pydantic schemas ───────────────────────────────────────────────────────────


class CredentialOut(BaseModel):
    credential_type: str
    name: str
    is_configured: bool
    value_hint: Optional[str] = None
    rotated_at: Optional[str] = None


class ConnectionOut(BaseModel):
    last_sync: Optional[str] = None
    last_sync_full: Optional[str] = None
    last_failed_sync: Optional[str] = None
    avg_latency: Optional[str] = None
    uptime: Optional[str] = None
    health_history: List[str] = []


class AuthOut(BaseModel):
    token_expiry: Optional[str] = None
    scopes: List[str] = []
    missing_scopes: List[str] = []
    setup_progress: Optional[List[Dict[str, Any]]] = None


class CoverageItem(BaseModel):
    label: str
    enabled: bool


class ActivityItem(BaseModel):
    ts: str
    event: str
    result: str
    actor: Optional[str] = None


class WorkflowsOut(BaseModel):
    playbooks: List[str] = []
    alerts: List[str] = []
    policies: List[str] = []
    cases: List[str] = []


class LogItem(BaseModel):
    id: str
    event_at: str
    action: str
    actor: Optional[str] = None
    result: str
    message: Optional[str] = None
    detail: Dict[str, Any] = {}


class IntegrationSummary(BaseModel):
    id: str
    external_id: Optional[str] = None
    connector_type: Optional[str] = Field(default=None, alias="connectorType")
    name: str
    abbrev: Optional[str] = None
    category: str
    status: str
    auth_method: str = Field(alias="authMethod")
    owner: Optional[str] = None
    owner_display: Optional[str] = Field(default=None, alias="ownerDisplay")
    environment: str
    enabled: bool
    description: Optional[str] = None
    vendor: Optional[str] = None
    tags: List[str] = []
    config: Dict[str, Any] = {}
    # Flattened commonly-read fields for the list view
    last_sync: Optional[str] = Field(default=None, alias="lastSync")
    avg_latency: Optional[str] = Field(default=None, alias="avgLatency")
    uptime: Optional[str] = None
    health_history: Optional[List[str]] = Field(default=None, alias="healthHistory")

    model_config = {"populate_by_name": True}


class IntegrationDetail(IntegrationSummary):
    # Full nested shape consumed by the detail panel
    credentials: List[CredentialOut] = []
    connection: Optional[ConnectionOut] = None
    auth: Optional[AuthOut] = None
    coverage: List[CoverageItem] = []
    activity: List[ActivityItem] = []
    workflows: Optional[WorkflowsOut] = None
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="lastModified")

    model_config = {"populate_by_name": True}


class IntegrationCreate(BaseModel):
    external_id: Optional[str] = None
    connector_type: Optional[str] = None
    name: str
    abbrev: Optional[str] = None
    category: str
    auth_method: str = "API Key"
    owner: Optional[str] = None
    owner_display: Optional[str] = None
    environment: str = "Production"
    enabled: bool = True
    description: Optional[str] = None
    vendor: Optional[str] = None
    tags: List[str] = []
    config: Dict[str, Any] = {}
    # Schema-driven initial credentials — e.g. ``{"api_key": "sk-…"}``.
    # Split into credentials vs config at create-time via the registry.
    credentials: Dict[str, Any] = {}
    status: str = "Not Configured"


class IntegrationUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    owner: Optional[str] = None
    owner_display: Optional[str] = None
    environment: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class ConfigureRequest(BaseModel):
    """
    Flexible Configure payload.  Two modes, both supported.

    Schema-driven (new, preferred) — ``fields`` carries every form value
    keyed by the registry ``field.key``.  The backend looks up the row's
    ``connector_type`` in :mod:`connector_registry`, splits ``fields``
    into (credentials, config) using ``secret_field_keys()``, and writes
    each bucket.  The UI sends one dict and doesn't need to know which
    values are secret.  Empty strings are treated as "leave unchanged"
    so a no-op form save doesn't clobber a stored secret with "".

    Legacy (pre-registry) — the explicit ``api_key`` / ``username`` /
    ``password`` / ``service_account_json`` / ``bootstrap_servers`` /
    ``config`` fields.  Still accepted so the old archetype-branching UI
    keeps working while the schema-driven modal rolls out.  The two
    modes don't conflict — if both are present, fields wins for the
    same key.
    """
    # Schema-driven path — every form value keyed by field.key.
    fields:               Optional[Dict[str, Any]] = None

    # Legacy path
    api_key:              Optional[str] = None
    username:             Optional[str] = None
    password:             Optional[str] = None
    service_account_json: Optional[str] = None
    bootstrap_servers:    Optional[str] = None
    config:               Optional[Dict[str, Any]] = None


class MetricsOut(BaseModel):
    total: int
    connected: int
    healthy: int
    needs_attention: int
    failed_syncs_24h: int


# ─── Serialization helpers ──────────────────────────────────────────────────────


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _summary(i: Integration) -> IntegrationSummary:
    conn = i.connection
    return IntegrationSummary(
        id=str(i.id),
        external_id=i.external_id,
        connectorType=getattr(i, "connector_type", None),
        name=i.name,
        abbrev=i.abbrev,
        category=i.category,
        status=i.status.value if i.status else "Not Configured",
        authMethod=i.auth_method.value if i.auth_method else "API Key",
        owner=i.owner,
        ownerDisplay=i.owner_display,
        environment=i.environment,
        enabled=bool(i.enabled),
        description=i.description,
        vendor=i.vendor,
        tags=list(i.tags or []),
        config=dict(i.config or {}),
        lastSync=conn.last_sync if conn else None,
        avgLatency=conn.avg_latency if conn else None,
        uptime=conn.uptime if conn else None,
        healthHistory=list(conn.health_history) if (conn and conn.health_history) else None,
    )


def _detail(i: Integration) -> IntegrationDetail:
    base = _summary(i).model_dump(by_alias=True)
    conn = i.connection
    auth = i.auth
    wf = i.workflows
    return IntegrationDetail(
        **base,
        createdAt=_iso(i.created_at),
        lastModified=_iso(i.updated_at),
        credentials=[
            CredentialOut(
                credential_type=c.credential_type,
                name=c.name,
                is_configured=bool(c.is_configured),
                value_hint=c.value_hint,
                rotated_at=_iso(c.rotated_at),
            )
            for c in (i.credentials or [])
        ],
        connection=ConnectionOut(
            last_sync=conn.last_sync if conn else None,
            last_sync_full=conn.last_sync_full if conn else None,
            last_failed_sync=conn.last_failed_sync if conn else None,
            avg_latency=conn.avg_latency if conn else None,
            uptime=conn.uptime if conn else None,
            health_history=list(conn.health_history) if (conn and conn.health_history) else [],
        ) if conn else None,
        auth=AuthOut(
            token_expiry=auth.token_expiry if auth else None,
            scopes=list(auth.scopes) if auth else [],
            missing_scopes=list(auth.missing_scopes) if auth else [],
            setup_progress=list(auth.setup_progress) if (auth and auth.setup_progress) else None,
        ) if auth else None,
        coverage=[
            CoverageItem(label=c.label, enabled=bool(c.enabled))
            for c in sorted(i.coverage or [], key=lambda x: x.position)
        ],
        activity=[
            ActivityItem(
                ts=a.ts_display,
                event=a.event,
                result=a.result.value if a.result else "Info",
                actor=a.actor,
            )
            for a in (i.activity or [])
        ],
        workflows=WorkflowsOut(
            playbooks=list(wf.playbooks) if wf else [],
            alerts=list(wf.alerts) if wf else [],
            policies=list(wf.policies) if wf else [],
            cases=list(wf.cases) if wf else [],
        ) if wf else WorkflowsOut(),
    )


async def _get_integration_or_404(db: AsyncSession, integration_id: str) -> Integration:
    try:
        uid = uuid.UUID(integration_id)
    except ValueError:
        # Allow lookup by external_id slug ('int-003') as a convenience
        row = (await db.execute(
            select(Integration).where(Integration.external_id == integration_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Integration not found")
        return row
    row = await db.get(Integration, uid)
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return row


async def _write_log(
    db: AsyncSession, integration_id: uuid.UUID,
    action: str, actor: Optional[str], result: str,
    message: Optional[str] = None, detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Append-only Logs tab entry."""
    db.add(IntegrationLog(
        integration_id=integration_id,
        action=action,
        actor=actor,
        result=IntegrationActivityResult(result),
        message=message,
        detail=detail or {},
    ))


def _ts_display(dt: datetime) -> str:
    return dt.strftime("%b %-d · %H:%M UTC") if hasattr(dt, "strftime") else dt.isoformat()


async def _append_activity(
    db: AsyncSession, integration_id: uuid.UUID,
    event: str, result: str, actor: Optional[str] = None,
) -> None:
    now = datetime.now(tz=timezone.utc)
    db.add(IntegrationActivity(
        integration_id=integration_id,
        ts_display=_ts_display(now),
        event_at=now,
        event=event,
        result=IntegrationActivityResult(result),
        actor=actor,
    ))


# ─── Auth ────────────────────────────────────────────────────────────────────────

# Thin wrappers around the app-level auth dependencies so the router stays
# self-contained.  The bare `app` name matches the flattened Dockerfile
# layout; when imported from the repo root during tests, we fall back to the
# packaged path.

def _app_module():
    # Prefer the bare `app` name (matches the flattened Dockerfile layout
    # used at runtime), but fall through to the packaged path if either
    # (a) `app` isn't importable, or (b) `app` IS importable but resolves
    # to a DIFFERENT service's app.py — for example in the monorepo test
    # environment, `services/api/app.py` and `services/spm_api/app.py`
    # both sit on sys.path, and which one `import app` wins depends on
    # the order in tests/conftest.py.  Detect the wrong module by the
    # absence of `verify_jwt` (only spm-api's app.py exposes it) and fall
    # through to the explicit path.
    try:
        import app as _m  # type: ignore
        if hasattr(_m, "verify_jwt"):
            return _m
    except ModuleNotFoundError:
        pass
    from services.spm_api import app as _m  # type: ignore
    return _m


# NOTE: these wrappers must expose a FastAPI-introspectable signature.
# Using (*args, **kwargs) breaks FastAPI's dependency injection — the DI
# layer reads the wrapper's signature via inspect.signature() and cannot
# see the Header/Depends markers that live on the real impl in app.py.
# We mirror the real signatures here and call the underlying functions
# directly (bypassing their Depends markers since the values are already
# resolved by the time the wrapper runs).
def verify_jwt(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    return _app_module().verify_jwt(authorization=authorization)


def require_admin(claims: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    if "spm:admin" not in claims.get("roles", []):
        raise HTTPException(status_code=403, detail="spm:admin role required")
    return claims


def require_auditor(claims: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    roles = claims.get("roles", [])
    if "spm:admin" not in roles and "spm:auditor" not in roles:
        raise HTTPException(
            status_code=403, detail="spm:auditor or spm:admin role required"
        )
    return claims


def _actor(claims: Dict[str, Any]) -> str:
    return claims.get("sub") or claims.get("email") or "system"


# ─── List / metrics ─────────────────────────────────────────────────────────────


@router.get("", response_model=List[IntegrationSummary])
async def list_integrations(
    category: Optional[str] = Query(None),
    vendor:   Optional[str] = Query(
        None,
        description=(
            "Exact-match vendor filter (e.g. 'Tavily'). Used by FieldSpec "
            "type='enum_integration' dropdowns that need a vendor-specific "
            "subset of an integration category."
        ),
    ),
    status_: Optional[str] = Query(None, alias="status"),
    q: Optional[str] = Query(None, description="Case-insensitive name/description search"),
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
):
    stmt = select(Integration)
    if category:
        stmt = stmt.where(Integration.category == category)
    if vendor:
        stmt = stmt.where(Integration.vendor == vendor)
    if status_:
        stmt = stmt.where(Integration.status == IntegrationStatus(status_))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(
            func.lower(Integration.name).like(like),
            func.lower(Integration.description).like(like),
        ))
    stmt = stmt.order_by(Integration.category, Integration.name)
    result = await db.execute(stmt)
    return [_summary(i) for i in result.scalars().all()]


@router.get("/metrics", response_model=MetricsOut)
async def integrations_metrics(
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
):
    """Top-of-page KPIs for the Integrations dashboard."""
    total_q    = await db.execute(select(func.count()).select_from(Integration))
    total      = int(total_q.scalar_one() or 0)

    healthy_q  = await db.execute(select(func.count()).select_from(Integration)
                                  .where(Integration.status == IntegrationStatus.Healthy))
    healthy    = int(healthy_q.scalar_one() or 0)

    connected_q = await db.execute(
        select(func.count()).select_from(Integration)
        .where(Integration.enabled.is_(True))
        .where(Integration.status != IntegrationStatus.NotConfigured)
    )
    connected = int(connected_q.scalar_one() or 0)

    needs_q = await db.execute(
        select(func.count()).select_from(Integration)
        .where(Integration.status.in_([
            IntegrationStatus.Warning, IntegrationStatus.Error,
            IntegrationStatus.Partial, IntegrationStatus.NotConfigured,
        ]))
    )
    needs = int(needs_q.scalar_one() or 0)

    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    failed_q = await db.execute(
        select(func.count()).select_from(IntegrationActivity)
        .where(IntegrationActivity.event_at >= since)
        .where(IntegrationActivity.result == IntegrationActivityResult.Error)
    )
    failed = int(failed_q.scalar_one() or 0)

    return MetricsOut(
        total=total, connected=connected, healthy=healthy,
        needs_attention=needs, failed_syncs_24h=failed,
    )


# ─── Connector catalog ──────────────────────────────────────────────────────────


@router.get("/connector-types", response_model=List[Dict[str, Any]])
async def get_connector_types(
    _claims: Dict = Depends(verify_jwt),
):
    """Return the connector catalog — every vendor schema the platform
    knows how to render and probe.  Used by the Add Integration vendor
    picker and by the schema-driven Configure modal to render the right
    fields per connector."""
    try:
        from connector_registry import list_connector_types  # type: ignore
    except ModuleNotFoundError:
        from services.spm_api.connector_registry import list_connector_types  # type: ignore
    return list_connector_types()


# ─── CRUD ───────────────────────────────────────────────────────────────────────


@router.post("", response_model=IntegrationDetail, status_code=201)
async def create_integration(
    body: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    try:
        status_enum = IntegrationStatus(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status!r}")
    try:
        auth_enum = IntegrationAuthMethod(body.auth_method)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid auth_method: {body.auth_method!r}")

    # Schema-driven split — if connector_type + credentials dict are
    # supplied, consult the registry to figure out which keys in
    # body.config are actually secret (and should be moved to the
    # credentials table) vs. plaintext knobs that belong in config.
    # This lets the Add Integration form send one dict keyed by
    # field.key and the backend routes each value correctly.
    secret_keys: List[str] = []
    split_creds: Dict[str, Any] = {}
    split_config: Dict[str, Any] = dict(body.config or {})
    if body.connector_type:
        try:
            from connector_registry import get_connector, secret_field_keys  # type: ignore
        except ModuleNotFoundError:
            from services.spm_api.connector_registry import (  # type: ignore
                get_connector, secret_field_keys,
            )
        if get_connector(body.connector_type) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown connector_type: {body.connector_type!r}",
            )
        secret_keys = secret_field_keys(body.connector_type)
        for k, v in list(split_config.items()):
            if k in secret_keys:
                # value snuck into config but is actually secret — move it.
                split_creds[k] = v
                split_config.pop(k)
        # credentials dict always takes precedence
        for k, v in (body.credentials or {}).items():
            split_creds[k] = v

    row = Integration(
        external_id=body.external_id,
        connector_type=body.connector_type,
        name=body.name, abbrev=body.abbrev, category=body.category,
        status=status_enum, auth_method=auth_enum,
        owner=body.owner, owner_display=body.owner_display,
        environment=body.environment, enabled=body.enabled,
        description=body.description, vendor=body.vendor,
        tags=list(body.tags or []), config=split_config,
    )
    db.add(row)
    await db.flush()
    # Initialize side-tables so tab GETs return a shape, not nulls
    db.add(IntegrationConnection(integration_id=row.id))
    db.add(IntegrationAuth(integration_id=row.id))
    db.add(IntegrationWorkflow(integration_id=row.id))

    # Persist any initial secrets supplied via body.credentials.  We
    # write these as credential_type=<field.key> so the probe dispatcher
    # (which keys off field.key) picks them up verbatim.  Empty strings
    # are skipped so a blank field doesn't create an "is_configured=True"
    # row with no value.
    for key, raw in split_creds.items():
        if not isinstance(raw, str) or not raw.strip():
            continue
        db.add(IntegrationCredential(
            integration_id=row.id,
            credential_type=key,
            name=key.replace("_", " ").title(),
            value_enc=_encode_secret(raw.strip()),
            value_hint=_mask(raw.strip()),
            is_configured=True,
            rotated_at=datetime.now(tz=timezone.utc),
        ))
    # Flip Not Configured → Healthy if ANY secret was written on create.
    if split_creds and row.status == IntegrationStatus.NotConfigured:
        row.status = IntegrationStatus.Healthy

    await _write_log(db, row.id, "create", _actor(claims), "Success",
                     message=f"Integration {row.name!r} created")
    await db.commit()
    await db.refresh(row)
    return _detail(row)


@router.get("/{integration_id}", response_model=IntegrationDetail)
async def get_integration(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
):
    row = await _get_integration_or_404(db, integration_id)
    return _detail(row)


@router.patch("/{integration_id}", response_model=IntegrationDetail)
async def update_integration(
    integration_id: str,
    body: IntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    row = await _get_integration_or_404(db, integration_id)
    changed: Dict[str, Any] = {}
    if body.name is not None:          row.name = body.name;              changed["name"] = body.name
    if body.category is not None:      row.category = body.category;      changed["category"] = body.category
    if body.owner is not None:         row.owner = body.owner;            changed["owner"] = body.owner
    if body.owner_display is not None: row.owner_display = body.owner_display
    if body.environment is not None:   row.environment = body.environment
    if body.enabled is not None:       row.enabled = body.enabled;        changed["enabled"] = body.enabled
    if body.description is not None:   row.description = body.description
    if body.tags is not None:          row.tags = list(body.tags);        changed["tags"] = body.tags
    if body.config is not None:        row.config = {**(row.config or {}), **body.config}; changed["config"] = body.config
    if body.status is not None:
        try:
            row.status = IntegrationStatus(body.status)
            changed["status"] = body.status
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status!r}")
    await _write_log(db, row.id, "update", _actor(claims), "Info",
                     message=f"Updated {', '.join(changed.keys()) or 'no fields'}", detail=changed)
    await db.commit()
    await db.refresh(row)
    return _detail(row)


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(require_admin),
):
    row = await _get_integration_or_404(db, integration_id)
    await db.execute(delete(Integration).where(Integration.id == row.id))
    await db.commit()
    return None


# ─── Tab endpoints ──────────────────────────────────────────────────────────────


@router.get("/{integration_id}/overview", response_model=IntegrationDetail)
async def tab_overview(integration_id: str, db: AsyncSession = Depends(get_db),
                       _claims: Dict = Depends(verify_jwt)):
    return _detail(await _get_integration_or_404(db, integration_id))


@router.get("/{integration_id}/connection", response_model=ConnectionOut)
async def tab_connection(integration_id: str, db: AsyncSession = Depends(get_db),
                         _claims: Dict = Depends(verify_jwt)):
    row = await _get_integration_or_404(db, integration_id)
    c = row.connection
    return ConnectionOut(
        last_sync=c.last_sync if c else None,
        last_sync_full=c.last_sync_full if c else None,
        last_failed_sync=c.last_failed_sync if c else None,
        avg_latency=c.avg_latency if c else None,
        uptime=c.uptime if c else None,
        health_history=list(c.health_history) if (c and c.health_history) else [],
    )


@router.get("/{integration_id}/auth", response_model=AuthOut)
async def tab_auth(integration_id: str, db: AsyncSession = Depends(get_db),
                   _claims: Dict = Depends(verify_jwt)):
    row = await _get_integration_or_404(db, integration_id)
    a = row.auth
    return AuthOut(
        token_expiry=a.token_expiry if a else None,
        scopes=list(a.scopes) if a else [],
        missing_scopes=list(a.missing_scopes) if a else [],
        setup_progress=list(a.setup_progress) if (a and a.setup_progress) else None,
    )


@router.get("/{integration_id}/coverage", response_model=List[CoverageItem])
async def tab_coverage(integration_id: str, db: AsyncSession = Depends(get_db),
                       _claims: Dict = Depends(verify_jwt)):
    row = await _get_integration_or_404(db, integration_id)
    return [CoverageItem(label=c.label, enabled=bool(c.enabled))
            for c in sorted(row.coverage or [], key=lambda x: x.position)]


@router.get("/{integration_id}/activity", response_model=List[ActivityItem])
async def tab_activity(integration_id: str, limit: int = 50,
                       db: AsyncSession = Depends(get_db),
                       _claims: Dict = Depends(verify_jwt)):
    row = await _get_integration_or_404(db, integration_id)
    items = (row.activity or [])[:limit]
    return [ActivityItem(ts=a.ts_display, event=a.event,
                         result=a.result.value if a.result else "Info",
                         actor=a.actor)
            for a in items]


@router.get("/{integration_id}/workflows", response_model=WorkflowsOut)
async def tab_workflows(integration_id: str, db: AsyncSession = Depends(get_db),
                        _claims: Dict = Depends(verify_jwt)):
    row = await _get_integration_or_404(db, integration_id)
    w = row.workflows
    return WorkflowsOut(
        playbooks=list(w.playbooks) if w else [],
        alerts=list(w.alerts) if w else [],
        policies=list(w.policies) if w else [],
        cases=list(w.cases) if w else [],
    )


@router.get("/{integration_id}/logs", response_model=List[LogItem])
async def tab_logs(integration_id: str, limit: int = 200,
                   db: AsyncSession = Depends(get_db),
                   _claims: Dict = Depends(require_auditor)):
    row = await _get_integration_or_404(db, integration_id)
    items = (row.logs or [])[:limit]
    return [LogItem(
        id=str(l.id),
        event_at=_iso(l.event_at),
        action=l.action,
        actor=l.actor,
        result=l.result.value if l.result else "Info",
        message=l.message,
        detail=dict(l.detail or {}),
    ) for l in items]


# ─── Actions ────────────────────────────────────────────────────────────────────


@router.post("/{integration_id}/configure", response_model=IntegrationDetail)
async def configure_integration(
    integration_id: str,
    body: ConfigureRequest,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    """
    Write/update credentials and/or config knobs.  Marks the integration
    Healthy (if previously Not Configured) and appends an activity entry.

    Two input modes:
      * ``body.fields`` — schema-driven dict keyed by registry field.key.
        Split into (credentials, config) via secret_field_keys() and
        written.  Empty-string values are skipped so blank inputs don't
        clobber existing secrets.
      * legacy explicit fields (api_key / password / …) — still handled
        below for back-compat with the pre-registry UI.
    """
    row = await _get_integration_or_404(db, integration_id)

    # ── Schema-driven path ──────────────────────────────────────────────────
    if body.fields:
        ctype = getattr(row, "connector_type", None)
        if not ctype:
            # No connector_type set — treat every supplied field as
            # plaintext config, since we can't know which are secret.
            # This is rare and only hits pre-migration rows that no one
            # has refreshed via bootstrap.
            non_empty = {k: v for k, v in body.fields.items()
                         if not (isinstance(v, str) and not v.strip())}
            if non_empty:
                row.config = {**(row.config or {}), **non_empty}
        else:
            try:
                from connector_registry import (  # type: ignore
                    get_connector, secret_field_keys, validate_submission,
                )
            except ModuleNotFoundError:
                from services.spm_api.connector_registry import (  # type: ignore
                    get_connector, secret_field_keys, validate_submission,
                )
            ok, msg = validate_submission(ctype, body.fields, partial=True)
            if not ok:
                raise HTTPException(status_code=400, detail=msg)
            secret_keys = set(secret_field_keys(ctype))
            # Split
            new_config: Dict[str, Any] = {}
            new_creds: Dict[str, str] = {}
            for k, v in (body.fields or {}).items():
                # Skip empty strings — "leave blank to keep existing".
                if isinstance(v, str) and not v.strip():
                    continue
                if k in secret_keys:
                    if isinstance(v, str):
                        new_creds[k] = v.strip()
                else:
                    new_config[k] = v
            if new_config:
                row.config = {**(row.config or {}), **new_config}
            for key, raw in new_creds.items():
                cred = next(
                    (c for c in (row.credentials or []) if c.credential_type == key),
                    None,
                )
                if cred is None:
                    cred = IntegrationCredential(
                        integration_id=row.id,
                        credential_type=key,
                        name=key.replace("_", " ").title(),
                    )
                    db.add(cred)
                cred.value_enc = _encode_secret(raw)
                cred.value_hint = _mask(raw)
                cred.is_configured = bool(raw)
                cred.rotated_at = datetime.now(tz=timezone.utc)
                await _append_activity(
                    db, row.id, f"{key.replace('_', ' ').title()} configured",
                    "Success", actor=_actor(claims),
                )

    # Config knobs (legacy explicit "config" dict) — merged into existing
    if body.config:
        row.config = {**(row.config or {}), **body.config}

    # Username is non-secret — live alongside `model` inside the config
    # JSON so the UI can read it back without a credentials lookup.
    if body.username is not None and body.username.strip():
        row.config = {**(row.config or {}), "username": body.username.strip()}

    # Secret update — single primary credential per credential_type.
    # api_key (AI-provider shape) and password (basic-auth shape) are
    # handled the same way modulo the type label; this keeps the
    # upsert logic in one place instead of forking it per archetype.
    def _upsert_secret(cred_type: str, display_name: str, raw: str) -> None:
        cred = next(
            (c for c in (row.credentials or []) if c.credential_type == cred_type),
            None,
        )
        if cred is None:
            cred = IntegrationCredential(
                integration_id=row.id,
                credential_type=cred_type,
                name=display_name,
            )
            db.add(cred)
        cred.value_enc = _encode_secret(raw)
        cred.value_hint = _mask(raw)
        cred.is_configured = bool(raw)
        cred.rotated_at = datetime.now(tz=timezone.utc)

    if body.api_key is not None and body.api_key.strip():
        _upsert_secret("api_key", "Primary API key", body.api_key.strip())
        await _append_activity(db, row.id, "API key configured", "Success",
                               actor=_actor(claims))

    if body.password is not None and body.password.strip():
        _upsert_secret("password", "Primary password", body.password.strip())
        await _append_activity(db, row.id, "Password configured", "Success",
                               actor=_actor(claims))

    # Cert archetype: persist service_account_json alongside the other
    # secret-kinds.  The display name mirrors what Kafka/Vertex seeds
    # use so the UI reads back a consistent "Service account cert" label.
    if body.service_account_json is not None and body.service_account_json.strip():
        _upsert_secret(
            "service_account_json",
            "Service account cert",
            body.service_account_json.strip(),
        )
        await _append_activity(db, row.id, "Service account cert configured",
                               "Success", actor=_actor(claims))

    # bootstrap_servers is the one config knob we promote to a first-class
    # request field so the Kafka form can send it without building a dict.
    # Merged into config just like any other non-secret knob.
    if body.bootstrap_servers is not None and body.bootstrap_servers.strip():
        row.config = {**(row.config or {}),
                      "bootstrap_servers": body.bootstrap_servers.strip()}

    # Transition Not Configured → Healthy on first successful configure
    if row.status == IntegrationStatus.NotConfigured:
        row.status = IntegrationStatus.Healthy

    await _write_log(
        db, row.id, "configure", _actor(claims), "Success",
        message="Integration configured",
        detail={
            "config_keys":      list((body.config or {}).keys()),
            "api_key_updated":  bool(body.api_key  and body.api_key.strip()),
            "password_updated": bool(body.password and body.password.strip()),
            "cert_updated":     bool(body.service_account_json
                                     and body.service_account_json.strip()),
            "bootstrap_set":    bool(body.bootstrap_servers
                                     and body.bootstrap_servers.strip()),
            "username_set":     bool(body.username and body.username.strip()),
        },
    )
    await db.commit()
    await db.refresh(row)

    # Live-credential write-through: nuke any cached values for this vendor
    # so the next get_credential() call for any consumer (api, orchestrator,
    # guard) reads the freshly-committed value instead of waiting out the
    # cache TTL.  Best-effort — failures here log a warning but don't fail
    # the configure request, since the DB write already succeeded and the
    # worst case is a TTL-window of stale reads.
    if row.external_id:
        try:
            invalidate_credential_cache(row.external_id)
        except Exception as exc:  # pragma: no cover — defence in depth
            log.warning(
                "configure: cache invalidation failed for vendor=%s (%s); "
                "new credential will become visible after TTL expiry",
                row.external_id, exc,
            )

    return _detail(row)


@router.post("/{integration_id}/test", response_model=Dict[str, Any])
async def test_integration(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    """
    Live vendor health check.  Dispatches to a provider-specific probe that
    hits a cheap read-only endpoint (typically /v1/models or /api/tags)
    with a short timeout.  Result is persisted to integration_activity /
    integration_logs, and the row's status flips to Healthy/Error so the
    list view reflects what just happened.

    If the integration isn't configured (no api_key, not enabled, or an
    unknown vendor we have no probe for yet), the call returns ok=False
    with a diagnostic message rather than raising — the user asked for
    "if we did, I want to know it's alive", and a clear error is more
    useful than a 500.
    """
    row = await _get_integration_or_404(db, integration_id)

    # Decode the stored api_key if present.  Passed as None when there
    # isn't one — the probe helper will short-circuit into a "missing
    # credentials" failure for vendors that need a key.
    #
    # Matching is on credential_type (the discriminator), NOT name —
    # the display name is user-facing text like "Primary API key" or
    # "HEC token", which would never equal the literal "api_key".  An
    # earlier version matched on .name and silently passed api_key=None
    # to every probe, which is why Test always said "no API key
    # configured".
    primary = next(
        (c for c in (row.credentials or [])
         if c.credential_type == "api_key" and c.is_configured),
        None,
    )
    api_key = _decode_secret(primary.value_enc) if primary else None

    # If the row is disabled, don't even probe — the user toggled it off
    # on purpose.  Tell them clearly instead of letting the vendor 401.
    if not row.enabled:
        ok, msg, latency = False, "Test skipped — integration is disabled", None
    else:
        ok, msg, latency = await _probe_vendor(row, api_key)

    # Reflect the probe outcome on the row itself so the list view turns
    # green/red without a separate sync.  We only flip *to* Healthy/Error
    # on an enabled row — disabled rows keep their Disabled status.
    if row.enabled:
        row.status = IntegrationStatus.Healthy if ok else IntegrationStatus.Error

    # Touch the connection row's last_sync on success so the UI's "last
    # sync" string reflects the most recent liveness confirmation.
    if ok and row.connection is not None:
        now = datetime.now(timezone.utc)
        row.connection.last_sync = "just now"
        row.connection.last_sync_full = now.strftime("%b %-d · %H:%M UTC")
        if latency is not None:
            row.connection.avg_latency = f"{latency}ms"

    result = "Success" if ok else "Error"
    await _append_activity(db, row.id, f"Test connection — {result.lower()}", result,
                           actor=_actor(claims))
    await _write_log(db, row.id, "test", _actor(claims), result, message=msg)
    await db.commit()
    return {"ok": ok, "message": msg, "latency_ms": latency}


@router.post("/{integration_id}/disable", response_model=IntegrationDetail)
async def disable_integration(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    row = await _get_integration_or_404(db, integration_id)
    row.enabled = False
    row.status = IntegrationStatus.Disabled
    await _append_activity(db, row.id, "Integration disabled", "Info",
                           actor=_actor(claims))
    await _write_log(db, row.id, "disable", _actor(claims), "Info",
                     message="Integration disabled")
    await db.commit()
    await db.refresh(row)
    return _detail(row)


@router.post("/{integration_id}/enable", response_model=IntegrationDetail)
async def enable_integration(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    row = await _get_integration_or_404(db, integration_id)
    row.enabled = True
    # Coming back from Disabled → default to Healthy if credentials exist,
    # Not Configured otherwise.
    if row.status == IntegrationStatus.Disabled:
        has_cred = any(c.is_configured for c in (row.credentials or []))
        row.status = IntegrationStatus.Healthy if has_cred else IntegrationStatus.NotConfigured
    await _append_activity(db, row.id, "Integration enabled", "Success",
                           actor=_actor(claims))
    await _write_log(db, row.id, "enable", _actor(claims), "Success",
                     message="Integration enabled")
    await db.commit()
    await db.refresh(row)
    return _detail(row)


@router.post("/{integration_id}/rotate-credentials", response_model=IntegrationDetail)
async def rotate_credentials(
    integration_id: str,
    body: ConfigureRequest,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    """
    Rotate the primary api_key.  body.api_key MUST be supplied — this endpoint
    never auto-generates a secret (that's the vendor's job).
    """
    if not body.api_key:
        raise HTTPException(status_code=400, detail="api_key is required to rotate")
    row = await _get_integration_or_404(db, integration_id)
    cred = next((c for c in (row.credentials or [])
                 if c.credential_type == "api_key"), None)
    if cred is None:
        cred = IntegrationCredential(
            integration_id=row.id, credential_type="api_key",
            name="Primary API key",
        )
        db.add(cred)
    raw = body.api_key.strip()
    cred.value_enc = _encode_secret(raw)
    cred.value_hint = _mask(raw)
    cred.is_configured = True
    cred.rotated_at = datetime.now(tz=timezone.utc)
    await _append_activity(db, row.id, "Credential rotated", "Success",
                           actor=_actor(claims))
    await _write_log(db, row.id, "rotate", _actor(claims), "Success",
                     message="Primary credential rotated")
    await db.commit()
    await db.refresh(row)
    return _detail(row)


@router.post("/{integration_id}/sync", response_model=Dict[str, Any])
async def sync_integration(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    """
    Manual sync trigger.  Bumps the connection's last_sync fields.
    """
    row = await _get_integration_or_404(db, integration_id)
    conn = row.connection
    now = datetime.now(tz=timezone.utc)
    if conn is None:
        conn = IntegrationConnection(integration_id=row.id)
        db.add(conn)
    conn.last_sync = "just now"
    conn.last_sync_full = now.strftime("%b %-d · %H:%M UTC")
    await _append_activity(db, row.id, "Manual sync triggered", "Success",
                           actor=_actor(claims))
    await _write_log(db, row.id, "sync", _actor(claims), "Success",
                     message="Manual sync triggered")
    await db.commit()
    return {"ok": True, "last_sync_full": conn.last_sync_full}


# Vendor docs URL lookup — used by the "Open Docs" quick action.
_DOCS_URLS = {
    "OpenAI":               "https://platform.openai.com/docs/api-reference",
    "Azure OpenAI":         "https://learn.microsoft.com/azure/ai-services/openai/",
    "Anthropic":            "https://docs.anthropic.com/en/api",
    "Amazon Bedrock":       "https://docs.aws.amazon.com/bedrock/",
    "Google Vertex AI":     "https://cloud.google.com/vertex-ai/docs",
    "Splunk":               "https://docs.splunk.com/Documentation",
    "Microsoft Sentinel":   "https://learn.microsoft.com/azure/sentinel/",
    "Jira":                 "https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
    "ServiceNow":           "https://developer.servicenow.com/",
    "Slack":                "https://api.slack.com/",
    "Okta":                 "https://developer.okta.com/docs/reference/",
    "Entra ID":             "https://learn.microsoft.com/entra/identity/",
    "Amazon S3":            "https://docs.aws.amazon.com/s3/",
    "Confluence":           "https://developer.atlassian.com/cloud/confluence/rest/v2/",
    "Kafka":                "https://kafka.apache.org/documentation/",
}


@router.get("/{integration_id}/docs", response_model=Dict[str, Any])
async def integration_docs(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
):
    row = await _get_integration_or_404(db, integration_id)
    return {"url": _DOCS_URLS.get(row.name), "name": row.name}


# ─── Bootstrap endpoint (replaces the old scripts/seed_integrations.py) ───────
#
# Only ONE endpoint is needed now: POST /integrations/bootstrap.  Services
# read their managed configuration DIRECTLY from spm-db at startup via
# platform_shared.integration_config.hydrate_env_from_db() — no sidecar env
# file, no HTTP round-trip to spm-api.  See that module for the full flow.
#
# Auth model:
#   POST /integrations/bootstrap  — requires admin JWT.  Inserts/updates the
#                                    18 seed rows and (on first run only)
#                                    copies bootstrap secrets from this
#                                    container's process env into the DB.
#                                    After the first successful run the
#                                    operator strips the managed keys from
#                                    .env and the DB is canonical forever.


async def _upsert_integration(db: AsyncSession, seed: Dict[str, Any]) -> Integration:
    """Idempotent upsert keyed by external_id.

    Moved here (out of the former scripts/seed_integrations.py) so the
    bootstrap is callable via HTTP rather than requiring a separate disk
    script.  Returns the Integration row after flush.
    """
    existing = (await db.execute(
        select(Integration).where(Integration.external_id == seed["external_id"])
    )).scalar_one_or_none()

    if existing is None:
        row = Integration(
            external_id=seed["external_id"],
            name=seed["name"], abbrev=seed["abbrev"],
            category=seed["category"],
            status=IntegrationStatus(seed["status"]),
            auth_method=IntegrationAuthMethod(seed["auth_method"]),
            owner=seed["owner"], owner_display=seed["owner_display"],
            environment=seed["environment"], enabled=seed["enabled"],
            description=seed["description"], vendor=seed["vendor"],
            tags=list(seed.get("tags") or []),
            config=dict(seed.get("config") or {}),
        )
        db.add(row)
        await db.flush()
        log.info("bootstrap: inserted %s (%s)", seed["external_id"], seed["name"])
    else:
        row = existing
        row.name          = seed["name"]
        row.abbrev        = seed["abbrev"]
        row.category      = seed["category"]
        row.status        = IntegrationStatus(seed["status"])
        row.auth_method   = IntegrationAuthMethod(seed["auth_method"])
        row.owner         = seed["owner"]
        row.owner_display = seed["owner_display"]
        row.environment   = seed["environment"]
        row.enabled       = seed["enabled"]
        row.description   = seed["description"]
        row.vendor        = seed["vendor"]
        row.tags          = list(seed.get("tags") or [])
        # Merge config so operator edits survive re-bootstraps; fall back to
        # seed values only for keys not yet set.
        merged_config = {**(seed.get("config") or {}), **dict(row.config or {})}
        row.config = merged_config
        log.info("bootstrap: updated %s (%s)", seed["external_id"], seed["name"])

    # Connection (unique per integration)
    conn_data = seed.get("connection") or {}
    conn = (await db.execute(
        select(IntegrationConnection).where(IntegrationConnection.integration_id == row.id)
    )).scalar_one_or_none()
    if conn is None:
        db.add(IntegrationConnection(integration_id=row.id, **conn_data))
    else:
        for k, v in conn_data.items():
            setattr(conn, k, v)

    # Auth (unique per integration)
    auth_data = seed.get("auth") or {}
    auth = (await db.execute(
        select(IntegrationAuth).where(IntegrationAuth.integration_id == row.id)
    )).scalar_one_or_none()
    if auth is None:
        db.add(IntegrationAuth(integration_id=row.id, **auth_data))
    else:
        for k, v in auth_data.items():
            setattr(auth, k, v)

    # Workflows (unique per integration)
    wf_data = seed.get("workflows") or {}
    wf = (await db.execute(
        select(IntegrationWorkflow).where(IntegrationWorkflow.integration_id == row.id)
    )).scalar_one_or_none()
    if wf is None:
        db.add(IntegrationWorkflow(integration_id=row.id, **wf_data))
    else:
        for k, v in wf_data.items():
            setattr(wf, k, v)

    # Coverage — replace (simple, safe because label+position form natural PK)
    await db.execute(
        delete(IntegrationCoverage).where(IntegrationCoverage.integration_id == row.id)
    )
    for i, (label, enabled) in enumerate(seed.get("coverage") or []):
        db.add(IntegrationCoverage(
            integration_id=row.id, position=i, label=label, enabled=bool(enabled),
        ))

    # Activity — replace so bootstraps don't accumulate
    await db.execute(
        delete(IntegrationActivity).where(IntegrationActivity.integration_id == row.id)
    )
    now = datetime.now(tz=timezone.utc)
    for ts, evt, result in (seed.get("activity") or []):
        db.add(IntegrationActivity(
            integration_id=row.id, ts_display=ts,
            event_at=now, event=evt,
            result=IntegrationActivityResult(result), actor=None,
        ))

    # Credentials — idempotent.  If env_var is set and exported, write the
    # value; otherwise leave the credential row with is_configured=False.
    # On re-bootstrap we DO NOT overwrite an existing configured secret
    # unless the env var carries a new non-empty value — rotation happens
    # via POST /{id}/configure or POST /{id}/rotate-credentials.
    for cred_seed in seed.get("credentials") or []:
        ctype = cred_seed["type"]
        cname = cred_seed["name"]
        env_var = cred_seed.get("env_var")
        raw_value = (os.getenv(env_var) or "").strip() if env_var else ""

        existing_cred = (await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_id == row.id,
                IntegrationCredential.credential_type == ctype,
            )
        )).scalar_one_or_none()
        if existing_cred is None:
            existing_cred = IntegrationCredential(
                integration_id=row.id,
                credential_type=ctype, name=cname,
            )
            db.add(existing_cred)
        existing_cred.name = cname
        if raw_value:
            existing_cred.value_enc = _encode_secret(raw_value)
            existing_cred.value_hint = _mask(raw_value)
            existing_cred.is_configured = True
            existing_cred.rotated_at = datetime.now(tz=timezone.utc)
            log.info("  bootstrap: populated credential %s/%s from env",
                     seed["external_id"], ctype)

    return row


class BootstrapResult(BaseModel):
    upserted: int
    external_ids: List[str]


@router.post("/bootstrap", response_model=BootstrapResult)
async def bootstrap_integrations(
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
):
    """Seed the integrations tables from the in-process seed data module.

    This replaces the old scripts/seed_integrations.py disk script.  Admin
    JWT required.  Idempotent — safe to call on every deploy as a
    migration step.

    First run: reads live secrets from this container's env
    (ANTHROPIC_API_KEY, TAVILY_API_KEY, GARAK_INTERNAL_SECRET) and copies
    them into integration_credentials.  After the first successful run the
    operator can strip those env vars from .env — subsequent bootstraps
    won't overwrite DB values with empty env.
    """
    try:
        from integrations_seed_data import build_seed
    except ModuleNotFoundError:
        from services.spm_api.integrations_seed_data import build_seed

    seed_data = build_seed()
    ids: List[str] = []
    actor = _actor(claims)
    for entry in seed_data:
        row = await _upsert_integration(db, entry)
        ids.append(entry["external_id"])
        # Per-integration log entry so each bootstrap is auditable against
        # the integration it touched (IntegrationLog.integration_id is NOT NULL).
        await _write_log(
            db, integration_id=row.id, action="bootstrap",
            actor=actor, result="Success",
            message=f"Bootstrapped via /integrations/bootstrap",
            detail={"external_id": entry["external_id"]},
        )
    await db.commit()
    log.info("bootstrap complete — upserted %d integrations by %s", len(ids), actor)
    return BootstrapResult(upserted=len(ids), external_ids=ids)


# NOTE: GET /integrations/env was intentionally removed — services hydrate
# their process env directly from spm-db via
# platform_shared.integration_config.hydrate_env_from_db(), which keeps
# secrets off the HTTP wire entirely.
