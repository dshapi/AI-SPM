"""CRUD tests for SessionRepository (SQLAlchemy)."""
import json
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from models.session import SessionRecord, SessionRepository
from db.models import AgentSessionORM


def _make_record(**overrides) -> SessionRecord:
    base = dict(
        session_id="sess-001",
        agent_id="agent-a",
        user_id="user-1",
        tenant_id="tenant-x",
        prompt_hash="abc123",
        tools=["tool_a"],
        context={"env": "test"},
        status="started",
        risk_score=0.1,
        risk_tier="low",
        risk_signals=["none"],
        policy_decision="allow",
        policy_reason="ok",
        policy_version="v1",
        trace_id="trace-001",
    )
    base.update(overrides)
    return SessionRecord(**base)


@pytest.mark.asyncio
async def test_insert_and_get_by_id(db_session):
    repo = SessionRepository(db_session)
    rec = _make_record()
    await repo.insert(rec)

    fetched = await repo.get_by_id("sess-001")
    assert fetched is not None
    assert fetched.session_id == "sess-001"
    assert fetched.agent_id == "agent-a"
    assert fetched.risk_score == 0.1
    assert fetched.tools == ["tool_a"]
    assert fetched.context == {"env": "test"}
    assert fetched.policy_decision == "allow"


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown(db_session):
    repo = SessionRepository(db_session)
    result = await repo.get_by_id("does-not-exist")
    assert result is None


@pytest.mark.asyncio
async def test_update_status(db_session):
    repo = SessionRepository(db_session)
    await repo.insert(_make_record(session_id="sess-002", status="started"))

    await repo.update_status("sess-002", "completed")

    fetched = await repo.get_by_id("sess-002")
    assert fetched.status == "completed"


@pytest.mark.asyncio
async def test_list_by_agent_returns_newest_first(db_session):
    repo = SessionRepository(db_session)
    now = datetime.now(timezone.utc)

    rec1 = _make_record(
        session_id="sess-003",
        agent_id="agent-b",
        created_at=now.replace(second=0),
        updated_at=now.replace(second=0),
    )
    rec2 = _make_record(
        session_id="sess-004",
        agent_id="agent-b",
        created_at=now.replace(second=10),
        updated_at=now.replace(second=10),
    )
    await repo.insert(rec1)
    await repo.insert(rec2)

    results = await repo.list_by_agent("agent-b", limit=10)
    assert len(results) == 2
    assert results[0].session_id == "sess-004"   # newest first


@pytest.mark.asyncio
async def test_list_by_agent_limit(db_session):
    repo = SessionRepository(db_session)
    for i in range(5):
        await repo.insert(_make_record(session_id=f"sess-lim-{i}", agent_id="agent-c"))
    results = await repo.list_by_agent("agent-c", limit=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_orm_tables_created(db_session):
    """ORM models map to the correct table names."""
    from db.models import AgentSessionORM, SessionEventORM
    assert AgentSessionORM.__tablename__ == "agent_sessions"
    assert SessionEventORM.__tablename__ == "session_events"
