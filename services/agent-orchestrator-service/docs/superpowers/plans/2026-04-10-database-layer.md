# Database Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw `aiosqlite` persistence layer with SQLAlchemy 2.0 async ORM, add an `EventRepository` that persists lifecycle events to a `session_events` table, and wire up Alembic for schema migrations.

**Architecture:** A new `db/` package owns the SQLAlchemy engine, declarative `Base`, and ORM models (`AgentSessionORM`, `SessionEventORM`). Repositories (`SessionRepository`, `EventRepository`) are thin wrappers that receive an `AsyncSession` per-request via FastAPI dependency injection — no shared mutable state. The `EventStore` (in-memory) is preserved as the fast read path; the `EventRepository` adds durable persistence by bulk-inserting events at step 7 of the pipeline.

**Tech Stack:** SQLAlchemy 2.0 (`sqlalchemy[asyncio]`), aiosqlite (async SQLite driver), Alembic 1.13, pytest-asyncio

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `db/__init__.py` | Empty package marker |
| `db/base.py` | `Base` (DeclarativeBase), `make_engine()`, `make_session_factory()` |
| `db/models.py` | `AgentSessionORM` + `SessionEventORM` (SQLAlchemy declarative ORM classes) |
| `models/event.py` | `EventRecord` (domain dataclass) + `EventRepository` (SQLAlchemy CRUD) |
| `alembic.ini` | Alembic configuration pointing to `sqlite+aiosqlite:///./agent_orchestrator.db` |
| `alembic/env.py` | Alembic environment wired for async SQLAlchemy |
| `alembic/script.py.mako` | Default Alembic migration template |
| `alembic/versions/001_initial_tables.py` | Initial migration: `agent_sessions` + `session_events` |
| `tests/db/__init__.py` | Empty package marker |
| `tests/db/conftest.py` | Shared `db_session` fixture: in-memory SQLite + all tables |
| `tests/db/test_session_repository.py` | CRUD tests for `SessionRepository` |
| `tests/db/test_event_repository.py` | CRUD tests for `EventRepository` |
| `tests/db/test_alembic_migrations.py` | Migration smoke test (upgrade + downgrade) |

### Modified files
| File | What changes |
|------|-------------|
| `models/session.py` | `SessionRepository` rewritten to use `AsyncSession`; `SessionRecord` dataclass unchanged |
| `dependencies/db.py` | New `get_async_db` (yields `AsyncSession`), updated `get_session_repo`, new `get_event_repo` |
| `requirements.txt` | Add `sqlalchemy[asyncio]>=2.0.36`, `alembic>=1.13.3`, `pytest-asyncio>=0.24` |
| `main.py` | Lifespan: replace aiosqlite init with SQLAlchemy engine + `create_all` (dev path) |
| `services/session_service.py` | Add `event_repo` constructor param; step 7 also bulk-persists events |
| `routers/sessions.py` | `get_session_service()` injects `event_repo` |

---

## Task 0: Update requirements and install packages

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add new dependencies**

Replace the Database section of `requirements.txt`:
```
# ─── Database ────────────────────────────────────────────────────────────────
sqlalchemy[asyncio]>=2.0.36     # Async ORM — replaces raw aiosqlite calls
aiosqlite>=0.20.0               # Async SQLite driver for SQLAlchemy
alembic>=1.13.3                 # Schema migration tool

# ─── Testing ─────────────────────────────────────────────────────────────────
pytest>=8.3.4
pytest-asyncio>=0.24.0          # Async test support
anyio[trio]>=4.6.2              # pytest-asyncio backend
```

- [ ] **Step 2: Install**

```bash
cd /sessions/wizardly-happy-cori/mnt/AISPM/services/agent-orchestrator-service
pip install "sqlalchemy[asyncio]>=2.0.36" "alembic>=1.13.3" "pytest-asyncio>=0.24.0" --break-system-packages -q
```

Expected: no errors. `sqlalchemy`, `alembic`, `pytest-asyncio` importable.

- [ ] **Step 3: Smoke-test imports**

```bash
python -c "from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker; from alembic import config; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add sqlalchemy[asyncio], alembic, pytest-asyncio"
```

---

## Task 1: SQLAlchemy base + ORM models

**Files:**
- Create: `db/__init__.py`
- Create: `db/base.py`
- Create: `db/models.py`
- Create: `tests/db/__init__.py`
- Create: `tests/db/conftest.py`
- Create: `tests/db/test_session_repository.py` (first failing test only — full CRUD in Task 2)

- [ ] **Step 1: Write the failing ORM test**

Create `tests/db/conftest.py`:
```python
"""Shared fixtures for DB-layer tests."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from db.base import Base


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite with all tables created; auto-disposed after test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
```

Create `tests/db/__init__.py` (empty).

Create `tests/db/test_session_repository.py` with just the first test:
```python
import pytest
from db.models import AgentSessionORM, SessionEventORM


@pytest.mark.asyncio
async def test_orm_tables_created(db_session):
    """ORM models map to the correct table names."""
    assert AgentSessionORM.__tablename__ == "agent_sessions"
    assert SessionEventORM.__tablename__ == "session_events"
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /sessions/wizardly-happy-cori/mnt/AISPM/services/agent-orchestrator-service
python -m pytest tests/db/test_session_repository.py::test_orm_tables_created -v
```

Expected: `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Create `db/` package**

Create `db/__init__.py` (empty).

Create `db/base.py`:
```python
"""
db/base.py
──────────
SQLAlchemy async engine factory and declarative base.

All ORM models import Base from here so Alembic autogenerate
can discover every table in a single import.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — every ORM model inherits from this."""
    pass


def make_engine(db_url: str) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine.
    db_url must use the sqlite+aiosqlite:// scheme for SQLite,
    or postgresql+asyncpg:// for PostgreSQL.
    """
    return create_async_engine(db_url, echo=False, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to *engine*. expire_on_commit=False
    prevents lazy-load errors after commit in async context."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

Create `db/models.py`:
```python
"""
db/models.py
────────────
SQLAlchemy ORM table definitions.

Two tables:
  agent_sessions  — one row per AI agent session
  session_events  — lifecycle events emitted during a session

Both are imported in alembic/env.py so autogenerate picks them up.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from db.base import Base


class AgentSessionORM(Base):
    """
    Persistent record for one agent session.

    Column naming note: the ORM column is named 'decision' (concise SQL-friendly
    name) but maps to SessionRecord.policy_decision in the domain layer.
    The mapping helper _orm_to_record() converts 'orm.decision' → 'policy_decision'
    and the insert() method maps 'rec.policy_decision' → 'decision=...' explicitly.
    This is intentional; do not rename without updating both sides.

    JSON fields (tools, context, risk_signals) are stored as JSON-serialised strings
    because SQLite has no native JSON column type.
    """
    __tablename__ = "agent_sessions"

    id             = Column(String,               primary_key=True)
    user_id        = Column(String,               nullable=False)
    agent_id       = Column(String,               nullable=False)
    tenant_id      = Column(String,               nullable=True)
    status         = Column(String,               nullable=False)
    risk_score     = Column(Float,                nullable=False)
    decision       = Column(String,               nullable=False)   # maps to SessionRecord.policy_decision
    # ── Extended metadata ─────────────────────────────────────────────
    prompt_hash    = Column(String,               nullable=False)
    risk_tier      = Column(String,               nullable=False)
    risk_signals   = Column(Text,                 nullable=False)   # JSON array
    tools          = Column(Text,                 nullable=False)   # JSON array
    context        = Column(Text,                 nullable=False)   # JSON object
    policy_reason  = Column(String,               nullable=False)
    policy_version = Column(String,               nullable=False)
    trace_id       = Column(String,               nullable=False)
    created_at     = Column(DateTime(timezone=True), nullable=False)
    updated_at     = Column(DateTime(timezone=True), nullable=False)

    events = relationship(
        "SessionEventORM",
        back_populates="session",
        lazy="select",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_agent_sessions_user_id",   "user_id"),
        Index("ix_agent_sessions_agent_id",  "agent_id"),
        Index("ix_agent_sessions_tenant_id", "tenant_id"),
    )


class SessionEventORM(Base):
    """
    One row per lifecycle event emitted during a session.
    payload is a JSON string (the event's domain payload dict).
    """
    __tablename__ = "session_events"

    id         = Column(String,               primary_key=True)
    session_id = Column(
        String,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String,               nullable=False)
    payload    = Column(Text,                 nullable=False)   # JSON string
    timestamp  = Column(DateTime(timezone=True), nullable=False)

    session = relationship("AgentSessionORM", back_populates="events")

    __table_args__ = (
        Index("ix_session_events_session_id", "session_id"),
        Index("ix_session_events_event_type", "event_type"),
    )
```

- [ ] **Step 4: Run test — expect PASS**

```bash
python -m pytest tests/db/test_session_repository.py::test_orm_tables_created -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add db/ tests/db/
git commit -m "feat(db): add SQLAlchemy async engine, Base, and ORM models (AgentSessionORM, SessionEventORM)"
```

---

## Task 2: SQLAlchemy SessionRepository

**Files:**
- Modify: `models/session.py`
- Modify: `tests/db/test_session_repository.py`

- [ ] **Step 1: Write failing CRUD tests**

Replace the contents of `tests/db/test_session_repository.py` with:
```python
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
    import datetime as dt

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
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/db/test_session_repository.py -v
```

Expected: `ImportError` or attribute errors from old `SessionRepository`.

- [ ] **Step 3: Rewrite `models/session.py`**

```python
"""
models/session.py
─────────────────
SQLite persistence layer using SQLAlchemy 2.0 async ORM.

SessionRecord  — the internal domain dataclass (never exported to routers).
SessionRepository — thin async repository; one instance per request,
                    constructed with an injected AsyncSession.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentSessionORM

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Domain model (internal — never exported to routers)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionRecord:
    session_id: str
    agent_id: str
    user_id: str
    tenant_id: Optional[str]
    prompt_hash: str
    tools: List[str]
    context: Dict[str, Any]
    status: str
    risk_score: float
    risk_tier: str
    risk_signals: List[str]
    policy_decision: str
    policy_reason: str
    policy_version: str
    trace_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────────────

class SessionRepository:
    """
    Thin async repository over the agent_sessions table.
    Receives an AsyncSession per request — no shared connection state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write ──────────────────────────────────────────────────────────

    async def insert(self, rec: SessionRecord) -> None:
        orm = AgentSessionORM(
            id=str(rec.session_id),
            user_id=rec.user_id,
            agent_id=rec.agent_id,
            tenant_id=rec.tenant_id,
            status=rec.status,
            risk_score=rec.risk_score,
            decision=rec.policy_decision,
            prompt_hash=rec.prompt_hash,
            risk_tier=rec.risk_tier,
            risk_signals=json.dumps(rec.risk_signals),
            tools=json.dumps(rec.tools),
            context=json.dumps(rec.context),
            policy_reason=rec.policy_reason,
            policy_version=rec.policy_version,
            trace_id=rec.trace_id,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
        )
        self._session.add(orm)
        await self._session.commit()
        logger.debug("Inserted agent_session id=%s", rec.session_id)

    async def update_status(self, session_id: str, status: str) -> None:
        now = datetime.now(timezone.utc)
        await self._session.execute(
            update(AgentSessionORM)
            .where(AgentSessionORM.id == session_id)
            .values(status=status, updated_at=now)
        )
        await self._session.commit()

    # ── Read ───────────────────────────────────────────────────────────

    async def get_by_id(self, session_id: str) -> Optional[SessionRecord]:
        result = await self._session.execute(
            select(AgentSessionORM).where(AgentSessionORM.id == session_id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_record(orm) if orm else None

    async def list_by_agent(
        self, agent_id: str, limit: int = 50
    ) -> List[SessionRecord]:
        result = await self._session.execute(
            select(AgentSessionORM)
            .where(AgentSessionORM.agent_id == agent_id)
            .order_by(AgentSessionORM.created_at.desc())
            .limit(limit)
        )
        return [_orm_to_record(row) for row in result.scalars()]


# ─────────────────────────────────────────────────────────────────────────────
# Mapping helper
# ─────────────────────────────────────────────────────────────────────────────

def _orm_to_record(orm: AgentSessionORM) -> SessionRecord:
    return SessionRecord(
        session_id=orm.id,
        agent_id=orm.agent_id,
        user_id=orm.user_id,
        tenant_id=orm.tenant_id,
        prompt_hash=orm.prompt_hash,
        tools=json.loads(orm.tools),
        context=json.loads(orm.context),
        status=orm.status,
        risk_score=orm.risk_score,
        risk_tier=orm.risk_tier,
        risk_signals=json.loads(orm.risk_signals),
        policy_decision=orm.decision,
        policy_reason=orm.policy_reason,
        policy_version=orm.policy_version,
        trace_id=orm.trace_id,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/db/test_session_repository.py -v
```

Expected: all 6 tests `PASSED`.

- [ ] **Step 5: Verify existing tests still pass**

```bash
python -m pytest tests/ -v --ignore=tests/db -q
```

Expected: 58 tests pass. (The existing tests use `AsyncMock` for `session_repo`, so they are unaffected by the internal repo rewrite.)

- [ ] **Step 6: Commit**

```bash
git add models/session.py tests/db/test_session_repository.py
git commit -m "feat(db): rewrite SessionRepository using SQLAlchemy 2.0 AsyncSession"
```

---

## Task 3: EventRepository

**Files:**
- Create: `models/event.py`
- Create: `tests/db/test_event_repository.py`

- [ ] **Step 1: Write failing EventRepository tests**

Create `tests/db/test_event_repository.py`:
```python
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

    import datetime as dt
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
python -m pytest tests/db/test_event_repository.py -v
```

Expected: `ModuleNotFoundError: No module named 'models.event'`

- [ ] **Step 3: Create `models/event.py`**

```python
"""
models/event.py
───────────────
SQLAlchemy persistence for session lifecycle events.

EventRecord    — the internal domain dataclass.
EventRepository — thin async repository; one instance per request,
                  constructed with an injected AsyncSession.

Design: events are always appended (immutable audit log). No update
or delete operations are exposed. The EventStore (in-memory) remains
the fast read-path for active sessions; EventRepository provides
durable storage for completed sessions and cross-restart queries.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SessionEventORM

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Domain model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EventRecord:
    """
    Internal domain object for one session lifecycle event.
    `payload` is a JSON string (the event's domain payload dict).
    `id` is auto-generated as a UUID string if not supplied.
    """
    session_id: str
    event_type: str
    payload: str                    # JSON string
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid4()))


# ─────────────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────────────

class EventRepository:
    """
    Thin async repository over the session_events table.
    Receives an AsyncSession per request — no shared state.
    All writes are append-only (no updates or deletes).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write ──────────────────────────────────────────────────────────

    async def insert(self, record: EventRecord) -> None:
        """Persist a single event record."""
        self._session.add(_record_to_orm(record))
        await self._session.commit()
        logger.debug("Inserted event id=%s type=%s", record.id, record.event_type)

    async def bulk_insert(self, records: List[EventRecord]) -> None:
        """
        Persist multiple event records in a single commit.
        Preferred over calling insert() in a loop.
        """
        for record in records:
            self._session.add(_record_to_orm(record))
        await self._session.commit()
        logger.debug("Bulk inserted %d events", len(records))

    # ── Read ───────────────────────────────────────────────────────────

    async def get_by_session_id(self, session_id: str) -> List[EventRecord]:
        """Return all events for a session ordered by timestamp ascending."""
        result = await self._session.execute(
            select(SessionEventORM)
            .where(SessionEventORM.session_id == session_id)
            .order_by(SessionEventORM.timestamp)
        )
        return [_orm_to_record(row) for row in result.scalars()]

    async def get_latest_by_type(
        self, session_id: str, event_type: str
    ) -> Optional[EventRecord]:
        """Return the most recent event of a given type for a session."""
        result = await self._session.execute(
            select(SessionEventORM)
            .where(
                SessionEventORM.session_id == session_id,
                SessionEventORM.event_type == event_type,
            )
            .order_by(SessionEventORM.timestamp.desc())
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_record(orm) if orm else None


# ─────────────────────────────────────────────────────────────────────────────
# Mapping helpers
# ─────────────────────────────────────────────────────────────────────────────

def _record_to_orm(record: EventRecord) -> SessionEventORM:
    return SessionEventORM(
        id=record.id,
        session_id=record.session_id,
        event_type=record.event_type,
        payload=record.payload,
        timestamp=record.timestamp,
    )


def _orm_to_record(orm: SessionEventORM) -> EventRecord:
    return EventRecord(
        id=orm.id,
        session_id=orm.session_id,
        event_type=orm.event_type,
        payload=orm.payload,
        timestamp=orm.timestamp,
    )
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/db/test_event_repository.py -v
```

Expected: all 6 tests `PASSED`.

- [ ] **Step 5: Run all DB tests**

```bash
python -m pytest tests/db/ -v
```

Expected: 12 tests pass.

- [ ] **Step 6: Commit**

```bash
git add models/event.py tests/db/test_event_repository.py
git commit -m "feat(db): add EventRecord and EventRepository for session_events persistence"
```

---

## Task 4: Update dependencies/db.py

**Files:**
- Modify: `dependencies/db.py`

No new tests needed — this is pure FastAPI wiring, tested via integration in the service tests. The existing tests mock the repo, so they're unaffected.

> **Architecture note — per-request instantiation:** After this change, `SessionRepository` and `EventRepository` are constructed **per HTTP request**, not once at startup. `app.state.session_repo` is removed from `main.py`. The `async_session_factory` is stored on `app.state` at startup; each request dependency call creates a fresh `AsyncSession`. FastAPI's dependency cache ensures `get_async_db` is called once per request even when both repos depend on it — they share one `AsyncSession` and thus one implicit transaction context.

- [ ] **Step 1: Rewrite `dependencies/db.py`**

```python
"""
dependencies/db.py
──────────────────
FastAPI dependency functions for database access.

get_async_db       — yields a fresh AsyncSession per request (auto-closed).
get_session_repo   — returns SessionRepository bound to the request's session.
get_event_repo     — returns EventRepository bound to the request's session.

IMPORTANT: SessionRepository and EventRepository are instantiated per-request,
not stored on app.state. The shared state is app.state.async_session_factory
(the session factory, not a session itself). This ensures each request gets
its own AsyncSession with no cross-request shared state.

Because FastAPI caches dependencies within a single request, get_async_db
is called once even when both get_session_repo and get_event_repo are
declared as dependencies in the same route — they share the same AsyncSession
and therefore the same database transaction.
"""
from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.event import EventRepository
from models.session import SessionRepository


async def get_async_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: yields one AsyncSession per HTTP request.

    The session factory is stored on app.state at startup.
    The session is automatically closed when the response is sent.
    """
    factory = request.app.state.async_session_factory
    async with factory() as session:
        yield session


async def get_session_repo(
    session: AsyncSession = Depends(get_async_db),
) -> SessionRepository:
    """FastAPI dependency: returns SessionRepository for the current request."""
    return SessionRepository(session)


async def get_event_repo(
    session: AsyncSession = Depends(get_async_db),
) -> EventRepository:
    """FastAPI dependency: returns EventRepository for the current request."""
    return EventRepository(session)
```

- [ ] **Step 2: Verify import**

```bash
python -c "from dependencies.db import get_async_db, get_session_repo, get_event_repo; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Verify full test suite still passes**

```bash
python -m pytest tests/ -q
```

Expected: 64+ tests pass (58 original + 12 DB layer).

- [ ] **Step 4: Commit**

```bash
git add dependencies/db.py
git commit -m "feat(db): update dependency injection — get_async_db, get_session_repo, get_event_repo"
```

---

## Task 5: Alembic migrations

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/001_initial_tables.py`
- Create: `tests/db/test_alembic_migrations.py`

- [ ] **Step 1: Write migration smoke test**

Create `tests/db/test_alembic_migrations.py`:
```python
"""Smoke test: alembic upgrade head creates both tables; downgrade drops them."""
import os
import subprocess
import tempfile
import pytest


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=30
    )


def test_upgrade_and_downgrade():
    """Run 'alembic upgrade head' then 'alembic downgrade base' on a temp DB."""
    svc_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    env_vars = os.environ.copy()
    env_vars["DB_PATH"] = db_path

    try:
        # -- upgrade --
        result = _run(
            ["python", "-m", "alembic", "-x", f"db_path={db_path}", "upgrade", "head"],
            cwd=svc_dir,
        )
        assert result.returncode == 0, f"upgrade failed:\n{result.stderr}"

        # -- verify tables exist --
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "agent_sessions" in tables, f"agent_sessions not found in {tables}"
        assert "session_events" in tables, f"session_events not found in {tables}"

        # -- downgrade --
        result = _run(
            ["python", "-m", "alembic", "-x", f"db_path={db_path}", "downgrade", "base"],
            cwd=svc_dir,
        )
        assert result.returncode == 0, f"downgrade failed:\n{result.stderr}"

        # -- verify tables gone --
        conn = sqlite3.connect(db_path)
        tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "agent_sessions" not in tables_after
        assert "session_events" not in tables_after

    finally:
        os.unlink(db_path)
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
python -m pytest tests/db/test_alembic_migrations.py -v
```

Expected: error — `alembic.ini` not found.

- [ ] **Step 3: Initialise Alembic**

```bash
cd /sessions/wizardly-happy-cori/mnt/AISPM/services/agent-orchestrator-service
alembic init alembic
```

This creates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, and `alembic/versions/`.

- [ ] **Step 4: Configure `alembic.ini`**

Edit the `sqlalchemy.url` line in `alembic.ini`:
```ini
sqlalchemy.url = sqlite+aiosqlite:///./agent_orchestrator.db
```

- [ ] **Step 5: Rewrite `alembic/env.py`**

Replace the generated `alembic/env.py` entirely:
```python
"""
alembic/env.py
──────────────
Alembic environment for async SQLAlchemy + SQLite.

Supports:
  • alembic upgrade head        — run migrations forward
  • alembic downgrade base      — roll back all migrations
  • alembic revision --autogenerate  — generate new migration from ORM diff

Pass a custom DB path at the command line with:
  alembic -x db_path=/path/to/test.db upgrade head
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Register ORM models so autogenerate can see all tables ────────────────────
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.base import Base
from db.models import AgentSessionORM, SessionEventORM  # noqa: F401

# ─────────────────────────────────────────────────────────────────────────────

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Allow overriding the DB path via -x db_path=... on the CLI."""
    db_path = context.get_x_argument(as_dictionary=True).get("db_path")
    if db_path:
        return f"sqlite+aiosqlite:///{db_path}"
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,          # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,          # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()
    connectable = async_engine_from_config(
        cfg, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Create initial migration**

Create `alembic/versions/001_initial_tables.py`:
```python
"""Initial schema: agent_sessions and session_events

Revision ID: 001
Revises:
Create Date: 2026-04-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id",             sa.String,               primary_key=True),
        sa.Column("user_id",        sa.String,               nullable=False),
        sa.Column("agent_id",       sa.String,               nullable=False),
        sa.Column("tenant_id",      sa.String,               nullable=True),
        sa.Column("status",         sa.String,               nullable=False),
        sa.Column("risk_score",     sa.Float,                nullable=False),
        sa.Column("decision",       sa.String,               nullable=False),
        sa.Column("prompt_hash",    sa.String,               nullable=False),
        sa.Column("risk_tier",      sa.String,               nullable=False),
        sa.Column("risk_signals",   sa.Text,                 nullable=False),
        sa.Column("tools",          sa.Text,                 nullable=False),
        sa.Column("context",        sa.Text,                 nullable=False),
        sa.Column("policy_reason",  sa.String,               nullable=False),
        sa.Column("policy_version", sa.String,               nullable=False),
        sa.Column("trace_id",       sa.String,               nullable=False),
        sa.Column("created_at",     sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_sessions_user_id",   "agent_sessions", ["user_id"])
    op.create_index("ix_agent_sessions_agent_id",  "agent_sessions", ["agent_id"])
    op.create_index("ix_agent_sessions_tenant_id", "agent_sessions", ["tenant_id"])

    op.create_table(
        "session_events",
        sa.Column("id",         sa.String,                  primary_key=True),
        sa.Column("session_id", sa.String,
                  sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event_type", sa.String,                  nullable=False),
        sa.Column("payload",    sa.Text,                    nullable=False),
        sa.Column("timestamp",  sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_session_events_session_id", "session_events", ["session_id"])
    op.create_index("ix_session_events_event_type", "session_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("session_events")
    op.drop_table("agent_sessions")
```

- [ ] **Step 7: Run migration smoke test — expect PASS**

```bash
python -m pytest tests/db/test_alembic_migrations.py -v
```

Expected: `PASSED`

- [ ] **Step 8: Commit**

```bash
git add alembic.ini alembic/ tests/db/test_alembic_migrations.py
git commit -m "feat(db): add Alembic migrations — initial agent_sessions + session_events schema"
```

---

## Task 6: Wire main.py, session_service.py, and routers/sessions.py

**Files:**
- Modify: `main.py`
- Modify: `services/session_service.py`
- Modify: `routers/sessions.py`
- Modify: `tests/services/test_session_service_full.py`

- [ ] **Step 1: Write failing integration test for event persistence**

Add to `tests/services/test_session_service_full.py`:
```python
@pytest.mark.asyncio
async def test_events_persisted_to_event_repo(publisher, store, identity):
    """EventRepository.bulk_insert is called once per session creation."""
    mock_repo = AsyncMock()
    mock_repo.insert.return_value = None
    mock_event_repo = AsyncMock()

    svc = SessionService(
        risk_engine=RiskEngine(),
        policy_client=PolicyClient(),
        event_publisher=publisher,
        session_repo=mock_repo,
        event_store=store,
        llm_client=None,
        prompt_processor=None,
        event_repo=mock_event_repo,
    )

    from schemas.session import CreateSessionRequest
    req = CreateSessionRequest(agent_id="agent-1", prompt="hello world")
    await svc.create_session(request=req, identity=identity, trace_id="t-ev")

    # bulk_insert must have been called with at least the prompt.received event
    mock_event_repo.bulk_insert.assert_called_once()
    call_args = mock_event_repo.bulk_insert.call_args[0][0]
    assert len(call_args) >= 1
    event_types = {e.event_type for e in call_args}
    assert "prompt.received" in event_types


@pytest.mark.asyncio
async def test_session_service_works_without_event_repo(publisher, store, identity):
    """event_repo=None is safe — no AttributeError."""
    mock_repo = AsyncMock()
    svc = SessionService(
        risk_engine=RiskEngine(),
        policy_client=PolicyClient(),
        event_publisher=publisher,
        session_repo=mock_repo,
        event_store=store,
        event_repo=None,
    )
    from schemas.session import CreateSessionRequest
    req = CreateSessionRequest(agent_id="agent-1", prompt="hello")
    result = await svc.create_session(request=req, identity=identity, trace_id="t-no-ev")
    assert result.session_id is not None
```

- [ ] **Step 2: Run new tests — expect FAIL**

```bash
python -m pytest tests/services/test_session_service_full.py::test_events_persisted_to_event_repo tests/services/test_session_service_full.py::test_session_service_works_without_event_repo -v
```

Expected: `TypeError` — `SessionService.__init__` doesn't accept `event_repo`.

- [ ] **Step 3: Update `services/session_service.py`**

Add `event_repo` to `__init__`:
```python
from models.event import EventRecord, EventRepository

class SessionService:
    def __init__(
        self,
        risk_engine: RiskEngine,
        policy_client: PolicyClient,
        event_publisher: EventPublisher,
        session_repo: SessionRepository,
        event_store: EventStore,
        llm_client=None,
        prompt_processor=None,
        event_repo=None,       # EventRepository | None
    ) -> None:
        self._risk      = risk_engine
        self._policy    = policy_client
        self._publisher = event_publisher
        self._repo      = session_repo
        self._store     = event_store
        self._llm       = llm_client
        self._processor = prompt_processor
        self._event_repo = event_repo
```

Then in `create_session`, extend step 7 to also persist events:
```python
        # ── Step 7: persist session + lifecycle events ─────────────────────
        await self._repo.insert(record)
        if self._event_repo:
            try:
                current_events = await self._store.get_events(session_id)
                # EventType is `str, Enum` so .value gives the plain string.
                # e.payload is Dict[str, Any]; json.dumps serialises it to Text.
                import json as _json
                event_records = [
                    EventRecord(
                        session_id=str(session_id),
                        event_type=e.event_type.value,   # e.g. "prompt.received"
                        payload=_json.dumps(e.payload),  # Dict → JSON string
                        timestamp=e.timestamp,
                    )
                    for e in current_events
                ]
                await self._event_repo.bulk_insert(event_records)
                logger.debug(
                    "Persisted %d events for session=%s", len(event_records), session_id
                )
            except Exception as exc:
                logger.warning(
                    "Event persistence failed session=%s: %s — continuing",
                    session_id, exc,
                )

- [ ] **Step 4: Run new tests — expect PASS**

```bash
python -m pytest tests/services/test_session_service_full.py -v
```

Expected: all 11 tests pass (9 existing + 2 new).

- [ ] **Step 5: Update `main.py`**

Replace the aiosqlite-based startup block:

```python
    # ── Database (SQLAlchemy async + SQLite) ─────────────────────────────────
    from db.base import make_engine, make_session_factory
    from db.models import Base

    db_url = f"sqlite+aiosqlite:///{DB_PATH}"
    engine = make_engine(db_url)

    # Dev path: create tables automatically via create_all.
    # Production path: set DB_AUTO_CREATE_TABLES=false and run
    # `alembic upgrade head` before deploying.
    if os.getenv("DB_AUTO_CREATE_TABLES", "true").lower() == "true":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("create_all complete (dev mode)")

    app.state.db_engine = engine
    app.state.async_session_factory = make_session_factory(engine)
    logger.info("Database engine initialised: %s", db_url)
```

And in teardown replace `await repo.close()` with:
```python
    await app.state.db_engine.dispose()
```

Also remove the old `repo = SessionRepository(db_path=DB_PATH)` / `await repo.connect()` / `app.state.session_repo = repo` lines.

> **Note:** Remove the old `from models.session import SessionRepository` import from the top of `main.py` — `SessionRepository` is now constructed per-request via DI, not at startup. `app.state.session_repo` no longer exists. Keep other imports.

> **DB_AUTO_CREATE_TABLES:** Set to `false` in production and run `alembic upgrade head` during deployment instead. Default is `true` for local dev convenience.

- [ ] **Step 6: Update `routers/sessions.py`**

Add `event_repo` injection to `get_session_service`:
```python
from dependencies.db import get_session_repo, get_event_repo
from models.event import EventRepository

def get_session_service(
    request: Request,
    repo: SessionRepository = Depends(get_session_repo),
    event_repo: EventRepository = Depends(get_event_repo),
) -> SessionService:
    return SessionService(
        risk_engine=request.app.state.risk_engine,
        policy_client=request.app.state.policy_client,
        event_publisher=request.app.state.event_publisher,
        session_repo=repo,
        event_store=request.app.state.event_store,
        llm_client=getattr(request.app.state, "llm_client", None),
        prompt_processor=getattr(request.app.state, "prompt_processor", None),
        event_repo=event_repo,
    )
```

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -v -q
```

Expected: 70+ tests pass (58 original + 12 DB layer + 2 new service tests).

- [ ] **Step 8: Commit**

```bash
git add main.py services/session_service.py routers/sessions.py tests/services/test_session_service_full.py
git commit -m "feat(db): wire SQLAlchemy into main.py, session_service, and router — events persisted at step 7"
```

---

## Verification checklist

Before calling this done, confirm:

- [ ] `python -m pytest tests/ -q` → all tests green, no warnings about missing fixtures
- [ ] `alembic upgrade head` runs without error against a fresh SQLite file
- [ ] `alembic downgrade base` drops both tables cleanly
- [ ] `python -c "from db.base import Base; from db.models import AgentSessionORM, SessionEventORM; print(list(Base.metadata.tables))"` → prints `['agent_sessions', 'session_events']`
- [ ] Server starts: `uvicorn main:app --port 8094 &` → `=== agent-orchestrator-service ready ===` in logs, no errors
- [ ] POST to `/api/v1/sessions` → session row appears in `agent_sessions`, events appear in `session_events`

---

## Running migrations (developer reference)

```bash
# Apply all migrations (run before first start in prod)
alembic upgrade head

# Generate a new migration after changing db/models.py
alembic revision --autogenerate -m "describe what changed"

# Roll back one revision
alembic downgrade -1

# Roll back everything
alembic downgrade base

# Pass a custom DB path (useful in CI)
alembic -x db_path=/tmp/test.db upgrade head
```
