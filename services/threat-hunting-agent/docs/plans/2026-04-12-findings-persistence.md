# Findings Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every structured `Finding` dict from `run_hunt()` to the `threat_findings` DB table and expose a full repository/service layer for create, read, filter, status-update, and case-linkage operations.

**Architecture:** The `agent-orchestrator-service` owns the DB; it already has a thin `ThreatFindingORM` model that needs 14 new columns. The `threat-hunting-agent` gains a `FindingsService` HTTP client that calls the orchestrator's `/api/v1/threat-findings` endpoint after every hunt. Case creation remains optional — a finding is always persisted regardless of `should_open_case`.

**Tech Stack:** SQLAlchemy async ORM (AsyncSession), aiosqlite (test), asyncpg (prod), Alembic `render_as_batch=True`, Pydantic v2, httpx (agent → orchestrator HTTP), pytest-asyncio.

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `services/agent-orchestrator-service/db/models.py` | Add 14 new columns to `ThreatFindingORM` |
| Create | `services/agent-orchestrator-service/alembic/versions/005_expand_threat_findings.py` | ALTER TABLE migration |
| Modify | `services/agent-orchestrator-service/threat_findings/schemas.py` | Expand `FindingRecord`, `CreateFindingRequest`; add `FindingFilter` |
| Modify | `services/agent-orchestrator-service/threat_findings/models.py` | Add `get_by_id`, `list_findings`, `update_status`, `attach_case` |
| Modify | `services/agent-orchestrator-service/threat_findings/service.py` | Add `persist_finding_from_dict`, `link_case`, `mark_status` |
| Create | `services/agent-orchestrator-service/tests/threat_findings/test_repository.py` | 12 integration tests against SQLite in-memory |
| Modify | `services/agent-orchestrator-service/tests/threat_findings/test_service.py` | Tests for new service methods |
| Modify | `services/threat-hunting-agent/tools/case_tool.py` | Expand `create_threat_finding` payload with all Finding fields |
| Create | `services/threat-hunting-agent/service/__init__.py` | Package init |
| Create | `services/threat-hunting-agent/service/findings_service.py` | `FindingsService` HTTP client |
| Modify | `services/threat-hunting-agent/consumer/kafka_consumer.py` | Call `persist_fn` after each hunt |
| Modify | `services/threat-hunting-agent/app.py` | Wire `FindingsService` into consumer |
| Create | `services/threat-hunting-agent/tests/test_findings_service.py` | 5 unit tests with mocked HTTP |

---

## Task 1: Expand ORM model — add 14 new columns to `ThreatFindingORM`

**Files:**
- Modify: `services/agent-orchestrator-service/db/models.py`

- [ ] **Step 1: Write the failing test (ensures new columns exist in ORM)**

  Create `services/agent-orchestrator-service/tests/db/test_threat_finding_orm_schema.py`:

  ```python
  """Smoke-test: every new column must exist on ThreatFindingORM."""
  from db.models import ThreatFindingORM

  NEW_COLUMNS = {
      "confidence", "risk_score", "hypothesis", "asset", "environment",
      "correlated_events", "correlated_findings", "triggered_policies",
      "policy_signals", "recommended_actions", "should_open_case",
      "case_id", "source", "updated_at", "timestamp",
  }

  def test_new_columns_on_orm():
      cols = {c.key for c in ThreatFindingORM.__table__.columns}
      missing = NEW_COLUMNS - cols
      assert not missing, f"Missing ORM columns: {missing}"
  ```

- [ ] **Step 2: Run it — expect FAIL**

  ```bash
  cd services/agent-orchestrator-service
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/db/test_threat_finding_orm_schema.py -v
  ```

  Expected: `FAILED — Missing ORM columns: {...}`

- [ ] **Step 3: Implement — add columns to `ThreatFindingORM`**

  In `db/models.py`, extend `ThreatFindingORM.__table_args__` and add columns after `closed_at`:

  ```python
  from sqlalchemy import Boolean  # add to existing import

  class ThreatFindingORM(Base):
      __tablename__ = "threat_findings"

      id          = Column(String, primary_key=True)
      batch_hash  = Column(String, nullable=False, unique=True)
      title       = Column(String, nullable=False)
      severity    = Column(String, nullable=False)
      description = Column(Text,   nullable=False)
      evidence    = Column(Text,   nullable=False)   # JSON list
      ttps        = Column(Text,   nullable=False, default="[]")
      tenant_id   = Column(String, nullable=False)
      status      = Column(String, nullable=False, default="open")
      created_at  = Column(String, nullable=False)
      closed_at   = Column(String, nullable=True)

      # ── New fields (all nullable for backward compat) ─────────────────
      timestamp           = Column(String,  nullable=True)   # Finding.timestamp (UTC ISO)
      confidence          = Column(Float,   nullable=True)
      risk_score          = Column(Float,   nullable=True)
      hypothesis          = Column(Text,    nullable=True)
      asset               = Column(String,  nullable=True)
      environment         = Column(String,  nullable=True)
      correlated_events   = Column(Text,    nullable=True)   # JSON list
      correlated_findings = Column(Text,    nullable=True)   # JSON list
      triggered_policies  = Column(Text,    nullable=True)   # JSON list
      policy_signals      = Column(Text,    nullable=True)   # JSON list of dicts
      recommended_actions = Column(Text,    nullable=True)   # JSON list
      should_open_case    = Column(Boolean, nullable=True)
      case_id             = Column(String,  nullable=True)
      source              = Column(String,  nullable=True)
      updated_at          = Column(String,  nullable=True)

      __table_args__ = (
          Index("ix_threat_findings_tenant",   "tenant_id", "created_at"),
          Index("ix_threat_findings_severity", "severity",  "status"),
      )
  ```

  Also add `Boolean` to the SQLAlchemy import at the top of `db/models.py`.

- [ ] **Step 4: Run the test — expect PASS**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/db/test_threat_finding_orm_schema.py -v
  ```

  Expected: `PASSED`

- [ ] **Step 5: Commit**

  ```bash
  cd services/agent-orchestrator-service
  git add db/models.py tests/db/test_threat_finding_orm_schema.py
  git commit -m "feat(orchestrator): expand ThreatFindingORM with 14 new Finding fields"
  ```

---

## Task 2: Alembic migration 005 — ALTER TABLE to add new columns

**Files:**
- Create: `services/agent-orchestrator-service/alembic/versions/005_expand_threat_findings.py`

- [ ] **Step 1: Write migration**

  ```python
  """Expand threat_findings with full Finding schema fields.

  Revision ID: 005
  Revises: 004
  Create Date: 2026-04-12
  """
  from __future__ import annotations
  from alembic import op
  import sqlalchemy as sa

  revision: str = "005"
  down_revision: str | None = "004"
  branch_labels = None
  depends_on = None

  _NEW_COLS = [
      ("timestamp",           sa.String,  True),
      ("confidence",          sa.Float,   True),
      ("risk_score",          sa.Float,   True),
      ("hypothesis",          sa.Text,    True),
      ("asset",               sa.String,  True),
      ("environment",         sa.String,  True),
      ("correlated_events",   sa.Text,    True),
      ("correlated_findings", sa.Text,    True),
      ("triggered_policies",  sa.Text,    True),
      ("policy_signals",      sa.Text,    True),
      ("recommended_actions", sa.Text,    True),
      ("should_open_case",    sa.Boolean, True),
      ("case_id",             sa.String,  True),
      ("source",              sa.String,  True),
      ("updated_at",          sa.String,  True),
  ]

  def upgrade() -> None:
      with op.batch_alter_table("threat_findings") as batch_op:
          for col_name, col_type, nullable in _NEW_COLS:
              batch_op.add_column(sa.Column(col_name, col_type, nullable=nullable))

  def downgrade() -> None:
      with op.batch_alter_table("threat_findings") as batch_op:
          for col_name, _, _ in _NEW_COLS:
              batch_op.drop_column(col_name)
  ```

  **Important:** `render_as_batch=True` is already set in `alembic/env.py` — no changes needed there.

- [ ] **Step 2: Verify migration runs without error (dry-run via upgrade)**

  ```bash
  cd services/agent-orchestrator-service
  # Use a temp SQLite DB for the smoke-test
  ALCHEMY_DATABASE_URL="sqlite:////tmp/test_migrate_005.db" \
    PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" \
    alembic upgrade head 2>&1 | tail -20
  ```

  Expected: no tracebacks; `Running upgrade 004 -> 005` line appears.

- [ ] **Step 3: Commit**

  ```bash
  git add alembic/versions/005_expand_threat_findings.py
  git commit -m "feat(orchestrator): alembic migration 005 — expand threat_findings columns"
  ```

---

## Task 3: Expand schemas — `FindingRecord`, `CreateFindingRequest`, `FindingFilter`

**Files:**
- Modify: `services/agent-orchestrator-service/threat_findings/schemas.py`

- [ ] **Step 1: Write failing test**

  ```python
  # tests/threat_findings/test_schemas.py
  from threat_findings.schemas import FindingRecord, CreateFindingRequest, FindingFilter

  def test_finding_record_new_fields():
      rec = FindingRecord(id="x", batch_hash="h", title="T", severity="high",
                          description="d", evidence=[], ttps=[], tenant_id="t1")
      assert rec.confidence is None
      assert rec.risk_score is None
      assert rec.hypothesis is None
      assert rec.should_open_case is False
      assert rec.status == "open"

  def test_create_finding_request_accepts_new_fields():
      req = CreateFindingRequest(
          title="T", severity="high", description="d", tenant_id="t1",
          batch_hash="h", confidence=0.8, risk_score=0.9,
          hypothesis="H", evidence=[], recommended_actions=["block"],
      )
      assert req.confidence == 0.8

  def test_finding_filter_defaults():
      f = FindingFilter()
      assert f.severity is None
      assert f.limit == 50
  ```

- [ ] **Step 2: Run — expect FAIL** (FindingFilter not yet importable)

  ```bash
  cd services/agent-orchestrator-service
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/threat_findings/test_schemas.py -v
  ```

- [ ] **Step 3: Implement expanded schemas**

  Replace `threat_findings/schemas.py` in full:

  > **Backward compat note:** `FindingRecord.evidence` changes from `Dict[str, Any]` to `List[Any]`
  > to match `Finding.evidence: List[str]`. `CreateFindingRequest.evidence` also changes.
  > The existing `create_finding()` service method passes `evidence=req.evidence` — after this
  > change it will pass a list, which is correct. Any integration test that currently passes
  > a dict to `evidence` must be updated to pass a list instead.

  ```python
  from __future__ import annotations
  from dataclasses import dataclass, field
  from datetime import datetime, timezone
  from typing import Any, Dict, List, Optional
  from pydantic import BaseModel, Field


  def _utcnow() -> str:
      return datetime.now(timezone.utc).isoformat()


  @dataclass
  class FindingRecord:
      id:           str
      batch_hash:   str
      title:        str
      severity:     str
      description:  str
      evidence:     List[Any]   # was Dict; list matches Finding.evidence: List[str]
      ttps:         List[str]
      tenant_id:    str
      status:       str = "open"
      created_at:   str = field(default_factory=_utcnow)
      closed_at:    Optional[str] = None
      deduplicated: bool = False     # transient — not persisted

      # ── New Finding fields ────────────────────────────────────────────
      timestamp:           Optional[str]        = None
      confidence:          Optional[float]      = None
      risk_score:          Optional[float]      = None
      hypothesis:          Optional[str]        = None
      asset:               Optional[str]        = None
      environment:         Optional[str]        = None
      correlated_events:   Optional[List[str]]  = None
      correlated_findings: Optional[List[str]]  = None
      triggered_policies:  Optional[List[str]]  = None
      policy_signals:      Optional[List[Any]]  = None
      recommended_actions: Optional[List[str]]  = None
      should_open_case:    bool                 = False
      case_id:             Optional[str]        = None
      source:              Optional[str]        = None
      updated_at:          Optional[str]        = None


  class CreateFindingRequest(BaseModel):
      title:       str   = Field(..., min_length=1)
      severity:    str   = Field(..., pattern="^(low|medium|high|critical)$")
      description: str   = Field(..., min_length=1)
      evidence:    List[Any] = Field(default_factory=list)
      ttps:        List[str] = Field(default_factory=list)
      tenant_id:   str   = Field(..., min_length=1)
      batch_hash:  str   = Field(..., min_length=1)

      # ── New fields (all optional for backward compat) ─────────────────
      timestamp:           Optional[str]       = None
      confidence:          Optional[float]     = Field(None, ge=0.0, le=1.0)
      risk_score:          Optional[float]     = Field(None, ge=0.0, le=1.0)
      hypothesis:          Optional[str]       = None
      asset:               Optional[str]       = None
      environment:         Optional[str]       = None
      correlated_events:   Optional[List[str]] = None
      correlated_findings: Optional[List[str]] = None
      triggered_policies:  Optional[List[str]] = None
      policy_signals:      Optional[List[Any]] = None
      recommended_actions: Optional[List[str]] = None
      should_open_case:    bool                = False
      case_id:             Optional[str]       = None
      source:              Optional[str]       = None


  @dataclass
  class FindingFilter:
      severity:   Optional[str]  = None
      status:     Optional[str]  = None
      asset:      Optional[str]  = None
      tenant_id:  Optional[str]  = None
      has_case:   Optional[bool] = None
      from_ts:    Optional[str]  = None
      to_ts:      Optional[str]  = None
      limit:      int            = 50
      offset:     int            = 0


  class FindingResponse(BaseModel):
      id:           str
      title:        str
      severity:     str
      status:       str
      created_at:   str
      deduplicated: bool = False
      confidence:   Optional[float] = None
      risk_score:   Optional[float] = None
      should_open_case: bool = False

      @classmethod
      def from_record(cls, rec: FindingRecord) -> "FindingResponse":
          return cls(
              id=rec.id, title=rec.title, severity=rec.severity,
              status=rec.status, created_at=rec.created_at,
              deduplicated=rec.deduplicated,
              confidence=rec.confidence,
              risk_score=rec.risk_score,
              should_open_case=rec.should_open_case,
          )
  ```

- [ ] **Step 4: Run — expect PASS**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/threat_findings/test_schemas.py -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add threat_findings/schemas.py tests/threat_findings/test_schemas.py
  git commit -m "feat(orchestrator): expand FindingRecord + CreateFindingRequest + add FindingFilter"
  ```

---

## Task 4: Expand repository — `get_by_id`, `list_findings`, `update_status`, `attach_case`

**Files:**
- Modify: `services/agent-orchestrator-service/threat_findings/models.py`
- Create: `services/agent-orchestrator-service/tests/threat_findings/test_repository.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/threat_findings/test_repository.py`:

  ```python
  """Integration tests for ThreatFindingRepository against SQLite in-memory."""
  from __future__ import annotations
  import json
  import pytest
  import pytest_asyncio
  from threat_findings.models import ThreatFindingRepository
  from threat_findings.schemas import FindingRecord, FindingFilter


  def _rec(
      id: str = "id1",
      batch_hash: str = "bh1",
      severity: str = "high",
      status: str = "open",
      tenant_id: str = "t1",
      should_open_case: bool = False,
  ) -> FindingRecord:
      return FindingRecord(
          id=id, batch_hash=batch_hash, title="Test Finding",
          severity=severity, description="desc",
          evidence=["ev1"], ttps=["T1234"], tenant_id=tenant_id,
          status=status, confidence=0.8, risk_score=0.9,
          hypothesis="H", should_open_case=should_open_case,
      )


  class TestInsertAndFetch:
      @pytest.mark.asyncio
      async def test_get_by_batch_hash_returns_record(self, db_session):
          repo = ThreatFindingRepository(db_session)
          await repo.insert(_rec())
          result = await repo.get_by_batch_hash("bh1")
          assert result is not None
          assert result.title == "Test Finding"

      @pytest.mark.asyncio
      async def test_get_by_id_returns_record(self, db_session):
          repo = ThreatFindingRepository(db_session)
          await repo.insert(_rec())
          result = await repo.get_by_id("id1")
          assert result is not None
          assert result.id == "id1"

      @pytest.mark.asyncio
      async def test_get_by_id_unknown_returns_none(self, db_session):
          repo = ThreatFindingRepository(db_session)
          result = await repo.get_by_id("nope")
          assert result is None

      @pytest.mark.asyncio
      async def test_new_fields_round_trip(self, db_session):
          repo = ThreatFindingRepository(db_session)
          rec = _rec(should_open_case=True)
          rec.policy_signals = [{"type": "gap_detected", "policy": "p1", "confidence": 0.7}]
          rec.recommended_actions = ["block", "escalate"]
          await repo.insert(rec)
          fetched = await repo.get_by_id("id1")
          assert fetched.confidence == 0.8
          assert fetched.should_open_case is True
          assert fetched.policy_signals[0]["type"] == "gap_detected"
          assert "block" in fetched.recommended_actions


  class TestListFindings:
      @pytest.mark.asyncio
      async def test_list_returns_all_without_filter(self, db_session):
          repo = ThreatFindingRepository(db_session)
          await repo.insert(_rec(id="a", batch_hash="bh_a"))
          await repo.insert(_rec(id="b", batch_hash="bh_b", severity="low"))
          results = await repo.list_findings(FindingFilter())
          assert len(results) == 2

      @pytest.mark.asyncio
      async def test_list_filter_by_severity(self, db_session):
          repo = ThreatFindingRepository(db_session)
          await repo.insert(_rec(id="a", batch_hash="bh_a", severity="high"))
          await repo.insert(_rec(id="b", batch_hash="bh_b", severity="low"))
          results = await repo.list_findings(FindingFilter(severity="high"))
          assert len(results) == 1
          assert results[0].severity == "high"

      @pytest.mark.asyncio
      async def test_list_filter_by_status(self, db_session):
          repo = ThreatFindingRepository(db_session)
          await repo.insert(_rec(id="a", batch_hash="bh_a", status="open"))
          await repo.insert(_rec(id="b", batch_hash="bh_b", status="resolved"))
          results = await repo.list_findings(FindingFilter(status="open"))
          assert len(results) == 1

      @pytest.mark.asyncio
      async def test_list_limit_respected(self, db_session):
          repo = ThreatFindingRepository(db_session)
          for i in range(5):
              await repo.insert(_rec(id=f"id{i}", batch_hash=f"bh{i}"))
          results = await repo.list_findings(FindingFilter(limit=2))
          assert len(results) == 2


  class TestUpdateStatus:
      @pytest.mark.asyncio
      async def test_update_status(self, db_session):
          repo = ThreatFindingRepository(db_session)
          await repo.insert(_rec())
          await repo.update_status("id1", "investigating")
          updated = await repo.get_by_id("id1")
          assert updated.status == "investigating"

      @pytest.mark.asyncio
      async def test_update_status_noop_unknown_id(self, db_session):
          repo = ThreatFindingRepository(db_session)
          # Should not raise
          await repo.update_status("nonexistent", "resolved")


  class TestAttachCase:
      @pytest.mark.asyncio
      async def test_attach_case(self, db_session):
          repo = ThreatFindingRepository(db_session)
          await repo.insert(_rec())
          await repo.attach_case("id1", "case-abc")
          updated = await repo.get_by_id("id1")
          assert updated.case_id == "case-abc"
  ```

- [ ] **Step 2: Run — expect FAIL** (methods not yet implemented)

  ```bash
  cd services/agent-orchestrator-service
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/threat_findings/test_repository.py -v
  ```

- [ ] **Step 3: Implement expanded repository**

  Replace `threat_findings/models.py` in full:

  ```python
  from __future__ import annotations
  import json
  import logging
  from typing import List, Optional
  from sqlalchemy import select, update
  from sqlalchemy.ext.asyncio import AsyncSession
  from db.models import ThreatFindingORM
  from threat_findings.schemas import FindingFilter, FindingRecord

  logger = logging.getLogger(__name__)


  def _json_loads_safe(value: Optional[str], default):
      """Safely decode a JSON string; return `default` on None or error."""
      if value is None:
          return default
      try:
          return json.loads(value)
      except (json.JSONDecodeError, TypeError):
          return default


  def _orm_to_record(row: ThreatFindingORM) -> FindingRecord:
      return FindingRecord(
          id=row.id,
          batch_hash=row.batch_hash,
          title=row.title,
          severity=row.severity,
          description=row.description,
          evidence=_json_loads_safe(row.evidence, []),
          ttps=_json_loads_safe(row.ttps, []),
          tenant_id=row.tenant_id,
          status=row.status,
          created_at=row.created_at,
          closed_at=row.closed_at,
          # New fields
          timestamp=row.timestamp,
          confidence=row.confidence,
          risk_score=row.risk_score,
          hypothesis=row.hypothesis,
          asset=row.asset,
          environment=row.environment,
          correlated_events=_json_loads_safe(row.correlated_events, None),
          correlated_findings=_json_loads_safe(row.correlated_findings, None),
          triggered_policies=_json_loads_safe(row.triggered_policies, None),
          policy_signals=_json_loads_safe(row.policy_signals, None),
          recommended_actions=_json_loads_safe(row.recommended_actions, None),
          should_open_case=bool(row.should_open_case) if row.should_open_case is not None else False,
          case_id=row.case_id,
          source=row.source,
          updated_at=row.updated_at,
      )


  class ThreatFindingRepository:
      def __init__(self, session: AsyncSession) -> None:
          self._session = session

      async def get_by_batch_hash(self, batch_hash: str) -> Optional[FindingRecord]:
          stmt = select(ThreatFindingORM).where(ThreatFindingORM.batch_hash == batch_hash)
          result = await self._session.execute(stmt)
          row = result.scalar_one_or_none()
          return _orm_to_record(row) if row else None

      async def get_by_id(self, finding_id: str) -> Optional[FindingRecord]:
          stmt = select(ThreatFindingORM).where(ThreatFindingORM.id == finding_id)
          result = await self._session.execute(stmt)
          row = result.scalar_one_or_none()
          return _orm_to_record(row) if row else None

      async def insert(self, rec: FindingRecord) -> None:
          orm = ThreatFindingORM(
              id=rec.id,
              batch_hash=rec.batch_hash,
              title=rec.title,
              severity=rec.severity,
              description=rec.description,
              evidence=json.dumps(rec.evidence if rec.evidence is not None else []),
              ttps=json.dumps(rec.ttps if rec.ttps is not None else []),
              tenant_id=rec.tenant_id,
              status=rec.status,
              created_at=rec.created_at,
              closed_at=rec.closed_at,
              # New fields
              timestamp=rec.timestamp,
              confidence=rec.confidence,
              risk_score=rec.risk_score,
              hypothesis=rec.hypothesis,
              asset=rec.asset,
              environment=rec.environment,
              correlated_events=json.dumps(rec.correlated_events) if rec.correlated_events is not None else None,
              correlated_findings=json.dumps(rec.correlated_findings) if rec.correlated_findings is not None else None,
              triggered_policies=json.dumps(rec.triggered_policies) if rec.triggered_policies is not None else None,
              policy_signals=json.dumps(rec.policy_signals) if rec.policy_signals is not None else None,
              recommended_actions=json.dumps(rec.recommended_actions) if rec.recommended_actions is not None else None,
              should_open_case=rec.should_open_case,
              case_id=rec.case_id,
              source=rec.source,
              updated_at=rec.updated_at,
          )
          self._session.add(orm)
          await self._session.commit()

      async def list_findings(self, filters: FindingFilter) -> List[FindingRecord]:
          stmt = select(ThreatFindingORM)
          if filters.severity:
              stmt = stmt.where(ThreatFindingORM.severity == filters.severity)
          if filters.status:
              stmt = stmt.where(ThreatFindingORM.status == filters.status)
          if filters.asset:
              stmt = stmt.where(ThreatFindingORM.asset == filters.asset)
          if filters.tenant_id:
              stmt = stmt.where(ThreatFindingORM.tenant_id == filters.tenant_id)
          if filters.has_case is True:
              stmt = stmt.where(ThreatFindingORM.case_id.isnot(None))
          if filters.has_case is False:
              stmt = stmt.where(ThreatFindingORM.case_id.is_(None))
          if filters.from_ts:
              stmt = stmt.where(ThreatFindingORM.created_at >= filters.from_ts)
          if filters.to_ts:
              stmt = stmt.where(ThreatFindingORM.created_at <= filters.to_ts)
          stmt = stmt.limit(filters.limit).offset(filters.offset)
          result = await self._session.execute(stmt)
          return [_orm_to_record(row) for row in result.scalars()]

      async def update_status(self, finding_id: str, new_status: str) -> None:
          from datetime import datetime, timezone
          stmt = (
              update(ThreatFindingORM)
              .where(ThreatFindingORM.id == finding_id)
              .values(
                  status=new_status,
                  updated_at=datetime.now(timezone.utc).isoformat(),
              )
          )
          await self._session.execute(stmt)
          await self._session.commit()

      async def attach_case(self, finding_id: str, case_id: str) -> None:
          stmt = (
              update(ThreatFindingORM)
              .where(ThreatFindingORM.id == finding_id)
              .values(case_id=case_id)
          )
          await self._session.execute(stmt)
          await self._session.commit()
  ```

- [ ] **Step 4: Run — expect PASS**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/threat_findings/test_repository.py -v
  ```

  Expected: 12 tests PASSED

- [ ] **Step 5: Commit**

  ```bash
  git add threat_findings/models.py tests/threat_findings/test_repository.py
  git commit -m "feat(orchestrator): expand ThreatFindingRepository with get_by_id, list_findings, update_status, attach_case"
  ```

---

## Task 5: Expand service — `persist_finding_from_dict`, `link_case`, `mark_status`

**Files:**
- Modify: `services/agent-orchestrator-service/threat_findings/service.py`
- Modify: `services/agent-orchestrator-service/tests/threat_findings/test_service.py`

- [ ] **Step 1: Write failing tests**

  Add to `tests/threat_findings/test_service.py` (create the file if it doesn't exist):

  ```python
  """Tests for ThreatFindingsService."""
  from __future__ import annotations
  import pytest
  from unittest.mock import AsyncMock, MagicMock
  from threat_findings.service import ThreatFindingsService
  from threat_findings.schemas import FindingRecord


  def _repo(existing=None):
      repo = MagicMock()
      repo.get_by_batch_hash = AsyncMock(return_value=existing)
      repo.insert = AsyncMock()
      repo.update_status = AsyncMock()
      repo.attach_case = AsyncMock()
      return repo


  class TestPersistFindingFromDict:
      @pytest.mark.asyncio
      async def test_persists_new_finding(self):
          svc = ThreatFindingsService()
          repo = _repo(existing=None)
          finding_dict = {
              "finding_id": "fid1",
              "timestamp": "2026-04-12T00:00:00+00:00",
              "severity": "high",
              "confidence": 0.8,
              "risk_score": 0.9,
              "title": "Test",
              "hypothesis": "H",
              "evidence": ["ev1"],
              "correlated_events": [],
              "triggered_policies": [],
              "policy_signals": [],
              "recommended_actions": ["block"],
              "should_open_case": True,
          }
          rec = await svc.persist_finding_from_dict(finding_dict, "t1", repo)
          assert rec.id == "fid1"
          assert rec.should_open_case is True
          repo.insert.assert_called_once()

      @pytest.mark.asyncio
      async def test_deduplicates_existing(self):
          existing_rec = FindingRecord(
              id="old", batch_hash="bh", title="T", severity="low",
              description="d", evidence=[], ttps=[], tenant_id="t1",
          )
          svc = ThreatFindingsService()
          repo = _repo(existing=existing_rec)
          finding_dict = {
              "finding_id": "new", "timestamp": "2026-04-12T00:00:00+00:00",
              "severity": "high", "confidence": 0.8, "risk_score": 0.9,
              "title": "T", "hypothesis": "H", "evidence": [],
              "correlated_events": [], "triggered_policies": [],
              "policy_signals": [], "recommended_actions": [], "should_open_case": False,
          }
          rec = await svc.persist_finding_from_dict(finding_dict, "t1", repo)
          assert rec.deduplicated is True
          repo.insert.assert_not_called()

      @pytest.mark.asyncio
      async def test_link_case_calls_attach(self):
          svc = ThreatFindingsService()
          repo = _repo()
          await svc.link_case("fid1", "case-x", repo)
          repo.attach_case.assert_called_once_with("fid1", "case-x")

      @pytest.mark.asyncio
      async def test_mark_status_calls_update(self):
          svc = ThreatFindingsService()
          repo = _repo()
          await svc.mark_status("fid1", "investigating", repo)
          repo.update_status.assert_called_once_with("fid1", "investigating")
  ```

- [ ] **Step 2: Run — expect FAIL**

  ```bash
  cd services/agent-orchestrator-service
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/threat_findings/test_service.py -v
  ```

- [ ] **Step 3: Implement expanded service**

  Append the following new methods to `ThreatFindingsService` in `threat_findings/service.py` (keep existing `create_finding` intact):

  ```python
  import json
  import hashlib
  from datetime import datetime, timezone

  # Add to top-level imports in service.py
  # from threat_findings.schemas import FindingRecord, FindingFilter  (add FindingFilter)


  def _finding_batch_hash(tenant_id: str, title: str, evidence: list) -> str:
      canonical = json.dumps(
          {"tenant_id": tenant_id, "title": title, "evidence": evidence},
          sort_keys=True, default=str,
      )
      return hashlib.sha256(canonical.encode()).hexdigest()


  # Add these methods inside ThreatFindingsService:

  async def persist_finding_from_dict(
      self,
      finding_dict: dict,
      tenant_id: str,
      repo,   # ThreatFindingRepository
  ) -> FindingRecord:
      """
      Persist a Finding dict (from run_hunt) without auto-opening a Case.
      Deduplicates by batch_hash.  Returns the FindingRecord (new or existing).
      """
      title = finding_dict.get("title", "")
      evidence = finding_dict.get("evidence", [])
      batch_hash = _finding_batch_hash(tenant_id, title, evidence)

      existing = await repo.get_by_batch_hash(batch_hash)
      if existing:
          logger.info("Deduplicated finding batch_hash=%s", batch_hash)
          existing.deduplicated = True
          return existing

      rec = FindingRecord(
          id=finding_dict.get("finding_id", str(uuid4())),
          batch_hash=batch_hash,
          title=title,
          severity=finding_dict.get("severity", "low"),
          description=finding_dict.get("hypothesis", ""),
          evidence=evidence,
          ttps=finding_dict.get("triggered_policies", []),
          tenant_id=tenant_id,
          status="open",
          timestamp=finding_dict.get("timestamp"),
          confidence=finding_dict.get("confidence"),
          risk_score=finding_dict.get("risk_score"),
          hypothesis=finding_dict.get("hypothesis"),
          asset=finding_dict.get("asset"),
          environment=finding_dict.get("environment"),
          correlated_events=finding_dict.get("correlated_events"),
          correlated_findings=finding_dict.get("correlated_findings"),
          triggered_policies=finding_dict.get("triggered_policies"),
          policy_signals=finding_dict.get("policy_signals"),
          recommended_actions=finding_dict.get("recommended_actions"),
          should_open_case=bool(finding_dict.get("should_open_case", False)),
          source="threat-hunting-agent",
          updated_at=datetime.now(timezone.utc).isoformat(),
      )
      await repo.insert(rec)
      logger.info(
          "Persisted finding id=%s tenant=%s severity=%s should_open_case=%s",
          rec.id, rec.tenant_id, rec.severity, rec.should_open_case,
      )
      return rec

  async def link_case(
      self,
      finding_id: str,
      case_id: str,
      repo,  # ThreatFindingRepository
  ) -> None:
      """Associate an existing Case with a Finding."""
      await repo.attach_case(finding_id, case_id)
      logger.info("Linked finding_id=%s to case_id=%s", finding_id, case_id)

  async def mark_status(
      self,
      finding_id: str,
      new_status: str,
      repo,  # ThreatFindingRepository
  ) -> None:
      """Transition finding to open | investigating | resolved."""
      assert new_status in ("open", "investigating", "resolved"), \
          f"Invalid status: {new_status}"
      await repo.update_status(finding_id, new_status)
      logger.info("Finding %s → status=%s", finding_id, new_status)
  ```

  Also add `from uuid import uuid4` to top of `service.py` if not already present.

- [ ] **Step 4: Run — expect PASS**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/threat_findings/test_service.py -v
  ```

- [ ] **Step 5: Run full orchestrator test suite**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest --tb=short -q
  ```

  Expected: all existing tests still PASS

- [ ] **Step 6: Commit**

  ```bash
  git add threat_findings/service.py tests/threat_findings/test_service.py
  git commit -m "feat(orchestrator): add persist_finding_from_dict, link_case, mark_status to ThreatFindingsService"
  ```

---

## Task 6: Expand agent `create_threat_finding` — send all Finding fields

**Files:**
- Modify: `services/threat-hunting-agent/tools/case_tool.py`

The existing `create_threat_finding` sends only `title, severity, description, evidence, ttps, tenant_id, batch_hash`.  We need to forward the full Finding payload so the orchestrator can persist all fields.

- [ ] **Step 1: Write failing test**

  Add to `services/threat-hunting-agent/tests/test_case_tool.py` (create if needed):

  ```python
  """Tests for case_tool extended payload."""
  import json
  from unittest.mock import MagicMock
  from tools.case_tool import create_threat_finding, set_http_client


  def _fake_client(status=201):
      client = MagicMock()
      resp = MagicMock()
      resp.status_code = status
      resp.raise_for_status = MagicMock()
      resp.json.return_value = {"id": "fid1", "deduplicated": False}
      client.get.return_value = MagicMock(
          raise_for_status=MagicMock(),
          json=MagicMock(return_value={"token": "tok"}),
      )
      client.post.return_value = resp
      return client


  def test_create_threat_finding_sends_new_fields():
      fake = _fake_client()
      set_http_client(fake)
      result = create_threat_finding(
          tenant_id="t1",
          title="Test",
          severity="high",
          description="desc",
          evidence=["ev1"],
          ttps=["T1234"],
          confidence=0.8,
          risk_score=0.9,
          hypothesis="H",
          recommended_actions=["block"],
          should_open_case=True,
      )
      payload = json.loads(fake.post.call_args.kwargs["json"]
                           if "json" in fake.post.call_args.kwargs
                           else fake.post.call_args[1]["json"])
      assert payload["confidence"] == 0.8
      assert payload["should_open_case"] is True
      assert payload["recommended_actions"] == ["block"]
  ```

- [ ] **Step 2: Run — expect FAIL** (signature doesn't accept new kwargs)

  ```bash
  cd services/threat-hunting-agent
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/test_case_tool.py::test_create_threat_finding_sends_new_fields -v
  ```

- [ ] **Step 3: Expand `create_threat_finding` signature and payload**

  In `tools/case_tool.py`, replace `create_threat_finding` with:

  ```python
  def create_threat_finding(
      tenant_id: str,
      title: str,
      severity: str,
      description: str,
      evidence: list,
      ttps: Optional[List[str]] = None,
      # ── New optional fields (all from Finding) ────────────────────────
      timestamp: Optional[str] = None,
      confidence: Optional[float] = None,
      risk_score: Optional[float] = None,
      hypothesis: Optional[str] = None,
      asset: Optional[str] = None,
      environment: Optional[str] = None,
      correlated_events: Optional[List[str]] = None,
      correlated_findings: Optional[List[str]] = None,
      triggered_policies: Optional[List[str]] = None,
      policy_signals: Optional[List[dict]] = None,
      recommended_actions: Optional[List[str]] = None,
      should_open_case: bool = False,
      source: Optional[str] = None,
  ) -> str:
      """Submit a structured threat finding to the orchestrator."""
      if severity not in ("low", "medium", "high", "critical"):
          return json.dumps({"error": f"Invalid severity '{severity}'."})
      try:
          token = _fetch_dev_token()
      except Exception as exc:
          return json.dumps({"error": f"auth failure: {exc}"})

      # _compute_batch_hash is already defined in case_tool.py (line 136 of current file)
      # It accepts any JSON-serializable evidence value; evidence is List[str] from Finding
      batch_hash = _compute_batch_hash(tenant_id, title, evidence)
      payload = {
          "title": title,
          "severity": severity,
          "description": description,
          "evidence": evidence,
          "tenant_id": tenant_id,
          "ttps": ttps or [],
          "batch_hash": batch_hash,
          # New fields
          "timestamp": timestamp,
          "confidence": confidence,
          "risk_score": risk_score,
          "hypothesis": hypothesis,
          "asset": asset,
          "environment": environment,
          "correlated_events": correlated_events,
          "correlated_findings": correlated_findings,
          "triggered_policies": triggered_policies,
          "policy_signals": policy_signals,
          "recommended_actions": recommended_actions,
          "should_open_case": should_open_case,
          "source": source or "threat-hunting-agent",
      }
      # Remove None values to keep payload clean
      payload = {k: v for k, v in payload.items() if v is not None}

      try:
          client = _get_client()
          resp = client.post(
              f"{_orchestrator_url}/api/v1/threat-findings",
              json=payload,
              headers={"Authorization": f"Bearer {token}"},
          )
          resp.raise_for_status()
          return json.dumps(resp.json())
      except httpx.HTTPStatusError as exc:
          logger.error("create_threat_finding HTTP %d: %s",
                       exc.response.status_code, exc.response.text)
          return json.dumps({"error": f"HTTP {exc.response.status_code}"})
      except Exception as exc:
          logger.exception("create_threat_finding failed: %s", exc)
          return json.dumps({"error": str(exc)})
  ```

- [ ] **Step 4: Run — expect PASS**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/test_case_tool.py -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  cd services/threat-hunting-agent
  git add tools/case_tool.py tests/test_case_tool.py
  git commit -m "feat(agent): expand create_threat_finding to forward all Finding fields to orchestrator"
  ```

---

## Task 7: Agent `FindingsService` — HTTP client to persist every finding

**Files:**
- Create: `services/threat-hunting-agent/service/__init__.py`
- Create: `services/threat-hunting-agent/service/findings_service.py`
- Create: `services/threat-hunting-agent/tests/test_findings_service.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/test_findings_service.py`:

  ```python
  """Unit tests for FindingsService — all HTTP calls are mocked."""
  import json
  import pytest
  from unittest.mock import MagicMock, patch
  from service.findings_service import FindingsService


  def _minimal_finding() -> dict:
      return {
          "finding_id": "fid1",
          "timestamp": "2026-04-12T00:00:00+00:00",
          "severity": "high",
          "confidence": 0.8,
          "risk_score": 0.9,
          "title": "Test Finding",
          "hypothesis": "H",
          "evidence": ["ev1"],
          "correlated_events": [],
          "triggered_policies": [],
          "policy_signals": [],
          "recommended_actions": ["block"],
          "should_open_case": True,
      }


  class TestFindingsService:
      def _svc(self):
          return FindingsService(
              orchestrator_url="http://orchestrator:8094",
              dev_token_url="http://api:8080/dev-token",
          )

      def test_persist_finding_calls_orchestrator(self):
          svc = self._svc()
          mock_resp = MagicMock()
          mock_resp.json.return_value = {"id": "fid1", "deduplicated": False}
          mock_resp.raise_for_status = MagicMock()
          with patch.object(svc._client, "get") as mock_get, \
               patch.object(svc._client, "post") as mock_post:
              mock_get.return_value = MagicMock(
                  raise_for_status=MagicMock(),
                  json=MagicMock(return_value={"token": "tok"}),
              )
              mock_post.return_value = mock_resp
              result = svc.persist_finding(_minimal_finding(), "t1")
          assert result["id"] == "fid1"
          mock_post.assert_called_once()

      def test_persist_finding_returns_fallback_on_http_error(self):
          svc = self._svc()
          with patch.object(svc._client, "get") as mock_get, \
               patch.object(svc._client, "post") as mock_post:
              mock_get.return_value = MagicMock(
                  raise_for_status=MagicMock(),
                  json=MagicMock(return_value={"token": "tok"}),
              )
              mock_post.side_effect = Exception("connection refused")
              result = svc.persist_finding(_minimal_finding(), "t1")
          assert "error" in result

      def test_persist_finding_sends_should_open_case(self):
          svc = self._svc()
          captured = {}
          mock_resp = MagicMock()
          mock_resp.json.return_value = {"id": "x", "deduplicated": False}
          mock_resp.raise_for_status = MagicMock()
          def capture_post(url, json=None, headers=None):
              captured["payload"] = json
              return mock_resp
          with patch.object(svc._client, "get") as mock_get, \
               patch.object(svc._client, "post", side_effect=capture_post):
              mock_get.return_value = MagicMock(
                  raise_for_status=MagicMock(),
                  json=MagicMock(return_value={"token": "tok"}),
              )
              svc.persist_finding(_minimal_finding(), "t1")
          assert captured["payload"]["should_open_case"] is True

      def test_persist_many_calls_persist_for_each(self):
          svc = self._svc()
          findings = [_minimal_finding(), {**_minimal_finding(), "finding_id": "fid2"}]
          with patch.object(svc, "persist_finding", return_value={"id": "x"}) as mock_p:
              results = svc.persist_many(findings, "t1")
          assert mock_p.call_count == 2
          assert len(results) == 2

      def test_link_case_posts_to_correct_url(self):
          svc = self._svc()
          mock_resp = MagicMock()
          mock_resp.raise_for_status = MagicMock()
          mock_resp.json.return_value = {}
          with patch.object(svc._client, "get") as mock_get, \
               patch.object(svc._client, "patch") as mock_patch:
              mock_get.return_value = MagicMock(
                  raise_for_status=MagicMock(),
                  json=MagicMock(return_value={"token": "tok"}),
              )
              mock_patch.return_value = mock_resp
              svc.link_case("fid1", "case-x")
          mock_patch.assert_called_once()
          url = mock_patch.call_args[0][0]
          assert "fid1" in url
  ```

- [ ] **Step 2: Run — expect FAIL** (module doesn't exist yet)

  ```bash
  cd services/threat-hunting-agent
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/test_findings_service.py -v
  ```

- [ ] **Step 3: Implement `service/__init__.py` and `service/findings_service.py`**

  Create `service/__init__.py` (empty):
  ```python
  ```

  Create `service/findings_service.py`:

  ```python
  """
  service/findings_service.py
  ────────────────────────────
  HTTP client that persists every Finding dict to the orchestrator's
  /api/v1/threat-findings endpoint.

  Uses a synchronous httpx.Client (thread-safe; one instance per app).
  Case linkage and status updates are sent via PATCH calls to the same service.
  """
  from __future__ import annotations

  import json
  import logging
  from typing import Any, Dict, List, Optional

  import httpx

  logger = logging.getLogger(__name__)


  class FindingsService:
      """Stateless singleton; one instance on app.state."""

      def __init__(
          self,
          orchestrator_url: str = "http://agent-orchestrator:8094",
          dev_token_url: str = "http://api:8080/dev-token",
          timeout: float = 10.0,
      ) -> None:
          self._orchestrator_url = orchestrator_url.rstrip("/")
          self._dev_token_url = dev_token_url
          self._client = httpx.Client(timeout=timeout)

      def _fetch_token(self) -> str:
          resp = self._client.get(self._dev_token_url)
          resp.raise_for_status()
          data = resp.json()
          token = data.get("token") or data.get("access_token")
          if not token:
              raise ValueError(f"dev-token endpoint returned: {list(data.keys())}")
          return token

      def persist_finding(self, finding_dict: Dict[str, Any], tenant_id: str) -> dict:
          """
          POST finding_dict to /api/v1/threat-findings.
          Returns the response JSON dict, or {"error": ...} on failure.
          Never raises.
          """
          try:
              token = self._fetch_token()
          except Exception as exc:
              logger.warning("FindingsService: token fetch failed: %s", exc)
              return {"error": f"auth: {exc}"}

          import hashlib
          evidence = finding_dict.get("evidence", [])
          title = finding_dict.get("title", "")
          canonical = json.dumps(
              {"tenant_id": tenant_id, "title": title, "evidence": evidence},
              sort_keys=True, default=str,
          )
          batch_hash = hashlib.sha256(canonical.encode()).hexdigest()

          payload = {
              "title": title,
              "severity": finding_dict.get("severity", "low"),
              "description": finding_dict.get("hypothesis", ""),
              "evidence": evidence,
              "ttps": finding_dict.get("triggered_policies", []),
              "tenant_id": tenant_id,
              "batch_hash": batch_hash,
              # Full Finding fields
              "timestamp": finding_dict.get("timestamp"),
              "confidence": finding_dict.get("confidence"),
              "risk_score": finding_dict.get("risk_score"),
              "hypothesis": finding_dict.get("hypothesis"),
              "asset": finding_dict.get("asset"),
              "environment": finding_dict.get("environment"),
              "correlated_events": finding_dict.get("correlated_events"),
              "correlated_findings": finding_dict.get("correlated_findings"),
              "triggered_policies": finding_dict.get("triggered_policies"),
              "policy_signals": finding_dict.get("policy_signals"),
              "recommended_actions": finding_dict.get("recommended_actions"),
              "should_open_case": bool(finding_dict.get("should_open_case", False)),
              "source": "threat-hunting-agent",
          }
          # Remove None values
          payload = {k: v for k, v in payload.items() if v is not None}

          try:
              resp = self._client.post(
                  f"{self._orchestrator_url}/api/v1/threat-findings",
                  json=payload,
                  headers={"Authorization": f"Bearer {token}"},
              )
              resp.raise_for_status()
              data = resp.json()
              logger.info(
                  "FindingsService: persisted id=%s deduplicated=%s",
                  data.get("id"), data.get("deduplicated"),
              )
              return data
          except Exception as exc:
              logger.exception("FindingsService.persist_finding failed: %s", exc)
              return {"error": str(exc)}

      def persist_many(
          self, findings: List[Dict[str, Any]], tenant_id: str
      ) -> List[dict]:
          """Persist a list of findings; continues on individual errors."""
          return [self.persist_finding(f, tenant_id) for f in findings]

      def link_case(self, finding_id: str, case_id: str) -> dict:
          """PATCH /api/v1/threat-findings/{finding_id}/case."""
          try:
              token = self._fetch_token()
              resp = self._client.patch(
                  f"{self._orchestrator_url}/api/v1/threat-findings/{finding_id}/case",
                  json={"case_id": case_id},
                  headers={"Authorization": f"Bearer {token}"},
              )
              resp.raise_for_status()
              return resp.json()
          except Exception as exc:
              logger.exception("FindingsService.link_case failed: %s", exc)
              return {"error": str(exc)}

      def mark_status(self, finding_id: str, new_status: str) -> dict:
          """PATCH /api/v1/threat-findings/{finding_id}/status."""
          try:
              token = self._fetch_token()
              resp = self._client.patch(
                  f"{self._orchestrator_url}/api/v1/threat-findings/{finding_id}/status",
                  json={"status": new_status},
                  headers={"Authorization": f"Bearer {token}"},
              )
              resp.raise_for_status()
              return resp.json()
          except Exception as exc:
              logger.exception("FindingsService.mark_status failed: %s", exc)
              return {"error": str(exc)}
  ```

- [ ] **Step 4: Run — expect PASS**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/test_findings_service.py -v
  ```

  Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

  ```bash
  git add service/__init__.py service/findings_service.py tests/test_findings_service.py
  git commit -m "feat(agent): add FindingsService HTTP client for orchestrator persistence"
  ```

---

## Task 8: Wire `FindingsService` into Kafka consumer and app startup

**Files:**
- Modify: `services/threat-hunting-agent/consumer/kafka_consumer.py`
- Modify: `services/threat-hunting-agent/app.py`

- [ ] **Step 1: Write failing test for consumer wiring**

  Add to `tests/test_kafka_consumer.py`:

  ```python
  class TestPersistFn:
      def test_persist_fn_called_after_hunt(self):
          persisted = []
          thc = _make_thc([], batch_window_sec=9999,
                          persist_fn=lambda t, f: persisted.append((t, f)))
          thc._queues["t1"].append({"event_id": "e1"})
          thc._stop_event.set()
          thc._fire_hunts()
          assert len(persisted) == 1
          assert persisted[0][0] == "t1"

      def test_persist_fn_none_does_not_crash(self):
          thc = _make_thc([], batch_window_sec=9999, persist_fn=None)
          thc._queues["t1"].append({"event_id": "e1"})
          thc._stop_event.set()
          thc._fire_hunts()  # should not raise
  ```

  Also update `_make_thc` to accept `persist_fn`:

  ```python
  def _make_thc(
      messages: list,
      hunt_fn=None,
      batch_window_sec: int = 60,
      queue_max: int = 10,
      persist_fn=None,
  ) -> ThreatHuntConsumer:
      hunt_called: List[tuple] = []

      def default_hunt(tenant_id, events):
          hunt_called.append((tenant_id, events))
          return {"title": "ok", "severity": "low", "finding_id": "f1"}

      thc = ThreatHuntConsumer(
          kafka_bootstrap="localhost:9092",
          tenant_list=["t1", "t2"],
          hunt_agent=hunt_fn or default_hunt,
          batch_window_sec=batch_window_sec,
          queue_max=queue_max,
          consumer_factory=lambda: _make_consumer(messages),
          persist_fn=persist_fn,
      )
      thc._hunt_called = hunt_called
      return thc
  ```

- [ ] **Step 2: Run — expect FAIL**

  ```bash
  cd services/threat-hunting-agent
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest tests/test_kafka_consumer.py::TestPersistFn -v
  ```

- [ ] **Step 3: Add `persist_fn` to `ThreatHuntConsumer`**

  In `consumer/kafka_consumer.py`, update `__init__` signature:

  ```python
  def __init__(
      self,
      kafka_bootstrap: str,
      tenant_list: list,
      hunt_agent: Callable,
      batch_window_sec: int = 60,
      queue_max: int = 500,
      consumer_factory: Optional[Callable] = None,
      persist_fn: Optional[Callable] = None,   # NEW
  ) -> None:
      ...
      self._persist_fn = persist_fn
  ```

  In `_fire_hunts`, after the `finding = self._hunt_agent(...)` call:

  ```python
  finding = self._hunt_agent(tenant_id, events)
  if isinstance(finding, dict):
      logger.info(
          "Hunt complete: tenant=%s finding_id=%s severity=%s should_open_case=%s",
          tenant_id, finding.get("finding_id"), finding.get("severity"),
          finding.get("should_open_case"),
      )
      if self._persist_fn is not None:
          try:
              self._persist_fn(tenant_id, finding)
          except Exception as persist_exc:
              logger.exception(
                  "persist_fn failed tenant=%s: %s", tenant_id, persist_exc
              )
  else:
      logger.info("Hunt complete: tenant=%s summary_len=%d",
                  tenant_id, len(str(finding)))
  ```

- [ ] **Step 4: Wire `FindingsService` in `app.py`**

  In `app.py` lifespan, after building the agent and before starting the Kafka consumer, add:

  ```python
  from service.findings_service import FindingsService  # top of file

  # -- Findings persistence service ----------------------------------------
  findings_svc = FindingsService(
      orchestrator_url=settings.orchestrator_url,
      dev_token_url=f"{settings.platform_api_url}/dev-token",
  )
  app.state.findings_svc = findings_svc
  logger.info("FindingsService configured: orchestrator=%s", settings.orchestrator_url)

  # -- Kafka consumer ----------------------------------------------------------
  def _persist(tenant_id: str, finding: dict) -> None:
      findings_svc.persist_finding(finding, tenant_id)

  consumer = ThreatHuntConsumer(
      kafka_bootstrap=settings.kafka_bootstrap_servers,
      tenant_list=settings.tenant_list,
      hunt_agent=_hunt,
      batch_window_sec=settings.hunt_batch_window_sec,
      queue_max=settings.hunt_queue_max,
      persist_fn=_persist,   # NEW
  )
  ```

- [ ] **Step 5: Run all agent tests**

  ```bash
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest --tb=short -q
  ```

  Expected: all 127+ tests PASS

- [ ] **Step 6: Commit**

  ```bash
  git add consumer/kafka_consumer.py app.py tests/test_kafka_consumer.py
  git commit -m "feat(agent): wire FindingsService.persist_finding into ThreatHuntConsumer after each hunt"
  ```

---

## Task 9: Full test run — both services

- [ ] **Step 1: Run orchestrator full suite**

  ```bash
  cd services/agent-orchestrator-service
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest --tb=short -q
  ```

  Expected: all tests PASS (including new repository + service tests)

- [ ] **Step 2: Run agent full suite**

  ```bash
  cd services/threat-hunting-agent
  PATH="$PATH:/sessions/fervent-kind-dirac/.local/bin" pytest --tb=short -q
  ```

  Expected: all tests PASS (including new FindingsService + consumer tests)

- [ ] **Step 3: Final integration commit**

  ```bash
  cd services/threat-hunting-agent
  git add -p  # review any unstaged changes
  git commit -m "chore: final wiring — findings persistence end-to-end complete"
  ```

---

## Summary of Contracts Preserved

- `run_hunt()` return type unchanged (`-> dict`) — no callers broken
- `create_finding()` in orchestrator service unchanged — existing API consumers unaffected
- All new `CreateFindingRequest` fields are optional — existing callers that omit them continue to work
- `ThreatFindingORM` new columns are all `nullable=True` — migration is backward compatible with rows written by migration 004
- `ThreatHuntConsumer` `persist_fn` defaults to `None` — existing tests pass without modification
