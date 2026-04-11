"""
SQLite in-memory engine + session fixture for policy store tests.
Each test gets a fresh, isolated database — no state leaks between tests.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import AgentSessionORM, SessionEventORM, CaseORM  # noqa: F401 — register tables
from policies.db_models import PolicyORM                          # noqa: F401 — register table


@pytest.fixture()
def db_session():
    """Yield a sync SQLAlchemy Session backed by a fresh in-memory SQLite DB."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
