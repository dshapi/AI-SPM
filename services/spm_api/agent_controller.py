"""Orchestrator for the agent runtime control plane — Kubernetes backend.

Replaces the Docker SDK with the kubernetes Python client.
The public interface is unchanged:

  * mint_agent_tokens
  * create_agent_topics / delete_agent_topics
  * spawn_agent_pod   (was spawn_agent_container)
  * stop_agent_pod    (was stop_agent_container)
  * deploy_agent / start_agent / stop_agent / retire_agent

K8s design
──────────
* One Pod per agent in the ``aispm-agents`` namespace (isolated from
  the main ``aispm`` namespace; NetworkPolicy enforced separately).
* Agent source code lives in a per-agent ConfigMap
  (``agent-code-{id}``) mounted read-only at ``/agent/agent.py``.
  The loader.py entrypoint exec()s that file — same contract as the
  old Docker bind-mount, zero changes to agent_runtime.
* ConfigMap is created/refreshed in spawn_agent_pod and deleted in
  stop_agent_pod so the lifecycle is fully self-contained.
* Resource requests/limits mirror the old Docker defaults (512 Mi / 500m).
* The Pod uses the ``agent-runtime`` ServiceAccount
  (automountServiceAccountToken: false).
* spm-api must run with the ``spm-api`` ServiceAccount which has an
  RBAC Role granting pods + configmaps in ``aispm-agents``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from typing import Optional, Tuple

log = logging.getLogger(__name__)


# ─── Constants — env-overridable ──────────────────────────────────────────────

_AGENT_NAMESPACE  = os.environ.get("AGENT_POD_NAMESPACE", "aispm-agents")
_AGENT_IMAGE      = os.environ.get("AGENT_RUNTIME_IMAGE", "aispm-agent-runtime:latest")
# Empty default: dev clusters without Kata schedule on the default
# runtime; prod sets AGENT_RUNTIME_CLASS=kata via the spm-api Pod env
# (see deploy/helm/aispm/templates/spm-api-deployment.yaml).
_AGENT_RUNTIME_CLASS = os.environ.get("AGENT_RUNTIME_CLASS", "")
_KAFKA_BOOTSTRAP  = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")
_AGENT_MCP_URL    = os.environ.get("AGENT_MCP_URL",      "http://spm-mcp.aispm.svc.cluster.local:8500/mcp")
_AGENT_LLM_BASE_URL = os.environ.get("AGENT_LLM_BASE_URL", "http://spm-llm-proxy.aispm.svc.cluster.local:8500/v1")
_AGENT_CONTROLLER_URL = os.environ.get("AGENT_CONTROLLER_URL", "http://spm-api.aispm.svc.cluster.local:8092")

_READY_POLL_INTERVAL_S = float(os.environ.get("AGENT_READY_POLL_INTERVAL_S", "0.5"))
_READY_TIMEOUT_S       = float(os.environ.get("AGENT_READY_TIMEOUT_S",       "30"))
_READY_SLEEP_S         = float(os.environ.get("AGENT_READY_SLEEP_S", "0"))


# ─── 1. Token minting ─────────────────────────────────────────────────────────

def mint_agent_tokens() -> Tuple[str, str]:
    """Return ``(mcp_token, llm_api_key)`` — two 32-byte URL-safe tokens."""
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)


# ─── 2. Kafka topic CRUD ──────────────────────────────────────────────────────

def _kafka_admin():
    from kafka.admin import KafkaAdminClient  # type: ignore
    return KafkaAdminClient(
        bootstrap_servers=_KAFKA_BOOTSTRAP,
        client_id="spm-api-agent-ctl",
    )


async def create_agent_topics(*, tenant_id: str, agent_id: str,
                               partitions: int = 1,
                               replication: int = 1) -> None:
    """Create per-agent ``chat.in`` + ``chat.out`` topics. Idempotent."""
    from kafka.admin import NewTopic                           # type: ignore
    from kafka.errors import TopicAlreadyExistsError           # type: ignore
    from platform_shared.topics import agent_topics_for        # type: ignore

    t = agent_topics_for(tenant_id, agent_id)
    new_topics = [NewTopic(name=name, num_partitions=partitions,
                           replication_factor=replication)
                  for name in t.all()]
    admin = _kafka_admin()
    try:
        try:
            admin.create_topics(new_topics=new_topics, validate_only=False)
        except TopicAlreadyExistsError:
            log.info("create_agent_topics: already exist for %s/%s",
                     tenant_id, agent_id)
    finally:
        admin.close()


async def delete_agent_topics(*, tenant_id: str, agent_id: str) -> None:
    """Delete both per-agent topics. Idempotent on missing topics."""
    from kafka.errors import UnknownTopicOrPartitionError  # type: ignore
    from platform_shared.topics import agent_topics_for   # type: ignore

    t = agent_topics_for(tenant_id, agent_id)
    admin = _kafka_admin()
    try:
        try:
            admin.delete_topics(t.all())
        except UnknownTopicOrPartitionError:
            log.info("delete_agent_topics: already absent for %s/%s",
                     tenant_id, agent_id)
        except Exception as e:                             # noqa: BLE001
            log.warning("delete_agent_topics: non-fatal error for %s/%s: %s",
                        tenant_id, agent_id, e)
    finally:
        admin.close()


# ─── 3. Kubernetes Pod spawn / stop ───────────────────────────────────────────

def _k8s_core() -> "kubernetes.client.CoreV1Api":  # type: ignore[name-defined]
    """Return a configured CoreV1Api client.

    Uses in-cluster config when running inside k8s; falls back to
    KUBECONFIG (local dev / CI) so unit tests can mock it without
    patching os.environ.
    """
    import kubernetes  # type: ignore
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
    return kubernetes.client.CoreV1Api()


def _configmap_name(agent_id: str) -> str:
    return f"agent-code-{agent_id}"


def _pod_name(agent_id: str) -> str:
    return f"agent-{agent_id}"


def _build_configmap(agent_id: str, code_blob: str):
    """Build the V1ConfigMap object carrying the agent source."""
    import kubernetes.client as k8s  # type: ignore
    return k8s.V1ConfigMap(
        api_version="v1",
        kind="ConfigMap",
        metadata=k8s.V1ObjectMeta(
            name=_configmap_name(agent_id),
            namespace=_AGENT_NAMESPACE,
            labels={"app": "agent-runtime", "agent-id": agent_id},
        ),
        data={"agent.py": code_blob},
    )


def _build_pod(agent_id: str, mcp_token: str, tenant_id: str = "",
               llm_api_key: str = ""):
    """Build the V1Pod spec for an agent runtime instance.

    Config-via-env vs config-via-/bootstrap
    ───────────────────────────────────────
    The plan's design has the agent fetch its config (Kafka brokers,
    tenant id, …) from ``GET /agents/{id}/bootstrap`` after start.
    That round-trip can fail in non-trivial ways (Istio Ambient↔sidecar
    mTLS interop, NetworkPolicy timing, sidecar not yet ready, …) and
    every one of them turns into a CrashLoopBackOff before the agent
    can do useful work.

    spm-api already knows all of those values — they're in its own
    environment from the platform-env ConfigMap and on the Agent row
    in the DB. So we propagate them on the Pod env directly. The
    /bootstrap endpoint can stay as a refresh / dynamic-config path
    later, but the cold-start contract no longer depends on it.
    """
    import kubernetes.client as k8s  # type: ignore

    cm_name  = _configmap_name(agent_id)
    pod_name = _pod_name(agent_id)

    return k8s.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=k8s.V1ObjectMeta(
            name=pod_name,
            namespace=_AGENT_NAMESPACE,
            labels={"app": "agent-runtime", "agent-id": agent_id},
        ),
        spec=k8s.V1PodSpec(
            # Kata microVM isolation per the plan when AGENT_RUNTIME_CLASS
            # is set (typically "kata" in prod). Empty/None falls through
            # to the cluster's default runtime — the dev path.
            runtime_class_name=(_AGENT_RUNTIME_CLASS or None),
            service_account_name="agent-runtime",
            automount_service_account_token=False,
            restart_policy="OnFailure",
            security_context=k8s.V1PodSecurityContext(
                run_as_non_root=True,
                run_as_user=10001,
                run_as_group=10001,
                fs_group=10001,
                seccomp_profile=k8s.V1SeccompProfile(type="RuntimeDefault"),
            ),
            containers=[
                k8s.V1Container(
                    name="agent",
                    image=_AGENT_IMAGE,
                    image_pull_policy="IfNotPresent",
                    security_context=k8s.V1SecurityContext(
                        allow_privilege_escalation=False,
                        run_as_non_root=True,
                        run_as_user=10001,
                        run_as_group=10001,
                        # Read-only root FS — the only writable paths
                        # are the explicit emptyDir mounts below
                        # (/tmp). Any attacker that pwns agent.py can't
                        # drop binaries into /usr/local/bin or rewrite
                        # /agent/loader.py. Bytecode writes are
                        # disabled via PYTHONDONTWRITEBYTECODE so the
                        # standard library import path is fine.
                        read_only_root_filesystem=True,
                        capabilities=k8s.V1Capabilities(drop=["ALL"]),
                        seccomp_profile=k8s.V1SeccompProfile(type="RuntimeDefault"),
                    ),
                    env=[
                        k8s.V1EnvVar(name="AGENT_ID",       value=agent_id),
                        k8s.V1EnvVar(name="TENANT_ID",      value=tenant_id),
                        k8s.V1EnvVar(name="MCP_TOKEN",      value=mcp_token),
                        # Per-agent token for spm-llm-proxy auth
                        # (matched against agents.llm_api_key in the DB).
                        k8s.V1EnvVar(name="LLM_API_KEY",    value=llm_api_key),
                        k8s.V1EnvVar(name="CONTROLLER_URL", value=_AGENT_CONTROLLER_URL),
                        k8s.V1EnvVar(name="MCP_URL",        value=_AGENT_MCP_URL),
                        k8s.V1EnvVar(name="LLM_BASE_URL",   value=_AGENT_LLM_BASE_URL),
                        k8s.V1EnvVar(name="KAFKA_BOOTSTRAP_SERVERS",
                                     value=_KAFKA_BOOTSTRAP),
                        # Read-only root FS support — Python won't try
                        # to drop .pyc files alongside the source.
                        k8s.V1EnvVar(name="PYTHONDONTWRITEBYTECODE",
                                     value="1"),
                        k8s.V1EnvVar(name="TMPDIR", value="/tmp"),
                        # langchain / huggingface / httpx default cache
                        # locations all land under HOME — point them
                        # at a writable emptyDir so they don't ENOSPC
                        # against the read-only root.
                        k8s.V1EnvVar(name="HOME", value="/tmp"),
                        k8s.V1EnvVar(name="XDG_CACHE_HOME", value="/tmp/.cache"),
                    ],
                    resources=k8s.V1ResourceRequirements(
                        requests={"memory": "512Mi", "cpu": "250m"},
                        limits={"memory": "512Mi",  "cpu": "500m",
                                "ephemeral-storage": "256Mi"},
                    ),
                    volume_mounts=[
                        k8s.V1VolumeMount(
                            name="agent-code",
                            mount_path="/agent/agent.py",
                            sub_path="agent.py",
                            read_only=True,
                        ),
                        # Writable scratch — paired with TMPDIR=/tmp
                        # and HOME=/tmp env vars above so any library
                        # that wants to write a temp file or cache has
                        # somewhere to land. Capped to 64 MiB so a
                        # rogue agent can't fill node-local storage.
                        k8s.V1VolumeMount(
                            name="tmp",
                            mount_path="/tmp",
                        ),
                    ],
                )
            ],
            volumes=[
                k8s.V1Volume(
                    name="agent-code",
                    config_map=k8s.V1ConfigMapVolumeSource(name=cm_name),
                ),
                k8s.V1Volume(
                    name="tmp",
                    empty_dir=k8s.V1EmptyDirVolumeSource(
                        medium="Memory",       # tmpfs — never spills to disk
                        size_limit="64Mi",
                    ),
                ),
            ],
        ),
    )


_DELETE_WAIT_TIMEOUT_S = float(os.environ.get("AGENT_DELETE_WAIT_TIMEOUT_S", "30"))
_DELETE_WAIT_INTERVAL_S = float(os.environ.get("AGENT_DELETE_WAIT_INTERVAL_S", "0.25"))


def _wait_until_absent(get_fn, name: str, *,
                       timeout_s: float = _DELETE_WAIT_TIMEOUT_S,
                       interval_s: float = _DELETE_WAIT_INTERVAL_S) -> None:
    """Poll ``get_fn(name, namespace)`` until it returns 404.

    Kubernetes ``delete_*`` calls are *non-blocking*: they return
    success the moment the API server records the deletion, even
    though the object stays in ``Terminating`` until graceful shutdown
    completes. A subsequent ``create_*`` with the same name during
    that window returns 409 AlreadyExists — which is exactly the bug
    this helper exists to prevent.
    """
    import time as _time
    from kubernetes.client.exceptions import ApiException  # type: ignore

    deadline = _time.monotonic() + timeout_s
    while _time.monotonic() < deadline:
        try:
            get_fn(name, _AGENT_NAMESPACE)
        except ApiException as e:
            if e.status == 404:
                return
            raise
        _time.sleep(interval_s)
    raise TimeoutError(
        f"resource {name!r} still present in namespace "
        f"{_AGENT_NAMESPACE!r} after {timeout_s:.0f}s — stuck Terminating?"
    )


async def spawn_agent_pod(*, agent_id: str,
                           mcp_token: str,
                           code_blob: Optional[str] = None,
                           # kept for API compatibility — no longer used in k8s
                           tenant_id: str = "",
                           code_path: str = "",
                           llm_api_key: str = "",
                           mem_mb: int = 512,
                           cpu_quota: float = 0.5) -> str:
    """Create (or replace) the agent Pod + ConfigMap in ``aispm-agents``.

    Returns the Pod name.

    Idempotent: if a Pod/ConfigMap with the same name already exists
    (previous failed deploy, crash loop, or a Pod still in
    ``Terminating`` from the last stop), they are force-deleted and
    we wait for the API server to actually remove them before issuing
    the new create. Without that wait, ``create_namespaced_pod``
    returns 409 ``object is being deleted`` mid-shutdown.

    ``code_blob`` must be non-empty in k8s mode — there is no host
    bind-mount path to fall back on.  ``deploy_agent`` asserts this
    before calling.
    """
    import kubernetes  # type: ignore
    from kubernetes.client.exceptions import ApiException  # type: ignore

    if not code_blob:
        raise ValueError(
            f"spawn_agent_pod: agent {agent_id!r} has no code_blob — "
            "cannot create ConfigMap; re-upload the agent source."
        )

    core = _k8s_core()
    pod_name = _pod_name(agent_id)
    cm_name  = _configmap_name(agent_id)

    # ── idempotent cleanup ────────────────────────────────────────────
    # Force-delete (grace_period_seconds=0) so we don't wait the full
    # terminationGracePeriodSeconds on a stale Pod we're about to
    # replace. Then poll get_* until 404 — see _wait_until_absent for
    # why this can't be skipped.
    for resource, delete_fn, get_fn, name in [
        ("Pod",       core.delete_namespaced_pod,
                      core.read_namespaced_pod,        pod_name),
        ("ConfigMap", core.delete_namespaced_config_map,
                      core.read_namespaced_config_map, cm_name),
    ]:
        try:
            delete_fn(name, _AGENT_NAMESPACE, grace_period_seconds=0)
            log.info("spawn_agent_pod: deleting stale %s %s", resource, name)
        except ApiException as e:
            if e.status == 404:
                continue
            log.warning("spawn_agent_pod: cleanup %s %s: %s", resource, name, e)
            # Even on a non-404 error, fall through to the wait — the
            # delete may have been accepted before the response failed.
        try:
            _wait_until_absent(get_fn, name)
            log.info("spawn_agent_pod: stale %s %s gone", resource, name)
        except TimeoutError as e:
            # Surface as ApiException so callers handle uniformly.
            raise RuntimeError(
                f"spawn_agent_pod: could not clean up stale {resource} "
                f"{name!r}: {e}"
            ) from e

    # ── create ConfigMap ──────────────────────────────────────────────
    core.create_namespaced_config_map(
        namespace=_AGENT_NAMESPACE,
        body=_build_configmap(agent_id, code_blob),
    )
    log.info("spawn_agent_pod: ConfigMap %s created", cm_name)

    # ── create Pod ────────────────────────────────────────────────────
    pod = core.create_namespaced_pod(
        namespace=_AGENT_NAMESPACE,
        body=_build_pod(agent_id, mcp_token,
                        tenant_id=tenant_id,
                        llm_api_key=llm_api_key),
    )
    log.info("spawn_agent_pod: Pod %s created (uid=%s)", pod_name, pod.metadata.uid)
    return pod_name


# Back-compat alias — callers that import spawn_agent_container still work.
spawn_agent_container = spawn_agent_pod


async def stop_agent_pod(agent_id: str) -> None:
    """Delete the agent Pod + ConfigMap. No-op if already absent."""
    import kubernetes  # type: ignore
    from kubernetes.client.exceptions import ApiException  # type: ignore

    core = _k8s_core()
    pod_name = _pod_name(agent_id)
    cm_name  = _configmap_name(agent_id)

    for resource, delete_fn, name in [
        ("Pod",       core.delete_namespaced_pod,        pod_name),
        ("ConfigMap", core.delete_namespaced_config_map, cm_name),
    ]:
        try:
            delete_fn(name, _AGENT_NAMESPACE)
            log.info("stop_agent_pod: deleted %s %s", resource, name)
        except ApiException as e:
            if e.status == 404:
                log.info("stop_agent_pod: %s %s already absent", resource, name)
            else:
                log.warning("stop_agent_pod: error deleting %s %s: %s",
                            resource, name, e)


# Back-compat alias.
stop_agent_container = stop_agent_pod


# ─── 4. SQLAlchemy session helpers (unchanged) ────────────────────────────────

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


# ─── 5. High-level lifecycle (unchanged logic) ────────────────────────────────

async def deploy_agent(db, agent_id) -> None:
    """Deploy: create topics → mark starting → spawn Pod → poll ready."""
    from spm.db.models import Agent  # type: ignore

    a = await _db_get(db, Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    code_blob = getattr(a, "code_blob", None)
    if not code_blob:
        raise ValueError(
            f"agent {agent_id!r} has no code_blob — re-upload the agent source "
            "before deploying to Kubernetes."
        )

    await create_agent_topics(tenant_id=a.tenant_id, agent_id=str(a.id))

    a.runtime_state = "starting"
    await _db_commit(db)

    await spawn_agent_pod(
        agent_id=str(a.id),
        tenant_id=a.tenant_id,
        code_blob=code_blob,
        mcp_token=a.mcp_token,
        llm_api_key=a.llm_api_key,
        mem_mb=512,
        cpu_quota=0.5,
    )

    if _READY_SLEEP_S > 0:
        await asyncio.sleep(_READY_SLEEP_S)
        a.runtime_state = "running"
        await _db_commit(db)
        return

    try:
        await _wait_for_ready(db, agent_id, timeout_s=_READY_TIMEOUT_S)
    except TimeoutError as e:
        log.warning("deploy_agent: ready timeout — marking crashed: %s", e)
        a.runtime_state = "crashed"
        await _db_commit(db)


async def _wait_for_ready(db, agent_id, *, timeout_s: float) -> None:
    """Poll the agents row until ``runtime_state == 'running'``.

    Uses expire_all() to bust SQLAlchemy's identity map between polls
    so we see commits from the /ready endpoint's session.
    """
    import time
    from spm.db.models import Agent  # type: ignore

    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        try:
            db.expire_all()
        except Exception:  # noqa: BLE001
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
    """Idempotent start — used by the run/stop toggle."""
    from spm.db.models import Agent  # type: ignore

    a = await _db_get(db, Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")
    if a.runtime_state == "running":
        return

    code_blob = getattr(a, "code_blob", None)
    await spawn_agent_pod(
        agent_id=str(a.id),
        tenant_id=a.tenant_id,
        code_blob=code_blob,
        mcp_token=a.mcp_token,
        llm_api_key=a.llm_api_key,
    )
    a.runtime_state = "starting"
    await _db_commit(db)


async def stop_agent(db, agent_id) -> None:
    """Stop the agent's Pod. Topics are preserved for resume."""
    from spm.db.models import Agent  # type: ignore

    a = await _db_get(db, Agent, agent_id)
    if a is None:
        raise ValueError(f"agent {agent_id!r} not found")

    await stop_agent_pod(str(a.id))
    a.runtime_state = "stopped"
    await _db_commit(db)


async def retire_agent(db, agent_id) -> None:
    """Permanent removal: stop Pod, delete topics, delete DB row."""
    from sqlalchemy import select                 # type: ignore
    from sqlalchemy.orm import selectinload       # type: ignore
    from spm.db.models import Agent              # type: ignore

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

    try:
        await stop_agent_pod(str(a.id))
    except Exception as e:  # noqa: BLE001
        log.warning("retire_agent: pod stop failed for %s: %s", a.id, e)

    try:
        await delete_agent_topics(tenant_id=a.tenant_id, agent_id=str(a.id))
    except Exception as e:  # noqa: BLE001
        log.warning("retire_agent: topic delete failed for %s: %s", a.id, e)

    await _db_delete(db, a)
    await _db_commit(db)
