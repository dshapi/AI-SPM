"""Orchestrator for the agent runtime control plane.

A single module that owns all the side-effects involved in deploying a
customer agent:

  * minting per-agent ``mcp_token`` and ``llm_api_key`` bearer tokens
  * creating / deleting the per-agent Kafka chat topic pair
  * spawning, stopping, and retiring the agent's Docker container
  * driving the high-level lifecycle state transitions on the
    ``agents`` row (``deploy / start / stop / retire``)

Kept in one module for V1 simplicity. If V2 grows replicated controllers
or non-Docker runtimes (Firecracker, k8s, …) the right factoring is
strategy classes per backend with this file as the dispatch layer.

All token storage is plaintext on the row in V1 — the row is admin-only
and never returned in any API response, so the threat model is "another
admin reads the DB", which is already the case for every other field.
V2 encrypts at rest with the same Fernet key used for
``integration_credentials``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from typing import Optional, Tuple

log = logging.getLogger(__name__)


# ─── Constants — env-overridable for tests / non-default deploys ───────────

_AGENT_NETWORK = os.environ.get("AGENT_NETWORK_NAME", "agent-net")
_AGENT_IMAGE   = os.environ.get("AGENT_RUNTIME_IMAGE", "aispm-agent-runtime:latest")
_KAFKA_BOOTSTRAP = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092",
)
# Canonical in-cluster URLs for the platform services the SDK talks to.
# Single source of truth — exposed via ``agent_routes.bootstrap_endpoint``
# so the SDK can read them from the DB-backed controller instead of
# pulling them from its own container env.
_AGENT_MCP_URL      = os.environ.get(
    "AGENT_MCP_URL",      "http://spm-mcp:8500/mcp",
)
_AGENT_LLM_BASE_URL = os.environ.get(
    "AGENT_LLM_BASE_URL", "http://spm-llm-proxy:8500/v1",
)
_AGENT_CONTROLLER_URL = os.environ.get(
    "AGENT_CONTROLLER_URL", "http://spm-api:8092",
)
# Phase 2: replaced the hardcoded sleep with a real handshake. The
# SDK's ``aispm.ready()`` POSTs to /agents/{id}/ready which flips
# runtime_state→running. We poll for that transition with a short
# interval and a generous total budget so slow customer agents
# (e.g. LangChain warmups) aren't false-positively marked crashed.
_READY_POLL_INTERVAL_S = float(os.environ.get("AGENT_READY_POLL_INTERVAL_S", "0.5"))
_READY_TIMEOUT_S       = float(os.environ.get("AGENT_READY_TIMEOUT_S",       "30"))

# Phase 1 fallback — kept for any caller that explicitly opts in via
# the env var. Default behaviour is poll-based.
_READY_SLEEP_S = float(os.environ.get("AGENT_READY_SLEEP_S", "0"))


# Resolved once at import time. Real ``docker.errors.NotFound`` when the
# SDK is installed, a stub Exception subclass otherwise. Exported (no
# leading underscore on the import-resolved alias) so tests can construct
# the same class agent_controller catches without needing the docker SDK
# installed in their environment.
try:
    from docker.errors import NotFound as _NotFound  # type: ignore
except ImportError:                                  # pragma: no cover
    class _NotFound(Exception):
        pass


# ─── 1. Token minting ──────────────────────────────────────────────────────

def mint_agent_tokens() -> Tuple[str, str]:
    """Return ``(mcp_token, llm_api_key)`` — two distinct random
    URL-safe base64 strings (~43 chars each).

    Both tokens are 32 bytes of entropy. Distinct ones make later
    revocation easier — rotating one doesn't force the other to roll.
    """
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)


# ─── 2. Kafka topic CRUD ───────────────────────────────────────────────────

def _kafka_admin():
    """Return a configured KafkaAdminClient. Imported lazily so the
    module is importable in test envs without kafka-python installed."""
    from kafka.admin import KafkaAdminClient  # type: ignore
    return KafkaAdminClient(
        bootstrap_servers=_KAFKA_BOOTSTRAP,
        client_id="spm-api-agent-ctl",
    )


async def create_agent_topics(*, tenant_id: str, agent_id: str,
                                partitions: int = 1,
                                replication: int = 1) -> None:
    """Create the per-agent ``chat.in`` + ``chat.out`` topics.

    Idempotent at the broker level — if the topic already exists,
    Kafka raises ``TopicAlreadyExistsError``; we swallow that so
    re-deploying an agent is safe.
    """
    from kafka.admin import NewTopic                              # type: ignore
    from kafka.errors import TopicAlreadyExistsError              # type: ignore
    from platform_shared.topics import agent_topics_for           # type: ignore

    t = agent_topics_for(tenant_id, agent_id)
    new_topics = [NewTopic(name=name, num_partitions=partitions,
                           replication_factor=replication)
                  for name in t.all()]

    admin = _kafka_admin()
    try:
        try:
            admin.create_topics(new_topics=new_topics, validate_only=False)
        except TopicAlreadyExistsError:
            log.info("agent topics already exist for tenant=%s agent=%s",
                     tenant_id, agent_id)
    finally:
        admin.close()


async def delete_agent_topics(*, tenant_id: str, agent_id: str) -> None:
    """Delete both per-agent topics. Used on retire.

    Idempotent: swallows ``UnknownTopicOrPartitionError`` (the topics
    never got created — agent was never deployed, or was already
    retired) so the rest of retire_agent still runs and the row gets
    cleaned out of the DB. Other broker errors propagate.
    """
    from kafka.errors import UnknownTopicOrPartitionError          # type: ignore
    from platform_shared.topics import agent_topics_for           # type: ignore

    t = agent_topics_for(tenant_id, agent_id)
    admin = _kafka_admin()
    try:
        try:
            admin.delete_topics(t.all())
        except UnknownTopicOrPartitionError:
            log.info("delete_agent_topics: topics for %s/%s already absent",
                     tenant_id, agent_id)
        except Exception as e:                                    # noqa: BLE001
            # Don't block retire on broker quirks (broker not reachable,
            # transient leadership election, etc.). Log loudly so ops
            # notices, but continue.
            log.warning(
                "delete_agent_topics: non-fatal kafka error for %s/%s: %s",
                tenant_id, agent_id, e,
            )
    finally:
        admin.close()


# ─── 3. Docker spawn / stop ────────────────────────────────────────────────

def _docker_client():
    """Return a Docker client (``from_env``). Lazy import so the module
    is importable when the docker SDK isn't installed."""
    import docker  # type: ignore
    return docker.from_env()


def _resolve_host_code_path(code_path: str) -> str:
    """Translate the row's stored ``code_path`` to a host-resolvable
    bind-mount source.

    Three cases:
      1. Absolute path that already lives on the host
         (``${AGENT_CODE_HOST_DIR}/<id>/agent.py``) → use as-is.
      2. Container path under ``/app/DataVolums/agents/...`` →
         swap the prefix for ``AGENT_CODE_HOST_DIR``.
      3. Relative path (``DataVolums/agents/...``) → prepend
         ``AGENT_CODE_HOST_DIR``.

    Falls back to ``code_path`` unchanged if ``AGENT_CODE_HOST_DIR``
    is unset (test mode where docker is mocked anyway).
    """
    host_dir = os.environ.get("AGENT_CODE_HOST_DIR", "").rstrip("/")
    if not host_dir:
        return code_path
    p = code_path.lstrip("./")
    # Strip the well-known container prefixes.
    for prefix in ("app/DataVolums/agents/", "DataVolums/agents/"):
        if p.startswith(prefix):
            return f"{host_dir}/{p[len(prefix):]}"
    if code_path.startswith("/app/DataVolums/agents/"):
        return host_dir + code_path[len("/app/DataVolums/agents"):]
    if code_path.startswith(host_dir):
        return code_path
    # Last-resort: treat code_path as a bare filename relative to the
    # host_dir.
    return f"{host_dir}/{code_path.lstrip('/')}"


def _ensure_code_on_disk(host_path: str, code_blob: Optional[str]) -> None:
    """Phase 4 self-heal: rewrite the agent.py bind-mount source from
    the DB blob if the host file is missing.

    This is called right before ``client.containers.run()`` so the
    docker daemon's bind-mount can resolve the path. Without this an
    operator who cleaned up ``DataVolums/agents/`` (or anyone /
    anything that touched the host directory) would be left with a
    permanently broken agent — which is exactly the surprise that
    motivated the Phase 4 ``code_blob`` column.

    The path inside spm-api's container view is computed from
    ``host_path`` by undoing the AGENT_CODE_HOST_DIR translation. If
    ``code_blob`` is empty (legacy Phase 1-3 row), no-op — the
    operator must re-upload to recover.
    """
    if not code_blob:
        return  # legacy row; nothing to restore from
    container_dir = os.environ.get("AGENT_CODE_CONTAINER_DIR",
                                     "/app/DataVolums/agents")
    host_dir = os.environ.get("AGENT_CODE_HOST_DIR", "")
    if host_dir and host_path.startswith(host_dir):
        rel = host_path[len(host_dir):].lstrip("/")
        container_path = os.path.join(container_dir, rel)
    else:
        # Best-effort: try the host path directly (bind-mount may share it).
        container_path = host_path
    if os.path.isfile(container_path):
        return                                                  # already there
    log.info("ensure_code_on_disk: regenerating %s from DB blob",
             container_path)
    os.makedirs(os.path.dirname(container_path), exist_ok=True)
    with open(container_path, "w", encoding="utf-8") as f:
        f.write(code_blob)


async def spawn_agent_container(*, agent_id: str, tenant_id: str,
                                 code_path: str,
                                 mcp_token: str, llm_api_key: str,
                                 mem_mb: int = 512,
                                 cpu_quota: float = 0.5,
                                 code_blob: Optional[str] = None,
                                 ) -> str:
    """Spawn an ``aispm-agent-runtime`` container for the given agent.

    Returns the Docker container id. The container is detached and
    bound to the internal-only ``agent-net`` network; the agent has no
    direct internet egress — only ``spm-mcp``, ``spm-llm-proxy``, and
    Kafka are reachable.

    Idempotent on container name: if a container named
    ``agent-{id}`` already exists it must be stopped first. We don't
    auto-replace because that would race with concurrent
    start_agent / deploy_agent calls.
    """
    client = _docker_client()
    # Minimal identity-bootstrap env. Everything else (tenant_id, MCP /
    # LLM URLs, llm_api_key, kafka bootstrap) is fetched by the SDK at
    # import time from the controller's GET /agents/{id}/bootstrap
    # endpoint, which reads from the DB. Tenant_id and llm_api_key are
    # kept out of the container env on purpose — the agent gets them
    # from the same DB-backed bootstrap call.
    env = {
        "AGENT_ID":       agent_id,
        "MCP_TOKEN":      mcp_token,
        "CONTROLLER_URL": _AGENT_CONTROLLER_URL,
    }
    # Silence unused-arg lint — these still flow through deploy_agent
    # for back-compat callers but are no longer leaked into the agent's
    # process environment.
    _ = (tenant_id, llm_api_key)
    host_path = _resolve_host_code_path(code_path)
    log.info("spawn_agent_container: agent=%s code_path=%s host_path=%s",
             agent_id, code_path, host_path)

    # Self-heal: if the host volume's agent.py is missing (operator
    # ran rm by mistake, fresh dev box, retired agent re-attempted,
    # etc.), rewrite it from the DB blob before docker bind-mounts it.
    _ensure_code_on_disk(host_path, code_blob)

    # Idempotency — if a previous container with the same name still
    # exists (crashed, exited, or even still running), Docker would
    # reject the new run with "name already in use". Force-remove the
    # stale one first so /start works as a true "give me a fresh
    # container" verb.
    container_name = f"agent-{agent_id}"
    try:
        existing = client.containers.get(container_name)
        log.info("spawn_agent_container: removing stale container %s (status=%s)",
                 container_name, existing.status)
        try:
            existing.stop(timeout=5)
        except Exception:                                # noqa: BLE001
            pass
        existing.remove(force=True)
    except _NotFound:
        pass
    except Exception as e:                               # noqa: BLE001
        # Don't block spawn if cleanup hits a transient docker hiccup —
        # the run() below will surface a clearer error if it can't
        # actually create the new container.
        log.warning("spawn_agent_container: cleanup failed for %s: %s",
                    container_name, e)

    ctr = client.containers.run(
        _AGENT_IMAGE,
        name=container_name,
        environment=env,
        volumes={host_path: {"bind": "/agent/agent.py", "mode": "ro"}},
        mem_limit=f"{mem_mb}m",
        nano_cpus=int(cpu_quota * 1_000_000_000),
        network=_AGENT_NETWORK,
        detach=True,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 1},
    )
    return ctr.id


async def stop_agent_container(agent_id: str) -> None:
    """Stop + remove the agent's container. No-op if missing.

    SIGTERM with 10s grace, then SIGKILL via Docker's force-stop. The
    SDK's signal handler (Phase 2) drains in-flight messages cleanly
    inside the grace window.

    ``_NotFound`` is resolved at module import time (above) so the
    behaviour is identical whether the docker SDK is installed or not.
    """
    client = _docker_client()
    name = f"agent-{agent_id}"

    try:
        ctr = client.containers.get(name)
    except _NotFound:
        log.info("stop_agent_container: %s not running (no-op)", name)
        return
    try:
        ctr.stop(timeout=10)
    finally:
        try:
            ctr.remove(force=True)
        except _NotFound:
            pass

# ─── 4. High-level orchestration ───────────────────────────────────────────
#
# spm-api uses SQLAlchemy AsyncSession in production. AsyncSession.get()
# and AsyncSession.commit() return coroutines that MUST be awaited;
# without the await the row is a coroutine object that has no .id /
# .runtime_state, so any access raises AttributeError → 500. The unit
# tests use a MagicMock that returns sync values, which is why the
# bug only surfaces against the real DB.
#
# These two helpers paper over the difference so each lifecycle
# function can call them uniformly. They detect the awaitable shape
# at runtime instead of checking the session class.

async def _db_get(db, model, pk):
    res = db.get(model, pk)
    if hasattr(res, "__await__"):
        res = await res
    return res


async def _db_commit(db) -> None:
    res = db.commit()
    if hasattr(res, "__await__"):
        await res


async def _db_delete(db, obj) -> None:
    res = db.delete(obj)
    if hasattr(res, "__await__"):
        await res


async def deploy_agent(db, agent_id) -> None:
    """Deploy: create topics → mark starting → spawn → mark running.

    Kept procedural (not state-machined) because the V1 transitions are
    linear and adding a state machine adds more code than it saves.
    """
    from spm.db.models import Agent  # type: ignore

    a = await _db_get(db, Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    await create_agent_topics(tenant_id=a.tenant_id, agent_id=str(a.id))

    a.runtime_state = "starting"
    await _db_commit(db)

    await spawn_agent_container(
        agent_id=str(a.id), tenant_id=a.tenant_id,
        code_path=a.code_path,
        mcp_token=a.mcp_token, llm_api_key=a.llm_api_key,
        mem_mb=512, cpu_quota=0.5,
        # Phase 4 self-heal — pass the DB-stored source so spawn can
        # regenerate the bind-mount source if the host file is gone.
        code_blob=getattr(a, "code_blob", None),
    )

    # Phase 2: poll for the SDK's /ready handshake. The endpoint
    # (POST /api/spm/agents/{id}/ready, called by aispm.ready())
    # flips runtime_state to "running" — we just wait for that
    # transition to appear on the row.
    if _READY_SLEEP_S > 0:
        # Compatibility branch — explicit opt-in only.
        await asyncio.sleep(_READY_SLEEP_S)
        a.runtime_state = "running"
        await _db_commit(db)
        return

    try:
        await _wait_for_ready(db, agent_id, timeout_s=_READY_TIMEOUT_S)
    except TimeoutError as e:
        # Agent spawned but never called aispm.ready() within the
        # window. Most common cause: running the Phase 1 stub image
        # (which never calls ready()), or network mis-wiring (the
        # agent can't resolve spm-api). Flip the row to "crashed" so
        # the operator sees the failure in the UI instead of a row
        # frozen at "starting" forever. Container is still up — the
        # operator can read its logs to diagnose.
        log.warning("deploy_agent: ready timeout — marking crashed: %s", e)
        a.runtime_state = "crashed"
        await _db_commit(db)
        return


async def _wait_for_ready(db, agent_id, *, timeout_s: float) -> None:
    """Poll the agents row until ``runtime_state == 'running'``.

    Critical SQLAlchemy detail
    ──────────────────────────
    The ``/ready`` endpoint runs in a different ``AsyncSession`` than
    the upload route that called us. When ``ready_endpoint`` commits
    ``runtime_state = "running"``, our session does NOT see the change
    because the Agent row is pinned in our session's identity map at
    its loaded value. ``db.get()`` is identity-map first — it returns
    the cached object without re-querying.

    Without ``expire_all()`` (or per-row ``refresh``), this loop spins
    on a stale snapshot of ``starting`` for the full timeout window
    and then incorrectly marks the row ``crashed``, even though the
    agent successfully called ``aispm.ready()`` seconds earlier. The
    UI then shows a fake Restart button on a perfectly-healthy agent.

    Raises ``TimeoutError`` if the agent never signals ready within
    *timeout_s*; the caller catches and flips the row to ``crashed``.
    """
    import time
    from spm.db.models import Agent  # type: ignore

    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        # Drop our identity-map cache so the next get() hits the DB.
        # expire_all() on AsyncSession is a sync method (per
        # SQLAlchemy docs) — it doesn't await; it just marks objects
        # stale. The next attribute access / get() then re-queries.
        try:
            db.expire_all()
        except Exception:                                # noqa: BLE001
            # Tests sometimes pass a plain dict-like stub; ignore.
            pass
        a = await _db_get(db, Agent, agent_id)
        if a is None:
            raise ValueError(f"agent {agent_id!r} disappeared during ready poll")
        if a.runtime_state == "running":
            return
        await asyncio.sleep(_READY_POLL_INTERVAL_S)
    raise TimeoutError(
        f"agent {agent_id} did not signal ready within {timeout_s:.0f}s"
    )


async def start_agent(db, agent_id) -> None:
    """Idempotent start — used by the run/stop toggle.

    If already ``running``, no-op. If ``stopped`` or ``crashed``, spawn
    the container and mark ``starting``. The async readiness step is
    deliberately absent here — start is a "best-effort kick" the UI
    polls for state transition.
    """
    from spm.db.models import Agent  # type: ignore

    a = await _db_get(db, Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")
    if a.runtime_state == "running":
        return

    await spawn_agent_container(
        agent_id=str(a.id), tenant_id=a.tenant_id,
        code_path=a.code_path,
        mcp_token=a.mcp_token, llm_api_key=a.llm_api_key,
        code_blob=getattr(a, "code_blob", None),
    )
    a.runtime_state = "starting"
    await _db_commit(db)


async def stop_agent(db, agent_id) -> None:
    """Stop the agent's container. State stays as the row; topics are
    preserved so resuming a chat session keeps history."""
    from spm.db.models import Agent  # type: ignore

    a = await _db_get(db, Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    await stop_agent_container(str(a.id))
    a.runtime_state = "stopped"
    await _db_commit(db)


async def retire_agent(db, agent_id) -> None:
    """Permanent removal: stop the container, delete topics, then the
    row. Soft-delete is V2 (we'd flip a deleted_at column instead).

    Both the container-stop and the topic-delete are best-effort —
    they may fail for any number of reasons (docker daemon unreachable,
    container already gone, broker quirks, topic never existed). We
    swallow those failures so the DB row still gets cleaned up.
    Otherwise a half-deployed agent becomes un-deletable from the UI.

    Loading note
    ────────────
    The Agent → AgentChatSession relationship has
    ``cascade="all, delete-orphan"``. Under AsyncSession that means
    the delete handler needs the ``sessions`` collection populated up
    front; otherwise SQLAlchemy tries to lazy-load it synchronously
    inside the async context and raises ``MissingGreenlet``. We
    selectinload it explicitly here.
    """
    from sqlalchemy import select                                  # type: ignore
    from sqlalchemy.orm import selectinload                        # type: ignore
    from spm.db.models import Agent                                # type: ignore

    # Eager-load sessions so cascade-delete doesn't trigger a sync
    # lazy-load. Falls back to plain _db_get for sync mock sessions
    # used by the test suite.
    if hasattr(db, "execute"):
        stmt = (
            select(Agent)
            .where(Agent.id == agent_id)
            .options(selectinload(Agent.sessions))
        )
        result = await db.execute(stmt)
        a = result.scalar_one_or_none()
    else:
        a = await _db_get(db, Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    tenant_id = a.tenant_id
    aid_str   = str(a.id)

    try:
        await stop_agent_container(aid_str)
    except Exception as e:                                        # noqa: BLE001
        log.warning("retire_agent: container stop failed for %s: %s",
                    aid_str, e)

    try:
        await delete_agent_topics(tenant_id=tenant_id, agent_id=aid_str)
    except Exception as e:                                        # noqa: BLE001
        log.warning("retire_agent: topic delete failed for %s: %s",
                    aid_str, e)

    await _db_delete(db, a)
    await _db_commit(db)
