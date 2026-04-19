"""
Tests for the pre-connect event buffer in ws/connection_manager.py.

Motivation
──────────
Before this fix, ConnectionManager.broadcast() silently dropped events when
no WebSocket had yet registered for the session_id. This produced the
"stuck running" / non-deterministic built-in-prompt behaviour: simulation
events fired into the void during the client's WS-handshake window were
never seen by the browser, so the UI waited forever for a terminal event
that had in fact been emitted.

These tests lock in the new guarantee: events broadcast before any WS
connects are buffered per session and flushed to the first connection that
arrives.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ws.connection_manager import (
    ConnectionManager,
    BUFFER_MAX_PER_SESSION,
)


def _make_fake_ws() -> MagicMock:
    """Create a mock WebSocket whose `accept` is an AsyncMock."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_broadcast_without_connection_buffers_event():
    cm = ConnectionManager()
    ev = {"event_type": "simulation.started", "session_id": "sid-1", "payload": {}}

    # No WS connected yet — broadcast must not raise and the event must be
    # stashed in the pre-connect buffer (implementation detail, but testing
    # via the observable behaviour below).
    await cm.broadcast("sid-1", ev)
    assert cm._pending.get("sid-1") is not None
    assert len(cm._pending["sid-1"]) == 1


@pytest.mark.asyncio
async def test_connect_flushes_buffered_events_in_order():
    """The first WS to connect receives all events buffered beforehand, in order."""
    cm = ConnectionManager()
    session_id = "sid-flush"

    for i in range(3):
        await cm.broadcast(session_id, {
            "event_type": f"simulation.progress",
            "session_id": session_id,
            "payload":    {"i": i},
        })

    ws = _make_fake_ws()
    queue = await cm.connect(session_id, ws)
    ws.accept.assert_awaited_once()

    # All 3 buffered events should now be in the queue, FIFO-ordered.
    drained = []
    while not queue.empty():
        drained.append(queue.get_nowait())
    assert [e["payload"]["i"] for e in drained] == [0, 1, 2]
    # Pending buffer is consumed
    assert session_id not in cm._pending


@pytest.mark.asyncio
async def test_broadcast_after_connect_goes_straight_to_queue():
    """When a WS is already connected, broadcast bypasses the buffer."""
    cm = ConnectionManager()
    ws = _make_fake_ws()
    queue = await cm.connect("sid-live", ws)

    await cm.broadcast("sid-live", {
        "event_type": "simulation.completed",
        "session_id": "sid-live",
        "payload":    {"summary": {}},
    })

    # Queue has the event; pending buffer is empty.
    assert queue.qsize() == 1
    assert "sid-live" not in cm._pending


@pytest.mark.asyncio
async def test_buffer_caps_at_max_per_session():
    """Buffer is bounded — overflow is logged but does not raise."""
    cm = ConnectionManager()
    sid = "sid-overflow"
    for i in range(BUFFER_MAX_PER_SESSION + 20):
        await cm.broadcast(sid, {"event_type": "e", "payload": {"i": i}})
    buf = cm._pending[sid]
    # Either we capped at BUFFER_MAX_PER_SESSION (deque maxlen) or the
    # overflow warning path kept it at the cap — either way bounded.
    assert len(buf) <= BUFFER_MAX_PER_SESSION


@pytest.mark.asyncio
async def test_disconnect_does_not_resurrect_buffer():
    """
    After a WS disconnects, subsequent broadcasts should buffer for the NEXT
    connection (the usual reconnect flow). This validates that the logic
    treats 'no entries' as 'buffer it', not 'drop it', even after prior
    connection activity.
    """
    cm = ConnectionManager()
    ws = _make_fake_ws()
    await cm.connect("sid-reconnect", ws)
    await cm.disconnect("sid-reconnect", ws)

    # Now broadcast — no WS → must buffer.
    await cm.broadcast("sid-reconnect", {"event_type": "simulation.error",
                                         "payload": {"error_message": "x"}})
    assert "sid-reconnect" in cm._pending
    assert len(cm._pending["sid-reconnect"]) == 1

    # A new WS connects — receives the buffered error.
    ws2 = _make_fake_ws()
    queue = await cm.connect("sid-reconnect", ws2)
    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_isolation_between_sessions():
    """Buffers are scoped by session_id; cross-session leakage is impossible."""
    cm = ConnectionManager()
    await cm.broadcast("sid-A", {"event_type": "a", "payload": {}})
    await cm.broadcast("sid-B", {"event_type": "b", "payload": {}})

    ws_a = _make_fake_ws()
    queue_a = await cm.connect("sid-A", ws_a)
    assert queue_a.qsize() == 1
    ev = queue_a.get_nowait()
    assert ev["event_type"] == "a"

    # sid-B's buffer is untouched.
    assert "sid-B" in cm._pending
    assert len(cm._pending["sid-B"]) == 1
