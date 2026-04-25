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
    """Delete both per-agent topics. Used on retire."""
    from platform_shared.topics import agent_topics_for           # type: ignore

    t = agent_topics_for(tenant_id, agent_id)
    admin = _kafka_admin()
    try:
        admin.delete_topics(t.all())
    finally:
        admin.close()


# ─── 3. Docker spawn / stop ────────────────────────────────────────────────

def _docker_client():
    """Return a Docker client (``from_env``). Lazy import so the module
    is importable when the docker SDK isn't installed."""
    import docker  # type: ignore
    return docker.from_env()


async def spawn_agent_container(*, agent_id: str, tenant_id: str,
                                 code_path: str,
                                 mcp_token: str, llm_api_key: str,
                                 mem_mb: int = 512,
                                 cpu_quota: float = 0.5,
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
    env = {
        "AGENT_ID":                 agent_id,
        "TENANT_ID":                tenant_id,
        "MCP_URL":                  "http://spm-mcp:8500/mcp",
        "MCP_TOKEN":                mcp_token,
        "LLM_BASE_URL":             "http://spm-llm-proxy:8500/v1",
        "LLM_API_KEY":              llm_api_key,
        "KAFKA_BOOTSTRAP_SERVERS":  _KAFKA_BOOTSTRAP,
    }
    ctr = client.containers.run(
        _AGENT_IMAGE,
        name=f"agent-{agent_id}",
        environment=env,
        volumes={code_path: {"bind": "/agent/agent.py", "mode": "ro"}},
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
    """
    import docker.errors  # type: ignore
    client = _docker_client()
    name = f"agent-{agent_id}"
    try:
        ctr = client.containers.get(name)
    except docker.errors.NotFound:
        log.info("stop_agent_container: %s not running (no-op)", name)
        return
    try:
        ctr.stop(timeout=10)
    finally:
        try:
            ctr.remove(force=True)
        except docker.errors.NotFound:
            pass


# ─── 4. High-level orchestration ───────────────────────────────────────────

async def deploy_agent(db, agent_id) -> None:
    """Deploy: create topics → mark starting → spawn → mark running.

    Kept procedural (not state-machined) because the V1 transitions are
    linear and adding a state machine adds more code than it saves.
    """
    from spm.db.models import Agent  # type: ignore

    a = db.get(Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    await create_agent_topics(tenant_id=a.tenant_id, agent_id=str(a.id))

    a.runtime_state = "starting"
    db.commit()

    await spawn_agent_container(
        agent_id=str(a.id), tenant_id=a.tenant_id,
        code_path=a.code_path,
        mcp_token=a.mcp_token, llm_api_key=a.llm_api_key,
        mem_mb=512, cpu_quota=0.5,
    )

    # Phase 2: poll for the SDK's /ready handshake. The endpoint
    # (POST /api/spm/agents/{id}/ready, called by aispm.ready())
    # flips runtime_state to "running" — we just wait for that
    # transition to appear on the row.
    if _READY_SLEEP_S > 0:
        # Compatibility branch — explicit opt-in only.
        await asyncio.sleep(_READY_SLEEP_S)
        a.runtime_state = "running"
        db.commit()
        return

    await _wait_for_ready(db, agent_id, timeout_s=_READY_TIMEOUT_S)


async def _wait_for_ready(db, agent_id, *, timeout_s: float) -> None:
    """Poll the agents row until ``runtime_state == 'running'``.

    Raises ``TimeoutError`` if the agent never signals ready within
    *timeout_s*; the caller (the upload route) catches and converts
    to a 504 so the operator sees a clear error.
    """
    import time
    from spm.db.models import Agent  # type: ignore

    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        a = db.get(Agent, agent_id)
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

    a = db.get(Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")
    if a.runtime_state == "running":
        return

    await spawn_agent_container(
        agent_id=str(a.id), tenant_id=a.tenant_id,
        code_path=a.code_path,
        mcp_token=a.mcp_token, llm_api_key=a.llm_api_key,
    )
    a.runtime_state = "starting"
    db.commit()


async def stop_agent(db, agent_id) -> None:
    """Stop the agent's container. State stays as the row; topics are
    preserved so resuming a chat session keeps history."""
    from spm.db.models import Agent  # type: ignore

    a = db.get(Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    await stop_agent_container(str(a.id))
    a.runtime_state = "stopped"
    db.commit()


async def retire_agent(db, agent_id) -> None:
    """Permanent removal: stop the container, delete topics, then the
    row. Soft-delete is V2 (we'd flip a deleted_at column instead)."""
    from spm.db.models import Agent  # type: ignore

    a = db.get(Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    tenant_id = a.tenant_id
    aid_str   = str(a.id)
    await stop_agent_container(aid_str)
    await delete_agent_topics(tenant_id=tenant_id, agent_id=aid_str)
    db.delete(a)
    db.commit()
