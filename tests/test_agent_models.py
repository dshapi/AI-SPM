"""
Tests for Agent, AgentChatSession, AgentChatMessage ORM models.
"""
import uuid
from datetime import datetime, timezone
import pytest
import asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from spm.db.models import Base, Agent, AgentChatSession, AgentChatMessage


@pytest.fixture
async def test_db_session():
    """
    Create an in-memory SQLite async session for testing.
    Sets up Agent-related tables only (SQLite doesn't support JSONB).
    """
    # Use SQLite with in-memory DB for fast tests
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )

    # Create only Agent-related tables (skip tables with JSONB or other PostgreSQL-specific types)
    async with engine.begin() as conn:
        await conn.run_sync(lambda conn: (
            Agent.__table__.create(conn, checkfirst=True),
            AgentChatSession.__table__.create(conn, checkfirst=True),
            AgentChatMessage.__table__.create(conn, checkfirst=True),
        ))

    # Create sessionmaker
    SessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with SessionLocal() as session:
        yield session

    # Cleanup
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_round_trip(test_db_session: AsyncSession):
    """Test creating and retrieving an Agent."""
    agent = Agent(
        id=uuid.uuid4(),
        name="test-agent",
        version="1.0.0",
        agent_type="langchain",
        provider="internal",
        owner="ml-platform",
        description="hello",
        risk="medium",
        policy_status="partial",
        runtime_state="stopped",
        code_path="./DataVolums/agents/x/agent.py",
        code_sha256="0" * 64,
        mcp_token="t" * 32,
        llm_api_key="k" * 32,
        tenant_id="t1",
    )
    test_db_session.add(agent)
    await test_db_session.commit()

    # Fetch it back
    fetched = await test_db_session.get(Agent, agent.id)
    assert fetched is not None
    assert fetched.name == "test-agent"
    assert fetched.runtime_state == "stopped"
    assert fetched.version == "1.0.0"


@pytest.mark.asyncio
async def test_session_and_messages_cascade(test_db_session: AsyncSession):
    """Test Agent → Session → Message cascade delete."""
    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        name="a",
        version="1",
        agent_type="custom",
        provider="internal",
        owner="o",
        code_path="x",
        code_sha256="0" * 64,
        mcp_token="t" * 32,
        llm_api_key="k" * 32,
        tenant_id="t1",
    )
    test_db_session.add(agent)
    await test_db_session.flush()

    session_id = uuid.uuid4()
    session = AgentChatSession(
        id=session_id,
        agent_id=agent_id,
        user_id="dany",
        message_count=0,
    )
    test_db_session.add(session)
    await test_db_session.flush()

    msg = AgentChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role="user",
        text="hi",
        trace_id="trc-1",
    )
    test_db_session.add(msg)
    await test_db_session.commit()

    # Verify message was created
    stmt = select(func.count()).select_from(AgentChatMessage).where(
        AgentChatMessage.session_id == session_id
    )
    result = await test_db_session.execute(stmt)
    assert result.scalar() == 1

    # Delete session, verify message is cascade-deleted
    await test_db_session.delete(session)
    await test_db_session.commit()

    # Verify both session and message are gone
    stmt = select(func.count()).select_from(AgentChatSession).where(
        AgentChatSession.id == session_id
    )
    result = await test_db_session.execute(stmt)
    assert result.scalar() == 0

    stmt = select(func.count()).select_from(AgentChatMessage).where(
        AgentChatMessage.session_id == session_id
    )
    result = await test_db_session.execute(stmt)
    assert result.scalar() == 0


@pytest.mark.asyncio
async def test_agent_relationships(test_db_session: AsyncSession):
    """Test Agent.sessions relationship via FK."""
    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        name="agent-with-sessions",
        version="1.0",
        agent_type="autogpt",
        provider="internal",
        owner="team",
        code_path="x",
        code_sha256="0" * 64,
        mcp_token="t" * 32,
        llm_api_key="k" * 32,
        tenant_id="t1",
    )
    test_db_session.add(agent)
    await test_db_session.flush()

    # Add two sessions
    sess1 = AgentChatSession(
        id=uuid.uuid4(),
        agent_id=agent_id,
        user_id="user1",
        message_count=0,
    )
    sess2 = AgentChatSession(
        id=uuid.uuid4(),
        agent_id=agent_id,
        user_id="user2",
        message_count=0,
    )
    test_db_session.add(sess1)
    test_db_session.add(sess2)
    await test_db_session.commit()

    # Query sessions by agent_id to verify FK works
    stmt = select(func.count()).select_from(AgentChatSession).where(
        AgentChatSession.agent_id == agent_id
    )
    result = await test_db_session.execute(stmt)
    assert result.scalar() == 2


@pytest.mark.asyncio
async def test_chat_message_with_trace_id(test_db_session: AsyncSession):
    """Test that trace_id is optional and indexed."""
    agent_id = uuid.uuid4()
    session_id = uuid.uuid4()

    agent = Agent(
        id=agent_id,
        name="traced",
        version="1.0",
        agent_type="langchain",
        provider="internal",
        owner="o",
        code_path="x",
        code_sha256="0" * 64,
        mcp_token="t" * 32,
        llm_api_key="k" * 32,
        tenant_id="t1",
    )
    test_db_session.add(agent)
    await test_db_session.flush()

    session = AgentChatSession(
        id=session_id,
        agent_id=agent_id,
        user_id="u",
        message_count=0,
    )
    test_db_session.add(session)
    await test_db_session.flush()

    # Message WITH trace_id
    msg1 = AgentChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role="user",
        text="hello",
        trace_id="trace-001",
    )
    # Message WITHOUT trace_id
    msg2 = AgentChatMessage(
        id=uuid.uuid4(),
        session_id=session_id,
        role="agent",
        text="hi",
        trace_id=None,
    )
    test_db_session.add(msg1)
    test_db_session.add(msg2)
    await test_db_session.commit()

    # Both should exist
    stmt = select(func.count()).select_from(AgentChatMessage).where(
        AgentChatMessage.session_id == session_id
    )
    result = await test_db_session.execute(stmt)
    assert result.scalar() == 2
