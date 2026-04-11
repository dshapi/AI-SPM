# Policies PostgreSQL Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the thread-locked in-memory `policies/store.py` with a sync SQLAlchemy store backed by PostgreSQL (SQLite for local dev/tests), keeping every API contract and all router/service files untouched.

**Architecture:** The policies module is intentionally synchronous — its `router.py` uses plain `def` endpoints, which FastAPI runs in a threadpool. We therefore use **synchronous SQLAlchemy** (`create_engine` / `Session`) with `psycopg2-binary` for Postgres and `sqlite` for dev/tests. This means zero changes to `router.py` or `service.py`. A new `init_db(url)` function in `store.py` replaces the module-level in-memory dict, called from the FastAPI lifespan. Snapshots (for version restore) move from a module-level dict into a `snapshots` JSON column on the policy row.

**Tech Stack:** SQLAlchemy 2.x (sync), psycopg2-binary, Alembic, pytest with SQLite in-memory for tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `policies/db_models.py` | SQLAlchemy ORM `PolicyORM` model |
| **Create** | `policies/seed.py` | 9 default policies seed function |
| **Rewrite** | `policies/store.py` | Sync DB-backed store; same public interface |
| **Create** | `alembic/versions/002_add_policies_table.py` | Migration: create `policies` table |
| **Modify** | `alembic/env.py` | Import `PolicyORM` so autogenerate sees it |
| **Modify** | `main.py` | Call `store.init_db()` + `seed_policies()` in lifespan |
| **Modify** | `requirements.txt` | Add `psycopg2-binary` |
| **Create** | `tests/policies/__init__.py` | Pytest package marker |
| **Create** | `tests/policies/conftest.py` | In-memory SQLite engine fixture |
| **Create** | `tests/policies/test_store.py` | Full store CRUD + restore tests |

**Do not touch:** `policies/router.py`, `policies/service.py`, `policies/models.py`

---

## Task 1 — SQLAlchemy ORM model (`policies/db_models.py`)

**Files:**
- Create: `services/agent-orchestrator-service/policies/db_models.py`

- [ ] **Step 1: Create the file**

```python
"""
policies/db_models.py
─────────────────────
SQLAlchemy ORM table for the policies store.

Column design rationale
───────────────────────
• Simple scalar fields (name, version, mode …) → individual String/Integer columns
  so queries can filter/sort without JSON path expressions.
• Structured / variable-length data (history, logic tokens, scope arrays, impact
  counters, snapshots) → JSON columns.  PostgreSQL stores these as JSONB; SQLite
  serialises them as text via SQLAlchemy's JSON type.
• `snapshots` is a dict[version_str, full_policy_dict] used by restore_policy().
  Stored on the same row to avoid a separate table.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.types import JSON

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PolicyORM(Base):
    __tablename__ = "policies"

    # ── Identity ─────────────────────────────────────────────────────────────
    policy_id        = Column(String,  primary_key=True, index=True)
    name             = Column(String,  nullable=False)
    version          = Column(String,  nullable=False, default="v1")
    type             = Column(String,  nullable=False)
    mode             = Column(String,  nullable=False, default="Monitor")
    status           = Column(String,  nullable=False, default="Active")

    # ── Display / meta ────────────────────────────────────────────────────────
    scope            = Column(String,  nullable=False, default="")   # human-readable string
    owner            = Column(String,  nullable=False, default="")
    created_by       = Column(String,  nullable=False, default="")
    created          = Column(String,  nullable=False, default="")
    updated          = Column(String,  nullable=False, default="")
    updated_full     = Column(String,  nullable=False, default="")
    description      = Column(String,  nullable=False, default="")

    # ── Stats ─────────────────────────────────────────────────────────────────
    affected_assets  = Column(Integer, nullable=False, default=0)
    related_alerts   = Column(Integer, nullable=False, default=0)
    linked_sims      = Column(Integer, nullable=False, default=0)

    # ── JSON payload columns ──────────────────────────────────────────────────
    # agents / tools / data_sources / environments / exceptions → list[str]
    agents           = Column(JSON, nullable=False, default=list)
    tools            = Column(JSON, nullable=False, default=list)
    data_sources     = Column(JSON, nullable=False, default=list)
    environments     = Column(JSON, nullable=False, default=list)
    exceptions       = Column(JSON, nullable=False, default=list)

    # impact counters  → {blocked, flagged, unchanged, total}
    impact           = Column(JSON, nullable=False,
                              default=lambda: {"blocked": 0, "flagged": 0,
                                               "unchanged": 0, "total": 100})

    # history          → list[{version, by, when, change}]
    history          = Column(JSON, nullable=False, default=list)

    # logic tokens     → list[{t, v}]  (derived from logic_code, stored for fast read)
    logic            = Column(JSON, nullable=False, default=list)

    # ── Raw logic code ────────────────────────────────────────────────────────
    logic_code       = Column(String, nullable=False, default="")
    logic_language   = Column(String, nullable=False, default="rego")

    # ── Snapshots for version restore ─────────────────────────────────────────
    # dict[version_str, full_policy_dict_at_that_version]
    snapshots        = Column(JSON, nullable=False, default=dict)

    # ── Audit timestamps ──────────────────────────────────────────────────────
    created_at       = Column(DateTime(timezone=True), nullable=False,
                              default=_utcnow)
    updated_at       = Column(DateTime(timezone=True), nullable=False,
                              default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 2: Verify the model imports cleanly**

```bash
cd services/agent-orchestrator-service
python3 -c "from policies.db_models import PolicyORM; print('OK', PolicyORM.__tablename__)"
```
Expected: `OK policies`

- [ ] **Step 3: Commit**
```bash
git add services/agent-orchestrator-service/policies/db_models.py
git commit -m "feat(policies): add PolicyORM SQLAlchemy model"
```

---

## Task 2 — Alembic migration (`alembic/versions/002_add_policies_table.py`)

**Files:**
- Create: `services/agent-orchestrator-service/alembic/versions/002_add_policies_table.py`
- Modify: `services/agent-orchestrator-service/alembic/env.py` (add PolicyORM import)

- [ ] **Step 1: Update `alembic/env.py` — add PolicyORM import**

Find the block that currently reads:
```python
from db.models import AgentSessionORM, SessionEventORM  # noqa: F401
```
Change it to:
```python
from db.models import AgentSessionORM, SessionEventORM  # noqa: F401
from policies.db_models import PolicyORM                # noqa: F401
```

- [ ] **Step 2: Create the migration file**

```python
"""Add policies table

Revision ID: 002
Revises: 001
Create Date: 2026-04-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("policy_id",       sa.String,  primary_key=True),
        sa.Column("name",            sa.String,  nullable=False),
        sa.Column("version",         sa.String,  nullable=False),
        sa.Column("type",            sa.String,  nullable=False),
        sa.Column("mode",            sa.String,  nullable=False),
        sa.Column("status",          sa.String,  nullable=False),
        sa.Column("scope",           sa.String,  nullable=False, server_default=""),
        sa.Column("owner",           sa.String,  nullable=False, server_default=""),
        sa.Column("created_by",      sa.String,  nullable=False, server_default=""),
        sa.Column("created",         sa.String,  nullable=False, server_default=""),
        sa.Column("updated",         sa.String,  nullable=False, server_default=""),
        sa.Column("updated_full",    sa.String,  nullable=False, server_default=""),
        sa.Column("description",     sa.String,  nullable=False, server_default=""),
        sa.Column("affected_assets", sa.Integer, nullable=False, server_default="0"),
        sa.Column("related_alerts",  sa.Integer, nullable=False, server_default="0"),
        sa.Column("linked_sims",     sa.Integer, nullable=False, server_default="0"),
        # JSON columns — PostgreSQL stores as JSONB; SQLite serialises as TEXT
        sa.Column("agents",        sa.JSON, nullable=False),
        sa.Column("tools",         sa.JSON, nullable=False),
        sa.Column("data_sources",  sa.JSON, nullable=False),
        sa.Column("environments",  sa.JSON, nullable=False),
        sa.Column("exceptions",    sa.JSON, nullable=False),
        sa.Column("impact",        sa.JSON, nullable=False),
        sa.Column("history",       sa.JSON, nullable=False),
        sa.Column("logic",         sa.JSON, nullable=False),
        sa.Column("logic_code",    sa.String, nullable=False, server_default=""),
        sa.Column("logic_language",sa.String, nullable=False, server_default="rego"),
        sa.Column("snapshots",     sa.JSON, nullable=False),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",    sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_policies_policy_id", "policies", ["policy_id"])
    op.create_index("ix_policies_type",      "policies", ["type"])
    op.create_index("ix_policies_mode",      "policies", ["mode"])
    op.create_index("ix_policies_status",    "policies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_policies_status",    "policies")
    op.drop_index("ix_policies_mode",      "policies")
    op.drop_index("ix_policies_type",      "policies")
    op.drop_index("ix_policies_policy_id", "policies")
    op.drop_table("policies")
```

- [ ] **Step 3: Verify migration runs against SQLite (dev)**

```bash
cd services/agent-orchestrator-service
alembic -x db_path=/tmp/test_migration.db upgrade head
```
Expected: no errors, both `001` and `002` applied.

- [ ] **Step 4: Verify downgrade**

```bash
alembic -x db_path=/tmp/test_migration.db downgrade -1
alembic -x db_path=/tmp/test_migration.db upgrade head
```
Expected: clean round-trip.

- [ ] **Step 5: Commit**
```bash
git add alembic/versions/002_add_policies_table.py alembic/env.py
git commit -m "feat(policies): alembic migration 002 — add policies table"
```

---

## Task 3 — Seed data (`policies/seed.py`)

Extract the 9 default policies from the current `store.py` into a standalone function. This keeps `store.py` clean and lets tests opt-in to seeding.

**Files:**
- Create: `services/agent-orchestrator-service/policies/seed.py`

- [ ] **Step 1: Write the failing test first**

Create `tests/policies/test_store.py` (file will grow across tasks):

```python
"""
tests/policies/test_store.py
────────────────────────────
Tests for the DB-backed policy store.
Uses an in-memory SQLite database via the `db_session` fixture in conftest.py.
"""
import pytest
from policies import store
from policies.seed import seed_policies


def test_seed_creates_nine_policies(db_session):
    store.init_db_for_session(db_session)
    seed_policies()
    policies = store.list_policies()
    assert len(policies) == 9


def test_seed_idempotent(db_session):
    store.init_db_for_session(db_session)
    seed_policies()
    seed_policies()            # second call must be a no-op
    assert len(store.list_policies()) == 9


def test_seed_prompt_guard_present(db_session):
    store.init_db_for_session(db_session)
    seed_policies()
    names = [p["name"] for p in store.list_policies()]
    assert "Prompt-Guard" in names
```

- [ ] **Step 2: Run test — expect FAIL (seed.py doesn't exist yet)**

```bash
cd services/agent-orchestrator-service
python3 -m pytest tests/policies/test_store.py::test_seed_creates_nine_policies -v
```
Expected: `ImportError` or `ModuleNotFoundError`

- [ ] **Step 3: Create `tests/policies/__init__.py` (empty) and `tests/policies/conftest.py`**

```python
# tests/policies/conftest.py
"""
SQLite in-memory engine + session fixture for policy store tests.
Each test gets a fresh, isolated database.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
# Import ORM models so Base.metadata includes all tables
from db.models import AgentSessionORM, SessionEventORM, CaseORM  # noqa: F401
from policies.db_models import PolicyORM                          # noqa: F401


@pytest.fixture()
def db_session():
    """Yield a sync SQLAlchemy Session backed by an in-memory SQLite DB."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
```

- [ ] **Step 4: Create `policies/seed.py`**

Move the raw seed data out of `store.py`. The function checks whether policies already exist before inserting.

```python
"""
policies/seed.py
─────────────────
Default policy seed data.
Called once at application startup if the policies table is empty.
Importing this module has NO side effects — seeding happens only when
seed_policies() is explicitly called.
"""
from __future__ import annotations

# ── Rego / JSON source code strings ──────────────────────────────────────────
# These are imported from store so the tokeniser stays co-located with them.
from .store import (
    _PROMPT_GUARD_CODE,
    _TOOL_SCOPE_CODE,
    _PII_MASK_CODE,
    _WRITE_APPROVAL_CODE,
    _TOKEN_BUDGET_CODE,
    _OUTPUT_FILTER_CODE,
    _EGRESS_CONTROL_CODE,
    _RAG_RETRIEVAL_CODE,
    _JAILBREAK_DETECT_CODE,
    _tokenise,
    create_policy_raw,   # internal helper we'll add to store.py
    list_policies,
)


_SEED_DATA = [
    {
        "id": "pg-v3",
        "name": "Prompt-Guard",
        "version": "v3",
        "type": "prompt-safety",
        "mode": "Enforce",
        "status": "Active",
        "scope": "All Production Agents",
        "owner": "security-ops",
        "createdBy": "admin@orbyx.ai",
        "created": "Mar 12, 2026",
        "updated": "2d ago",
        "updatedFull": "Apr 7, 2026 · 09:14 UTC",
        "description": "Detects and blocks adversarial prompt patterns including jailbreaks, role-play overrides, and Base64-encoded bypass attempts before they reach any production model invocation.",
        "affectedAssets": 8,
        "relatedAlerts": 4,
        "linkedSimulations": 2,
        "agents": ["CustomerSupport-GPT", "ThreatHunter-AI", "DataPipeline-Orchestrator"],
        "tools": [],
        "dataSources": [],
        "environments": ["Production"],
        "exceptions": ["staging-test-agent-01"],
        "impact": {"blocked": 4, "flagged": 11, "unchanged": 105, "total": 120},
        "history": [
            {"version": "v3", "by": "admin@orbyx.ai",   "when": "Apr 7, 2026 · 09:14",  "change": "Added Base64 payload detection. Confidence threshold raised to 0.92."},
            {"version": "v2", "by": "sec-eng@orbyx.ai", "when": "Mar 28, 2026 · 14:02", "change": "Expanded jailbreak signature library. Added roleplay framing detection."},
            {"version": "v1", "by": "admin@orbyx.ai",   "when": "Mar 12, 2026 · 10:30", "change": "Initial policy created. Basic injection pattern matching."},
        ],
        "logic_code": _PROMPT_GUARD_CODE,
        "logic_language": "rego",
    },
    # … (Tool-Scope, PII-Mask, Write-Approval, Token-Budget, Output-Filter,
    #    Egress-Control, RAG-Retrieval-Limit, Jailbreak-Detect)
    # Full data copied verbatim from the existing store.py _seed() function.
    # Omitted here for brevity — see implementation note below.
]


def seed_policies() -> None:
    """
    Insert default policies if the table is empty.
    Safe to call multiple times (idempotent).
    """
    if list_policies():          # already has rows → skip
        return
    for raw in _SEED_DATA:
        raw["logic"] = _tokenise(raw["logic_code"], raw["logic_language"])
        create_policy_raw(raw)   # bypasses version bumping; stores exact seed data
```

> **Implementation note:** Copy the remaining 8 policy dicts verbatim from `store.py`'s `_seed()` function into `_SEED_DATA`. They are omitted here to avoid repetition — the content is unchanged from the original.

- [ ] **Step 5: Run failing tests**

```bash
python3 -m pytest tests/policies/test_store.py -v
```
Expected: failures because `store.init_db_for_session`, `create_policy_raw` don't exist yet.

- [ ] **Step 6: Commit skeleton**

```bash
git add tests/policies/ policies/seed.py
git commit -m "feat(policies): add seed.py + test skeleton (red)"
```

---

## Task 4 — Rewrite `policies/store.py` (DB-backed, same interface)

This is the core task. The public function signatures are **identical** to today. Only the implementation changes.

**Files:**
- Rewrite: `services/agent-orchestrator-service/policies/store.py`

- [ ] **Step 1: Write all remaining tests before touching store.py**

Add to `tests/policies/test_store.py`:

```python
from policies.models import PolicyCreate, PolicyUpdate


# ── CRUD ─────────────────────────────────────────────────────────────────────

def test_create_and_get(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(
        name="Test", type="prompt-safety", mode="Enforce",
        status="Active", scope="All", owner="ops",
        description="desc", logic_code="allow = true", logic_language="rego",
        agents=[], tools=[], data_sources=[], environments=[], exceptions=[],
    ), actor="test")
    assert p["name"] == "Test"
    assert p["version"] == "v1"

    fetched = store.get_policy(p["id"])
    assert fetched is not None
    assert fetched["id"] == p["id"]


def test_get_missing_returns_none(db_session):
    store.init_db_for_session(db_session)
    assert store.get_policy("no-such-id") is None


def test_list_policies(db_session):
    store.init_db_for_session(db_session)
    store.create_policy(PolicyCreate(name="A", type="privacy",   logic_code=""), actor="t")
    store.create_policy(PolicyCreate(name="B", type="data-access", logic_code=""), actor="t")
    assert len(store.list_policies()) == 2


def test_update_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="X", type="privacy", logic_code=""), actor="t")
    updated = store.update_policy(p["id"], PolicyUpdate(mode="Monitor"), actor="t")
    assert updated["mode"] == "Monitor"
    assert updated["version"] == "v2"          # version bumped
    assert len(updated["history"]) == 2        # v1 + v2 entries


def test_update_missing_returns_none(db_session):
    store.init_db_for_session(db_session)
    assert store.update_policy("ghost", PolicyUpdate(mode="Monitor")) is None


def test_delete_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="Del", type="privacy", logic_code=""), actor="t")
    assert store.delete_policy(p["id"]) is True
    assert store.get_policy(p["id"]) is None


def test_delete_missing_returns_false(db_session):
    store.init_db_for_session(db_session)
    assert store.delete_policy("ghost") is False


def test_duplicate_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="Orig", type="privacy", logic_code="x = 1"), actor="t")
    dup = store.duplicate_policy(p["id"], actor="t")
    assert dup["name"] == "Orig (Copy)"
    assert dup["version"] == "v1"
    assert dup["id"] != p["id"]
    assert dup["logic_code"] == "x = 1"


# ── Version restore ───────────────────────────────────────────────────────────

def test_restore_policy(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="R", type="privacy",
                                         logic_code="original"), actor="t")
    v1 = p["version"]
    store.update_policy(p["id"], PolicyUpdate(logic_code="updated"), actor="t")

    restored = store.restore_policy(p["id"], v1)
    assert restored is not None
    assert restored["logic_code"] == "original"
    assert restored["version"] == "v3"      # v1 → v2 (update) → v3 (restore)


def test_restore_missing_version_returns_none(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="R2", type="privacy",
                                          logic_code="x"), actor="t")
    assert store.restore_policy(p["id"], "v99") is None


def test_list_restorable_versions(db_session):
    store.init_db_for_session(db_session)
    p = store.create_policy(PolicyCreate(name="R3", type="privacy",
                                          logic_code="a"), actor="t")
    store.update_policy(p["id"], PolicyUpdate(logic_code="b"), actor="t")
    versions = store.list_restorable_versions(p["id"])
    assert "v1" in versions
    assert "v2" not in versions   # v2 is current — not restorable to itself
```

- [ ] **Step 2: Run all tests — expect failures**

```bash
python3 -m pytest tests/policies/test_store.py -v 2>&1 | tail -20
```
Expected: ~15 failures / import errors

- [ ] **Step 3: Rewrite `policies/store.py`**

Key design:
- Module-level `_engine` and `_SessionLocal` (None until `init_db()` called)
- `init_db(db_url)` — creates engine + runs `create_all` (dev only)
- `init_db_for_session(session)` — test escape hatch: injects a pre-made Session
- All public functions create a session from `_SessionLocal()`, commit, close
- `_to_dict(orm)` converts `PolicyORM` row → `dict` matching the old store shape
- Rego code constants + `_tokenise` stay in this file (imported by `seed.py`)
- `create_policy_raw(raw_dict)` is an internal helper used only by `seed.py`

```python
"""
policies/store.py
──────────────────
DB-backed policy store — synchronous SQLAlchemy.

Public interface is identical to the previous in-memory implementation.
The only breaking internal change: _seed() is gone; call seed.seed_policies()
from main.py lifespan instead.

Thread safety: SQLAlchemy's Session is not thread-safe. Each call creates a
new Session from _SessionLocal and closes it on exit. This mirrors the old
threading.Lock pattern but via connection pool management.

DB initialisation
─────────────────
Call init_db(db_url) once at startup (FastAPI lifespan).
For tests, use init_db_for_session(session) to inject a pre-made Session.

Supported URL schemes
─────────────────────
  sqlite:///path/to/file.db        — local dev / tests
  sqlite:///:memory:               — in-memory (tests only)
  postgresql+psycopg2://user:pw@host:5432/db  — production
"""
from __future__ import annotations

import copy
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .db_models import PolicyORM
from .models import PolicyCreate, PolicyUpdate

# ── Module-level engine / session factory (set by init_db) ────────────────────
_SessionLocal: Optional[sessionmaker] = None
_test_session: Optional[Session] = None   # injected by init_db_for_session


# ── Initialisation ────────────────────────────────────────────────────────────

def init_db(db_url: str, create_tables: bool = True) -> None:
    """
    Initialise the synchronous engine and session factory.
    Call once from main.py lifespan before any store function is used.
    """
    global _SessionLocal
    from db.base import Base  # local import avoids circular at module load
    engine = create_engine(db_url, echo=False, future=True)
    if create_tables:
        Base.metadata.create_all(engine, checkfirst=True)
    _SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db_for_session(session: Session) -> None:
    """
    Test helper: inject a pre-made Session so all store functions use it.
    Bypasses _SessionLocal entirely — no connection pool needed.
    """
    global _test_session
    _test_session = session


def _get_session() -> Session:
    """Return the active test session, or open a new one from _SessionLocal."""
    if _test_session is not None:
        return _test_session
    if _SessionLocal is None:
        raise RuntimeError("Policy store not initialised — call init_db() first.")
    return _SessionLocal()


def _close(session: Session) -> None:
    """Close session only if it is NOT the injected test session."""
    if session is not _test_session:
        session.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_display() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y")


def _now_full() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")


def _bump_version(current: str) -> str:
    try:
        return f"v{int(current.lstrip('v')) + 1}"
    except ValueError:
        return current + ".1"


def _to_dict(row: PolicyORM) -> dict:
    """Convert a PolicyORM row to the dict shape the router/service expect."""
    return {
        "id":               row.policy_id,
        "name":             row.name,
        "version":          row.version,
        "type":             row.type,
        "mode":             row.mode,
        "status":           row.status,
        "scope":            row.scope,
        "owner":            row.owner,
        "createdBy":        row.created_by,
        "created":          row.created,
        "updated":          row.updated,
        "updatedFull":      row.updated_full,
        "description":      row.description,
        "affectedAssets":   row.affected_assets,
        "relatedAlerts":    row.related_alerts,
        "linkedSimulations":row.linked_sims,
        "agents":           row.agents       or [],
        "tools":            row.tools        or [],
        "dataSources":      row.data_sources or [],
        "environments":     row.environments or [],
        "exceptions":       row.exceptions   or [],
        "impact":           row.impact       or {},
        "history":          row.history      or [],
        "logic":            row.logic        or [],
        "logic_code":       row.logic_code,
        "logic_language":   row.logic_language,
    }


# ── Public CRUD ───────────────────────────────────────────────────────────────

def list_policies() -> list[dict]:
    session = _get_session()
    try:
        rows = session.execute(select(PolicyORM)).scalars().all()
        return [_to_dict(r) for r in rows]
    finally:
        _close(session)


def get_policy(policy_id: str) -> Optional[dict]:
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        return _to_dict(row) if row else None
    finally:
        _close(session)


def create_policy(data: PolicyCreate, actor: str = "api") -> dict:
    pid    = str(uuid.uuid4())[:8]
    now_f  = _now_full()
    now_d  = _now_display()
    logic  = _tokenise(data.logic_code, data.logic_language)
    entry  = {"version": "v1", "by": actor, "when": now_f, "change": "Policy created."}
    snap   = {}

    row = PolicyORM(
        policy_id       = pid,
        name            = data.name,
        version         = "v1",
        type            = data.type,
        mode            = data.mode,
        status          = data.status,
        scope           = data.scope,
        owner           = data.owner,
        created_by      = actor,
        created         = now_d,
        updated         = "just now",
        updated_full    = now_f,
        description     = data.description,
        affected_assets = 0,
        related_alerts  = 0,
        linked_sims     = 0,
        agents          = data.agents,
        tools           = data.tools,
        data_sources    = data.data_sources,
        environments    = data.environments,
        exceptions      = data.exceptions,
        impact          = {"blocked": 0, "flagged": 0, "unchanged": 0, "total": 0},
        history         = [entry],
        logic           = logic,
        logic_code      = data.logic_code,
        logic_language  = data.logic_language,
        snapshots       = snap,
    )
    session = _get_session()
    try:
        session.add(row)
        session.commit()
        result = _to_dict(row)
        # Store v1 snapshot after commit (so row has persisted ID)
        _save_snapshot(policy_id=pid, version="v1", data=result, session=session)
        return result
    finally:
        _close(session)


def update_policy(policy_id: str, data: PolicyUpdate,
                  actor: str = "api") -> Optional[dict]:
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return None

        changed: list[str] = []

        if data.name is not None and data.name != row.name:
            row.name = data.name;  changed.append("name")
        if data.mode is not None and data.mode != row.mode:
            changed.append(f"mode {row.mode} → {data.mode}");  row.mode = data.mode
        if data.status is not None:
            row.status = data.status
        if data.scope is not None:
            row.scope = data.scope
        if data.owner is not None:
            row.owner = data.owner
        if data.description is not None:
            row.description = data.description
        if data.agents is not None:
            row.agents = data.agents
        if data.tools is not None:
            row.tools = data.tools
        if data.data_sources is not None:
            row.data_sources = data.data_sources
        if data.environments is not None:
            row.environments = data.environments
        if data.exceptions is not None:
            row.exceptions = data.exceptions
        if data.logic_code is not None:
            lang = data.logic_language or row.logic_language
            row.logic_code     = data.logic_code
            row.logic_language = lang
            row.logic          = _tokenise(data.logic_code, lang)
            changed.append("logic updated")

        new_ver          = _bump_version(row.version)
        now_f            = _now_full()
        row.version      = new_ver
        row.updated      = "just now"
        row.updated_full = now_f
        summary          = "; ".join(changed) if changed else "Updated."
        history          = list(row.history or [])
        history.insert(0, {"version": new_ver, "by": actor,
                            "when": now_f, "change": summary})
        row.history = history

        # Persist snapshot for new version
        result_dict = _to_dict(row)
        snaps       = dict(row.snapshots or {})
        snaps[new_ver] = deepcopy(result_dict)
        row.snapshots = snaps

        session.commit()
        return result_dict
    finally:
        _close(session)


def delete_policy(policy_id: str) -> bool:
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True
    finally:
        _close(session)


def duplicate_policy(policy_id: str, actor: str = "api") -> Optional[dict]:
    src = get_policy(policy_id)
    if src is None:
        return None
    session = _get_session()
    try:
        now_f = _now_full()
        now_d = _now_display()
        pid   = str(uuid.uuid4())[:8]
        row   = PolicyORM(
            policy_id       = pid,
            name            = f"{src['name']} (Copy)",
            version         = "v1",
            type            = src["type"],
            mode            = "Monitor",
            status          = "Active",
            scope           = src["scope"],
            owner           = src["owner"],
            created_by      = actor,
            created         = now_d,
            updated         = "just now",
            updated_full    = now_f,
            description     = src["description"],
            affected_assets = 0,
            related_alerts  = 0,
            linked_sims     = 0,
            agents          = list(src.get("agents", [])),
            tools           = list(src.get("tools", [])),
            data_sources    = list(src.get("dataSources", [])),
            environments    = list(src.get("environments", [])),
            exceptions      = list(src.get("exceptions", [])),
            impact          = {"blocked": 0, "flagged": 0, "unchanged": 0, "total": 0},
            history         = [{"version": "v1", "by": actor, "when": now_f,
                                 "change": f"Duplicated from {src['name']} {src['version']}."}],
            logic           = list(src.get("logic", [])),
            logic_code      = src.get("logic_code", ""),
            logic_language  = src.get("logic_language", "rego"),
            snapshots       = {},
        )
        session.add(row)
        session.commit()
        result = _to_dict(row)
        _save_snapshot(policy_id=pid, version="v1", data=result, session=session)
        return result
    finally:
        _close(session)


# ── Restore ───────────────────────────────────────────────────────────────────

def restore_policy(policy_id: str, target_version: str,
                   actor: str = "api") -> Optional[dict]:
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return None
        snaps = row.snapshots or {}
        snap  = snaps.get(target_version)
        if snap is None:
            return None

        restored    = deepcopy(snap)
        new_ver     = _bump_version(row.version)
        now_f       = _now_full()
        history     = list(row.history or [])
        history.insert(0, {"version": new_ver, "by": actor,
                            "when": now_f,
                            "change": f"Restored from {target_version}."})

        # Apply snapshot fields back to ORM row
        row.name         = restored.get("name", row.name)
        row.type         = restored.get("type", row.type)
        row.mode         = restored.get("mode", row.mode)
        row.scope        = restored.get("scope", row.scope)
        row.owner        = restored.get("owner", row.owner)
        row.description  = restored.get("description", row.description)
        row.agents       = restored.get("agents", row.agents)
        row.tools        = restored.get("tools", row.tools)
        row.data_sources = restored.get("dataSources", row.data_sources)
        row.environments = restored.get("environments", row.environments)
        row.exceptions   = restored.get("exceptions", row.exceptions)
        row.logic        = restored.get("logic", row.logic)
        row.logic_code   = restored.get("logic_code", row.logic_code)
        row.logic_language = restored.get("logic_language", row.logic_language)
        row.version      = new_ver
        row.updated      = "just now"
        row.updated_full = now_f
        row.history      = history
        new_snaps        = dict(row.snapshots)
        new_snaps[new_ver] = deepcopy(_to_dict(row))
        row.snapshots    = new_snaps

        session.commit()
        return _to_dict(row)
    finally:
        _close(session)


def list_restorable_versions(policy_id: str) -> list[str]:
    session = _get_session()
    try:
        row = session.get(PolicyORM, policy_id)
        if row is None:
            return []
        current = row.version
        return [v for v in (row.snapshots or {}) if v != current]
    finally:
        _close(session)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _save_snapshot(policy_id: str, version: str, data: dict,
                   session: Session) -> None:
    """Add a snapshot entry to an existing row (called after create/duplicate)."""
    row = session.get(PolicyORM, policy_id)
    if row is None:
        return
    snaps = dict(row.snapshots or {})
    snaps[version] = deepcopy(data)
    row.snapshots  = snaps
    session.commit()


def create_policy_raw(raw: dict, actor: str = "seed") -> dict:
    """
    Insert a policy from a raw dict — used ONLY by seed.py.
    Bypasses version bumping; stores the exact version from the raw data.
    """
    session = _get_session()
    try:
        row = PolicyORM(
            policy_id       = raw["id"],
            name            = raw["name"],
            version         = raw["version"],
            type            = raw["type"],
            mode            = raw["mode"],
            status          = raw["status"],
            scope           = raw.get("scope", ""),
            owner           = raw.get("owner", ""),
            created_by      = raw.get("createdBy", actor),
            created         = raw.get("created", _now_display()),
            updated         = raw.get("updated", "just now"),
            updated_full    = raw.get("updatedFull", _now_full()),
            description     = raw.get("description", ""),
            affected_assets = raw.get("affectedAssets", 0),
            related_alerts  = raw.get("relatedAlerts", 0),
            linked_sims     = raw.get("linkedSimulations", 0),
            agents          = raw.get("agents", []),
            tools           = raw.get("tools", []),
            data_sources    = raw.get("dataSources", []),
            environments    = raw.get("environments", []),
            exceptions      = raw.get("exceptions", []),
            impact          = raw.get("impact", {}),
            history         = raw.get("history", []),
            logic           = raw.get("logic", []),
            logic_code      = raw.get("logic_code", ""),
            logic_language  = raw.get("logic_language", "rego"),
            snapshots       = {},
        )
        session.add(row)
        session.commit()
        return _to_dict(row)
    finally:
        _close(session)


# ── Rego / JSON tokeniser (also imported by seed.py) ─────────────────────────
# [Keep the existing _REGO_KW, _JSON_KW, and _tokenise() function verbatim]

# ── Source code constants (imported by seed.py) ───────────────────────────────
# [Keep all _PROMPT_GUARD_CODE … _JAILBREAK_DETECT_CODE constants verbatim]
```

> **Implementation note:** Copy `_REGO_KW`, `_JSON_KW`, `_tokenise()`, and all `_*_CODE` constants verbatim from the current `store.py`. Remove `_store`, `_lock`, `_snapshots`, `_seed()` and the `_seed()` auto-call at the bottom.

- [ ] **Step 4: Run all tests — expect green**

```bash
python3 -m pytest tests/policies/test_store.py -v
```
Expected: all 15 tests pass

- [ ] **Step 5: Commit**
```bash
git add policies/store.py policies/seed.py tests/policies/
git commit -m "feat(policies): DB-backed store with full test suite (green)"
```

---

## Task 5 — Wire into FastAPI lifespan (`main.py`)

**Files:**
- Modify: `services/agent-orchestrator-service/main.py`

- [ ] **Step 1: Add policy DB init + seed to lifespan**

In the `lifespan()` function, after the existing SQLite engine is created and `seed_demo` is called, add:

```python
    # -- Policy store --------------------------------------------------------
    # Supports SQLite (dev) or PostgreSQL (prod) via POLICY_DB_URL env var.
    # Falls back to the same SQLite file as the main sessions DB.
    policy_db_url = os.getenv(
        "POLICY_DB_URL",
        f"sqlite:///{DB_PATH}"           # sync driver — no +aiosqlite
    )
    from policies import store as policy_store
    from policies.seed import seed_policies
    policy_store.init_db(policy_db_url, create_tables=True)
    seed_policies()
    logger.info("Policy store initialised: %s", policy_db_url)
```

> **Why a separate `POLICY_DB_URL`?** The main DB engine uses `sqlite+aiosqlite` (async). The policy store uses plain `sqlite` (sync). They can point to the same file path — SQLAlchemy and SQLite handle mixed access safely for the read-heavy policy store. In production, set `POLICY_DB_URL=postgresql+psycopg2://...` to point at Postgres.

- [ ] **Step 2: Verify startup smoke test**

```bash
cd services/agent-orchestrator-service
python3 -c "
import asyncio
from main import create_app
app = create_app()
# If lifespan fails, this raises an exception
print('App created OK')
"
```
Expected: `App created OK`

- [ ] **Step 3: Verify the API returns 9 policies**

```bash
# Start the server and curl it (or use httpx in a test)
python3 -m pytest tests/test_startup_wiring.py -v
```

- [ ] **Step 4: Commit**
```bash
git add main.py
git commit -m "feat(policies): wire init_db + seed into FastAPI lifespan"
```

---

## Task 6 — Add PostgreSQL driver to requirements

**Files:**
- Modify: `services/agent-orchestrator-service/requirements.txt`
- Modify: `services/agent-orchestrator-service/Dockerfile` (if it exists)

- [ ] **Step 1: Add psycopg2-binary**

Add after the existing `# ─── Database ───` block:

```
psycopg2-binary>=2.9.9          # Sync PostgreSQL driver for policy store
```

- [ ] **Step 2: Verify install**

```bash
pip install psycopg2-binary --break-system-packages
python3 -c "import psycopg2; print('psycopg2', psycopg2.__version__)"
```

- [ ] **Step 3: Commit**
```bash
git add requirements.txt
git commit -m "feat(policies): add psycopg2-binary for PostgreSQL support"
```

---

## Task 7 — Docker Compose env var for production Postgres

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add `POLICY_DB_URL` to agent-orchestrator env block**

In `docker-compose.yml`, under `agent-orchestrator` → `environment`, add:

```yaml
      POLICY_DB_URL: postgresql+psycopg2://spm_rw:${SPM_DB_PASSWORD:-spmpass}@spm-db:5432/spm
```

> This reuses the existing `spm-db` PostgreSQL container — no new DB service needed. The `policies` table lives alongside the `spm` tables, which is fine since all schema changes go through Alembic.

- [ ] **Step 2: Run migration against Postgres (on the spm-db container)**

```bash
docker compose run --rm agent-orchestrator \
  sh -c "POLICY_DB_URL=postgresql+psycopg2://spm_rw:spmpass@spm-db:5432/spm \
         alembic upgrade head"
```

- [ ] **Step 3: Rebuild and verify**

```bash
docker compose up -d --build agent-orchestrator
curl -s http://localhost:8000/api/v1/policies | python3 -m json.tool | head -30
```
Expected: 9 policies returned as JSON.

- [ ] **Step 4: Commit**
```bash
git add docker-compose.yml
git commit -m "feat(policies): wire POLICY_DB_URL into docker-compose for postgres"
```

---

## Task 8 — Verification pass

- [ ] **Run full test suite**

```bash
cd services/agent-orchestrator-service
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all existing tests pass + all new policy tests pass, no regressions.

- [ ] **Smoke test every API endpoint**

```bash
BASE=http://localhost:8000/api/v1/policies

# List
curl -s $BASE | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d), 'policies')"

# Get one
ID=$(curl -s $BASE | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
curl -s $BASE/$ID | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['name'], d['version'])"

# Create
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"name":"Smoke","type":"privacy","mode":"Monitor","status":"Active","scope":"","owner":"","description":"","logic_code":"","logic_language":"rego","agents":[],"tools":[],"data_sources":[],"environments":[],"exceptions":[]}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('Created:', d['id'])"

# Update
curl -s -X PUT $BASE/$ID -H "Content-Type: application/json" -d '{"mode":"Draft"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('Updated mode:', d['mode'], 'version:', d['version'])"

# Duplicate
curl -s -X POST $BASE/$ID/duplicate | python3 -c "import json,sys; d=json.load(sys.stdin); print('Dup:', d['name'])"

# Validate
curl -s -X POST $BASE/$ID/validate | python3 -c "import json,sys; d=json.load(sys.stdin); print('Valid:', d['valid'])"

# Restorable versions
curl -s $BASE/$ID/restorable | python3 -m json.tool
```

- [ ] **Verify data survives container restart**

```bash
docker compose restart agent-orchestrator
curl -s http://localhost:8000/api/v1/policies | python3 -c "import json,sys; print(len(json.load(sys.stdin)), 'policies after restart')"
```
Expected: 9+ policies (seed data was not re-inserted since table is non-empty).

- [ ] **Final commit**
```bash
git add -A
git commit -m "feat(policies): postgres persistence — migration, store, seed, tests ✅"
```

---

## Summary of changes

| File | Change |
|------|--------|
| `policies/db_models.py` | **NEW** — `PolicyORM` SQLAlchemy model |
| `policies/seed.py` | **NEW** — 9 default policies seed function |
| `policies/store.py` | **REWRITE** — same interface, DB-backed |
| `alembic/versions/002_add_policies_table.py` | **NEW** — migration |
| `alembic/env.py` | **+2 lines** — import `PolicyORM` |
| `main.py` | **+5 lines** — call `init_db` + `seed_policies` |
| `requirements.txt` | **+1 line** — `psycopg2-binary` |
| `docker-compose.yml` | **+1 line** — `POLICY_DB_URL` env |
| `tests/policies/` | **NEW** — 15 deterministic DB tests |

**Unchanged:** `policies/router.py`, `policies/service.py`, `policies/models.py`, all existing tests.
