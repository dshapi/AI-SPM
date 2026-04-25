"""Lazy fire-and-forget Kafka producer for agent-runtime lineage events.

Used by spm-mcp and spm-llm-proxy (and any other internal service that
just needs to publish a one-off lineage envelope without holding a
producer for the lifetime of the request). Kept separate from
``platform_shared.lineage_events`` because that module's
``publish_lineage_event`` requires the caller to own the producer; this
helper hides that detail behind a single ``emit_agent_event`` call and
takes care of:

  * Lazy producer construction on first use (so importing this module is
    free for services that never emit).
  * Safe-on-init: if Kafka is unreachable at module load, the producer
    stays ``None`` and ``emit_agent_event`` becomes a no-op rather than
    raising. Lineage is best-effort — losing one row never breaks the
    serving path.
  * Fire-and-forget send: we do NOT call ``flush`` or ``future.get`` on
    the produced record. That keeps the call fast (~ms) inside an
    async hot-path; the kafka-python background thread does the actual
    network I/O.
  * Reusable across requests, but rebuilds on the next call if the
    previous send observed a fatal error (e.g. broker restart).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from platform_shared.lineage_events import build_lineage_envelope
from platform_shared.topics       import GlobalTopics

log = logging.getLogger(__name__)


_producer = None              # type: Optional[Any]
_producer_lock = threading.Lock()
_producer_dead = False        # set True after a fatal init failure to avoid retry storms


def _build_producer():
    """Construct a kafka-python KafkaProducer. Returns None on any
    init failure — caller treats that as 'producer unavailable'."""
    try:
        from kafka import KafkaProducer  # type: ignore
    except Exception as e:                                 # noqa: BLE001
        log.warning("lineage_producer: kafka-python not importable (%s)", e)
        return None
    bootstrap = os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092",
    )
    try:
        return KafkaProducer(
            bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
            value_serializer=lambda v: json.dumps(v).encode(),
            # Keep the producer light — we don't need durability for
            # best-effort audit, just throughput.
            linger_ms=10,
            request_timeout_ms=2000,
            retries=0,
            acks=0,
        )
    except Exception as e:                                 # noqa: BLE001
        log.warning("lineage_producer: KafkaProducer init failed (%s)", e)
        return None


def _get_producer():
    global _producer, _producer_dead
    if _producer_dead:
        return None
    if _producer is not None:
        return _producer
    with _producer_lock:
        if _producer is None:
            p = _build_producer()
            if p is None:
                _producer_dead = True   # don't retry every single call
            else:
                _producer = p
    return _producer


def emit_agent_event(
    *,
    session_id:  str,
    event_type:  str,
    payload:     Dict[str, Any],
    agent_id:    Optional[str] = None,
    tenant_id:   Optional[str] = None,
    user_id:     Optional[str] = None,
    correlation_id: Optional[str] = None,
    source:      str = "agent-runtime",
) -> bool:
    """Fire-and-forget publish of one agent-runtime lineage envelope.

    Returns True if the producer accepted the record for buffering;
    False if the producer is unavailable or the send raised. **Never
    raises** — callers can drop the return value entirely on the hot
    path.
    """
    p = _get_producer()
    if p is None:
        return False
    envelope = build_lineage_envelope(
        session_id     = session_id,
        event_type     = event_type,
        payload        = payload or {},
        agent_id       = agent_id,
        user_id        = user_id,
        tenant_id      = tenant_id,
        correlation_id = correlation_id,
        source         = source,
    )
    try:
        p.send(GlobalTopics.LINEAGE_EVENTS, envelope)
        return True
    except Exception as e:                                 # noqa: BLE001
        log.warning(
            "lineage_producer: send failed event_type=%s agent_id=%s err=%s",
            event_type, agent_id, e,
        )
        return False


__all__ = ["emit_agent_event"]
