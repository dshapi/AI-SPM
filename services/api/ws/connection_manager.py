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
from typing import Dict, Set, Tuple

from fastapi import WebSocket

log = logging.getLogger("api.ws.connection_manager")

QUEUE_MAX_SIZE: int = 256


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
        self._lock = asyncio.Lock()

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

        log.info(
            "ws_connected session_id=%s total=%d",
            session_id,
            self.total_connections,
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

    @property
    def active_session_ids(self) -> Set[str]:
        """Set of session_ids that currently have at least one live connection."""
        return set(self._connections.keys())

    @property
    def total_connections(self) -> int:
        """Total number of active WebSocket connections across all sessions."""
        return sum(len(v) for v in self._connections.values())
