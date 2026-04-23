"""
Tests for the persistent event log in ws/connection_manager.py.

Motivation
──────────
The Lineage admin page needs to show events from a session even AFTER the
WebSocket has disconnected (reload, navigation, etc.). The pre-connect
buffer is not enough — it is cleared the moment a WS connects. These tests
lock in the separate persistent log that survives disconnect and is exposed
via `get_session_events()` and `list_sessions()` (backing GET /sessions/**).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ws.connection_manager import (
    ConnectionManager,
    LOG_MAX_SESSIONS,
    LOG_MAX_EVENTS_PER_SESSION,
)


def _make_fake_ws() -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_broadcast_populates_persistent_log():
    cm = ConnectionManager()
    ev = {
        "event_type":    "session.started",
        "session_id":    "sid-A",
        "correlation_id": "c-1",
        "timestamp":     "2026-04-22T00:00:00Z",
        "payload":       {"prompt": "hi"},
    }
    await cm.broadcast("sid-A", ev)

    got = await cm.get_session_events("sid-A")
    assert got == [ev]


@pytest.mark.asyncio
async def test_log_survives_connect_and_flush():
    """Connecting a WS clears the pre-connect pending buffer but NOT the log."""
    cm = ConnectionManager()
    ev = {
        "event_type":  "session.started",
        "session_id":  "sid-A",
        "timestamp":   "2026-04-22T00:00:00Z",
        "payload":     {"prompt": "hi"},
    }
    await cm.broadcast("sid-A", ev)

    # Connect a WS — which pops the pending buffer.
    ws = _make_fake_ws()
    await cm.connect("sid-A", ws)

    # Persistent log must still hold the event.
    got = await cm.get_session_events("sid-A")
    assert got == [ev]


@pytest.mark.asyncio
async def test_log_survives_disconnect():
    cm = ConnectionManager()
    ws = _make_fake_ws()
    await cm.connect("sid-B", ws)

    ev = {
        "event_type":  "policy.allowed",
        "session_id":  "sid-B",
        "timestamp":   "2026-04-22T00:00:01Z",
        "payload":     {},
    }
    await cm.broadcast("sid-B", ev)
    await cm.disconnect("sid-B", ws)

    got = await cm.get_session_events("sid-B")
    assert got == [ev]


@pytest.mark.asyncio
async def test_per_session_event_cap():
    cm = ConnectionManager()
    total = LOG_MAX_EVENTS_PER_SESSION + 25
    for i in range(total):
        await cm.broadcast("sid-C", {"event_type": "x", "seq": i, "timestamp": f"t{i}"})

    got = await cm.get_session_events("sid-C")
    assert len(got) == LOG_MAX_EVENTS_PER_SESSION
    # Oldest are trimmed — we should only see the tail.
    assert got[0]["seq"] == total - LOG_MAX_EVENTS_PER_SESSION
    assert got[-1]["seq"] == total - 1


@pytest.mark.asyncio
async def test_session_cap_lru_eviction():
    cm = ConnectionManager()
    # Fill the log with LOG_MAX_SESSIONS sessions.
    for i in range(LOG_MAX_SESSIONS):
        await cm.broadcast(f"sid-{i}", {"event_type": "ping", "timestamp": f"t{i}"})
    # One more pushes the oldest (sid-0) out.
    await cm.broadcast("sid-NEW", {"event_type": "ping", "timestamp": "tNEW"})

    assert await cm.get_session_events("sid-0") == []
    assert len(await cm.get_session_events("sid-NEW")) == 1


@pytest.mark.asyncio
async def test_list_sessions_summary_shape():
    cm = ConnectionManager()
    await cm.broadcast("sid-X", {
        "event_type":    "session.started",
        "correlation_id": "c1",
        "timestamp":     "2026-04-22T00:00:00Z",
        "payload":       {"prompt": "hello world"},
    })
    await cm.broadcast("sid-X", {
        "event_type": "session.completed",
        "timestamp":  "2026-04-22T00:00:05Z",
        "payload":    {},
    })

    summary = await cm.list_sessions()
    assert len(summary) == 1
    row = summary[0]
    assert row["session_id"]       == "sid-X"
    assert row["event_count"]      == 2
    assert row["first_event_type"] == "session.started"
    assert row["last_event_type"]  == "session.completed"
    assert row["prompt"]           == "hello world"


@pytest.mark.asyncio
async def test_list_sessions_ordered_mru_first():
    cm = ConnectionManager()
    await cm.broadcast("sid-OLD", {"event_type": "x", "timestamp": "t1"})
    await cm.broadcast("sid-NEW", {"event_type": "x", "timestamp": "t2"})
    await cm.broadcast("sid-OLD", {"event_type": "y", "timestamp": "t3"})  # touches sid-OLD
    summary = await cm.list_sessions()
    # Most recently updated first.
    assert [s["session_id"] for s in summary] == ["sid-OLD", "sid-NEW"]
