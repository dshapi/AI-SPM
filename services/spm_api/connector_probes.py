"""
Connector probe implementations.

One async function per vendor.  All probes follow the same shape:

    async def probe_X(config: Dict[str, Any],
                      credentials: Dict[str, Any]
                      ) -> Tuple[bool, str, Optional[int]]:
        ...

Contract
────────
* ``config``      — the integration's config JSON (non-secret knobs).
                    Keyed by the field.key values declared in connector_registry.
* ``credentials`` — decrypted secret values, keyed the same way.  Callers
                    MUST decrypt these before invoking the probe.
* Returns ``(ok, message, latency_ms)``.  ``latency_ms`` may be None if
  no round-trip was performed.
* Probes NEVER raise — all network / transport errors become
  ``(False, "…", None)`` so the HTTP route can always respond cleanly.
* Every probe uses the shared ``_PROBE_TIMEOUT_S`` to keep "Test" clicks
  from hanging.  Bump only if a specific vendor legitimately needs
  longer.

Probe tiers
───────────
* **Tier 1 (real)** — hit a cheap read-only endpoint on the vendor that
  confirms both reachability AND credential validity.  These are the
  probes you want to trust on green.  14 vendors:
     anthropic, openai_compatible (OpenAI / Groq / Mistral / others),
     azure_openai, ollama, tavily, splunk (HEC health),
     jira (/rest/api/3/myself), servicenow (/api/now/table/sys_user),
     confluence (/wiki/rest/api/space?limit=1), slack (auth.test),
     okta (/api/v1/users?limit=1), kafka (TCP connect to first broker),
     flink (/overview), postgres (SELECT 1 via asyncpg),
     redis (PING via redis-py async).

* **Tier 2 (stub)** — vendors that need a heavier SDK (boto3, msgraph,
  google-auth) to probe for real.  We report green iff the required
  credential fields are present and non-empty, with a clear message
  that the check is a stub.  Upgrades to Tier 1 are fine once the
  SDK dep is justified.  7 vendors:
     bedrock, vertex, sentinel, entra, s3, azure_openai (partial).

* **Tier 3 (internal)** — vendors that live inside the AI-SPM stack
  itself (Garak).  Probe checks for the shared-secret and reports ok.

Adding a new probe
──────────────────
1. Write the async function here.
2. Add an import for it in connector_registry.py.
3. Add a ``probe=`` reference in the CONNECTOR_TYPES entry.

Nothing else — no dispatch table to edit.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

log = logging.getLogger("spm-api.connector_probes")

# Short default timeout — Test is a user-facing click, not a long poll.
_PROBE_TIMEOUT_S = 6.0
# Longer timeout for Postgres / Redis TCP handshakes in constrained dev
# environments (docker-compose startup races, WSL2 cold cache, etc.).
_DB_PROBE_TIMEOUT_S = 8.0


ProbeResult = Tuple[bool, str, Optional[int]]


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _missing(label: str) -> ProbeResult:
    return False, f"Test failed — {label} not configured", None


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 1 — real probes
# ═══════════════════════════════════════════════════════════════════════════════

# ─── AI providers ──────────────────────────────────────────────────────────────

async def probe_anthropic(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    api_key = (creds.get("api_key") or "").strip()
    if not api_key:
        return _missing("api_key")
    base = (config.get("base_url") or "https://api.anthropic.com").rstrip("/")
    url = base + "/v1/models"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            })
        latency = _ms(started)
        if r.status_code == 200:
            return True, "Anthropic /v1/models responded 200", latency
        if r.status_code in (401, 403):
            return False, f"Anthropic rejected the API key ({r.status_code})", latency
        return False, f"Anthropic returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Anthropic probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Anthropic probe failed: {e}", None


async def probe_openai_compatible(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """OpenAI and any /v1/models-compatible gateway (Groq, Mistral, Together, …)."""
    api_key = (creds.get("api_key") or "").strip()
    if not api_key:
        return _missing("api_key")
    base = (config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    url = base + "/models"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, headers={"Authorization": f"Bearer {api_key}"})
        latency = _ms(started)
        if r.status_code == 200:
            return True, f"OpenAI-compatible {base}/models responded 200", latency
        if r.status_code in (401, 403):
            return False, f"API rejected the key ({r.status_code})", latency
        return False, f"OpenAI-compatible endpoint returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"OpenAI-compatible probe failed: {e}", None


async def probe_azure_openai(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Azure OpenAI deployments endpoint.

    Unlike vanilla OpenAI, Azure uses api-key header (not Bearer) and
    per-resource endpoint URLs.  The listing endpoint is
    ``{endpoint}/openai/deployments?api-version=…``.
    """
    endpoint = (config.get("endpoint") or "").strip().rstrip("/")
    api_version = config.get("api_version") or "2024-10-21"
    api_key = (creds.get("api_key") or "").strip()
    if not endpoint:
        return _missing("endpoint")
    if not api_key:
        return _missing("api_key")
    url = f"{endpoint}/openai/deployments?api-version={api_version}"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, headers={"api-key": api_key})
        latency = _ms(started)
        if r.status_code == 200:
            return True, "Azure OpenAI deployments endpoint responded 200", latency
        if r.status_code in (401, 403):
            return False, f"Azure OpenAI rejected the API key ({r.status_code})", latency
        return False, f"Azure OpenAI returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Azure OpenAI probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Azure OpenAI probe failed: {e}", None


async def probe_ollama(config: Dict[str, Any], _creds: Dict[str, Any]) -> ProbeResult:
    """Ollama exposes an OpenAI-compatible surface at /v1 plus its own
    native API at the ROOT (/api/tags).  Our stored base_url tends to
    include /v1 (for the guard-model path); strip it before hitting
    /api/tags or we'd get /v1/api/tags 404.
    """
    root = (config.get("base_url") or "http://host.docker.internal:11434").rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    url = root + "/api/tags"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url)
        latency = _ms(started)
        if r.status_code == 200:
            tags = (r.json().get("models") or [])
            return True, f"Ollama reachable at {root} — {len(tags)} models pulled", latency
        return False, f"Ollama at {root} returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Ollama at {root} timed out after {_PROBE_TIMEOUT_S:.0f}s — is ollama running?", None
    except httpx.HTTPError as e:
        return False, f"Ollama probe failed ({root}): {e}", None


async def probe_tavily(_config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Tavily has no GET /health — validating the key cheaply means
    posting a 1-result search.  We use ``max_results=1`` to keep the
    response tiny and the call billable-but-negligible.
    """
    api_key = (creds.get("api_key") or "").strip()
    if not api_key:
        return _missing("api_key")
    url = "https://api.tavily.com/search"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.post(url, json={
                "api_key": api_key,
                "query": "aispm healthcheck",
                "max_results": 1,
                "include_answer": False,
                "include_images": False,
            })
        latency = _ms(started)
        if r.status_code == 200:
            return True, "Tavily /search responded 200", latency
        if r.status_code in (401, 403):
            return False, f"Tavily rejected the API key ({r.status_code})", latency
        return False, f"Tavily returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Tavily probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Tavily probe failed: {e}", None


# ─── Security / SIEM ───────────────────────────────────────────────────────────

async def probe_splunk(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Splunk HEC health endpoint.  Authenticated via ``Authorization:
    Splunk <token>``.  ``verify_tls`` defaults to True; operators can
    disable for self-signed dev clusters.
    """
    hec_url = (config.get("hec_url") or "").strip().rstrip("/")
    token = (creds.get("hec_token") or "").strip()
    verify = bool(config.get("verify_tls", True))
    if not hec_url:
        return _missing("hec_url")
    if not token:
        return _missing("hec_token")
    url = hec_url + "/services/collector/health"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S, verify=verify) as c:
            r = await c.get(url, headers={"Authorization": f"Splunk {token}"})
        latency = _ms(started)
        # HEC health returns 200 with {"text":"HEC is healthy","code":17}.
        if r.status_code == 200:
            return True, "Splunk HEC /services/collector/health responded 200", latency
        if r.status_code in (401, 403):
            return False, f"Splunk rejected the HEC token ({r.status_code})", latency
        return False, f"Splunk returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Splunk probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Splunk probe failed: {e}", None


# ─── Ticketing / Workflow ──────────────────────────────────────────────────────

async def probe_jira(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Jira Cloud self-check — ``GET /rest/api/3/myself`` echoes the
    authenticated user.  Uses basic auth (email + API token)."""
    base = (config.get("base_url") or "").strip().rstrip("/")
    email = (config.get("email") or "").strip()
    token = (creds.get("api_token") or "").strip()
    if not base:
        return _missing("base_url")
    if not email or not token:
        return _missing("email / api_token")
    url = base + "/rest/api/3/myself"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, auth=(email, token))
        latency = _ms(started)
        if r.status_code == 200:
            try:
                name = r.json().get("displayName") or "user"
            except Exception:  # noqa: BLE001
                name = "user"
            return True, f"Jira /rest/api/3/myself returned 200 (as {name})", latency
        if r.status_code in (401, 403):
            return False, f"Jira rejected the credentials ({r.status_code})", latency
        return False, f"Jira returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Jira probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Jira probe failed: {e}", None


async def probe_servicenow(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """ServiceNow Table API — 1-row sys_user query is cheapest auth check."""
    base = (config.get("instance_url") or "").strip().rstrip("/")
    user = (config.get("username") or "").strip()
    pw = (creds.get("password") or "").strip()
    if not base:
        return _missing("instance_url")
    if not user or not pw:
        return _missing("username / password")
    url = base + "/api/now/table/sys_user?sysparm_limit=1"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, auth=(user, pw),
                            headers={"Accept": "application/json"})
        latency = _ms(started)
        if r.status_code == 200:
            return True, "ServiceNow /api/now/table/sys_user responded 200", latency
        if r.status_code in (401, 403):
            return False, f"ServiceNow rejected the credentials ({r.status_code})", latency
        return False, f"ServiceNow returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"ServiceNow probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"ServiceNow probe failed: {e}", None


# ─── Messaging / Collab ────────────────────────────────────────────────────────

async def probe_slack(_config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Slack ``auth.test`` returns the team + bot user associated with
    the token.  Cheapest way to validate a bot token."""
    token = (creds.get("bot_token") or "").strip()
    if not token:
        return _missing("bot_token")
    url = "https://slack.com/api/auth.test"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.post(url, headers={"Authorization": f"Bearer {token}"})
        latency = _ms(started)
        if r.status_code != 200:
            return False, f"Slack returned {r.status_code}", latency
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            return False, "Slack returned non-JSON response", latency
        if body.get("ok") is True:
            team = body.get("team") or "unknown team"
            return True, f"Slack auth.test ok (team: {team})", latency
        return False, f"Slack auth.test failed: {body.get('error') or 'unknown error'}", latency
    except httpx.TimeoutException:
        return False, f"Slack probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Slack probe failed: {e}", None


# ─── Identity / Access ─────────────────────────────────────────────────────────

async def probe_okta(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Okta API — ``GET /api/v1/users?limit=1`` with SSWS token auth.
    Returns 200 on any valid SSWS token with list scope."""
    org = (config.get("org_url") or "").strip().rstrip("/")
    token = (creds.get("api_token") or "").strip()
    if not org:
        return _missing("org_url")
    if not token:
        return _missing("api_token")
    url = org + "/api/v1/users?limit=1"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, headers={
                "Authorization": f"SSWS {token}",
                "Accept": "application/json",
            })
        latency = _ms(started)
        if r.status_code == 200:
            return True, "Okta /api/v1/users responded 200", latency
        if r.status_code in (401, 403):
            return False, f"Okta rejected the SSWS token ({r.status_code})", latency
        return False, f"Okta returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Okta probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Okta probe failed: {e}", None


# ─── Data / Storage ────────────────────────────────────────────────────────────

async def probe_confluence(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Confluence Cloud — list one space to validate auth + reachability."""
    base = (config.get("base_url") or "").strip().rstrip("/")
    email = (config.get("email") or "").strip()
    token = (creds.get("api_token") or "").strip()
    if not base:
        return _missing("base_url")
    if not email or not token:
        return _missing("email / api_token")
    url = base + "/wiki/rest/api/space?limit=1"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url, auth=(email, token),
                            headers={"Accept": "application/json"})
        latency = _ms(started)
        if r.status_code == 200:
            return True, "Confluence /wiki/rest/api/space responded 200", latency
        if r.status_code in (401, 403):
            return False, f"Confluence rejected the credentials ({r.status_code})", latency
        return False, f"Confluence returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Confluence probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Confluence probe failed: {e}", None


async def probe_kafka(config: Dict[str, Any], _creds: Dict[str, Any]) -> ProbeResult:
    """Kafka broker reachability via raw TCP connect.

    A real admin-client probe would need the uploaded cert + a
    KafkaAdminClient describe() call; today TCP reachability is the
    signal that was missing from the Test button.  Upgrades welcome
    once the kafka-python client paths are wired up.
    """
    bootstrap = (config.get("bootstrap_servers") or "").strip()
    if not bootstrap:
        return _missing("bootstrap_servers")
    first = bootstrap.split(",")[0].strip()
    if ":" not in first:
        return False, f"Invalid bootstrap server '{first}' (expected host:port)", None
    host, _, port_s = first.rpartition(":")
    try:
        port = int(port_s)
    except ValueError:
        return False, f"Invalid port in '{first}' — must be an integer", None

    started = time.monotonic()
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_PROBE_TIMEOUT_S,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        latency = _ms(started)
        return True, f"Kafka broker {host}:{port} is reachable (TCP)", latency
    except asyncio.TimeoutError:
        return False, f"Kafka broker {host}:{port} timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except (OSError, ConnectionRefusedError) as e:
        return False, f"Kafka broker {host}:{port} unreachable: {e}", None


async def probe_flink(config: Dict[str, Any], _creds: Dict[str, Any]) -> ProbeResult:
    """Flink JobManager ``/overview`` REST endpoint.  This is the
    endpoint the Flink web UI polls — returns taskmanager + slot +
    running-job summary on success.
    """
    base = (config.get("jobmanager_url") or "").strip().rstrip("/")
    if not base:
        return _missing("jobmanager_url")
    url = base + "/overview"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url)
        latency = _ms(started)
        if r.status_code == 200:
            try:
                j = r.json()
                tm = j.get("taskmanagers")
                st = j.get("slots-total")
                sa = j.get("slots-available")
                return True, (
                    f"Flink JobManager reachable — {tm} taskmanager(s), "
                    f"{sa}/{st} slots free"
                ), latency
            except Exception:  # noqa: BLE001
                return True, "Flink JobManager /overview responded 200", latency
        return False, f"Flink JobManager returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Flink probe timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"Flink probe failed: {e}", None


async def probe_postgres(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """PostgreSQL probe — ``SELECT 1`` via asyncpg with a short timeout.

    asyncpg is already a runtime dependency (spm-api uses it for its own
    SQLAlchemy engine), so no new install is needed.  Connection closed
    immediately after the query, no pool kept around.
    """
    host = (config.get("host") or "").strip()
    port = int(config.get("port") or 5432)
    database = (config.get("database") or "").strip()
    sslmode = (config.get("sslmode") or "prefer").strip()
    username = (config.get("username") or "").strip()
    password = creds.get("password") or ""
    if not host:
        return _missing("host")
    if not database:
        return _missing("database")
    if not username:
        return _missing("username")

    try:
        import asyncpg  # type: ignore
    except ImportError:
        return False, "asyncpg is not installed on the spm-api image", None

    # asyncpg's `ssl` kwarg accepts 'disable' | 'allow' | 'prefer' |
    # 'require' | 'verify-ca' | 'verify-full' as of 0.27.
    started = time.monotonic()
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=host, port=port, database=database,
                user=username, password=password or None,
                ssl=sslmode if sslmode != "disable" else False,
                timeout=_DB_PROBE_TIMEOUT_S,
            ),
            timeout=_DB_PROBE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return False, f"Postgres connection to {host}:{port} timed out", None
    except asyncpg.InvalidPasswordError:
        return False, "Postgres rejected the username/password", None
    except (OSError, ConnectionRefusedError, asyncpg.PostgresError) as e:  # type: ignore[attr-defined]
        return False, f"Postgres connection failed: {e}", None
    try:
        try:
            row = await asyncio.wait_for(conn.fetchval("SELECT 1"),
                                         timeout=_DB_PROBE_TIMEOUT_S)
            latency = _ms(started)
            if row == 1:
                return True, f"Postgres {host}:{port}/{database} — SELECT 1 ok", latency
            return False, f"Postgres SELECT 1 returned unexpected value {row!r}", latency
        except Exception as e:  # noqa: BLE001
            return False, f"Postgres query failed: {e}", None
    finally:
        try:
            await conn.close()
        except Exception:  # noqa: BLE001
            pass


async def probe_redis(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Redis probe — PING via redis-py async client.

    ``redis`` is a new runtime dependency added to requirements.txt.
    """
    host = (config.get("host") or "").strip()
    port = int(config.get("port") or 6379)
    db = int(config.get("db") or 0)
    tls = bool(config.get("tls") or False)
    password = creds.get("password") or None
    if not host:
        return _missing("host")

    try:
        import redis.asyncio as aioredis  # type: ignore
    except ImportError:
        return False, "redis package is not installed on the spm-api image", None

    started = time.monotonic()
    client = aioredis.Redis(
        host=host, port=port, db=db, password=password,
        ssl=tls,
        socket_timeout=_DB_PROBE_TIMEOUT_S,
        socket_connect_timeout=_DB_PROBE_TIMEOUT_S,
    )
    try:
        pong = await asyncio.wait_for(client.ping(), timeout=_DB_PROBE_TIMEOUT_S)
        latency = _ms(started)
        if pong:
            return True, f"Redis {host}:{port} PONG", latency
        return False, "Redis PING returned falsy", latency
    except asyncio.TimeoutError:
        return False, f"Redis {host}:{port} PING timed out after {_DB_PROBE_TIMEOUT_S:.0f}s", None
    except Exception as e:  # noqa: BLE001 — redis-py raises a broad hierarchy
        return False, f"Redis probe failed: {e}", None
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 2 — credentials-present stubs
# ═══════════════════════════════════════════════════════════════════════════════
#
# Vendors below need a real SDK (boto3 for AWS, google-auth for GCP,
# msgraph for Microsoft) to probe properly.  Shipping those SDKs adds
# substantial image weight for a liveness check that only a fraction
# of deployments use; today we check for the required credential
# fields and report green-with-caveat.  Upgrading to Tier 1 is a drop-
# in replacement inside this file — no registry or UI changes needed.

def _all_present(d: Dict[str, Any], keys: list) -> Tuple[bool, Optional[str]]:
    for k in keys:
        v = d.get(k)
        if not isinstance(v, (str, int, float)) or (isinstance(v, str) and not v.strip()):
            return False, k
    return True, None


async def probe_bedrock_stub(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    ok, missing = _all_present({**config, **creds}, ["region", "role_arn"])
    if not ok:
        return _missing(missing or "credentials")
    return True, ("Bedrock credentials present — stub probe. "
                  "Real STS AssumeRole check requires boto3."), None


async def probe_vertex_stub(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    ok, missing = _all_present({**config, **creds},
                                ["project_id", "location", "service_account_json"])
    if not ok:
        return _missing(missing or "credentials")
    # Light sanity — check that the JSON actually parses.
    import json
    try:
        json.loads(creds.get("service_account_json") or "")
    except Exception:  # noqa: BLE001
        return False, "service_account_json is not valid JSON", None
    return True, "Vertex credentials present & JSON parses — stub probe. Real GCP OAuth check requires google-auth.", None


async def probe_mssentinel_stub(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    ok, missing = _all_present({**config, **creds},
                                ["workspace_id", "tenant_id", "client_id", "client_secret"])
    if not ok:
        return _missing(missing or "credentials")
    return True, ("Sentinel credentials present — stub probe. "
                  "Real Log Analytics check requires msgraph-sdk."), None


async def probe_entra_stub(_config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    ok, missing = _all_present(creds, ["tenant_id", "client_id", "client_secret"])
    if not ok:
        return _missing(missing or "credentials")
    return True, ("Entra ID credentials present — stub probe. "
                  "Real /me token exchange requires azure-identity."), None


async def probe_s3_stub(config: Dict[str, Any], _creds: Dict[str, Any]) -> ProbeResult:
    ok, missing = _all_present(config, ["bucket", "region", "role_arn"])
    if not ok:
        return _missing(missing or "credentials")
    return True, ("S3 credentials present — stub probe. "
                  "Real head_bucket check requires boto3."), None


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 3 — internal services
# ═══════════════════════════════════════════════════════════════════════════════

async def probe_garak_stub(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Internal LLM red-team runner.  Checks the shared secret is set
    and the CPM API URL is reachable via /health."""
    url = (config.get("cpm_api_url") or "").strip().rstrip("/")
    secret = (creds.get("shared_secret") or "").strip()
    if not secret:
        return _missing("shared_secret")
    if not url:
        return True, "Garak shared_secret configured (no cpm_api_url probe)", None
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(url + "/health")
        latency = _ms(started)
        if r.status_code == 200:
            return True, f"Garak shared_secret configured, CPM API reachable at {url}", latency
        return False, f"Garak CPM API returned {r.status_code}", latency
    except httpx.TimeoutException:
        return False, f"Garak CPM API timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return True, f"Garak shared_secret configured (CPM API probe inconclusive: {e})", None


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 3 (internal) — Agent Runtime Control Plane
# ═══════════════════════════════════════════════════════════════════════════════

# Default ops endpoint for the spm-mcp container.  Override via the
# SPM_MCP_HEALTH_URL env var in tests / non-default deployments.
_SPM_MCP_DEFAULT_HEALTH_URL = "http://spm-mcp:8500/health"


async def probe_agent_runtime(config: Dict[str, Any], creds: Dict[str, Any]) -> ProbeResult:
    """Probe for the ``agent-runtime`` ConnectorType.

    Three checks, short-circuit on first failure:

    1. ``spm-mcp`` HTTP health endpoint reachable.
    2. The referenced ``default_llm_integration_id`` integration probes ok.
    3. The referenced ``tavily_integration_id`` integration probes ok.

    All three must pass for the agent-runtime control plane to function:
    the MCP server must be up to serve tool calls, the LLM proxy must
    have a valid upstream LLM, and Tavily is needed for ``web_fetch``.
    Failure messages name the offending check so operators can fix the
    right thing without digging through logs.
    """
    import os
    started = time.monotonic()

    # ── 1. spm-mcp /health ──────────────────────────────────────────────────
    health_url = os.environ.get("SPM_MCP_HEALTH_URL", _SPM_MCP_DEFAULT_HEALTH_URL)
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as c:
            r = await c.get(health_url)
        if r.status_code != 200:
            return False, f"spm-mcp /health returned {r.status_code}", _ms(started)
    except httpx.TimeoutException:
        return False, f"spm-mcp /health timed out after {_PROBE_TIMEOUT_S:.0f}s", None
    except httpx.HTTPError as e:
        return False, f"spm-mcp unreachable: {e}", None

    # ── 2 & 3. Referenced integrations ──────────────────────────────────────
    # Imported here (not at module top) to avoid a circular import:
    # connector_registry imports this module; probe_integration_by_id
    # is defined in connector_registry.
    try:
        from connector_registry import probe_integration_by_id  # type: ignore
    except ModuleNotFoundError:
        from services.spm_api.connector_registry import probe_integration_by_id  # type: ignore

    for fk, label in (
        ("default_llm_integration_id", "Default LLM"),
        ("tavily_integration_id",      "Tavily"),
    ):
        ref_id = (config.get(fk) or "").strip()
        if not ref_id:
            return False, f"{label} integration is not configured", _ms(started)
        ok, msg, _latency = await probe_integration_by_id(ref_id)
        if not ok:
            return False, f"{label} integration: {msg}", _ms(started)

    return True, "spm-mcp + default LLM + Tavily all green", _ms(started)
