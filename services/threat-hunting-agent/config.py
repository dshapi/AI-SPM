from __future__ import annotations
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kafka — TENANTS is comma-separated, e.g. "t1,t2,t3"
    # The consumer subscribes to cpm.{tenant}.audit + cpm.{tenant}.decision
    # + cpm.{tenant}.posture_enriched for each tenant in the list.
    kafka_bootstrap_servers: str = "kafka-broker:9092"
    tenants: str = "t1"  # override with TENANTS=t1,t2,t3

    # Groq / LLM — GROQ_API_KEY is REQUIRED; service will refuse to start if missing
    groq_api_key: str = Field(..., min_length=1)
    groq_model:   str = "llama-3.3-70b-versatile"

    # Hunt tuning
    hunt_batch_window_sec: int = 30
    hunt_queue_max:        int = 20

    # Downstream services
    orchestrator_url:  str = "http://agent-orchestrator:8094"
    platform_api_url:  str = "http://api:8080"   # for dev-token auth
    guard_model_url:   str = "http://guard-model:8200"
    opa_url:           str = "http://opa:8181"

    # Databases
    spm_db_url:  str = "postgresql://spm_rw:spmpass@spm-db:5432/spm"
    redis_host:  str = "redis"
    redis_port:  int = 6379

    @property
    def tenant_list(self) -> list[str]:
        return [t.strip() for t in self.tenants.split(",") if t.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
