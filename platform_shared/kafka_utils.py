"""
Kafka producer / consumer factory with production-grade defaults.
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Optional, Union
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
from platform_shared.config import get_settings

log = logging.getLogger(__name__)


def _iso_from_epoch_ms(ts_ms: Optional[int]) -> str:
    """Convert epoch-milliseconds int to ISO-8601 UTC string."""
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def build_producer() -> KafkaProducer:
    """
    Build a KafkaProducer with:
    - JSON serialization
    - acks=all for durability
    - idempotent delivery (max_in_flight=1, retries=5)
    """
    s = get_settings()
    return KafkaProducer(
        bootstrap_servers=s.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        acks="all",
        retries=5,
        max_in_flight_requests_per_connection=1,
        compression_type="gzip",
        request_timeout_ms=10000,
        retry_backoff_ms=300,
    )


def build_consumer(topics: List[str], group_id: str) -> KafkaConsumer:
    """
    Build a KafkaConsumer with:
    - JSON deserialization
    - earliest offset reset for new groups
    - manual commit disabled (auto-commit enabled for simplicity in reference impl)
    """
    s = get_settings()
    return KafkaConsumer(
        *topics,
        bootstrap_servers=s.kafka_bootstrap_servers,
        group_id=group_id,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        auto_commit_interval_ms=1000,
        session_timeout_ms=30000,
        heartbeat_interval_ms=10000,
        max_poll_records=100,
        fetch_max_wait_ms=500,
    )


def safe_send(producer: KafkaProducer, topic: str, payload: dict) -> bool:
    """Send with error handling. Returns True on success."""
    try:
        future = producer.send(topic, payload)
        producer.flush(timeout=5)
        future.get(timeout=5)
        return True
    except KafkaError as e:
        log.error("Kafka send failed topic=%s error=%s", topic, e)
        return False


def send_event(
    producer: KafkaProducer,
    topic: str,
    model: Any,
    *,
    event_type: str,
    source_service: str,
    correlation_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> bool:
    """
    Serialize *model* and merge the normalized KafkaEnvelope fields into the
    outbound dict before calling safe_send().

    Why flat merge instead of a nested envelope?
    ────────────────────────────────────────────
    Existing consumers parse their specific domain model (e.g.
    PostureEnrichedEvent(**payload)) using Pydantic v2.  Pydantic v2 silently
    ignores extra fields by default, so adding new top-level keys never breaks
    existing consumers.  The WebSocket bridge and any future consumer that
    cares about the envelope fields can read them from the raw dict directly.

    Field resolution rules
    ──────────────────────
    session_id      explicit arg → model.session_id → None
    correlation_id  explicit arg → model.event_id   → ""
    timestamp       model.ts (epoch-ms) → now()
    """
    raw: dict = (
        model.model_dump() if hasattr(model, "model_dump") else dict(model)
    )

    # Resolve session_id
    resolved_sid = (
        session_id
        or raw.get("session_id")
        or None
    )

    # Resolve correlation_id — event_id is the causal anchor in legacy models
    resolved_cid = (
        correlation_id
        or raw.get("event_id")
        or raw.get("correlation_id")
        or ""
    )

    # Resolve ISO-8601 timestamp
    ts_ms: Optional[int] = raw.get("ts") or raw.get("requested_at")
    iso_ts = _iso_from_epoch_ms(ts_ms)

    # Merge envelope fields (never overwrite existing domain fields of same name)
    envelope_extras = {
        "event_type":     event_type,
        "source_service": source_service,
        "correlation_id": resolved_cid,
        "timestamp":      iso_ts,
    }
    if resolved_sid is not None:
        envelope_extras["session_id"] = resolved_sid

    # Envelope fields go in ONLY if not already declared by the domain model
    # (guards against overwriting e.g. a model's own event_type field)
    merged = {**envelope_extras, **raw}

    return safe_send(producer, topic, merged)
