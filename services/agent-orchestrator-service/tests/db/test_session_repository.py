import pytest
from db.models import AgentSessionORM, SessionEventORM


@pytest.mark.asyncio
async def test_orm_tables_created(db_session):
    """ORM models map to the correct table names."""
    assert AgentSessionORM.__tablename__ == "agent_sessions"
    assert SessionEventORM.__tablename__ == "session_events"
