from __future__ import annotations
import os
from pydantic_settings import BaseSettings


# This is a single-tenant system.  The tenant ID is always "t1".
TENANT_ID = "t1"


# ─── LLM backend (cluster-routed via spm-llm-proxy) ──────────────────────────
# The threat-hunting agent's reasoning LLM is reached through the
# in-cluster ``spm-llm-proxy`` Service, which exposes an OpenAI-compatible
# ``/v1`` endpoint and proxies to whichever upstream model is configured
# at the platform level (Groq, Ollama, Anthropic-via-shim, etc.).
#
# History: this was originally hardcoded to ``http://host.lima.internal:11434/v1``
# for an OrbStack k8s setup that ran Ollama on the host. After the move
# to Docker Desktop kind, that hostname does not resolve from inside
# pods and DNS errors floored every hunt cycle. The cluster Service
# resolves cleanly and lets the agent run regardless of which upstream
# the platform has rotated to. Env-overridable via AGENT_LLM_BASE_URL
# for non-default deployments. Variable name kept as ``GROQ_BASE_URL``
# for backward-compat with existing import sites.
HUNT_MODEL = os.environ.get("HUNT_MODEL", "llama3.2")
GROQ_BASE_URL = os.environ.get(
    "AGENT_LLM_BASE_URL",
    "http://spm-llm-proxy.aispm.svc.cluster.local:8500/v1",
)
GROQ_API_KEY = os.environ.get("AGENT_LLM_API_KEY", "local")  # any non-empty


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
