"""
ws/connection_manager.py
─────────────────────────
Registry of active WebSocket connections, keyed by session_id.

Design
──────
Each WebSocket connection receives its own bounded asyncio.Queue.  The
connection manager owns the mapping of session_id → {(ws_id, ws, queue)}.

The registry is protected by asyncio.Lock because all callers run in the
same event-loop thread (FastAPI / uvicorn).  The Kafka consumer thread
never touches this object directly — it interacts only with queues via
SessionEventConsumer's internal subscriber dict.

Backpressure:
  Queues are created here with QUEUE_MAX_SIZE.  The Kafka consumer checks
  queue.qsize() before putting; full queues result in a logged drop rather
  than blocking the consumer thread.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Deque, Dict, Set, Tuple

from fastapi import WebSocket

log = logging.getLogger("api.ws.connection_manager")

QUEUE_MAX_SIZE: int = 256

# ── Pre-connect event buffer ─────────────────────────────────────────────────
# If `broadcast()` is called before any WebSocket has registered for a
# session_id, we buffer the event in a bounded FIFO so it can be flushed to
# the first connection that arrives. This eliminates the "stuck running" race
# where simulation events fire while the client is still completing the WS
# handshake (which on cold Docker stacks can take a few seconds). Without the
# buffer those events would be silently dropped forever.
#
# The buffer is bounded per session (BUFFER_MAX_PER_SESSION) to prevent memory
# growth from orphan sessions, and entries older than BUFFER_TTL_S are evicted
# lazily on each broadcast.
BUFFER_MAX_PER_SESSION: int = 64
BUFFER_TTL_S: float = 120.0


# Internal entry: (ws_object_id, WebSocket, asyncio.Queue)
_Entry = Tuple[int, WebSocket, "asyncio.Queue[dict]"]


class ConnectionManager:
    """
    Tracks all active WebSocket connections by session_id.

    Public API
    ──────────
    connect(session_id, ws)    → accepts WS, returns the connection's Queue
    disconnect(session_id, ws) → removes the connection from the registry
    active_session_ids         → set of session_ids with live connections
    total_connections          → total active WS connection count
    """

    def __init__(self) -> None:
        # session_id → set of (id(ws), ws, queue) entries
        self._connections: Dict[str, Set[_Entry]] = {}
        # session_id → deque[(monotonic_ts, event_dict)] for pre-connect buffering
        self._pending: Dict[str, Deque[Tuple[float, dict]]] = {}
        self._lock = asyncio.Lock()

    # ── Internal pending-buffer helpers ──────────────────────────────────────

    def _evict_expired_locked(self, now: float) -> None:
        """Drop TTL-expired entries from every pending queue. Must hold lock."""
        stale = []
        for sid, buf in self._pending.items():
            while buf and (now - buf[0][0]) > BUFFER_TTL_S:
                buf.popleft()
            if not buf:
                stale.append(sid)
        for sid in stale:
            del self._pending[sid]

    async def connect(
        self,
        session_id: str,
        ws: WebSocket,
    ) -> "asyncio.Queue[dict]":
        """
        Accept a WebSocket upgrade and register the connection.

        Returns the asyncio.Queue that the endpoint should drain into
        WebSocket send calls.  The queue is bounded to QUEUE_MAX_SIZE.
        """
        await ws.accept()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
        entry: _Entry = (id(ws), ws, queue)

        async with self._lock:
            if session_id not in self._connections:
                self._connections[session_id] = set()
            self._connections[session_id].add(entry)
            # Drain any events buffered while no WS was connected so the
            # browser sees the full event sequence.
            pending = self._pending.pop(session_id, None)

        flushed = 0
        if pending:
            for _, ev in pending:
                if queue.qsize() < QUEUE_MAX_SIZE:
                    await queue.put(ev)
                    flushed += 1
                else:
                    log.warning(
                        "ws_flush_queue_full session_id=%s event_type=%s — dropping",
                        session_id,
                        ev.get("event_type", "?"),
                    )

        log.info(
            "ws_connected session_id=%s total=%d flushed=%d",
            session_id,
            self.total_connections,
            flushed,
        )
        return queue

    async def disconnect(
        self,
        session_id: str,
        ws: WebSocket,
    ) -> None:
        """Remove *ws* from the registry for *session_id*."""
        async with self._lock:
            if session_id in self._connections:
                self._connections[session_id] = {
                    e for e in self._connections[session_id] if e[1] is not ws
                }
                if not self._connections[session_id]:
                    del self._connections[session_id]

        log.info(
            "ws_disconnected session_id=%s total=%d",
            session_id,
            self.total_connections,
        )

    # ── Observability ─────────────────────────────────────────────────────────

    async def broadcast(self, session_id: str, event: dict) -> None:
        """
        Put *event* directly into all queues registered for *session_id*.

        Used by in-process background tasks (e.g. simulation runner) that
        want to stream events to the browser without going through Kafka.
        Safe to call from any coroutine running in the same event loop.

        When no WebSocket is registered for *session_id* yet, the event is
        stashed in a per-session pre-connect buffer (bounded, TTL-evicted)
        so that the very first WS connection will receive the full sequence.
        Without this, events emitted during the client's WS-handshake window
        were silently lost — the primary cause of "stuck running" and
        non-deterministic built-in prompt behaviour.
        """
        now = time.monotonic()
        async with self._lock:
            entries = set(self._connections.get(session_id, set()))
            if not entries:
                # No live connection — buffer for later flush.
                self._evict_expired_locked(now)
                buf = self._pending.get(session_id)
                if buf is None:
                    buf = deque(maxlen=BUFFER_MAX_PER_SESSION)
                    self._pending[session_id] = buf
                if len(buf) >= BUFFER_MAX_PER_SESSION:
                    # deque(maxlen=…) would drop oldest; we prefer a warning
                    # that matches the live-queue overflow behaviour.
                    log.warning(
                        "ws_buffer_full session_id=%s event_type=%s — dropping oldest",
                        session_id,
                        event.get("event_type", "?"),
                    )
                buf.append((now, event))
                return
        for _, _, queue in entries:
            if queue.qsize() < QUEUE_MAX_SIZE:
                await queue.put(event)
            else:
                log.warning(
                    "ws_broadcast_queue_full session_id=%s event_type=%s — dropping",
                    session_id,
                    event.get("event_type", "?"),
                )

    # ── Observability ─────────────────────────────────────────────────────────

    @property
    def active_session_ids(self) -> Set[str]:
        """Set of session_ids that currently have at least one live connection."""
        return set(self._connections.keys())

    @property
    def total_connections(self) -> int:
        """Total number of active WebSocket connections across all sessions."""
        return sum(len(v) for v in self._connections.values())
