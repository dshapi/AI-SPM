"""
Tests for services/agent-orchestrator-service/seed_demo.py
===========================================================

seed_demo_data() is an async function that accepts an async_sessionmaker.
The orchestrator ORM models use SQLite-compatible types (String, Float, …)
so we can run against an in-memory aiosqlite database without any Postgres.

Two important quirks in seed_demo_data() that the tests must handle:
  • DEMO_SESSIONS:  the seeder pops the "events" key from each session dict
    in-place on the first call.  Subsequent tests on a fresh DB would break
    if they consumed the same dicts.
  • DEMO_FINDINGS:  the seeder pops "created_at_offset" from each finding
    dict in-place on the first call.

The ``restore_demo_data`` autouse fixture deep-copies all three module-level
lists (DEMO_SESSIONS, DEMO_CASES, DEMO_FINDINGS) onto seed_demo's namespace
before each test via monkeypatch, so mutations in one test never leak into
the next.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── sys.path: make the service root and repo root importable ─────────────────
_SVC_ROOT  = Path(__file__).parents[1]   # services/agent-orchestrator-service/
_REPO_ROOT = _SVC_ROOT.parents[1]        # repo root

for _p in (str(_SVC_ROOT), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── ORM imports (must come after sys.path is set) ────────────────────────────
from db.base import Base  # noqa: E402
from db.models import (  # noqa: E402, F401 — registers all tables with Base.metadata
    AgentSessionORM,
    CaseORM,
    SessionEventORM,
    ThreatFindingORM,
)

import seed_demo  # noqa: E402
from seed_demo import (  # noqa: E402
    DEMO_CASES,
    DEMO_FINDINGS,
    DEMO_SESSIONS,
    seed_demo_data,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_factory():
    """
    Fresh in-memory SQLite DB per test.  All ORM tables are created via
    Base.metadata, then torn down on exit.  Yields the async_sessionmaker
    so it can be passed directly to seed_demo_data().
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
def restore_demo_data(monkeypatch):
    """
    seed_demo_data() mutates module-level lists in-place:
      - DEMO_SESSIONS dicts lose the "events" key (s.pop("events"))
      - DEMO_FINDINGS dicts lose the "created_at_offset" key (f.pop(…))

    This fixture replaces those lists on seed_demo's module namespace with a
    deep copy BEFORE each test, then monkeypatch restores the originals after
    each test.  Tests are therefore fully isolated from one another.
    """
    monkeypatch.setattr(seed_demo, "DEMO_SESSIONS", copy.deepcopy(seed_demo.DEMO_SESSIONS))
    monkeypatch.setattr(seed_demo, "DEMO_FINDINGS", copy.deepcopy(seed_demo.DEMO_FINDINGS))
    monkeypatch.setattr(seed_demo, "DEMO_CASES",    copy.deepcopy(seed_demo.DEMO_CASES))


# ── Helper ────────────────────────────────────────────────────────────────────

async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as db:
        result = await db.execute(select(func.count()).select_from(model))
        return result.scalar() or 0


# ── Session tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_creates_all_sessions(db_factory):
    """First run inserts one AgentSessionORM row per DEMO_SESSIONS entry."""
    await seed_demo_data(db_factory)
    count = await _count(db_factory, AgentSessionORM)
    assert count == len(DEMO_SESSIONS)


@pytest.mark.asyncio
async def test_seed_creates_session_events(db_factory):
    """Session events are inserted alongside their parent sessions."""
    await seed_demo_data(db_factory)
    count = await _count(db_factory, SessionEventORM)
    # Every demo session has at least one event
    assert count > 0


@pytest.mark.asyncio
async def test_seed_sessions_idempotent(db_factory):
    """Second run does not duplicate sessions (session_count > 0 guard)."""
    await seed_demo_data(db_factory)
    await seed_demo_data(db_factory)
    count = await _count(db_factory, AgentSessionORM)
    assert count == len(DEMO_SESSIONS)


@pytest.mark.asyncio
async def test_seed_events_idempotent(db_factory):
    """Second run does not duplicate session events."""
    await seed_demo_data(db_factory)
    events_after_first = await _count(db_factory, SessionEventORM)
    await seed_demo_data(db_factory)
    events_after_second = await _count(db_factory, SessionEventORM)
    assert events_after_first == events_after_second


# ── Case tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_creates_all_cases(db_factory):
    """First run inserts one CaseORM row per DEMO_CASES entry."""
    await seed_demo_data(db_factory)
    count = await _count(db_factory, CaseORM)
    assert count == len(DEMO_CASES)


@pytest.mark.asyncio
async def test_seed_cases_idempotent(db_factory):
    """Second run does not duplicate cases (case_id set-difference guard)."""
    await seed_demo_data(db_factory)
    await seed_demo_data(db_factory)
    count = await _count(db_factory, CaseORM)
    assert count == len(DEMO_CASES)


# ── Threat-finding tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_creates_all_findings(db_factory):
    """First run inserts one ThreatFindingORM row per DEMO_FINDINGS entry."""
    await seed_demo_data(db_factory)
    count = await _count(db_factory, ThreatFindingORM)
    assert count == len(DEMO_FINDINGS)


@pytest.mark.asyncio
async def test_seed_findings_idempotent(db_factory):
    """Second run does not duplicate findings (id set-difference guard)."""
    await seed_demo_data(db_factory)
    await seed_demo_data(db_factory)
    count = await _count(db_factory, ThreatFindingORM)
    assert count == len(DEMO_FINDINGS)


# ── Combined idempotency (all entity types together) ─────────────────────────

@pytest.mark.asyncio
async def test_seed_full_idempotency(db_factory):
    """
    After two complete seed runs all entity counts match the source data.
    This is the canonical idempotency test — it verifies that running the
    seeder twice produces the exact same DB state as running it once.
    """
    await seed_demo_data(db_factory)
    await seed_demo_data(db_factory)

    sessions  = await _count(db_factory, AgentSessionORM)
    cases     = await _count(db_factory, CaseORM)
    findings  = await _count(db_factory, ThreatFindingORM)

    assert sessions == len(DEMO_SESSIONS)
    assert cases    == len(DEMO_CASES)
    assert findings == len(DEMO_FINDINGS)
