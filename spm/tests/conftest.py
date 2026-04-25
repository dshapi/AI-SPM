import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from spm.db.models import Base, Agent, AgentChatSession, AgentChatMessage

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False
    )
    
    # Handle SQLite not supporting server_default datetime functions
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    
    # Create only Agent-related tables
    Agent.__table__.create(engine, checkfirst=True)
    AgentChatSession.__table__.create(engine, checkfirst=True)
    AgentChatMessage.__table__.create(engine, checkfirst=True)
    
    with Session(engine) as session:
        yield session
    
    # Cleanup
    AgentChatMessage.__table__.drop(engine, checkfirst=True)
    AgentChatSession.__table__.drop(engine, checkfirst=True)
    Agent.__table__.drop(engine, checkfirst=True)
