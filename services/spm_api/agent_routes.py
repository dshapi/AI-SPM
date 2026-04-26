"""HTTP endpoints for the agent runtime control plane.

Surface
───────
  POST   /api/spm/agents              — multipart upload + validate + (optionally) deploy
  GET    /api/spm/agents              — list (filter by tenant)
  GET    /api/spm/agents/{id}         — detail
  PATCH  /api/spm/agents/{id}         — partial update of safe fields
  DELETE /api/spm/agents/{id}         — retire (stop + delete topics + drop row)
  POST   /api/spm/agents/{id}/start   — async kick to spawn the container
  POST   /api/spm/agents/{id}/stop    — async kick to stop the container

Security
────────
* Reads  → ``verify_jwt`` (any authenticated user).
* Writes → ``require_admin`` (must carry ``spm:admin`` role).
* Tenant scoping is best-effort in V1: the JWT's tenant claim filters
  the list. Phase 2 enforces strict isolation across every endpoint.

Per the spec, ``mcp_token`` and ``llm_api_key`` are NEVER returned in
any response. The serializer in ``_to_dict`` strips them defensively.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Path as PathParam,
    UploadFile,
    status,
)

# Controller / validator — the spm_api service flattens its dir onto
# /app/ so siblings import bare; running tests from the repo root falls
# through to the packaged path.
try:
    from agent_controller import (                       # type: ignore
        deploy_agent, mint_agent_tokens,
        retire_agent, start_agent, stop_agent,
    )
    from agent_validator import validate_agent_code      # type: ignore
except ModuleNotFoundError:                              # pragma: no cover
    from services.spm_api.agent_controller import (
        deploy_agent, mint_agent_tokens,
        retire_agent, start_agent, stop_agent,
    )
    from services.spm_api.agent_validator import validate_agent_code

from spm.db.models  import Agent             # type: ignore
from spm.db.session import get_db            # type: ignore


# ─── Auth wrappers ─────────────────────────────────────────────────────────
#
# Defined locally (rather than imported from app) for two reasons:
#   1. Avoid the circular import — app.py imports our router at the
#      bottom; if we imported from app at module load we'd deadlock.
#   2. In the monorepo test env both ``services/api/app.py`` and
#      ``services/spm_api/app.py`` sit on sys.path; ``import app`` can
#      win whichever way and only one of them defines verify_jwt.
#      Same lazy-resolution dance integrations_routes.py uses.

def _app_module():
    """Lazily resolve the spm_api ``app`` module — the only one that
    defines ``verify_jwt`` / ``require_admin`` / ``_tenant_from_claims``."""
    try:
        import app as _m  # type: ignore
        if hasattr(_m, "verify_jwt"):
            return _m
    except ModuleNotFoundError:
        pass
    from services.spm_api import app as _m  # type: ignore
    return _m


def verify_jwt(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Wrapper that delegates to ``app.verify_jwt`` after FastAPI has
    resolved the Header dependency (we pass the raw value through)."""
    return _app_module().verify_jwt(authorization=authorization)


def require_admin(claims: Dict[str, Any] = Depends(verify_jwt)) -> Dict[str, Any]:
    if "spm:admin" not in claims.get("roles", []):
        raise HTTPException(status_code=403, detail="spm:admin role required")
    return claims


def _tenant_from_claims(claims: Dict[str, Any], fallback: str = "t1") -> str:
    return _app_module()._tenant_from_claims(claims, fallback=fallback)

log = logging.getLogger(__name__)

# Mount path is `/agents` — the UI's Vite proxy (and the production
# Traefik / nginx config that mirrors it) strips the `/api/spm` prefix
# before forwarding to spm-api, so the user-visible URL is
# `/api/spm/agents/...` even though FastAPI sees `/agents/...`. Mirrors
# the convention already in use by integrations_routes.py.
router = APIRouter(prefix="/agents", tags=["agents"])


# ─── Disk layout for uploaded code ─────────────────────────────────────────

# Where agent.py files live INSIDE this container — written by POST /agents.
CODE_ROOT_CONTAINER = Path("./DataVolumes/agents")

# Host-equivalent of the same directory, populated by docker-compose. The
# docker daemon resolves bind-mount paths against the HOST filesystem, so
# we store the HOST path on the row's `code_path` column and pass that to
# spawn_agent_container() at deploy time. Falls back to the container
# path when AGENT_CODE_HOST_DIR is unset (test/dev mode where spawn is
# mocked anyway).
import os as _os
_AGENT_CODE_HOST_DIR = _os.environ.get("AGENT_CODE_HOST_DIR", "")


# ─── Serializer ────────────────────────────────────────────────────────────

# Fields safe to PATCH. mcp_token / llm_api_key / runtime_state are
# managed by the controller; code_path / code_sha256 are managed by the
# upload pipeline; tenant_id never changes for a row.
ALLOWED_PATCH_FIELDS = {
    "description", "owner", "risk", "policy_status",
    "version", "agent_type", "name",
}


def _safe_get(obj, name, default=None):
    """Read ``obj.name`` and tolerate any failure (lazy-load mishaps,
    detached instance, missing column on a partial select). The route
    returns ``default`` for that one field instead of 500-ing the
    whole response."""
    try:
        return getattr(obj, name, default)
    except Exception:                                     # noqa: BLE001
        return default


def _enum_value(v):
    if v is None:
        return None
    if hasattr(v, "value"):
        return v.value
    return v


def _iso(dt):
    try:
        return dt.isoformat() if dt else None
    except Exception:                                     # noqa: BLE001
        return None


def _to_dict(a: Agent, *, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Public JSON shape. NEVER includes mcp_token / llm_api_key.

    Every attribute access is wrapped in ``_safe_get`` so a single
    column hiccup (e.g. an expired-after-commit attribute that
    SQLAlchemy can't lazy-load in this async context) returns
    ``None`` for that field instead of bringing down the whole route.
    """
    d: Dict[str, Any] = {
        "id":             str(_safe_get(a, "id", "")),
        "name":           _safe_get(a, "name"),
        "version":        _safe_get(a, "version"),
        "agent_type":     _enum_value(_safe_get(a, "agent_type")),
        "provider":       _enum_value(_safe_get(a, "provider")),
        "owner":          _safe_get(a, "owner"),
        "description":    _safe_get(a, "description"),
        "risk":           _enum_value(_safe_get(a, "risk")),
        "policy_status":  _enum_value(_safe_get(a, "policy_status")),
        "runtime_state":  _enum_value(_safe_get(a, "runtime_state")),
        "code_path":      _safe_get(a, "code_path"),
        "code_sha256":    _safe_get(a, "code_sha256"),
        "tenant_id":      _safe_get(a, "tenant_id"),
        "created_at":     _iso(_safe_get(a, "created_at")),
        "updated_at":     _iso(_safe_get(a, "updated_at")),
        "last_seen_at":   _iso(_safe_get(a, "last_seen_at")),
    }
    if warnings is not None:
        d["warnings"] = warnings
    return d


# ─── POST /agents — upload + validate ──────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    name:         str        = Form(...),
    version:      str        = Form(...),
    agent_type:   str        = Form(...),
    owner:        Optional[str] = Form(None),
    description:  str        = Form(""),
    deploy_after: bool       = Form(True),
    code:         UploadFile = File(...),
    db = Depends(get_db),
    claims = Depends(require_admin),
):
    """Upload an ``agent.py``, validate it, persist the row, and
    optionally trigger deploy.

    Returns 201 + the agent JSON on success, 422 with the offending
    error list on validation failure.
    """
    raw = (await code.read()).decode("utf-8", errors="replace")
    res = validate_agent_code(raw)
    if not res.ok:
        raise HTTPException(status_code=422, detail=res.errors)

    agent_id  = uuid.uuid4()
    tenant_id = _tenant_from_claims(claims, fallback="t1")

    # Write to the container path; remember the host-equivalent so
    # spawn_agent_container can pass it through to the docker daemon.
    code_dir = CODE_ROOT_CONTAINER / str(agent_id)
    code_dir.mkdir(parents=True, exist_ok=True)
    code_file = code_dir / "agent.py"
    code_file.write_text(raw)
    sha = hashlib.sha256(raw.encode()).hexdigest()

    if _AGENT_CODE_HOST_DIR:
        host_code_path = (Path(_AGENT_CODE_HOST_DIR) / str(agent_id) / "agent.py").as_posix()
    else:
        host_code_path = str(code_file)

    mcp_t, llm_t = mint_agent_tokens()

    a = Agent(
        id=agent_id, name=name, version=version, agent_type=agent_type,
        provider="internal", owner=owner, description=description,
        code_path=host_code_path, code_sha256=sha,
        # Phase 4 — also store the raw text in the DB so the platform
        # owns the source of truth. spawn_agent_container rewrites the
        # bind-mount source from this on every spawn, so manual host
        # cleanup of DataVolumes/agents/<id>/agent.py is now safe.
        code_blob=raw,
        mcp_token=mcp_t, llm_api_key=llm_t,
        tenant_id=tenant_id, runtime_state="stopped",
    )
    db.add(a)
    try:
        await _maybe_async_commit(db)
    except Exception as e:                                # noqa: BLE001
        # Most common case: name+version+tenant unique constraint
        # already exists (operator re-registering without bumping
        # version). Return 409 with a clear message instead of a
        # raw 500 sqlalchemy traceback.
        msg = str(getattr(e, "orig", None) or e).lower()
        if "uq_agents_name_ver_tenant" in msg or "unique constraint" in msg:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"An agent named {name!r} version {version!r} already "
                    f"exists in this tenant. Bump the version or use a "
                    f"different name."
                ),
            )
        # Unknown DB failure — log and surface a 500.
        log.exception("create_agent: commit failed")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register agent: {e}",
        )
    await _maybe_async_refresh(db, a)

    if deploy_after:
        try:
            await deploy_agent(db, agent_id)
        except Exception as e:                            # noqa: BLE001
            # Deploy failures shouldn't lose the row — the operator
            # can fix and retry via the start endpoint. Log and keep.
            log.warning("deploy after upload failed: %s", e)

    # deploy_agent's commit expires server-side-modified columns
    # (updated_at via onupdate=func.now). Refresh once more so the
    # subsequent _to_dict can read every column without triggering
    # a sync lazy-load → MissingGreenlet inside this async route.
    try:
        await _maybe_async_refresh(db, a)
    except Exception as e:                                # noqa: BLE001
        log.warning("create_agent: post-deploy refresh failed: %s", e)

    return _to_dict(a, warnings=res.warnings)


# ─── GET /agents — list ────────────────────────────────────────────────────

@router.get("")
async def list_agents(
    db = Depends(get_db),
    claims = Depends(verify_jwt),
):
    """List agents in the caller's tenant. V1 falls back to ``"t1"`` if
    the JWT lacks a tenant claim — matches the migration seed."""
    tenant_id = _tenant_from_claims(claims, fallback="t1")
    rows = await _list_agents_in_tenant(db, tenant_id)
    return [_to_dict(a) for a in rows]


# ─── GET /agents/{id} — detail ─────────────────────────────────────────────

@router.get("/{agent_id}")
async def get_agent(
    agent_id: str = PathParam(...),
    db = Depends(get_db),
    _claims = Depends(verify_jwt),
):
    a = await _get_agent_or_none(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return _to_dict(a)


# ─── PATCH /agents/{id} ────────────────────────────────────────────────────

@router.patch("/{agent_id}")
async def patch_agent(
    agent_id: str,
    body: Dict[str, Any],
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    a = await _get_agent_or_none(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")

    unknown = set(body.keys()) - ALLOWED_PATCH_FIELDS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown / disallowed fields: {sorted(unknown)}",
        )

    for k, v in body.items():
        setattr(a, k, v)
    await _maybe_async_commit(db)
    await _maybe_async_refresh(db, a)
    return _to_dict(a)


# ─── POST /agents/{id}/start | /stop ───────────────────────────────────────

@router.post("/{agent_id}/start", status_code=status.HTTP_202_ACCEPTED)
async def start_endpoint(
    agent_id: str,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    await start_agent(db, agent_id)
    return {"status": "starting"}


@router.post("/{agent_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_endpoint(
    agent_id: str,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    await stop_agent(db, agent_id)
    return {"status": "stopping"}


# ─── DELETE /agents/{id} ───────────────────────────────────────────────────

@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    agent_id: str,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    await retire_agent(db, agent_id)
    # 204 — body must be empty.
    return None


# ─── POST /agents/{id}/ready — Phase 2 SDK handshake ───────────────────────
#
# Called by ``aispm.lifecycle.ready()`` from inside the agent's
# container. Auth is the agent's own ``mcp_token`` — proves the caller
# is the agent we just spawned. Flips ``runtime_state`` to ``running``
# and stamps ``last_seen_at``; the controller's deploy_agent poll loop
# observes the transition and returns.

async def _resolve_agent_by_mcp_token(authorization: Optional[str]) -> Dict[str, Any]:
    """Resolve a Bearer header to the corresponding agent dict via the
    shared ``platform_shared.agent_tokens`` helper. Raises 401 on miss."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    from platform_shared.agent_tokens import resolve_agent_by_mcp_token
    token = authorization.removeprefix("Bearer ").strip()
    agent = await resolve_agent_by_mcp_token(token)
    if agent is None:
        raise HTTPException(status_code=401, detail="Unknown agent token")
    return agent


# ─── GET /agents/{id}/bootstrap — SDK boot-time DB read ────────────────────
#
# The agent's ``aispm`` SDK calls this on first import to learn its
# connection info (tenant_id, MCP / LLM / Kafka URLs, llm_api_key).
# Source of truth is the DB row + the controller's view of platform
# URLs — the SDK doesn't read those from env vars.
#
# Auth: the agent's own ``mcp_token`` (Bearer header). Only that agent
# can fetch its own bootstrap; cross-agent reads → 403.

def _platform_urls() -> Dict[str, str]:
    """Single canonical place for the in-cluster service URLs handed to
    every agent. Kept in the controller (not the SDK) so operators can
    re-target a deploy without rebuilding agent images."""
    from agent_controller import (
        _AGENT_MCP_URL,
        _AGENT_LLM_BASE_URL,
        _KAFKA_BOOTSTRAP,
    )
    return {
        "mcp_url":                 _AGENT_MCP_URL,
        "llm_base_url":            _AGENT_LLM_BASE_URL,
        "kafka_bootstrap_servers": _KAFKA_BOOTSTRAP,
    }


@router.get("/{agent_id}/bootstrap")
async def bootstrap_endpoint(
    agent_id: str,
    authorization: Optional[str] = Header(None),
    db = Depends(get_db),
):
    """Return the agent's connection bundle, sourced from the DB.

    Response shape::

        {
          "agent_id":    "...",
          "tenant_id":   "t1",
          "mcp_url":     "http://spm-mcp:8500/mcp",
          "llm_base_url":"http://spm-llm-proxy:8500/v1",
          "llm_api_key": "spm-llm-...",
          "kafka_bootstrap_servers": "kafka-broker:9092"
        }

    Read once by ``aispm`` on import; values flow into the SDK's module
    constants. Bearer must be the agent's own mcp_token.
    """
    caller = await _resolve_agent_by_mcp_token(authorization)
    if str(caller["id"]) != str(agent_id):
        raise HTTPException(status_code=403,
                             detail="Bearer token does not match agent_id")

    a = await _get_agent_or_none(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")

    urls = _platform_urls()
    return {
        "agent_id":                str(getattr(a, "id", agent_id)),
        "tenant_id":               str(getattr(a, "tenant_id", "") or ""),
        "mcp_url":                 urls["mcp_url"],
        "llm_base_url":            urls["llm_base_url"],
        "llm_api_key":             str(getattr(a, "llm_api_key", "") or ""),
        "kafka_bootstrap_servers": urls["kafka_bootstrap_servers"],
    }


@router.post("/{agent_id}/ready", status_code=status.HTTP_204_NO_CONTENT)
async def ready_endpoint(
    agent_id: str,
    authorization: Optional[str] = Header(None),
    db = Depends(get_db),
):
    """Idempotent — calling this multiple times keeps the agent in
    ``running`` and refreshes ``last_seen_at``.

    Auth is by the agent's own ``mcp_token``: a third party cannot
    flip another agent's state. The bearer must resolve to an agent
    whose ``id`` matches the path parameter; mismatch → 403.
    """
    caller = await _resolve_agent_by_mcp_token(authorization)
    if str(caller["id"]) != str(agent_id):
        raise HTTPException(status_code=403,
                             detail="Bearer token does not match agent_id")

    a = await _get_agent_or_none(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")

    from datetime import datetime, timezone
    a.runtime_state = "running"
    a.last_seen_at  = datetime.now(timezone.utc)
    await _maybe_async_commit(db)
    return None


# ─── GET /agents/{id}/secrets/{name} — Phase 2 ─────────────────────────────

@router.get("/{agent_id}/secrets/{name}")
async def get_secret_endpoint(
    agent_id: str,
    name: str,
    authorization: Optional[str] = Header(None),
    db = Depends(get_db),
):
    """Return ``{"value": str}`` for a per-agent secret.

    V1 stores per-agent secrets in ``agents.config.env_vars[name]``
    (added in this phase — the column was placeholder-shaped before).
    V2 will move the storage to ``integration_credentials`` keyed by
    ``(agent:{id}, name)`` so existing encryption applies; the wire
    surface stays the same.

    Auth is by the agent's own ``mcp_token`` — only the agent itself
    can read its secrets. 404 when the secret is missing.
    """
    caller = await _resolve_agent_by_mcp_token(authorization)
    if str(caller["id"]) != str(agent_id):
        raise HTTPException(status_code=403,
                             detail="Bearer token does not match agent_id")

    a = await _get_agent_or_none(db, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")

    env_vars = (getattr(a, "config", None) or {}).get("env_vars") or {}
    if name not in env_vars:
        raise HTTPException(status_code=404, detail=f"secret {name!r} not configured")
    return {"value": str(env_vars[name])}


# ─── GET /agents/{id}/sessions/{sid}/messages — Phase 2 ────────────────────

@router.get("/{agent_id}/sessions/{session_id}/messages")
async def session_messages_endpoint(
    agent_id: str,
    session_id: str,
    limit: int = 10,
    authorization: Optional[str] = Header(None),
    db = Depends(get_db),
):
    """Return the last *limit* persisted messages for a session.

    Used by ``aispm.chat.history()``. Same agent-token auth as the
    other Phase 2 endpoints; the session must belong to the calling
    agent.
    """
    caller = await _resolve_agent_by_mcp_token(authorization)
    if str(caller["id"]) != str(agent_id):
        raise HTTPException(status_code=403,
                             detail="Bearer token does not match agent_id")

    if hasattr(db, "execute"):
        from sqlalchemy import select  # type: ignore
        from spm.db.models import (    # type: ignore
            AgentChatMessage, AgentChatSession,
        )
        # Verify session belongs to this agent, then fetch its tail.
        sess_stmt = (
            select(AgentChatSession)
            .where(AgentChatSession.id == session_id)
            .where(AgentChatSession.agent_id == agent_id)
        )
        sess = (await db.execute(sess_stmt)).scalar_one_or_none()
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")

        msg_stmt = (
            select(AgentChatMessage)
            .where(AgentChatMessage.session_id == session_id)
            .order_by(AgentChatMessage.ts.desc())
            .limit(max(1, min(int(limit), 200)))
        )
        rows = list((await db.execute(msg_stmt)).scalars().all())
    else:                                                      # mock path
        rows = list(getattr(db, "messages_for", lambda *_: [])(
            agent_id, session_id, limit
        ))

    rows.reverse()  # chronological order; the query was DESC for the LIMIT
    return [
        {
            "role": (m.role.value if hasattr(m.role, "value") else m.role),
            "text": m.text,
            "ts":   m.ts.isoformat() if m.ts else None,
        }
        for m in rows
    ]


# ─── GET /agents/{id}/activity — Phase 4.5 unified activity tail ───────────
#
# Returns the last N events for one agent across:
#   • agent_chat_messages          — user/agent turns (populated by
#                                    agent_chat.py on every chat round-trip)
#   • session_events filtered      — AgentToolCall / AgentLLMCall events
#     by agent_id                    (populated by the global lineage_consumer
#                                    when spm-mcp / spm-llm-proxy emit them)
#
# Auth: admin JWT (the UI's dev-token has admin role). The endpoint is
# operator-facing — agents themselves don't need it.

@router.get("/{agent_id}/activity")
async def agent_activity_endpoint(
    agent_id: str,
    limit: int = 50,
    db = Depends(get_db),
    _claims = Depends(require_admin),
):
    """Return the most recent activity entries for one agent, newest-first.

    Each entry is shaped like::

        {
          "ts":         "2026-04-25T17:09:30.057170+00:00",
          "kind":       "chat" | "tool_call" | "llm_call",
          "session_id": "...",        # for chat rows; synthetic for tool/llm
          "role":       "user|agent", # chat only
          "text":       "...",        # chat only
          "tool":       "web_fetch",  # tool_call only
          "ok":         true,         # tool_call / llm_call
          "duration_ms":140,          # tool_call
          "model":      "...",        # llm_call
          "prompt_tokens": 12,        # llm_call
          "completion_tokens": 47,    # llm_call
          "trace_id":   "..."
        }

    Tail is capped to 200 to keep responses bounded; the UI polls
    every 5 s and renders newest-first.
    """
    cap = max(1, min(int(limit), 200))
    out = []

    if hasattr(db, "execute"):
        from sqlalchemy import select   # type: ignore
        from spm.db.models import AgentChatMessage, AgentChatSession  # type: ignore

        # 1. chat turns for any session belonging to this agent
        chat_stmt = (
            select(AgentChatMessage, AgentChatSession.id)
            .join(AgentChatSession,
                   AgentChatSession.id == AgentChatMessage.session_id)
            .where(AgentChatSession.agent_id == agent_id)
            .order_by(AgentChatMessage.ts.desc())
            .limit(cap)
        )
        for m, sid in (await db.execute(chat_stmt)).all():
            out.append({
                "ts":         m.ts.isoformat() if m.ts else None,
                "kind":       "chat",
                "session_id": str(sid),
                "role":       (m.role.value if hasattr(m.role, "value") else m.role),
                "text":       m.text,
                "trace_id":   getattr(m, "trace_id", None),
            })

        # 2. lineage events filtered by agent_id (best-effort — the
        # session_events table lives in the agent-orchestrator-service
        # DB schema, accessed via the same engine if it's reachable).
        # Wrapped in try so a missing table on a fresh dev box doesn't
        # break the UI.
        try:
            from sqlalchemy import text
            ev_rows = (await db.execute(
                text(
                    "SELECT timestamp, event_type, payload "
                    "FROM   session_events "
                    "WHERE  payload::text LIKE :needle "
                    "       OR session_id LIKE :prefix "
                    "ORDER BY timestamp DESC "
                    "LIMIT  :cap"
                ),
                {
                    "needle": f'%"agent_id": "{agent_id}"%',
                    "prefix": f"agent-{agent_id}-runtime",
                    "cap":    cap,
                },
            )).all()
            for ts, etype, raw_payload in ev_rows:
                import json as _json
                try:
                    p = _json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
                except Exception:
                    p = {}
                row = {
                    "ts":       ts.isoformat() if ts else None,
                    "kind":     ("tool_call" if etype == "AgentToolCall"
                                  else "llm_call" if etype == "AgentLLMCall"
                                  else etype.lower()),
                    "trace_id": p.get("trace_id"),
                    "ok":       p.get("ok", True),
                }
                if etype == "AgentToolCall":
                    row["tool"]        = p.get("tool")
                    row["duration_ms"] = p.get("duration_ms")
                elif etype == "AgentLLMCall":
                    row["model"]              = p.get("model")
                    row["prompt_tokens"]      = p.get("prompt_tokens")
                    row["completion_tokens"]  = p.get("completion_tokens")
                out.append(row)
        except Exception:                                  # noqa: BLE001
            # session_events not reachable — return chat-only timeline.
            pass

    # Sort the unified list newest-first and cap.
    out.sort(key=lambda r: r.get("ts") or "", reverse=True)
    return out[:cap]


# ─── DB helpers — async-vs-sync session compatibility ──────────────────────
#
# The dependency ``get_db`` yields an ``AsyncSession`` in production but
# tests sometimes hand in a sync ``MagicMock``. These helpers normalize
# the call sites so the route code reads cleanly either way.

async def _maybe_async_commit(db) -> None:
    fn = getattr(db, "commit", None)
    if fn is None:
        return
    res = fn()
    if hasattr(res, "__await__"):
        await res


async def _maybe_async_refresh(db, obj) -> None:
    fn = getattr(db, "refresh", None)
    if fn is None:
        return
    res = fn(obj)
    if hasattr(res, "__await__"):
        await res


async def _get_agent_or_none(db, agent_id) -> Optional[Agent]:
    res = db.get(Agent, agent_id)
    if hasattr(res, "__await__"):
        return await res
    return res


async def _list_agents_in_tenant(db, tenant_id: str) -> List[Agent]:
    """Return all agents in *tenant_id*. Works against both AsyncSession
    and sync mock sessions — the latter just returns from ``db.query()``.
    """
    # Real path: AsyncSession with execute(select).
    if hasattr(db, "execute"):
        from sqlalchemy import select  # type: ignore
        result = await db.execute(
            select(Agent).where(Agent.tenant_id == tenant_id)
        )
        return list(result.scalars().all())
    # Fallback for legacy / sync mocks.
    return list(db.query(Agent).filter(Agent.tenant_id == tenant_id).all())
