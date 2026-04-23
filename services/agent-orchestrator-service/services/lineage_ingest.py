"""
services/lineage_ingest.py
──────────────────────────
Single source-of-truth for persisting one UI-lineage event into
session_events. Both the legacy HTTP handler (routers/lineage.py) and the
new Kafka consumer (consumers/lineage_consumer.py) call into here so the
persisted EventRecord is byte-identical regardless of transport.

This is the cornerstone of the HTTP-vs-Kafka end-result parity guarantee
the test suite enforces: given the same input event, the row inserted into
session_events is the same row, and therefore the rendered Lineage graph
is unchanged.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from models.event import EventRecord, EventRepository
from models.session import SessionRecord, SessionRepository

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Input dataclass — accepts both the HTTP Pydantic model and a raw Kafka dict.
# A dataclass (not a Pydantic model) so the Kafka consumer doesn't need to
# import schemas.lineage; both transports normalise into this struct.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LineageEventInput:
    session_id:     str
    event_type:     str
    payload:        Dict[str, Any]
    timestamp:      Optional[datetime] = None
    correlation_id: Optional[str]      = None
    agent_id:       Optional[str]      = None
    user_id:        Optional[str]      = None
    tenant_id:      Optional[str]      = None
    source:         Optional[str]      = None

    @classmethod
    def from_kafka_envelope(cls, env: Dict[str, Any]) -> "LineageEventInput":
        """
        Build from the wire envelope produced by
        platform_shared/lineage_events.py:build_lineage_envelope.
        """
        ts_raw = env.get("timestamp")
        ts: Optional[datetime] = None
        if ts_raw:
            try:
                # Accept "Z" suffix as well as +00:00.
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except Exception:
                logger.debug("lineage-ingest: bad timestamp on envelope=%r", ts_raw)
                ts = None
        return cls(
            session_id     = env["session_id"],
            event_type     = env["event_type"],
            payload        = env.get("payload") or {},
            timestamp      = ts,
            correlation_id = env.get("correlation_id"),
            agent_id       = env.get("agent_id"),
            user_id        = env.get("user_id"),
            tenant_id      = env.get("tenant_id"),
            source         = env.get("source"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Placeholder session factory — same defaults as the HTTP path's
# _placeholder_session.  Kept here so the consumer needn't import the router.
# ─────────────────────────────────────────────────────────────────────────────

def _placeholder_session(
    session_id:  str,
    *,
    agent_id:    str = "chat-agent",
    user_id:     str = "anonymous",
    tenant_id:   Optional[str] = None,
    source:      str = "lineage-ingest",
    trace_id:    Optional[str] = None,
) -> SessionRecord:
    now = datetime.now(timezone.utc)
    return SessionRecord(
        session_id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        prompt_hash="",
        tools=[],
        context={"source": source},
        status="active",
        risk_score=0.0,
        risk_tier="unknown",
        risk_signals=[],
        policy_decision="pending",
        policy_reason="awaiting-decision",
        policy_version="n/a",
        trace_id=trace_id or str(uuid4()),
        created_at=now,
        updated_at=now,
    )


async def ensure_parent_session(
    session_repo: SessionRepository,
    *,
    session_id:  str,
    agent_id:    Optional[str],
    user_id:     Optional[str],
    tenant_id:   Optional[str],
    source:      Optional[str],
    trace_id:    Optional[str],
) -> bool:
    """
    Idempotent upsert of the parent agent_sessions row.
    Returns True iff this call inserted the placeholder.
    """
    existing = await session_repo.get_by_id(session_id)
    if existing is not None:
        return False

    placeholder = _placeholder_session(
        session_id=session_id,
        agent_id=agent_id or "chat-agent",
        user_id=user_id or "anonymous",
        tenant_id=tenant_id,
        source=source or "lineage-ingest",
        trace_id=trace_id,
    )
    try:
        await session_repo.insert(placeholder)
        logger.info(
            "lineage-ingest: created placeholder session=%s source=%s",
            session_id, source,
        )
        return True
    except Exception as exc:
        logger.debug(
            "lineage-ingest: placeholder insert swallowed session=%s err=%s",
            session_id, exc,
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Core persistence — used by HTTP and Kafka paths.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PersistResult:
    session_id:      str
    event_id:        str
    session_created: bool
    record:          EventRecord


async def persist_lineage_event(
    session_repo: SessionRepository,
    event_repo:   EventRepository,
    body:         LineageEventInput,
    *,
    trace_id_fallback: Optional[str] = None,
) -> PersistResult:
    """
    Persist one UI-lineage event. Steps:
      1. Upsert the FK-target agent_sessions row (idempotent).
      2. Build an EventRecord with payload encoded as JSON.
      3. EventRepository.insert(record).

    The EventRecord is constructed identically regardless of caller — same
    field order, same JSON serialization (json.dumps with default settings),
    same fallback-to-now timestamp behaviour.  Parity tests assert that two
    callers feeding identical LineageEventInput produce identical records.
    """
    trace_id = trace_id_fallback or body.correlation_id

    session_created = await ensure_parent_session(
        session_repo,
        session_id = body.session_id,
        agent_id   = body.agent_id,
        user_id    = body.user_id,
        tenant_id  = body.tenant_id,
        source     = body.source,
        trace_id   = trace_id,
    )

    record = EventRecord(
        session_id = body.session_id,
        event_type = body.event_type,
        payload    = json.dumps(body.payload or {}),
        timestamp  = body.timestamp or datetime.now(timezone.utc),
    )
    await event_repo.insert(record)

    return PersistResult(
        session_id      = body.session_id,
        event_id        = record.id,
        session_created = session_created,
        record          = record,
    )
