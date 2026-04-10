"""CRUD tests for EventRepository."""
import json
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from models.event import EventRecord, EventRepository
from models.session import SessionRecord, SessionRepository


def _make_session_rec(session_id: str = "s-001") -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        agent_id="agent-a",
        user_id="user-1",
        tenant_id=None,
        prompt_hash="h",
        tools=[],
        context={},
        status="started",
        risk_score=0.1,
        risk_tier="low",
        risk_signals=[],
        policy_decision="allow",
        policy_reason="ok",
        policy_version="v1",
        trace_id="t1",
    )


def _make_event(session_id: str = "s-001", event_type: str = "prompt.received") -> EventRecord:
    return EventRecord(
        session_id=session_id,
        event_type=event_type,
        payload=json.dumps({"step": 1}),
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_insert_and_get_by_session_id(db_session):
    # Must insert parent session first (FK constraint)
    await SessionRepository(db_session).insert(_make_session_rec("s-ev-001"))

    repo = EventRepository(db_session)
    ev = _make_event("s-ev-001", "prompt.received")
    await repo.insert(ev)

    results = await repo.get_by_session_id("s-ev-001")
    assert len(results) == 1
    assert results[0].event_type == "prompt.received"
    assert results[0].session_id == "s-ev-001"


@pytest.mark.asyncio
async def test_bulk_insert(db_session):
    await SessionRepository(db_session).insert(_make_session_rec("s-ev-002"))

    repo = EventRepository(db_session)
    events = [
        _make_event("s-ev-002", "prompt.received"),
        _make_event("s-ev-002", "risk.calculated"),
        _make_event("s-ev-002", "policy.decision"),
    ]
    await repo.bulk_insert(events)

    results = await repo.get_by_session_id("s-ev-002")
    assert len(results) == 3
    types = {r.event_type for r in results}
    assert types == {"prompt.received", "risk.calculated", "policy.decision"}


@pytest.mark.asyncio
async def test_get_by_session_id_empty_for_unknown(db_session):
    repo = EventRepository(db_session)
    results = await repo.get_by_session_id("nonexistent")
    assert results == []


@pytest.mark.asyncio
async def test_get_latest_by_type(db_session):
    await SessionRepository(db_session).insert(_make_session_rec("s-ev-003"))
    repo = EventRepository(db_session)

    now = datetime.now(timezone.utc)
    ev1 = EventRecord(
        session_id="s-ev-003",
        event_type="risk.calculated",
        payload='{"score": 0.1}',
        timestamp=now.replace(second=0),
    )
    ev2 = EventRecord(
        session_id="s-ev-003",
        event_type="risk.calculated",
        payload='{"score": 0.9}',
        timestamp=now.replace(second=5),
    )
    await repo.bulk_insert([ev1, ev2])

    latest = await repo.get_latest_by_type("s-ev-003", "risk.calculated")
    assert latest is not None
    assert json.loads(latest.payload)["score"] == 0.9


@pytest.mark.asyncio
async def test_get_latest_by_type_returns_none_for_unknown(db_session):
    await SessionRepository(db_session).insert(_make_session_rec("s-ev-004"))
    repo = EventRepository(db_session)
    result = await repo.get_latest_by_type("s-ev-004", "no.such.type")
    assert result is None


@pytest.mark.asyncio
async def test_event_id_auto_assigned(db_session):
    await SessionRepository(db_session).insert(_make_session_rec("s-ev-005"))
    repo = EventRepository(db_session)
    ev = _make_event("s-ev-005")
    assert ev.id != ""   # auto-generated UUID string
    await repo.insert(ev)
    results = await repo.get_by_session_id("s-ev-005")
    assert results[0].id == ev.id
