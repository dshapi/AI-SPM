"""
Audit emitter — structured audit events to Kafka audit topic.
Falls back to stdout JSON if Kafka is unavailable (never crashes callers).
"""
from __future__ import annotations
import json
import logging
import time
import threading
from typing import List, Optional

from platform_shared.models import AuditEvent

log = logging.getLogger(__name__)
_producer = None
_producer_lock = threading.Lock()


def _get_producer():
    global _producer
    with _producer_lock:
        if _producer is None:
            from platform_shared.kafka_utils import build_producer
            _producer = build_producer()
        return _producer


def emit_audit(
    tenant_id: str,
    component: str,
    event_type: str,
    event_id: Optional[str] = None,
    principal: Optional[str] = None,
    session_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    details: Optional[dict] = None,
    severity: str = "info",
    ttp_codes: Optional[List[str]] = None,
) -> None:
    """
    Emit a structured audit event. Always non-blocking.
    Routes to Kafka audit topic; falls back to stdout on failure.

    correlation_id — pass the originating event_id so audit events can be
    joined back to pipeline events by session consumers.
    """
    event = AuditEvent(
        ts=int(time.time() * 1000),
        tenant_id=tenant_id,
        component=component,
        event_type=event_type,
        event_id=event_id,
        principal=principal,
        session_id=session_id,
        correlation_id=correlation_id or event_id,
        details=details or {},
        severity=severity,
        ttp_codes=ttp_codes or [],
    )
    payload = event.model_dump()

    try:
        from platform_shared.topics import topics_for_tenant
        producer = _get_producer()
        topic = topics_for_tenant(tenant_id).audit
        producer.send(topic, payload)
        # Non-blocking: do not flush here to avoid latency
    except Exception as exc:
        # Audit must NEVER crash the main flow
        log.warning("Audit Kafka emit failed: %s — falling back to stdout", exc)
        print(f"[AUDIT] {json.dumps(payload, default=str)}")


def emit_security_alert(
    tenant_id: str,
    component: str,
    event_type: str,
    ttp_codes: List[str],
    event_id: Optional[str] = None,
    principal: Optional[str] = None,
    session_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Convenience wrapper for critical security events."""
    emit_audit(
        tenant_id=tenant_id,
        component=component,
        event_type=event_type,
        event_id=event_id,
        principal=principal,
        session_id=session_id,
        details=details,
        severity="critical",
        ttp_codes=ttp_codes,
    )
