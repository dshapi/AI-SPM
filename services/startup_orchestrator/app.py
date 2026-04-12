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
7. Service inventory registration in Redis

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
import hashlib

# Allow import of platform_shared from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis
import requests
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, KafkaError

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
REPLICATION_FACTOR = int(os.getenv("KAFKA_REPLICATION_FACTOR", "1"))
ENABLE_ACLS = os.getenv("KAFKA_ENABLE_ACLS", "true").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "3.0.0")
SPM_API_URL = os.getenv("SPM_API_URL", "http://spm-api:8092")

# Topic suffixes to create for each tenant
TOPIC_SUFFIXES = [
    "raw", "retrieved", "posture_enriched", "decision",
    "memory_request", "memory_result",
    "tool_request", "tool_result", "tool_observation",
    "final_response", "freeze_control", "audit",
    "approval_request", "approval_result",
]

# Consumer groups that must exist per tenant
CONSUMER_GROUPS = [
    "cpm-api", "cpm-retrieval", "cpm-processor", "cpm-policy-decider",
    "cpm-agent", "cpm-memory", "cpm-executor", "cpm-tool-parser",
    "cpm-output-guard", "cpm-flink-cep",
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
    {"service": "flink_cep", "port": None, "capabilities": ["behavioral_cep", "ttp_mapping"]},
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
    log.info("── Step 2: Waiting for Kafka at %s ──", KAFKA_BOOTSTRAP)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            admin = KafkaAdminClient(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                client_id="cpm-startup-orchestrator",
                request_timeout_ms=5000,
            )
            log.info("  ✓ Kafka reachable")
            return admin
        except KafkaError as e:
            log.info("  Kafka not ready: %s — retrying in 3s...", e)
            time.sleep(3)
    raise RuntimeError(f"Kafka not reachable after {max_wait}s")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Create Kafka topics
# ─────────────────────────────────────────────────────────────────────────────

def create_kafka_topics(admin: KafkaAdminClient) -> None:
    log.info("── Step 3: Creating Kafka topics ──")
    topics_to_create = []
    for tenant_id in TENANTS:
        for suffix in TOPIC_SUFFIXES:
            name = f"cpm.{tenant_id}.{suffix}"

            # Retention and cleanup policies per topic type
            config = {"cleanup.policy": "delete"}
            if suffix == "audit":
                config["retention.ms"] = str(90 * 24 * 3600 * 1000)  # 90 days
            elif suffix in ("freeze_control", "approval_request", "approval_result"):
                config["retention.ms"] = str(7 * 24 * 3600 * 1000)   # 7 days
            else:
                config["retention.ms"] = str(24 * 3600 * 1000)        # 24 hours

            topics_to_create.append(
                NewTopic(
                    name=name,
                    num_partitions=NUM_PARTITIONS,
                    replication_factor=REPLICATION_FACTOR,
                    topic_configs=config,
                )
            )
            log.info("  Queued: %s", name)

    try:
        admin.create_topics(new_topics=topics_to_create, validate_only=False)
        log.info("  ✓ %d topics created", len(topics_to_create))
    except TopicAlreadyExistsError:
        log.info("  Topics already exist — skipping")
    except Exception as e:
        log.warning("  Topic creation warning: %s", e)


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

    for tenant_id in TENANTS:
        principal = f"User:cpm-{tenant_id}"
        for suffix in TOPIC_SUFFIXES:
            topic = f"cpm.{tenant_id}.{suffix}"
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
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        log.debug("  ACL set: %s %s %s", principal, op, topic)
                    else:
                        log.warning("  ACL warning: %s", result.stderr.strip())
                except Exception as e:
                    log.warning("  ACL configure failed: %s", e)

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
                subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            except Exception:
                pass

        log.info("  ✓ ACLs configured for principal %s", principal)


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Redis defaults
# ─────────────────────────────────────────────────────────────────────────────

def seed_redis_defaults() -> None:
    log.info("── Step 5: Seeding Redis defaults ──")
    kwargs = {"host": REDIS_HOST, "port": REDIS_PORT, "decode_responses": True}
    if REDIS_PASSWORD:
        kwargs["password"] = REDIS_PASSWORD

    # Wait for Redis
    r = None
    for attempt in range(20):
        try:
            r = redis.Redis(**kwargs)
            r.ping()
            log.info("  ✓ Redis reachable at %s:%d", REDIS_HOST, REDIS_PORT)
            break
        except Exception as e:
            log.info("  Redis not ready: %s — retrying in 2s...", e)
            time.sleep(2)
    if r is None:
        raise RuntimeError("Redis not reachable at startup")

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

    # Wait for OPA
    for attempt in range(30):
        try:
            resp = requests.get(f"{OPA_URL}/health", timeout=3)
            if resp.status_code == 200:
                log.info("  ✓ OPA reachable at %s", OPA_URL)
                break
        except Exception:
            pass
        log.info("  OPA not ready — retrying in 3s... (%d/30)", attempt + 1)
        time.sleep(3)
    else:
        raise RuntimeError("OPA not reachable after 90s")

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
# Step 7: Emit startup audit event
# ─────────────────────────────────────────────────────────────────────────────

def emit_startup_audit(r: redis.Redis) -> None:
    log.info("── Step 7: Startup audit record ──")
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
                "topics_created": [f"cpm.{tenant_id}.{s}" for s in TOPIC_SUFFIXES],
                "acls_enabled": ENABLE_ACLS,
                "opa_url": OPA_URL,
            },
        }
        key = f"cpm:audit:startup:{tenant_id}:{int(time.time())}"
        r.set(key, json.dumps(record), ex=86400 * 30)
        log.info("  ✓ Startup audit record written for tenant %s", tenant_id)


# ─────────────────────────────────────────────────────────────────────────────
# Step 8: Create global SPM topic
# ─────────────────────────────────────────────────────────────────────────────

def create_global_topics(admin: KafkaAdminClient) -> None:
    """Create the global model_events topic used by AI SPM."""
    log.info("── Step 8: Creating global SPM topic ──")
    from platform_shared.topics import GlobalTopics
    topic_name = GlobalTopics().MODEL_EVENTS
    try:
        admin.create_topics([
            NewTopic(
                name=topic_name,
                num_partitions=1,
                replication_factor=REPLICATION_FACTOR,
                topic_configs={"retention.ms": str(7 * 24 * 3600 * 1000)},
            )
        ], validate_only=False)
        log.info("  ✓ Created: %s", topic_name)
    except TopicAlreadyExistsError:
        log.info("  Topic already exists — skipping")


# ─────────────────────────────────────────────────────────────────────────────
# Step 9: Self-register CPM models with AI SPM
# ─────────────────────────────────────────────────────────────────────────────

def register_cpm_models_with_spm() -> None:
    """Self-register CPM's own models in spm-api. Retries up to 10 times."""
    log.info("── Step 9: Registering CPM models with AI SPM ──")
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
    for attempt in range(10):
        try:
            for model in models:
                resp = requests.post(
                    f"{SPM_API_URL}/models",
                    json=model,
                    timeout=5.0,
                )
                if resp.status_code in (200, 201, 409):  # 409 = already exists, ok
                    log.info("  ✓ Registered: %s", model["name"])
                else:
                    raise RuntimeError(f"spm-api returned {resp.status_code}")
            return  # success
        except Exception as e:
            log.warning("  SPM registration attempt %d/10 failed: %s", attempt + 1, e)
            if attempt < 9:
                time.sleep(3)
    log.warning("  SPM registration failed after 10 attempts — continuing without it")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║   CPM Platform Startup Orchestrator v%s   ║", SERVICE_VERSION)
    log.info("╚══════════════════════════════════════════════╝")
    log.info("Environment: %s | Tenants: %s", ENVIRONMENT, TENANTS)

    try:
        ensure_rsa_keys()
        admin = wait_for_kafka()
        create_kafka_topics(admin)
        admin.close()
        configure_kafka_acls()
        r = seed_redis_defaults()
        validate_opa()
        # Reopen admin client for global topics
        admin2 = wait_for_kafka(max_wait=30)
        create_global_topics(admin2)
        admin2.close()
        register_cpm_models_with_spm()
        emit_startup_audit(r)

        log.info("╔══════════════════════════════════════════════╗")
        log.info("║   ✓ Platform startup complete                ║")
        log.info("╚══════════════════════════════════════════════╝")
        return 0

    except Exception as e:
        log.error("✗ Startup FAILED: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
