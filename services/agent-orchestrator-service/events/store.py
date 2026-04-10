"""
events/store.py
────────────────
In-memory EventStore for session lifecycle events.

Design
──────
• dict[session_id → deque[SessionLifecycleEvent]] gives O(1) append
  and O(1) lookup per session.
• asyncio.Lock per session prevents race conditions on concurrent
  requests touching the same session (e.g. parallel tool calls).
• A global lock guards the top-level dict so new session slots can
  be created atomically.
• Max events per session is bounded (default 500) so a single runaway
  session cannot exhaust memory.
• The store is intentionally NOT durable — on restart events are gone.
  Wire up an async consumer to PostgreSQL / OpenSearch for persistence.

Production swap-out
───────────────────
Replace the append / get_events methods with writes to:
  • PostgreSQL table: session_lifecycle_events
  • OpenSearch / Elasticsearch index: session-events-*
  • Redis Stream: XADD cpm.sessions.{session_id}.events
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from schemas.events import SessionLifecycleEvent

logger = logging.getLogger(__name__)

_DEFAULT_MAX_EVENTS = 500


class EventStore:
    """
    Thread-safe, in-memory store for session lifecycle events.

    One instance is created at app startup and injected via app.state.
    """

    def __init__(self, max_events_per_session: int = _DEFAULT_MAX_EVENTS) -> None:
        self._max = max_events_per_session
        # session_id (str) → deque of events
        self._store: Dict[str, deque[SessionLifecycleEvent]] = {}
        # Per-session locks prevent concurrent appends to the same deque
        self._locks: Dict[str, asyncio.Lock] = {}
        # Global lock guards creation of new session slots
        self._global_lock = asyncio.Lock()

    # ─────────────────────────────────────────────────────────────────────
    # Write
    # ─────────────────────────────────────────────────────────────────────

    async def append(self, event: SessionLifecycleEvent) -> None:
        """
        Append one lifecycle event to the session's event list.
        Creates the session slot on first write.
        """
        sid = str(event.session_id)

        # Ensure session slot exists
        if sid not in self._store:
            async with self._global_lock:
                if sid not in self._store:            # double-checked locking
                    self._store[sid] = deque(maxlen=self._max)
                    self._locks[sid] = asyncio.Lock()
                    logger.debug("EventStore: new session slot created sid=%s", sid)

        async with self._locks[sid]:
            self._store[sid].append(event)

        logger.debug(
            "EventStore.append: sid=%s type=%s step=%d total=%d",
            sid, event.event_type.value, event.step,
            len(self._store[sid]),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Read
    # ─────────────────────────────────────────────────────────────────────

    async def get_events(self, session_id: str) -> List[SessionLifecycleEvent]:
        """
        Return all events for a session, ordered by step (ascending).
        Returns empty list if session_id is unknown.
        """
        sid = str(session_id)
        if sid not in self._store:
            return []
        lock = self._locks.get(sid)
        if lock:
            async with lock:
                return list(self._store[sid])
        return list(self._store[sid])

    async def get_latest_event(
        self, session_id: str, event_type: Optional[str] = None
    ) -> Optional[SessionLifecycleEvent]:
        """
        Return the most recent event for a session, optionally filtered
        by event_type (e.g. 'session.completed').
        """
        events = await self.get_events(session_id)
        if not events:
            return None
        if event_type:
            filtered = [e for e in events if e.event_type.value == event_type]
            return filtered[-1] if filtered else None
        return events[-1]

    # ─────────────────────────────────────────────────────────────────────
    # Admin / observability
    # ─────────────────────────────────────────────────────────────────────

    def session_count(self) -> int:
        return len(self._store)

    def event_count(self, session_id: str) -> int:
        return len(self._store.get(str(session_id), []))

    def total_event_count(self) -> int:
        return sum(len(v) for v in self._store.values())

    async def purge_session(self, session_id: str) -> None:
        """Remove all events for a session (e.g. after archiving to DB)."""
        sid = str(session_id)
        async with self._global_lock:
            self._store.pop(sid, None)
            self._locks.pop(sid, None)
        logger.info("EventStore: purged session sid=%s", sid)
