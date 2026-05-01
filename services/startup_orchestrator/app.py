#!/usr/bin/env python3
"""
Startup Orchestrator — runs once at platform startup.

Automatically provisions:
1. RSA key pair (if missing)
2. Kafka topics (all tenants, all topic suffixes)
3. Kafka ACLs (per-tenant service principals)
4. Kafka consumer group pre-registration
5. Redis key schema defaults (rate limit config, freeze state sentinel)
6. OPA health check + policy validation
7. Self-register CPM models with AI SPM
8. Emit startup audit record

Run: python app.py
Exits 0 on success, 1 on failure.
"""
from __future__ import annotations
import os
import sys
import time
import json
import logging
import subprocess

# Allow import of platform_shared from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
import requests
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, KafkaError

# Single source of truth for the topic registry — DO NOT inline the
# topic list here. Adding new tenant or global topics is a one-line
# change in platform_shared/topics.py and this orchestrator picks it
# up automatically.
from platform_shared.topics import (
    GlobalTopics,
    all_topics_for_tenants,
    topics_for_tenant,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("startup-orchestrator")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration (read directly from env — no Settings singleton yet)
# ─────────────────────────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
OPA_URL = os.getenv("OPA_URL", "http://opa:8181")
TENANTS = ["t1"]  # single-tenant system
KEYS_DIR = os.getenv("KEYS_DIR", "/keys")
JWT_PRIVATE_KEY_PATH = os.getenv("JWT_PRIVATE_KEY_PATH", f"{KEYS_DIR}/private.pem")
JWT_PUBLIC_KEY_PATH = os.getenv("JWT_PUBLIC_KEY_PATH", f"{KEYS_DIR}/public.pem")
NUM_PARTITIONS = int(os.getenv("KAFKA_NUM_PARTITIONS", "3"))
# Default 3 matches the runbook design (3-broker HA cluster).
# Single-broker dev clusters MUST set KAFKA_REPLICATION_FACTOR=1 explicitly
# in their values overrides. Defaulting to 1 was a footgun: it silently
# produced topics that violated min.insync.replicas=2 on the prod cluster.
REPLICATION_FACTOR = int(os.getenv("KAFKA_REPLICATION_FACTOR", "3"))
ENABLE_ACLS = os.getenv("KAFKA_ENABLE_ACLS", "true").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "3.0.0")
SPM_API_URL = os.getenv("SPM_API_URL", "http://spm-api:8092")

# Per-topic retention overrides keyed by the FULL topic name suffix
# (the part after `cpm.<tenant>.`). Anything not listed here gets the
# default 24h retention. The topic NAMES themselves are derived from
# platform_shared/topics.py — we only own retention policy here.
RETENTION_OVERRIDES_MS: dict[str, int] = {
    "audit":            90 * 24 * 3600 * 1000,  # 90 days — compliance trail
    "audit_shadow":     7  * 24 * 3600 * 1000,  # 7 days  — shadow-run window
    "freeze_control":   7  * 24 * 3600 * 1000,
    "approval_request": 7  * 24 * 3600 * 1000,
    "approval_result":  7  * 24 * 3600 * 1000,
}
DEFAULT_RETENTION_MS = 24 * 3600 * 1000  # 24h

# Consumer groups that must exist per tenant
CONSUMER_GROUPS = [
    "cpm-api", "cpm-retrieval", "cpm-processor", "cpm-policy-decider",
    "cpm-agent", "cpm-memory", "cpm-executor", "cpm-tool-parser",
    "cpm-output-guard",
]

# Service registry entries (written to Redis at startup)
SERVICES = [
    {"service": "api", "port": 8080, "capabilities": ["ingress", "rate_limiting", "guard_gate"]},
    {"service": "guard_model", "port": 8200, "capabilities": ["content_screening", "llm_guard"]},
    {"service": "retrieval_gateway", "port": None, "capabilities": ["rag", "provenance_verification"]},
    {"service": "processor", "port": None, "capabilities": ["risk_scoring", "behavioral_analysis"]},
    {"service": "policy_decider", "port": None, "capabilities": ["opa_enforcement"]},
    {"service": "agent", "port": None, "capabilities": ["orchestration", "tool_routing"]},
    {"service": "memory_service", "port": None, "capabilities": ["session_memory", "longterm_memory"]},
    {"service": "executor", "port": None, "capabilities": ["tool_execution"]},
    {"service": "tool_parser", "port": None, "capabilities": ["output_sanitization"]},
    {"service": "output_guard", "port": None, "capabilities": ["pii_redaction", "secret_detection"]},
    {"service": "freeze_controller", "port": 8090, "capabilities": ["control_plane"]},
    {"service": "policy_simulator", "port": 8091, "capabilities": ["policy_testing"]},
    {"service": "flink_pyjob", "port": None, "capabilities": ["behavioral_cep", "ttp_mapping"]},
]


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: RSA key generation
# ─────────────────────────────────────────────────────────────────────────────

def ensure_rsa_keys() -> None:
    log.info("── Step 1: RSA key provisioning ──")
    os.makedirs(KEYS_DIR, exist_ok=True)

    if os.path.exists(JWT_PRIVATE_KEY_PATH) and os.path.exists(JWT_PUBLIC_KEY_PATH):
        log.info("  RSA keys already exist at %s — skipping generation", KEYS_DIR)
        return

    log.info("  Generating 2048-bit RSA key pair at %s ...", KEYS_DIR)
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        with open(JWT_PRIVATE_KEY_PATH, "wb") as f:
            f.write(private_pem)
        os.chmod(JWT_PRIVATE_KEY_PATH, 0o600)

        with open(JWT_PUBLIC_KEY_PATH, "wb") as f:
            f.write(public_pem)
        os.chmod(JWT_PUBLIC_KEY_PATH, 0o644)

        log.info("  ✓ RSA keys generated: private=%s public=%s", JWT_PRIVATE_KEY_PATH, JWT_PUBLIC_KEY_PATH)
    except Exception as e:
        log.error("  ✗ RSA key generation failed: %s", e)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Wait for Kafka
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_kafka(max_wait: int = 120) -> KafkaAdminClient:
    """Connect to Kafka and return a KafkaAdminClient, retrying until max_wait.

    Catches *all* exceptions (not just KafkaError) so that DNS failures,
    OS-level connection errors, and transient socket errors are all retried
    rather than crashing the orchestrator immediately.
    """
    log.info("── Step 2: Waiting for Kafka at %s (max %ds) ──", KAFKA_BOOTSTRAP, max_wait)
    deadline = time.time() + max_wait
    last_exc: Exception | None = None
    while time.time() < deadline:
        admin: KafkaAdminClient | None = None
        try:
            admin = KafkaAdminClient(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                client_id="cpm-startup-orchestrator",
                request_timeout_ms=5000,
                # Pin the API version to skip auto-probing. kafka-python-ng's
                # version probe sends ApiVersionsRequest_v4 first against
                # Confluent 7.6.x (Kafka 3.6) brokers that only support up to
                # v3, fails to fall back, and raises `UnrecognizedBrokerVersion`.
                # Confluent 7.6 is Kafka 3.6, which is wire-compatible with
                # client API version 2.5.0 — that's our floor.
                api_version=(2, 5, 0),
            )
            # Verify connectivity by listing topics — constructor alone doesn't
            # guarantee the broker is actually reachable and responsive.
            admin.list_topics()
            log.info("  ✓ Kafka reachable and responsive")
            return admin
        except Exception as e:
            last_exc = e
            if admin is not None:
                try:
                    admin.close()
                except Exception:
                    pass
            remaining = int(deadline - time.time())
            log.info("  Kafka not ready (%s) — retrying in 3s... (%ds remaining)", e, remaining)
            time.sleep(3)
    raise RuntimeError(
        f"Kafka not reachable after {max_wait}s — last error: {last_exc}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Create Kafka topics (tenant + global)
# ─────────────────────────────────────────────────────────────────────────────

def _retention_for(topic_name: str) -> int:
    """Return retention.ms for a topic, looking up the suffix after the
    final dot in `cpm.<tenant>.<suffix>` (or the whole name for global
    topics)."""
    suffix = topic_name.rsplit(".", 1)[-1] if topic_name.startswith("cpm.") else topic_name
    return RETENTION_OVERRIDES_MS.get(suffix, DEFAULT_RETENTION_MS)


def create_kafka_topics(admin: KafkaAdminClient) -> None:
    log.info("── Step 3: Creating Kafka topics ──")

    # Per-tenant topics are derived from platform_shared/topics.py so
    # adding a new topic there auto-provisions it on next boot. No
    # hand-maintained suffix list to drift out of sync.
    tenant_topic_names = all_topics_for_tenants(TENANTS)

    # Global topics live alongside tenant topics on the same cluster.
    global_topic_names = [
        GlobalTopics.MODEL_EVENTS,
        GlobalTopics.LINEAGE_EVENTS,
    ]

    all_names = tenant_topic_names + global_topic_names
    desired_configs: dict[str, dict[str, str]] = {}
    topics_to_create = []
    for name in all_names:
        config = {
            "cleanup.policy": "delete",
            "retention.ms":   str(_retention_for(name)),
        }
        desired_configs[name] = config
        topics_to_create.append(
            NewTopic(
                name=name,
                num_partitions=NUM_PARTITIONS,
                replication_factor=REPLICATION_FACTOR,
                topic_configs=config,
            )
        )
        log.info("  Queued: %s  (retention=%sh)", name, _retention_for(name) // 3600000)

    try:
        admin.create_topics(new_topics=topics_to_create, validate_only=False)
        log.info("  ✓ %d topics created", len(topics_to_create))
    except TopicAlreadyExistsError:
        log.info("  Topics already exist — running reconciliation pass")
    except KafkaError as e:
        # Individual topics may partially fail (e.g. some already exist and
        # the batch raises). Log as a warning — the orchestrator is designed
        # to be idempotent; missing topics will surface as consumer errors.
        log.warning("  Topic creation warning (some may already exist): %s", e)
    except Exception as e:
        log.error("  ✗ Topic creation failed: %s", e)
        raise

    # Reconcile drift on existing topics. RF mismatches require a
    # partition reassignment which is risky to do automatically — we WARN
    # so the operator notices and runs the migration script. Retention /
    # cleanup-policy drift is safe to fix in place via alter_configs.
    _reconcile_existing_topics(admin, desired_configs)


def _reconcile_existing_topics(admin: KafkaAdminClient,
                               desired_configs: dict[str, dict[str, str]]) -> None:
    """Compare existing topics against the desired registry config.

    For every topic in ``desired_configs``:
      - If the partition replication factor differs from REPLICATION_FACTOR
        we WARN. Auto-rewriting RF requires a partition reassignment plan
        and is intentionally NOT done here — the operator runs
        deploy/scripts/kafka-reconcile-topics.sh for that.
      - If retention.ms / cleanup.policy differ from the desired values we
        ALTER in place (safe operation, takes effect immediately).
    """
    from kafka.admin import ConfigResource, ConfigResourceType  # type: ignore

    topic_names = list(desired_configs.keys())
    try:
        meta = admin.describe_topics(topic_names)
    except Exception as exc:
        log.warning("  reconcile: describe_topics failed (%s) — skipping", exc)
        return

    # Index metadata by topic name. kafka-python returns a list of dicts;
    # each entry has 'topic', 'partitions' (list with 'replicas'), etc.
    rf_drift: list[tuple[str, int, int]] = []
    for entry in meta:
        name = entry.get("topic")
        if name not in desired_configs:
            continue
        partitions = entry.get("partitions") or []
        if not partitions:
            continue
        # Use partition 0 as the canonical RF — kafka enforces uniform RF
        # across partitions of a single topic.
        actual_rf = len(partitions[0].get("replicas") or [])
        if actual_rf != REPLICATION_FACTOR:
            rf_drift.append((name, actual_rf, REPLICATION_FACTOR))

    if rf_drift:
        log.warning("  ⚠  %d topic(s) have wrong replication factor:", len(rf_drift))
        for name, actual, desired in rf_drift:
            log.warning("       %s  rf=%d (expected %d)", name, actual, desired)
        log.warning("       Run deploy/scripts/kafka-reconcile-topics.sh to fix.")

    # Now reconcile per-topic configs (retention, cleanup.policy).
    try:
        resources = [ConfigResource(ConfigResourceType.TOPIC, n) for n in topic_names]
        described = admin.describe_configs(config_resources=resources)
    except Exception as exc:
        log.warning("  reconcile: describe_configs failed (%s) — skipping", exc)
        return

    altered = 0
    altered_resources = []
    for resp in described or []:
        # describe_configs returns DescribeConfigsResponse objects in
        # kafka-python; iterate its `resources` payload.
        for entry in getattr(resp, "resources", []) or []:
            # entry shape: (error_code, error_msg, resource_type, name, configs)
            try:
                _err_code, _err_msg, _rtype, name, configs = entry
            except Exception:
                continue
            if name not in desired_configs:
                continue
            actual = {c[0]: c[1] for c in (configs or [])}
            desired = desired_configs[name]
            drift = {k: v for k, v in desired.items() if str(actual.get(k)) != str(v)}
            if not drift:
                continue
            log.info("  reconcile: %s drift %s", name, drift)
            altered_resources.append(
                ConfigResource(ConfigResourceType.TOPIC, name, configs=desired)
            )
            altered += 1

    if altered_resources:
        try:
            admin.alter_configs(config_resources=altered_resources)
            log.info("  ✓ reconciled %d topic configs", altered)
        except Exception as exc:
            log.warning("  reconcile: alter_configs failed (%s)", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Kafka ACLs
# ─────────────────────────────────────────────────────────────────────────────

def configure_kafka_acls() -> None:
    log.info("── Step 4: Configuring Kafka ACLs ──")
    if not ENABLE_ACLS:
        log.info("  ACLs disabled (KAFKA_ENABLE_ACLS=false) — skipping")
        return

    # We use kafka-acls CLI (available in the cp-kafka image)
    kafka_acls_cmd = "/usr/bin/kafka-acls"
    if not os.path.exists(kafka_acls_cmd):
        kafka_acls_cmd = "kafka-acls"

    acl_errors = 0
    for tenant_id in TENANTS:
        principal = f"User:cpm-{tenant_id}"
        # ACL set should match what create_kafka_topics() provisions —
        # both pull from platform_shared.topics so they stay in lockstep.
        for topic in topics_for_tenant(tenant_id).all_topics():
            for op in ["Read", "Write", "Describe"]:
                cmd = [
                    kafka_acls_cmd,
                    "--bootstrap-server", KAFKA_BOOTSTRAP,
                    "--add",
                    "--allow-principal", principal,
                    "--operation", op,
                    "--topic", topic,
                ]
                try:
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        log.debug("  ACL set: %s %s %s", principal, op, topic)
                    else:
                        log.warning(
                            "  ACL non-zero exit for %s %s %s: %s",
                            principal, op, topic, result.stderr.strip()
                        )
                        acl_errors += 1
                except subprocess.TimeoutExpired:
                    log.warning("  ACL command timed out for %s %s %s", principal, op, topic)
                    acl_errors += 1
                except Exception as e:
                    log.warning("  ACL command failed for %s %s %s: %s", principal, op, topic, e)
                    acl_errors += 1

        # Consumer group ACLs
        for group in CONSUMER_GROUPS:
            cmd = [
                kafka_acls_cmd,
                "--bootstrap-server", KAFKA_BOOTSTRAP,
                "--add",
                "--allow-principal", principal,
                "--operation", "Read",
                "--group", group,
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    log.warning(
                        "  Consumer group ACL non-zero for %s/%s: %s",
                        principal, group, result.stderr.strip()
                    )
                    acl_errors += 1
            except subprocess.TimeoutExpired:
                log.warning("  Consumer group ACL timed out for %s/%s", principal, group)
                acl_errors += 1
            except Exception as e:
                log.warning("  Consumer group ACL failed for %s/%s: %s", principal, group, e)
                acl_errors += 1

        if acl_errors == 0:
            log.info("  ✓ ACLs configured for principal %s", principal)
        else:
            log.warning("  ACL configuration for %s completed with %d warning(s)", principal, acl_errors)


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Redis defaults
# ─────────────────────────────────────────────────────────────────────────────

def seed_redis_defaults() -> redis.Redis:
    log.info("── Step 5: Seeding Redis defaults ──")
    # Use platform_shared.redis so this picks up Sentinel-aware master
    # discovery when REDIS_SENTINEL_HOSTS is set (HA prod), and falls
    # back to direct REDIS_HOST:REDIS_PORT otherwise. Replaces the
    # earlier kwargs-then-redis.Redis() construction which pinned the
    # orchestrator to the haproxy redis-master Service.
    from platform_shared.redis import get_redis_client

    # Wait for Redis with explicit connection tracking.
    # NOTE: redis.Redis() does NOT connect on construction — it only connects
    # on the first command (ping). We must track success with a flag, not by
    # testing `r is None`, which would always be False after the first attempt.
    r: redis.Redis | None = None
    connected = False
    for attempt in range(20):
        try:
            candidate = get_redis_client(decode_responses=True)
            candidate.ping()
            r = candidate
            connected = True
            log.info("  ✓ Redis reachable (sentinel-aware client)")
            break
        except Exception as e:
            log.info(
                "  Redis not ready (attempt %d/20): %s — retrying in 2s...",
                attempt + 1, e
            )
            time.sleep(2)

    if not connected or r is None:
        raise RuntimeError(
            f"Redis not reachable after 20 attempts (40s) at {REDIS_HOST}:{REDIS_PORT}"
        )

    # Platform configuration keys
    platform_config = {
        "cpm:config:version": SERVICE_VERSION,
        "cpm:config:environment": ENVIRONMENT,
        "cpm:config:started_at": str(int(time.time())),
        "cpm:config:tenants": json.dumps(TENANTS),
    }
    for k, v in platform_config.items():
        r.set(k, v)
        log.info("  Set %s = %s", k, v)

    # Per-tenant: initialise freeze state as unfrozen
    for tenant_id in TENANTS:
        freeze_key = f"freeze:{tenant_id}:tenant"
        if not r.exists(freeze_key):
            r.set(freeze_key, "false")
            log.info("  Initialized freeze state: %s = false", freeze_key)

    # Service registry: write AI-BOM for each service
    for svc in SERVICES:
        key = f"cpm:registry:{svc['service']}"
        entry = {
            "service": svc["service"],
            "version": SERVICE_VERSION,
            "port": svc.get("port"),
            "capabilities": svc.get("capabilities", []),
            "registered_at": int(time.time()),
            "environment": ENVIRONMENT,
        }
        r.set(key, json.dumps(entry))
        r.expire(key, 3600)  # refreshed by each service's /health loop
        log.info("  Registered service: %s", svc["service"])

    # OPA policy version tracking
    r.set("cpm:policy:version", "3.0.0")
    r.set("cpm:policy:loaded_at", str(int(time.time())))

    log.info("  ✓ Redis defaults seeded")
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: OPA health + policy validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_opa() -> None:
    log.info("── Step 6: Validating OPA policies ──")

    # Wait for OPA health endpoint
    for attempt in range(30):
        try:
            resp = requests.get(f"{OPA_URL}/health", timeout=3)
            if resp.status_code == 200:
                log.info("  ✓ OPA reachable at %s", OPA_URL)
                break
        except Exception as e:
            log.info("  OPA not ready (attempt %d/30): %s — retrying in 3s...", attempt + 1, e)
        time.sleep(3)
    else:
        raise RuntimeError(f"OPA not reachable after 90s at {OPA_URL}")

    # Smoke-test each policy with minimal valid input
    policy_smoke_tests = [
        (
            "/v1/data/spm/prompt/allow",
            {
                "posture_score": 0.10,
                "signals": [],
                "behavioral_signals": [],
                "retrieval_trust": 1.0,
                "intent_drift": 0.0,
                "guard_verdict": "allow",
                "guard_score": 0.0,
                "auth_context": {"sub": "test", "tenant_id": "t1", "roles": ["user"], "scopes": [], "claims": {}},
            },
            "prompt",
        ),
        (
            "/v1/data/spm/tools/allow",
            {
                "tool_name": "calendar.read",
                "posture_score": 0.10,
                "signals": [],
                "intent": "read_calendar",
                "auth_context": {"sub": "test", "tenant_id": "t1", "roles": ["user"], "scopes": ["calendar:read"], "claims": {}},
            },
            "tools",
        ),
        (
            "/v1/data/spm/memory/allow",
            {
                "operation": "read",
                "namespace": "session",
                "posture_score": 0.05,
                "signals": [],
                "auth_context": {"sub": "test", "tenant_id": "t1", "roles": ["user"], "scopes": ["memory:read"], "claims": {}},
            },
            "memory",
        ),
        (
            "/v1/data/spm/output/allow",
            {"contains_pii": False, "contains_secret": False},
            "output",
        ),
        (
            "/v1/data/spm/agent/resolve_tool",
            {
                "prompt": "what is on my calendar today",
                "posture_score": 0.05,
                "signals": [],
                "auth_context": {"sub": "test", "tenant_id": "t1", "roles": ["user"], "scopes": ["calendar:read"], "claims": {}},
            },
            "agent",
        ),
    ]

    for path, input_data, policy_name in policy_smoke_tests:
        try:
            resp = requests.post(
                f"{OPA_URL}{path}",
                json={"input": input_data},
                timeout=5,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            decision = result.get("decision") if isinstance(result, dict) else None
            log.info("  ✓ Policy '%s' smoke test OK — decision: %s", policy_name, decision)
        except Exception as e:
            log.error("  ✗ Policy '%s' smoke test FAILED: %s", policy_name, e)
            raise RuntimeError(f"OPA policy '{policy_name}' failed smoke test") from e


# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Self-register CPM models with AI SPM
# ─────────────────────────────────────────────────────────────────────────────

def register_cpm_models_with_spm() -> None:
    """Self-register CPM's own models in spm-api.

    spm-api is NOT in startup-orchestrator's depends_on (it starts in parallel).
    This step retries for up to ~60s to give spm-api time to come up. If it
    doesn't, we log a warning and continue — models can be registered later on
    the next restart, and the warning makes it visible in logs.
    """
    log.info("── Step 7: Registering CPM models with AI SPM ──")
    models = [
        {
            "name": "llama-guard-3", "version": "3.0.0",
            "provider": "local", "purpose": "content_screening",
            "risk_tier": "limited", "tenant_id": "global",
            "status": "approved", "approved_by": "startup-orchestrator",
        },
        {
            "name": "output-guard-llm", "version": SERVICE_VERSION,
            "provider": "local", "purpose": "output_screening",
            "risk_tier": "limited", "tenant_id": "global",
            "status": "approved", "approved_by": "startup-orchestrator",
        },
    ]
    max_attempts = 20  # ~60s at 3s sleep
    for attempt in range(max_attempts):
        try:
            for model in models:
                resp = requests.post(
                    f"{SPM_API_URL}/models",
                    json=model,
                    timeout=5.0,
                )
                if resp.status_code in (200, 201, 409):  # 409 = already exists, ok
                    log.info("  ✓ Registered: %s (HTTP %d)", model["name"], resp.status_code)
                else:
                    raise RuntimeError(
                        f"spm-api returned {resp.status_code} for {model['name']}"
                    )
            return  # success
        except Exception as e:
            remaining = max_attempts - attempt - 1
            if remaining > 0:
                log.info(
                    "  SPM registration attempt %d/%d failed: %s — retrying in 3s...",
                    attempt + 1, max_attempts, e
                )
                time.sleep(3)
            else:
                log.warning(
                    "  ✗ SPM registration failed after %d attempts: %s — "
                    "models will be unregistered until the next restart",
                    max_attempts, e
                )


# ─────────────────────────────────────────────────────────────────────────────
# Step 8: Emit startup audit event
# ─────────────────────────────────────────────────────────────────────────────

def emit_startup_audit(r: redis.Redis) -> None:
    log.info("── Step 8: Startup audit record ──")
    for tenant_id in TENANTS:
        record = {
            "ts": int(time.time() * 1000),
            "tenant_id": tenant_id,
            "component": "startup-orchestrator",
            "event_type": "platform_startup",
            "severity": "info",
            "details": {
                "version": SERVICE_VERSION,
                "environment": ENVIRONMENT,
                "tenants": TENANTS,
                "topics_created": topics_for_tenant(tenant_id).all_topics(),
                "acls_enabled": ENABLE_ACLS,
                "opa_url": OPA_URL,
            },
        }
        key = f"cpm:audit:startup:{tenant_id}:{int(time.time())}"
        r.set(key, json.dumps(record), ex=86400 * 30)
        log.info("  ✓ Startup audit record written for tenant %s", tenant_id)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║   CPM Platform Startup Orchestrator v%s   ║", SERVICE_VERSION)
    log.info("╚══════════════════════════════════════════════╝")
    log.info("Environment: %s | Tenants: %s", ENVIRONMENT, TENANTS)

    admin: KafkaAdminClient | None = None
    try:
        # Step 1 — RSA keys (idempotent; must run before any JWT-signing service)
        ensure_rsa_keys()

        # Step 2+3 — Kafka: wait for readiness, create all topics in one pass
        admin = wait_for_kafka()
        try:
            create_kafka_topics(admin)
        finally:
            # Always close the admin client even if topic creation raises
            try:
                admin.close()
            except Exception:
                pass
            admin = None

        # Step 4 — ACLs (optional; controlled by KAFKA_ENABLE_ACLS)
        configure_kafka_acls()

        # Step 5 — Redis defaults; returns a live client for use in step 8
        r = seed_redis_defaults()

        # Step 6 — OPA health + policy smoke tests
        validate_opa()

        # Step 7 — Model registration in spm-api (best-effort with retries)
        register_cpm_models_with_spm()

        # Step 8 — Audit record (written last so it only appears on full success)
        emit_startup_audit(r)

        log.info("╔══════════════════════════════════════════════╗")
        log.info("║   ✓ Platform startup complete                ║")
        log.info("╚══════════════════════════════════════════════╝")
        return 0

    except Exception as e:
        log.error("✗ Startup FAILED: %s", e, exc_info=True)
        return 1
    finally:
        # Belt-and-suspenders: close admin if it was opened but never closed
        # (e.g. if wait_for_kafka succeeded but create_kafka_topics raised
        # before the inner finally ran due to a BaseException).
        if admin is not None:
            try:
                admin.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
