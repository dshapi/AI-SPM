"""
models/event.py
───────────────
SQLAlchemy persistence for session lifecycle events.

EventRecord    — the internal domain dataclass.
EventRepository — thin async repository; one instance per request,
                  constructed with an injected AsyncSession.

Design: events are always appended (immutable audit log). No update
or delete operations are exposed. The EventStore (in-memory) remains
the fast read-path for active sessions; EventRepository provides
durable storage for completed sessions and cross-restart queries.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SessionEventORM

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Domain model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EventRecord:
    """
    Internal domain object for one session lifecycle event.
    `payload` is a JSON string (the event's domain payload dict).
    `id` is auto-generated as a UUID string if not supplied.
    """
    session_id: str
    event_type: str
    payload: str                    # JSON string
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid4()))


# ─────────────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────────────

class EventRepository:
    """
    Thin async repository over the session_events table.
    Receives an AsyncSession per request — no shared state.
    All writes are append-only (no updates or deletes).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write ──────────────────────────────────────────────────────────

    async def insert(self, record: EventRecord) -> None:
        """Persist a single event record."""
        self._session.add(_record_to_orm(record))
        await self._session.commit()
        logger.debug("Inserted event id=%s type=%s", record.id, record.event_type)

    async def bulk_insert(self, records: List[EventRecord]) -> None:
        """
        Persist multiple event records in a single commit.
        Preferred over calling insert() in a loop.
        """
        for record in records:
            self._session.add(_record_to_orm(record))
        await self._session.commit()
        logger.debug("Bulk inserted %d events", len(records))

    # ── Read ───────────────────────────────────────────────────────────

    async def get_by_session_id(self, session_id: str) -> List[EventRecord]:
        """Return all events for a session ordered by timestamp ascending."""
        result = await self._session.execute(
            select(SessionEventORM)
            .where(SessionEventORM.session_id == session_id)
            .order_by(SessionEventORM.timestamp)
        )
        return [_orm_to_record(row) for row in result.scalars()]

    async def get_latest_by_type(
        self, session_id: str, event_type: str
    ) -> Optional[EventRecord]:
        """Return the most recent event of a given type for a session."""
        result = await self._session.execute(
            select(SessionEventORM)
            .where(
                SessionEventORM.session_id == session_id,
                SessionEventORM.event_type == event_type,
            )
            .order_by(SessionEventORM.timestamp.desc())
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_record(orm) if orm else None


# ─────────────────────────────────────────────────────────────────────────────
# Mapping helpers
# ─────────────────────────────────────────────────────────────────────────────

def _record_to_orm(record: EventRecord) -> SessionEventORM:
    return SessionEventORM(
        id=record.id,
        session_id=record.session_id,
        event_type=record.event_type,
        payload=record.payload,
        timestamp=record.timestamp,
    )


def _orm_to_record(orm: SessionEventORM) -> EventRecord:
    return EventRecord(
        id=orm.id,
        session_id=orm.session_id,
        event_type=orm.event_type,
        payload=orm.payload,
        timestamp=orm.timestamp,
    )
