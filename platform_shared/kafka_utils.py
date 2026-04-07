"""
Kafka producer / consumer factory with production-grade defaults.
"""
from __future__ import annotations
import json
import logging
from typing import List
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
from platform_shared.config import get_settings

log = logging.getLogger(__name__)


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
