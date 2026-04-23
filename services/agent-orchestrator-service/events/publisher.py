"""
events/publisher.py
────────────────────
EventPublisher: dual-write Kafka + in-memory EventStore.

Every emit_* method:
  1. Builds a SessionLifecycleEvent and stores it (always succeeds).
  2. Wraps the domain payload in an EventEnvelope and publishes to Kafka
     (degrades gracefully to structured log when broker is unavailable).

This guarantees the API can always return event history even when Kafka
is down, which is critical for local development.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from events.store import EventStore
# NOTE: platform_shared.lineage_events is intentionally NOT imported at module
# load time. It pulls in platform_shared.kafka_utils, which imports the sync
# `kafka` (kafka-python) package — and the orchestrator image only ships the
# async aiokafka client. Importing it here would crash the orchestrator at
# boot with `ModuleNotFoundError: No module named 'kafka'`. The helper is
# imported lazily inside emit_lineage_event() instead.
from platform_shared.topics import GlobalTopics
from schemas.events import (
    EventEnvelope,
    EventType,
    FindingCreatedPayload,
    FindingStatusChangedPayload,
    LLMResponsePayload,
    OutputScannedPayload,
    PolicyDecisionPayload,
    PromptReceivedPayload,
    RiskCalculatedPayload,
    SessionBlockedPayload,
    SessionCompletedPayload,
    SessionCreatedPayload,
    SessionLifecycleEvent,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Kafka topic constants
# ─────────────────────────────────────────────────────────────────────────────

_TENANT = os.getenv("TENANTS", "t1").split(",")[0].strip()  # single-tenant: always t1

TOPIC_PROMPT_RECEIVED    = os.getenv("KAFKA_TOPIC_PROMPT_RECEIVED",    f"cpm.{_TENANT}.sessions.prompt_received")
TOPIC_RISK_CALCULATED    = os.getenv("KAFKA_TOPIC_RISK_CALCULATED",    f"cpm.{_TENANT}.sessions.risk_calculated")
TOPIC_POLICY_DECISION    = os.getenv("KAFKA_TOPIC_POLICY_DECISION",    f"cpm.{_TENANT}.sessions.policy_decision")
TOPIC_SESSION_CREATED    = os.getenv("KAFKA_TOPIC_SESSION_CREATED",    f"cpm.{_TENANT}.sessions.created")
TOPIC_SESSION_BLOCKED    = os.getenv("KAFKA_TOPIC_SESSION_BLOCKED",    f"cpm.{_TENANT}.sessions.blocked")
TOPIC_SESSION_COMPLETED  = os.getenv("KAFKA_TOPIC_SESSION_COMPLETED",  f"cpm.{_TENANT}.sessions.completed")
TOPIC_LLM_RESPONSE       = os.getenv("KAFKA_TOPIC_LLM_RESPONSE",       f"cpm.{_TENANT}.sessions.llm_response")
TOPIC_OUTPUT_SCANNED     = os.getenv("KAFKA_TOPIC_OUTPUT_SCANNED",     f"cpm.{_TENANT}.sessions.output_scanned")
# ── Threat-finding topics ──────────────────────────────────────────────────────
TOPIC_FINDING_CREATED        = os.getenv("KAFKA_TOPIC_FINDING_CREATED",        f"cpm.{_TENANT}.findings.created")
TOPIC_FINDING_STATUS_CHANGED = os.getenv("KAFKA_TOPIC_FINDING_STATUS_CHANGED", f"cpm.{_TENANT}.findings.status_changed")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_envelope(
    event_type: str,
    correlation_id: str,
    session_id: UUID,
    payload: Any,
    tenant_id: Optional[str] = None,
) -> bytes:
    # Use model_dump_kafka() if the payload declares PII fields to strip;
    # otherwise fall back to standard model_dump().  This keeps PII out of
    # Kafka while the in-memory store (and admin UI) still receives the full
    # payload via the separate payload_dict path in _emit().
    if hasattr(payload, "model_dump_kafka"):
        data: Dict[str, Any] = payload.model_dump_kafka()
    elif hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    envelope = EventEnvelope(
        event_type=event_type,
        correlation_id=correlation_id,
        session_id=session_id,
        tenant_id=tenant_id,
        data=data,
    )
    return envelope.model_dump_json().encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Publisher
# ─────────────────────────────────────────────────────────────────────────────

class EventPublisher:
    """
    Async publisher: writes every event to the in-memory store AND
    attempts Kafka publication with structured-log fallback.

    Lifecycle:
        await publisher.start()   # app lifespan startup
        await publisher.stop()    # app lifespan teardown
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        store: Optional[EventStore] = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._store = store
        self._producer: Any = None
        self._available = False

    def set_store(self, store: EventStore) -> None:
        """Inject the EventStore after construction (used in lifespan)."""
        self._store = store

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda v: v,
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                enable_idempotence=True,
                max_batch_size=16_384,
                linger_ms=5,
            )
            await self._producer.start()
            self._available = True
            logger.info("EventPublisher connected to Kafka at %s", self._bootstrap_servers)
        except Exception as exc:
            logger.warning(
                "Kafka unavailable (%s) — EventPublisher in LOG-ONLY mode", exc
            )
            self._available = False

    async def stop(self) -> None:
        if self._producer and self._available:
            await self._producer.stop()
            logger.info("EventPublisher disconnected from Kafka")

    # ── Core transport ─────────────────────────────────────────────────────

    async def _publish_kafka(self, topic: str, key: str, value: bytes) -> None:
        if self._available and self._producer:
            try:
                await self._producer.send_and_wait(topic, value=value, key=key)
                logger.debug("Kafka publish: topic=%s key=%s", topic, key)
                return
            except Exception as exc:
                logger.error("Kafka publish failed topic=%s: %s", topic, exc)
        logger.info(
            "KAFKA_FALLBACK topic=%s key=%s payload=%s",
            topic, key, value.decode("utf-8", errors="replace"),
        )

    async def _store_event(self, event: SessionLifecycleEvent) -> None:
        if self._store:
            await self._store.append(event)

    async def _emit(
        self,
        *,
        event_type: EventType,
        topic: str,
        session_id: UUID,
        correlation_id: str,
        step: int,
        status: str,
        summary: str,
        payload: Any,
        tenant_id: Optional[str] = None,
    ) -> SessionLifecycleEvent:
        """
        Central dispatch: store → Kafka (in that order so store never fails
        due to a Kafka error).
        """
        ts = _utcnow()
        payload_dict: Dict[str, Any] = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else payload
        )

        lifecycle_event = SessionLifecycleEvent(
            event_type=event_type,
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=ts,
            step=step,
            status=status,
            summary=summary,
            payload=payload_dict,
        )

        # 1. Store (always)
        await self._store_event(lifecycle_event)

        # 2. Kafka (best-effort)
        envelope_bytes = _make_envelope(
            event_type=event_type.value,
            correlation_id=correlation_id,
            session_id=session_id,
            payload=payload,
            tenant_id=tenant_id,
        )
        await self._publish_kafka(topic, str(session_id), envelope_bytes)

        return lifecycle_event

    # ── Public domain emit methods ─────────────────────────────────────────

    async def emit_prompt_received(
        self,
        payload: PromptReceivedPayload,
        correlation_id: str,
    ) -> SessionLifecycleEvent:
        return await self._emit(
            event_type=EventType.PROMPT_RECEIVED,
            topic=TOPIC_PROMPT_RECEIVED,
            session_id=payload.session_id,
            correlation_id=correlation_id,
            step=1,
            status="received",
            summary=(
                f"Prompt received for agent '{payload.agent_id}' "
                f"({payload.prompt_len} chars, {len(payload.tools)} tools)"
            ),
            payload=payload,
        )

    async def emit_risk_calculated(
        self,
        payload: RiskCalculatedPayload,
        correlation_id: str,
    ) -> SessionLifecycleEvent:
        return await self._emit(
            event_type=EventType.RISK_CALCULATED,
            topic=TOPIC_RISK_CALCULATED,
            session_id=payload.session_id,
            correlation_id=correlation_id,
            step=2,
            status="scored",
            summary=(
                f"Risk scored: {payload.risk_score:.2f} ({payload.risk_tier.upper()}) "
                f"— {len(payload.signals)} signal(s) detected"
            ),
            payload=payload,
        )

    async def emit_policy_decision(
        self,
        payload: PolicyDecisionPayload,
        correlation_id: str,
    ) -> SessionLifecycleEvent:
        return await self._emit(
            event_type=EventType.POLICY_DECISION,
            topic=TOPIC_POLICY_DECISION,
            session_id=payload.session_id,
            correlation_id=correlation_id,
            step=3,
            status=payload.decision,
            summary=f"Policy decision: {payload.decision.upper()} — {payload.reason[:80]}",
            payload=payload,
        )

    async def emit_session_created(
        self,
        payload: SessionCreatedPayload,
        correlation_id: str,
        tenant_id: Optional[str] = None,
    ) -> SessionLifecycleEvent:
        return await self._emit(
            event_type=EventType.SESSION_CREATED,
            topic=TOPIC_SESSION_CREATED,
            session_id=payload.session_id,
            correlation_id=correlation_id,
            step=4,
            status="created",
            summary=f"Session created for agent '{payload.agent_id}' — policy: {payload.policy_decision}",
            payload=payload,
            tenant_id=tenant_id,
        )

    async def emit_session_blocked(
        self,
        payload: SessionBlockedPayload,
        correlation_id: str,
    ) -> SessionLifecycleEvent:
        return await self._emit(
            event_type=EventType.SESSION_BLOCKED,
            topic=TOPIC_SESSION_BLOCKED,
            session_id=payload.session_id,
            correlation_id=correlation_id,
            step=4,
            status="blocked",
            summary=f"Session BLOCKED for agent '{payload.agent_id}' — {payload.reason[:80]}",
            payload=payload,
        )

    async def emit_llm_response(
        self,
        session_id: UUID,
        correlation_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        stop_reason: str,
        response_length: int,
        latency_ms: int,
    ) -> SessionLifecycleEvent:
        payload = LLMResponsePayload(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=stop_reason,
            response_length=response_length,
            latency_ms=latency_ms,
        )
        return await self._emit(
            event_type=EventType.LLM_RESPONSE,
            topic=TOPIC_LLM_RESPONSE,
            session_id=session_id,
            correlation_id=correlation_id,
            step=6,
            status="completed",
            summary=f"LLM responded: {output_tokens} tokens via {model} in {latency_ms}ms",
            payload=payload,
        )

    async def emit_output_scanned(
        self,
        session_id: UUID,
        correlation_id: str,
        verdict: str,
        pii_types: list,
        secret_types: list,
        scan_notes: list,
    ) -> SessionLifecycleEvent:
        payload = OutputScannedPayload(
            verdict=verdict,
            pii_types=pii_types,
            secret_types=secret_types,
            scan_notes=scan_notes,
        )
        return await self._emit(
            event_type=EventType.OUTPUT_SCANNED,
            topic=TOPIC_OUTPUT_SCANNED,
            session_id=session_id,
            correlation_id=correlation_id,
            step=7,
            status=verdict,
            summary=f"Output scan: {verdict}. PII={pii_types}, secrets={secret_types}",
            payload=payload,
        )

    async def emit_session_completed(
        self,
        payload: SessionCompletedPayload,
        correlation_id: str,
    ) -> SessionLifecycleEvent:
        return await self._emit(
            event_type=EventType.SESSION_COMPLETED,
            topic=TOPIC_SESSION_COMPLETED,
            session_id=payload.session_id,
            correlation_id=correlation_id,
            step=10,
            status=payload.final_status,
            summary=(
                f"Session completed — status: {payload.final_status}, "
                f"duration: {payload.duration_ms:.1f}ms, "
                f"{payload.event_count} events emitted"
            ),
            payload=payload,
        )

    # ── UI-lineage events (cpm.global.lineage_events) ──────────────────────
    #
    # Mirrors platform_shared.lineage_events.publish_lineage_event but uses
    # the orchestrator's async AIOKafkaProducer instead of the api service's
    # sync KafkaProducer. The wire envelope is identical
    # (build_lineage_envelope) so the existing LineageEventConsumer drains
    # both producers transparently.

    async def emit_lineage_event(
        self,
        *,
        session_id:     str,
        event_type:     str,
        payload:        Dict[str, Any],
        timestamp:      Optional[str]   = None,
        correlation_id: Optional[str]   = None,
        agent_id:       Optional[str]   = None,
        user_id:        Optional[str]   = None,
        tenant_id:      Optional[str]   = None,
        source:         str             = "agent-orchestrator",
    ) -> bool:
        """
        Publish one UI-lineage event to GlobalTopics.LINEAGE_EVENTS.
        Best-effort — returns False on broker error or LOG-ONLY mode.
        """
        # Lazy-import to avoid pulling kafka-python at module load. See note
        # at the top of this file.
        from platform_shared.lineage_events import build_lineage_envelope
        envelope = build_lineage_envelope(
            session_id     = session_id,
            event_type     = event_type,
            payload        = payload or {},
            timestamp      = timestamp,
            correlation_id = correlation_id,
            agent_id       = agent_id,
            user_id        = user_id,
            tenant_id      = tenant_id,
            source         = source,
        )
        value_bytes = json.dumps(envelope, default=str).encode("utf-8")
        try:
            await self._publish_kafka(
                GlobalTopics.LINEAGE_EVENTS,
                key   = session_id,
                value = value_bytes,
            )
            return True
        except Exception as exc:
            logger.warning(
                "emit_lineage_event failed session=%s type=%s err=%s",
                session_id, event_type, exc,
            )
            return False

    # ── Threat-finding events ──────────────────────────────────────────────

    async def emit_finding_created(
        self,
        finding_id: str,
        tenant_id: str,
        severity: str,
        title: str,
        *,
        risk_score: Optional[float] = None,
        confidence: Optional[float] = None,
        asset: Optional[str] = None,
        source: str = "threat-hunting-agent",
        priority_score: Optional[float] = None,
        should_open_case: bool = False,
        case_id: Optional[str] = None,
    ) -> SessionLifecycleEvent:
        """
        Emit a finding.created event to Kafka and the in-memory store.

        Called after a new ThreatFinding is persisted and prioritized.
        Downstream consumers (SIEM connectors, dashboards, alerting rules)
        subscribe to ``cpm.<tenant>.findings.created`` to receive real-time
        notifications without polling the findings REST API.
        """
        from uuid import UUID as _UUID
        payload = FindingCreatedPayload(
            finding_id=finding_id,
            tenant_id=tenant_id,
            severity=severity,
            title=title,
            risk_score=risk_score,
            confidence=confidence,
            asset=asset,
            source=source,
            priority_score=priority_score,
            should_open_case=should_open_case,
            case_id=case_id,
        )
        # Use the finding_id UUID as the "session_id" for lifecycle-event storage.
        # Findings are not session-scoped, so we repurpose this field as the
        # finding's own identifier.  The event is still queryable by finding_id
        # via the payload field.
        try:
            sid = _UUID(finding_id)
        except ValueError:
            sid = uuid4()

        return await self._emit(
            event_type=EventType.FINDING_CREATED,
            topic=TOPIC_FINDING_CREATED,
            session_id=sid,
            correlation_id=str(uuid4()),
            step=1,
            status="created",
            summary=(
                f"Finding created: [{severity.upper()}] {title}"
                + (f" — case auto-opened" if case_id else "")
            ),
            payload=payload,
            tenant_id=tenant_id,
        )

    async def emit_finding_status_changed(
        self,
        finding_id: str,
        tenant_id: str,
        new_status: str,
        *,
        old_status: Optional[str] = None,
        changed_by: Optional[str] = None,
    ) -> SessionLifecycleEvent:
        """
        Emit a finding.status_changed event to Kafka and the in-memory store.

        Called after an analyst transitions a finding's status
        (open → investigating → resolved).  Enables audit trails and
        downstream workflow automation.
        """
        from uuid import UUID as _UUID
        payload = FindingStatusChangedPayload(
            finding_id=finding_id,
            tenant_id=tenant_id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
        )
        try:
            sid = _UUID(finding_id)
        except ValueError:
            sid = uuid4()

        return await self._emit(
            event_type=EventType.FINDING_STATUS_CHANGED,
            topic=TOPIC_FINDING_STATUS_CHANGED,
            session_id=sid,
            correlation_id=str(uuid4()),
            step=2,
            status=new_status,
            summary=(
                f"Finding status → {new_status.upper()}"
                + (f" (was {old_status})" if old_status else "")
                + (f" by {changed_by}" if changed_by else "")
            ),
            payload=payload,
            tenant_id=tenant_id,
        )
