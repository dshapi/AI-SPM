from __future__ import annotations
from pydantic import Field
from pydantic_settings import BaseSettings


# This is a single-tenant system.  The tenant ID is always "t1".
TENANT_ID = "t1"


class Settings(BaseSettings):
    # Kafka
    kafka_bootstrap_servers: str = "kafka-broker:9092"

    # Groq / LLM — GROQ_API_KEY is REQUIRED; service will refuse to start if missing
    groq_api_key: str = Field(..., min_length=1)
    hunt_model:   str = "llama-3.3-70b-versatile"

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
