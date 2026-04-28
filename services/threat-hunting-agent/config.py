from __future__ import annotations
from pydantic_settings import BaseSettings


# This is a single-tenant system.  The tenant ID is always "t1".
TENANT_ID = "t1"


# ─── Hardcoded LLM backend (OrbStack k8s → host Ollama) ──────────────────────
# Intentionally NOT exposed as env-configurable Settings fields so that
# hydrate_env_from_db() and stale shell exports cannot override them.
#
# From inside an OrbStack k8s pod, the host is reachable at host.lima.internal
# (host.docker.internal is a docker-engine-only alias and does NOT resolve
# inside k8s pods).  Run `getent hosts host.lima.internal` from inside a pod
# to confirm; on newer OrbStack builds host.orb.internal also resolves.
HUNT_MODEL    = "llama3.2"
GROQ_BASE_URL = "http://host.lima.internal:11434/v1"
GROQ_API_KEY  = "local"   # any non-empty string — Ollama ignores it


class Settings(BaseSettings):
    # Kafka
    kafka_bootstrap_servers: str = "kafka-broker:9092"

    # Hunt tuning
    hunt_batch_window_sec: int = 30
    hunt_queue_max:        int = 20
    threathunting_ai_interval_sec: int = 300

    # Downstream services
    orchestrator_url:  str = "http://agent-orchestrator:8094"
    platform_api_url:  str = "http://api:8080"   # for dev-token auth
    guard_model_url:   str = "http://guard-model:8200"
    opa_url:           str = "http://opa:8181"

    # Databases
    spm_db_url:  str = "postgresql://spm_rw:spmpass@spm-db:5432/spm"
    redis_host:  str = "redis"
    redis_port:  int = 6379

    model_config = {"env_file": ".env", "extra": "ignore"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
