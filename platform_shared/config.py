"""
Centralised settings — loaded from environment variables.
All services import get_settings() and read from this singleton.
"""
from __future__ import annotations
import os
from functools import lru_cache
from typing import List


class Settings:
    # ── Kafka ────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str
    kafka_enable_acls: bool
    kafka_num_partitions: int
    kafka_replication_factor: int

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_host: str
    redis_port: int
    redis_password: str

    # ── OPA ─────────────────────────────────────────────────────────────────
    opa_url: str
    opa_timeout: float

    # ── JWT (RS256) ──────────────────────────────────────────────────────────
    jwt_algorithm: str
    jwt_issuer: str
    jwt_private_key_path: str
    jwt_public_key_path: str
    jwt_audience: str

    # ── Tenants ──────────────────────────────────────────────────────────────
    tenants: List[str]

    # ── Guard model ──────────────────────────────────────────────────────────
    guard_model_url: str
    guard_model_enabled: bool
    guard_model_timeout: float

    # ── Rate limiting ────────────────────────────────────────────────────────
    rate_limit_rpm: int
    rate_limit_burst: int

    # ── CEP windows ──────────────────────────────────────────────────────────
    cep_short_window_sec: int
    cep_long_window_sec: int
    cep_short_threshold: int
    cep_long_threshold: int
    cep_intent_drift_threshold: float
    cep_session_history_size: int

    # ── Memory TTLs ──────────────────────────────────────────────────────────
    memory_session_ttl: int
    memory_longterm_ttl: int
    memory_system_ttl: int

    # ── Output guard ─────────────────────────────────────────────────────────
    output_guard_llm_enabled: bool
    output_guard_llm_url: str
    output_guard_llm_timeout: float

    # ── Posture thresholds ───────────────────────────────────────────────────
    posture_allow_threshold: float
    posture_escalate_threshold: float
    posture_block_threshold: float

    # ── Service identity ─────────────────────────────────────────────────────
    service_version: str
    environment: str

    def __init__(self) -> None:
        # Kafka
        self.kafka_bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
        self.kafka_enable_acls = os.getenv("KAFKA_ENABLE_ACLS", "true").lower() == "true"
        self.kafka_num_partitions = int(os.getenv("KAFKA_NUM_PARTITIONS", "3"))
        self.kafka_replication_factor = int(os.getenv("KAFKA_REPLICATION_FACTOR", "1"))

        # Redis
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_password = os.getenv("REDIS_PASSWORD", "")

        # OPA
        self.opa_url = os.getenv("OPA_URL", "http://localhost:8181")
        self.opa_timeout = float(os.getenv("OPA_TIMEOUT", "2.0"))

        # JWT
        self.jwt_algorithm = os.getenv("JWT_ALGORITHM", "RS256")
        self.jwt_issuer = os.getenv("JWT_ISSUER", "cpm-platform")
        self.jwt_private_key_path = os.getenv("JWT_PRIVATE_KEY_PATH", "/keys/private.pem")
        self.jwt_public_key_path = os.getenv("JWT_PUBLIC_KEY_PATH", "/keys/public.pem")
        self.jwt_audience = os.getenv("JWT_AUDIENCE", "cpm-api")

        # Tenants
        raw_tenants = os.getenv("TENANTS", "t1")
        self.tenants = [t.strip() for t in raw_tenants.split(",") if t.strip()]

        # Guard model
        self.guard_model_url = os.getenv("GUARD_MODEL_URL", "http://guard-model:8200")
        self.guard_model_enabled = os.getenv("GUARD_MODEL_ENABLED", "true").lower() == "true"
        # 60.0s default — high enough to cover local-LLM inference on CPU
        # (llama-3.1-8b on M-series CPU: 3–60s per /screen call).  Override
        # to 2.0–5.0 when using Groq cloud, via GUARD_MODEL_TIMEOUT env var.
        self.guard_model_timeout = float(os.getenv("GUARD_MODEL_TIMEOUT", "60.0"))

        # Rate limiting
        self.rate_limit_rpm = int(os.getenv("RATE_LIMIT_RPM", "60"))
        self.rate_limit_burst = int(os.getenv("RATE_LIMIT_BURST", "10"))

        # CEP
        self.cep_short_window_sec = int(os.getenv("CEP_SHORT_WINDOW_SEC", "120"))
        self.cep_long_window_sec = int(os.getenv("CEP_LONG_WINDOW_SEC", "3600"))
        self.cep_short_threshold = int(os.getenv("CEP_SHORT_THRESHOLD", "5"))
        self.cep_long_threshold = int(os.getenv("CEP_LONG_THRESHOLD", "15"))
        self.cep_intent_drift_threshold = float(os.getenv("CEP_INTENT_DRIFT_THRESHOLD", "0.65"))
        self.cep_session_history_size = int(os.getenv("CEP_SESSION_HISTORY_SIZE", "10"))

        # Memory TTLs (seconds)
        self.memory_session_ttl = int(os.getenv("MEMORY_SESSION_TTL_SEC", "3600"))
        self.memory_longterm_ttl = int(os.getenv("MEMORY_LONGTERM_TTL_SEC", "2592000"))
        self.memory_system_ttl = int(os.getenv("MEMORY_SYSTEM_TTL_SEC", "86400"))

        # Output guard
        self.output_guard_llm_enabled = os.getenv("OUTPUT_GUARD_LLM_ENABLED", "true").lower() == "true"
        self.output_guard_llm_url = os.getenv("OUTPUT_GUARD_LLM_URL", "http://guard-model:8200")
        self.output_guard_llm_timeout = float(os.getenv("OUTPUT_GUARD_LLM_TIMEOUT", "2.0"))

        # Posture thresholds
        self.posture_allow_threshold = float(os.getenv("POSTURE_ALLOW_THRESHOLD", "0.30"))
        self.posture_escalate_threshold = float(os.getenv("POSTURE_ESCALATE_THRESHOLD", "0.70"))
        self.posture_block_threshold = float(os.getenv("POSTURE_BLOCK_THRESHOLD", "0.70"))

        # Service identity
        self.service_version = os.getenv("SERVICE_VERSION", "3.0.0")
        self.environment = os.getenv("ENVIRONMENT", "production")

    def load_public_key(self) -> str:
        path = self.jwt_public_key_path
        try:
            with open(path) as f:
                return f.read().strip()
        except FileNotFoundError:
            key = os.getenv("JWT_PUBLIC_KEY", "")
            if not key:
                raise RuntimeError(f"JWT public key not found at {path} and JWT_PUBLIC_KEY env not set")
            return key

    def load_private_key(self) -> str:
        path = self.jwt_private_key_path
        try:
            with open(path) as f:
                return f.read().strip()
        except FileNotFoundError:
            key = os.getenv("JWT_PRIVATE_KEY", "")
            if not key:
                raise RuntimeError(f"JWT private key not found at {path} and JWT_PRIVATE_KEY env not set")
            return key

    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    def __repr__(self) -> str:
        return (
            f"Settings(env={self.environment}, tenants={self.tenants}, "
            f"kafka={self.kafka_bootstrap_servers}, opa={self.opa_url})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
