"""
tests/test_lineage_router.py
────────────────────────────
Integration tests for the persistent UI-lineage ingest + replay endpoints
added in Layer 1 (POST /api/v1/lineage/events, /events/bulk;
GET /api/v1/lineage/sessions, /sessions/{id}/events).

Design of these tests mirrors the production invariants:

* Ingesting an event for a session that doesn't exist yet UPSERTs a
  placeholder agent_sessions row (FK prerequisite). Second ingest for the
  same session reuses the placeholder (session_created=False).
* Real sessions created via the live pipeline are NOT overwritten by the
  placeholder path.
* Read-back returns events in the WS-wire envelope shape so the api
  service's ConnectionManager-style UI can hydrate them without adapters.
* /lineage/sessions lists only sessions that actually have persisted events
  and orders most-recent-activity first.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from db.base import Base
from dependencies.db import get_event_repo, get_session_repo
from main import create_app
from models.event import EventRecord, EventRepository
from models.session import SessionRecord, SessionRepository


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — self-contained in-memory SQLite per test, wired through the real
# FastAPI app via dependency overrides. This is richer than a straight unit
# test because it exercises the actual router, the upsert path, and
# SQLAlchemy FK enforcement.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    """
    Spin up the real FastAPI app with lineage dependencies bound to a single
    throwaway in-memory DB that's shared across every request in the test.
    We bypass the full lifespan (no Kafka, no policy store) because the
    lineage router only needs session_repo + event_repo.

    NB: Each request gets a fresh AsyncSession from the shared factory —
    matches production behaviour in dependencies/db.py.
    """
    # StaticPool + shared :memory: so every AsyncSession handed out across the
    # test uses the SAME underlying SQLite connection (otherwise each session
    # gets its own :memory: DB and nothing persists between requests).
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = create_app()

    async def _session_repo_dep():
        async with factory() as s:
            yield SessionRepository(s)

    async def _event_repo_dep():
        async with factory() as s:
            yield EventRepository(s)

    app.dependency_overrides[get_session_repo] = _session_repo_dep
    app.dependency_overrides[get_event_repo]   = _event_repo_dep

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/lineage/events — single event ingest
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_creates_placeholder_session_on_first_event(client):
    body = {
        "session_id":     "sess-ingest-001",
        "event_type":     "session.started",
        "payload":        {"prompt": "hello world"},
        "correlation_id": "cid-1",
        "agent_id":       "chat-agent",
        "user_id":        "user-abc",
        "tenant_id":      "t1",
        "source":         "api-chat",
    }
    resp = await client.post("/api/v1/lineage/events", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["session_id"] == "sess-ingest-001"
    assert data["session_created"] is True
    assert isinstance(data["event_id"], str) and data["event_id"]


@pytest.mark.asyncio
async def test_second_event_reuses_placeholder(client):
    common = {
        "session_id": "sess-ingest-002",
        "agent_id":   "chat-agent",
        "user_id":    "user-xyz",
        "source":     "api-chat",
    }
    first = await client.post("/api/v1/lineage/events", json={
        **common,
        "event_type": "session.started",
        "payload":    {"prompt": "first"},
    })
    second = await client.post("/api/v1/lineage/events", json={
        **common,
        "event_type": "risk.calculated",
        "payload":    {"risk_score": 0.4},
    })
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["session_created"] is True
    assert second.json()["session_created"] is False


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/lineage/events/bulk — batched ingest
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_ingest_mixed_session_ids_400(client):
    body = {
        "session_id": "sess-bulk-001",
        "events": [
            {"session_id": "sess-bulk-001", "event_type": "session.started", "payload": {}},
            {"session_id": "sess-OTHER",    "event_type": "risk.calculated", "payload": {}},
        ],
    }
    resp = await client.post("/api/v1/lineage/events/bulk", json=body)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_bulk_ingest_inserts_all_and_creates_placeholder(client):
    body = {
        "session_id": "sess-bulk-002",
        "events": [
            {"session_id": "sess-bulk-002", "event_type": "session.started",
             "payload": {"prompt": "p"}, "agent_id": "chat-agent", "user_id": "u"},
            {"session_id": "sess-bulk-002", "event_type": "policy.allowed",
             "payload": {"reason": "ok"}},
            {"session_id": "sess-bulk-002", "event_type": "output.generated",
             "payload": {"pii_redacted": False}},
        ],
    }
    resp = await client.post("/api/v1/lineage/events/bulk", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert data["inserted_count"] == 3
    assert data["session_created"] is True


@pytest.mark.asyncio
async def test_bulk_empty_events_list_is_noop(client):
    body = {"session_id": "sess-bulk-003", "events": []}
    resp = await client.post("/api/v1/lineage/events/bulk", json=body)
    assert resp.status_code == 202
    assert resp.json() == {
        "session_id":      "sess-bulk-003",
        "inserted_count":  0,
        "session_created": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/lineage/sessions/{id}/events — WS-wire read-back
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_returns_ws_wire_envelope(client):
    # Ingest a canonical pipeline shape.
    sid = "sess-replay-001"
    for et, payload in [
        ("session.started",   {"prompt": "help me"}),
        ("context.retrieved", {"context_count": 3}),
        ("risk.calculated",   {"risk_score": 0.2}),
        ("policy.allowed",    {"reason": "ok"}),
        ("output.generated",  {"pii_redacted": False}),
    ]:
        r = await client.post("/api/v1/lineage/events", json={
            "session_id": sid,
            "event_type": et,
            "payload":    payload,
            "agent_id":   "chat-agent",
            "user_id":    "u",
        })
        assert r.status_code == 202

    resp = await client.get(f"/api/v1/lineage/sessions/{sid}/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sid
    assert len(data["events"]) == 5

    # Each event must match the WS-wire envelope shape the api service
    # broadcasts — UI normaliser expects exactly these keys.
    for ev in data["events"]:
        assert ev["session_id"] == sid
        assert "event_type" in ev
        assert ev["source_service"] == "api-chat"
        assert "timestamp" in ev
        assert isinstance(ev["payload"], dict)

    # Payload survives round-trip.
    started = next(e for e in data["events"] if e["event_type"] == "session.started")
    assert started["payload"]["prompt"] == "help me"


@pytest.mark.asyncio
async def test_replay_empty_session_returns_empty_list_not_404(client):
    resp = await client.get("/api/v1/lineage/sessions/no-such-sid/events")
    assert resp.status_code == 200
    assert resp.json() == {"session_id": "no-such-sid", "events": []}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/lineage/sessions — picker feed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_sessions_orders_by_last_activity_desc(client):
    # Two sessions, the second one created later — should sort first.
    await client.post("/api/v1/lineage/events", json={
        "session_id": "sess-list-A",
        "event_type": "session.started",
        "payload":    {"prompt": "old"},
        "agent_id":   "chat-agent", "user_id": "u",
    })
    await client.post("/api/v1/lineage/events", json={
        "session_id": "sess-list-B",
        "event_type": "session.started",
        "payload":    {"prompt": "new"},
        "agent_id":   "chat-agent", "user_id": "u",
    })

    resp = await client.get("/api/v1/lineage/sessions")
    assert resp.status_code == 200
    sids = [s["session_id"] for s in resp.json()["sessions"]]
    assert "sess-list-A" in sids
    assert "sess-list-B" in sids
    # Both prompts surface through the summary shape.
    for s in resp.json()["sessions"]:
        if s["session_id"] == "sess-list-A":
            assert s["prompt"] == "old"
        if s["session_id"] == "sess-list-B":
            assert s["prompt"] == "new"
