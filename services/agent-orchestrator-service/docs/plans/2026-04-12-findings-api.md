# Findings Service API Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a REST API for the Alerts/Findings UI: list, detail, status mutation, case linkage, and bulk query — all backed by the existing `ThreatFindingsService` + `ThreatFindingRepository`.

**Architecture:** A new `api/findings_router.py` (prefix `/api/v1/findings`) delegates all work through `ThreatFindingsService`; no direct DB access from routes. Three new service methods (`get_finding_by_id`, `list_findings`, `count_findings`) are added. `FindingFilter` gains `min_risk_score` and `sort_by` for filtering and optional sorting.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, httpx AsyncClient (tests), pytest-asyncio.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `threat_findings/schemas.py` | Add `min_risk_score: Optional[float]` and `sort_by: Optional[str]` to `FindingFilter` |
| Modify | `threat_findings/models.py` | Add `count_findings()` method; add `min_risk_score` + `sort_by` clauses to `list_findings()` |
| Modify | `threat_findings/service.py` | Add `get_finding_by_id()`, `list_findings()`, `count_findings()` |
| Create | `api/__init__.py` | Package marker |
| Create | `api/findings_schemas.py` | API-facing Pydantic models: `FindingDetailResponse`, `FindingListItem`, `FindingListResponse`, `UpdateStatusRequest`, `LinkCaseRequest`, `QueryFindingsRequest` |
| Create | `api/findings_router.py` | Five REST endpoints, RBAC guards, trace-id headers, 404/400 handling |
| Modify | `main.py` | Import and register `findings_router` |
| Create | `tests/findings/__init__.py` | Package marker |
| Create | `tests/findings/conftest.py` | `client` fixture with dependency overrides |
| Create | `tests/findings/test_findings_api.py` | 10 router integration tests (mocked service) |

---

## Task 1: Extend `FindingFilter` + `ThreatFindingRepository`

**Files:**
- Modify: `threat_findings/schemas.py`
- Modify: `threat_findings/models.py`
- Test: `tests/threat_findings/test_repository.py` (add 3 tests)

### Why first?
The repository changes are the deepest layer; later tasks depend on them.

- [ ] **Step 1: Write three failing tests in `tests/threat_findings/test_repository.py`**

Append to the existing file:

```python
@pytest.mark.asyncio
async def test_list_findings_min_risk_score_filter(db_session):
    """Only findings with risk_score >= threshold are returned."""
    repo = ThreatFindingRepository(db_session)
    low = FindingRecord(
        id="f-low", batch_hash="h-low", title="Low", severity="low",
        description="d", evidence=[], ttps=[], tenant_id="t1",
        risk_score=0.2,
    )
    high = FindingRecord(
        id="f-high", batch_hash="h-high", title="High", severity="high",
        description="d", evidence=[], ttps=[], tenant_id="t1",
        risk_score=0.9,
    )
    await repo.insert(low)
    await repo.insert(high)
    results = await repo.list_findings(FindingFilter(min_risk_score=0.5))
    assert len(results) == 1
    assert results[0].id == "f-high"


@pytest.mark.asyncio
async def test_count_findings_matches_list_findings(db_session):
    """count_findings returns the same total as len(list_findings(...))."""
    repo = ThreatFindingRepository(db_session)
    for i in range(3):
        rec = FindingRecord(
            id=f"fc-{i}", batch_hash=f"hc-{i}", title=f"T{i}",
            severity="medium", description="d", evidence=[], ttps=[],
            tenant_id="tenant-count",
        )
        await repo.insert(rec)
    f = FindingFilter(tenant_id="tenant-count")
    count = await repo.count_findings(f)
    items = await repo.list_findings(f)
    assert count == len(items) == 3


@pytest.mark.asyncio
async def test_list_findings_sort_by_risk_score_desc(db_session):
    """sort_by='risk_score' returns highest risk_score first."""
    repo = ThreatFindingRepository(db_session)
    for score, fid in [(0.1, "s-low"), (0.8, "s-high"), (0.5, "s-mid")]:
        await repo.insert(FindingRecord(
            id=fid, batch_hash=f"hs-{fid}", title=fid, severity="low",
            description="d", evidence=[], ttps=[], tenant_id="t-sort",
            risk_score=score,
        ))
    results = await repo.list_findings(
        FindingFilter(tenant_id="t-sort", sort_by="risk_score")
    )
    scores = [r.risk_score for r in results]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: Run the three new tests to verify they FAIL**

```bash
cd services/agent-orchestrator-service
pytest tests/threat_findings/test_repository.py::test_list_findings_min_risk_score_filter \
       tests/threat_findings/test_repository.py::test_count_findings_matches_list_findings \
       tests/threat_findings/test_repository.py::test_list_findings_sort_by_risk_score_desc -v
```

Expected: 3 FAILs (AttributeError / TypeError on missing fields/methods)

- [ ] **Step 3: Add `min_risk_score` and `sort_by` to `FindingFilter` in `threat_findings/schemas.py`**

In the `FindingFilter` dataclass, append two new optional fields **after** `offset`:

```python
@dataclass
class FindingFilter:
    severity:       Optional[str]   = None
    status:         Optional[str]   = None
    asset:          Optional[str]   = None
    tenant_id:      Optional[str]   = None
    has_case:       Optional[bool]  = None
    from_ts:        Optional[str]   = None
    to_ts:          Optional[str]   = None
    limit:          int             = 50
    offset:         int             = 0
    # New fields
    min_risk_score: Optional[float] = None
    sort_by:        Optional[str]   = None   # "risk_score" | "timestamp" | None (default: created_at DESC)
```

- [ ] **Step 4: Extend `list_findings` and add `count_findings` in `threat_findings/models.py`**

Add the `Float` import to the top-of-file SQLAlchemy imports (already present via `ThreatFindingORM`; no change needed — `ThreatFindingORM.risk_score` is `Float`).

Replace the body of `list_findings` and add a new `count_findings` method:

```python
from sqlalchemy import select, update, func

# --- replace list_findings ---
async def list_findings(self, filters: FindingFilter) -> List[FindingRecord]:
    stmt = self._apply_filters(select(ThreatFindingORM), filters)
    # Sorting
    if filters.sort_by == "risk_score":
        stmt = stmt.order_by(ThreatFindingORM.risk_score.desc().nullslast())
    elif filters.sort_by == "timestamp":
        stmt = stmt.order_by(ThreatFindingORM.timestamp.desc().nullslast())
    else:
        stmt = stmt.order_by(ThreatFindingORM.created_at.desc())
    stmt = stmt.limit(filters.limit).offset(filters.offset)
    result = await self._session.execute(stmt)
    return [_orm_to_record(row) for row in result.scalars()]

# --- new method ---
async def count_findings(self, filters: FindingFilter) -> int:
    stmt = self._apply_filters(
        select(func.count()).select_from(ThreatFindingORM), filters
    )
    result = await self._session.execute(stmt)
    return result.scalar_one()

# --- private helper (add BEFORE list_findings) ---
def _apply_filters(self, stmt, filters: FindingFilter):
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
    if filters.min_risk_score is not None:
        stmt = stmt.where(ThreatFindingORM.risk_score >= filters.min_risk_score)
    return stmt
```

**Important:** Remove the inline filter clauses from the old `list_findings` body (they now live in `_apply_filters`). Also add `func` to the `from sqlalchemy import ...` line.

- [ ] **Step 5: Run the three new tests to verify they PASS**

```bash
pytest tests/threat_findings/test_repository.py::test_list_findings_min_risk_score_filter \
       tests/threat_findings/test_repository.py::test_count_findings_matches_list_findings \
       tests/threat_findings/test_repository.py::test_list_findings_sort_by_risk_score_desc -v
```

Expected: 3 PASSes

- [ ] **Step 6: Run the full repository test suite to confirm no regressions**

```bash
pytest tests/threat_findings/test_repository.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add threat_findings/schemas.py threat_findings/models.py \
        tests/threat_findings/test_repository.py
git commit -m "feat: extend FindingFilter with min_risk_score/sort_by; add count_findings to repo"
```

---

## Task 2: Extend `ThreatFindingsService` with read methods

**Files:**
- Modify: `threat_findings/service.py`
- Test: `tests/threat_findings/test_service.py` (add 3 tests)

### Why separate from Task 1?
The service layer sits above the repo; keeping concerns separate makes each diff reviewable on its own.

- [ ] **Step 1: Write three failing tests in `tests/threat_findings/test_service.py`**

Append to the existing file:

```python
@pytest.mark.asyncio
async def test_get_finding_by_id_returns_record(db_session):
    repo = ThreatFindingRepository(db_session)
    await repo.insert(FindingRecord(
        id="svc-1", batch_hash="sv-h1", title="SvcTest", severity="high",
        description="d", evidence=[], ttps=[], tenant_id="t1",
    ))
    svc = ThreatFindingsService()
    rec = await svc.get_finding_by_id("svc-1", repo)
    assert rec is not None
    assert rec.id == "svc-1"


@pytest.mark.asyncio
async def test_get_finding_by_id_missing_returns_none(db_session):
    repo = ThreatFindingRepository(db_session)
    svc = ThreatFindingsService()
    rec = await svc.get_finding_by_id("does-not-exist", repo)
    assert rec is None


@pytest.mark.asyncio
async def test_list_and_count_findings(db_session):
    repo = ThreatFindingRepository(db_session)
    for i in range(4):
        await repo.insert(FindingRecord(
            id=f"lc-{i}", batch_hash=f"lc-h{i}", title=f"LC{i}",
            severity="low", description="d", evidence=[], ttps=[],
            tenant_id="t-lc",
        ))
    svc = ThreatFindingsService()
    from threat_findings.schemas import FindingFilter
    f = FindingFilter(tenant_id="t-lc", limit=2)
    items = await svc.list_findings(f, repo)
    total = await svc.count_findings(f, repo)
    assert total == 4
    assert len(items) == 2
```

- [ ] **Step 2: Run the three new tests to verify they FAIL**

```bash
pytest tests/threat_findings/test_service.py::test_get_finding_by_id_returns_record \
       tests/threat_findings/test_service.py::test_get_finding_by_id_missing_returns_none \
       tests/threat_findings/test_service.py::test_list_and_count_findings -v
```

Expected: 3 FAILs (AttributeError — methods not yet defined)

- [ ] **Step 3: Add three methods to `ThreatFindingsService` in `threat_findings/service.py`**

Append after the existing `mark_status` method:

```python
async def get_finding_by_id(
    self,
    finding_id: str,
    repo: ThreatFindingRepository,
) -> Optional[FindingRecord]:
    """Return the FindingRecord for finding_id, or None if not found."""
    return await repo.get_by_id(finding_id)

async def list_findings(
    self,
    filters: FindingFilter,
    repo: ThreatFindingRepository,
) -> List[FindingRecord]:
    """Return paginated findings matching filters."""
    return await repo.list_findings(filters)

async def count_findings(
    self,
    filters: FindingFilter,
    repo: ThreatFindingRepository,
) -> int:
    """Return the total count matching filters (ignores limit/offset)."""
    return await repo.count_findings(filters)
```

Also update the imports at the top of `threat_findings/service.py` — add `Optional`, `List`, and `FindingFilter`:

```python
from typing import Optional, List    # add List and Optional if not already there
from threat_findings.schemas import CreateFindingRequest, FindingRecord, FindingFilter
```

- [ ] **Step 4: Run the three new tests to verify they PASS**

```bash
pytest tests/threat_findings/test_service.py::test_get_finding_by_id_returns_record \
       tests/threat_findings/test_service.py::test_get_finding_by_id_missing_returns_none \
       tests/threat_findings/test_service.py::test_list_and_count_findings -v
```

Expected: 3 PASSes

- [ ] **Step 5: Run the full service test suite to confirm no regressions**

```bash
pytest tests/threat_findings/test_service.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add threat_findings/service.py tests/threat_findings/test_service.py
git commit -m "feat: add get_finding_by_id, list_findings, count_findings to ThreatFindingsService"
```

---

## Task 3: Create `api/findings_schemas.py`

**Files:**
- Create: `api/__init__.py`
- Create: `api/findings_schemas.py`

These are pure Pydantic models — no DB or service dependencies — so they can be written and tested in isolation before the router exists.

- [ ] **Step 1: Create `api/__init__.py`**

```python
# api package
```

- [ ] **Step 2: Create `api/findings_schemas.py`**

```python
from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field

from threat_findings.schemas import FindingRecord


# ── List-level item (compact) ─────────────────────────────────────────────────

class FindingListItem(BaseModel):
    id:               str
    title:            str
    severity:         str
    status:           str
    created_at:       str
    updated_at:       Optional[str]  = None
    risk_score:       Optional[float] = None
    confidence:       Optional[float] = None
    asset:            Optional[str]  = None
    should_open_case: bool           = False
    case_id:          Optional[str]  = None
    source:           Optional[str]  = None

    @classmethod
    def from_record(cls, rec: FindingRecord) -> "FindingListItem":
        return cls(
            id=rec.id,
            title=rec.title,
            severity=rec.severity,
            status=rec.status,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            risk_score=rec.risk_score,
            confidence=rec.confidence,
            asset=rec.asset,
            should_open_case=rec.should_open_case,
            case_id=rec.case_id,
            source=rec.source,
        )


# ── Paginated list wrapper ────────────────────────────────────────────────────

class FindingListResponse(BaseModel):
    items:  List[FindingListItem]
    total:  int
    limit:  int
    offset: int


# ── Full detail (single finding) ─────────────────────────────────────────────

class FindingDetailResponse(BaseModel):
    id:                   str
    title:                str
    severity:             str
    status:               str
    created_at:           str
    updated_at:           Optional[str]       = None
    closed_at:            Optional[str]       = None
    tenant_id:            str
    batch_hash:           str
    description:          str
    evidence:             List[Any]           = Field(default_factory=list)
    ttps:                 List[str]           = Field(default_factory=list)
    timestamp:            Optional[str]       = None
    confidence:           Optional[float]     = None
    risk_score:           Optional[float]     = None
    hypothesis:           Optional[str]       = None
    asset:                Optional[str]       = None
    environment:          Optional[str]       = None
    correlated_events:    Optional[List[str]] = None
    correlated_findings:  Optional[List[str]] = None
    triggered_policies:   Optional[List[str]] = None
    policy_signals:       Optional[List[Any]] = None
    recommended_actions:  Optional[List[str]] = None
    should_open_case:     bool                = False
    case_id:              Optional[str]       = None
    source:               Optional[str]       = None

    @classmethod
    def from_record(cls, rec: FindingRecord) -> "FindingDetailResponse":
        return cls(
            id=rec.id,
            title=rec.title,
            severity=rec.severity,
            status=rec.status,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            closed_at=rec.closed_at,
            tenant_id=rec.tenant_id,
            batch_hash=rec.batch_hash,
            description=rec.description,
            evidence=rec.evidence or [],
            ttps=rec.ttps or [],
            timestamp=rec.timestamp,
            confidence=rec.confidence,
            risk_score=rec.risk_score,
            hypothesis=rec.hypothesis,
            asset=rec.asset,
            environment=rec.environment,
            correlated_events=rec.correlated_events,
            correlated_findings=rec.correlated_findings,
            triggered_policies=rec.triggered_policies,
            policy_signals=rec.policy_signals,
            recommended_actions=rec.recommended_actions,
            should_open_case=rec.should_open_case,
            case_id=rec.case_id,
            source=rec.source,
        )


# ── Mutation request bodies ───────────────────────────────────────────────────

class UpdateStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(open|investigating|resolved)$")


class LinkCaseRequest(BaseModel):
    case_id: str = Field(..., min_length=1)


# ── Bulk query body ───────────────────────────────────────────────────────────

class QueryFindingsRequest(BaseModel):
    severity:       Optional[str]   = None
    status:         Optional[str]   = Field(None, pattern="^(open|investigating|resolved)$")
    asset:          Optional[str]   = None
    tenant_id:      Optional[str]   = None
    has_case:       Optional[bool]  = None
    from_time:      Optional[str]   = None
    to_time:        Optional[str]   = None
    min_risk_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    limit:          int             = Field(50, ge=1, le=200)
    offset:         int             = Field(0, ge=0)
    sort_by:        Optional[str]   = Field(None, pattern="^(risk_score|timestamp)$")
```

- [ ] **Step 3: Smoke-test the schemas with Python**

```bash
cd services/agent-orchestrator-service
python - <<'EOF'
from api.findings_schemas import (
    FindingDetailResponse, FindingListItem, FindingListResponse,
    UpdateStatusRequest, LinkCaseRequest, QueryFindingsRequest,
)
from threat_findings.schemas import FindingRecord

rec = FindingRecord(
    id="x1", batch_hash="bh1", title="T", severity="high",
    description="D", evidence=[], ttps=[], tenant_id="t1",
)
detail = FindingDetailResponse.from_record(rec)
assert detail.id == "x1"
item = FindingListItem.from_record(rec)
assert item.severity == "high"
lr = FindingListResponse(items=[item], total=1, limit=50, offset=0)
assert lr.total == 1
usr = UpdateStatusRequest(status="investigating")
assert usr.status == "investigating"
lcr = LinkCaseRequest(case_id="case-abc")
assert lcr.case_id == "case-abc"
qr = QueryFindingsRequest(severity="high", limit=10, sort_by="risk_score")
assert qr.limit == 10
print("✓ all schemas OK")
EOF
```

Expected: `✓ all schemas OK`

- [ ] **Step 4: Commit**

```bash
git add api/__init__.py api/findings_schemas.py
git commit -m "feat: add api/findings_schemas — API-facing Pydantic models for findings endpoints"
```

---

## Task 4: Create `api/findings_router.py`

**Files:**
- Create: `api/findings_router.py`

### Route overview

| Method | Path | RBAC | Returns |
|--------|------|------|---------|
| GET | `/api/v1/findings` | `session.read` | `FindingListResponse` |
| GET | `/api/v1/findings/{finding_id}` | `session.read` | `FindingDetailResponse` |
| PATCH | `/api/v1/findings/{finding_id}/status` | `session.override` | `FindingDetailResponse` |
| POST | `/api/v1/findings/{finding_id}/link-case` | `session.override` | `FindingDetailResponse` |
| POST | `/api/v1/findings/query` | `session.read` | `FindingListResponse` |

**Note:** `POST /findings/query` must be defined **before** `POST /findings/{finding_id}/link-case` in the router to prevent the literal string `"query"` from being captured as `finding_id`. (Though FastAPI won't actually confuse them here since `/query` and `/{id}/link-case` have different path depths, defining query first is safer and clearer.)

- [ ] **Step 1: Create `api/findings_router.py`**

```python
from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.findings_schemas import (
    FindingDetailResponse,
    FindingListItem,
    FindingListResponse,
    LinkCaseRequest,
    QueryFindingsRequest,
    UpdateStatusRequest,
)
from dependencies.auth import IdentityContext
from dependencies.rbac import require_session_override, require_session_read
from schemas.session import ErrorDetail, ErrorResponse
from threat_findings.models import ThreatFindingRepository
from threat_findings.schemas import FindingFilter
from threat_findings.service import ThreatFindingsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/findings", tags=["Findings"])

_MAX_LIMIT = 200


# ── Dependency functions ──────────────────────────────────────────────────────

def get_findings_service(request: Request) -> ThreatFindingsService:
    return request.app.state.threat_findings_service


async def get_async_db(request: Request):
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


async def get_finding_repo(
    session: AsyncSession = Depends(get_async_db),
) -> ThreatFindingRepository:
    return ThreatFindingRepository(session)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_404(
    finding_id: str,
    svc: ThreatFindingsService,
    repo: ThreatFindingRepository,
    trace_id: str,
) -> FindingDetailResponse:
    rec = await svc.get_finding_by_id(finding_id, repo)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorDetail(
                code="FINDING_NOT_FOUND",
                message=f"Finding '{finding_id}' not found.",
                trace_id=trace_id,
            ).model_dump(),
        )
    return FindingDetailResponse.from_record(rec)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List findings with optional filters",
    responses={
        200: {"description": "Paginated list of findings"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def list_findings(
    request:        Request,
    response:       Response,
    severity:       Optional[str]   = Query(None),
    status_filter:  Optional[str]   = Query(None, alias="status"),
    asset:          Optional[str]   = Query(None),
    tenant_id:      Optional[str]   = Query(None),
    has_case:       Optional[bool]  = Query(None),
    from_time:      Optional[str]   = Query(None),
    to_time:        Optional[str]   = Query(None),
    min_risk_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    sort_by:        Optional[str]   = Query(None, pattern="^(risk_score|timestamp)$"),
    limit:          int             = Query(50, ge=1, le=_MAX_LIMIT),
    offset:         int             = Query(0, ge=0),
    identity:       IdentityContext         = Depends(require_session_read),
    repo:           ThreatFindingRepository = Depends(get_finding_repo),
    svc:            ThreatFindingsService   = Depends(get_findings_service),
) -> FindingListResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "GET /findings user=%s severity=%s status=%s tenant=%s trace=%s",
        identity.user_id, severity, status_filter, tenant_id, trace_id,
    )
    filters = FindingFilter(
        severity=severity,
        status=status_filter,
        asset=asset,
        tenant_id=tenant_id,
        has_case=has_case,
        from_ts=from_time,
        to_ts=to_time,
        min_risk_score=min_risk_score,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    items = await svc.list_findings(filters, repo)
    # count_findings calls _apply_filters (WHERE only, no LIMIT/OFFSET applied),
    # so passing the same filters gives the correct total count across all pages.
    total = await svc.count_findings(filters, repo)
    response.headers["X-Trace-ID"] = trace_id
    return FindingListResponse(
        items=[FindingListItem.from_record(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/query",
    summary="Bulk-query findings (body-based filters)",
    responses={
        200: {"description": "Paginated list of findings"},
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def query_findings(
    body:      QueryFindingsRequest,
    request:   Request,
    response:  Response,
    identity:  IdentityContext         = Depends(require_session_read),
    repo:      ThreatFindingRepository = Depends(get_finding_repo),
    svc:       ThreatFindingsService   = Depends(get_findings_service),
) -> FindingListResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "POST /findings/query user=%s trace=%s body=%s",
        identity.user_id, trace_id, body.model_dump(exclude_none=True),
    )
    filters = FindingFilter(
        severity=body.severity,
        status=body.status,
        asset=body.asset,
        tenant_id=body.tenant_id,
        has_case=body.has_case,
        from_ts=body.from_time,
        to_ts=body.to_time,
        min_risk_score=body.min_risk_score,
        sort_by=body.sort_by,
        limit=body.limit,
        offset=body.offset,
    )
    items = await svc.list_findings(filters, repo)
    # count_findings calls _apply_filters (WHERE only, no LIMIT/OFFSET), so
    # passing `filters` returns the correct total count across all pages.
    total = await svc.count_findings(filters, repo)
    response.headers["X-Trace-ID"] = trace_id
    return FindingListResponse(
        items=[FindingListItem.from_record(r) for r in items],
        total=total,
        limit=body.limit,
        offset=body.offset,
    )


@router.get(
    "/{finding_id}",
    summary="Get full finding detail",
    responses={
        200: {"description": "Full finding object"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_finding(
    finding_id: str,
    request:    Request,
    response:   Response,
    identity:   IdentityContext         = Depends(require_session_read),
    repo:       ThreatFindingRepository = Depends(get_finding_repo),
    svc:        ThreatFindingsService   = Depends(get_findings_service),
) -> FindingDetailResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "GET /findings/%s user=%s trace=%s", finding_id, identity.user_id, trace_id,
    )
    detail = await _get_or_404(finding_id, svc, repo, trace_id)
    response.headers["X-Trace-ID"] = trace_id
    return detail


@router.patch(
    "/{finding_id}/status",
    summary="Update finding status",
    responses={
        200: {"description": "Updated finding"},
        400: {"model": ErrorResponse, "description": "Invalid status value"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def update_status(
    finding_id: str,
    body:       UpdateStatusRequest,
    request:    Request,
    response:   Response,
    identity:   IdentityContext         = Depends(require_session_override),
    repo:       ThreatFindingRepository = Depends(get_finding_repo),
    svc:        ThreatFindingsService   = Depends(get_findings_service),
) -> FindingDetailResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "PATCH /findings/%s/status user=%s new_status=%s trace=%s",
        finding_id, identity.user_id, body.status, trace_id,
    )
    # Verify finding exists first
    await _get_or_404(finding_id, svc, repo, trace_id)
    try:
        await svc.mark_status(finding_id, body.status, repo)
    except AssertionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="INVALID_STATUS", message=str(exc), trace_id=trace_id,
            ).model_dump(),
        )
    # Re-fetch updated record
    detail = await _get_or_404(finding_id, svc, repo, trace_id)
    response.headers["X-Trace-ID"] = trace_id
    return detail


@router.post(
    "/{finding_id}/link-case",
    summary="Link an existing case to a finding",
    responses={
        200: {"description": "Updated finding with case_id set"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def link_case(
    finding_id: str,
    body:       LinkCaseRequest,
    request:    Request,
    response:   Response,
    identity:   IdentityContext         = Depends(require_session_override),
    repo:       ThreatFindingRepository = Depends(get_finding_repo),
    svc:        ThreatFindingsService   = Depends(get_findings_service),
) -> FindingDetailResponse:
    trace_id = getattr(request.state, "trace_id", "")
    logger.info(
        "POST /findings/%s/link-case user=%s case_id=%s trace=%s",
        finding_id, identity.user_id, body.case_id, trace_id,
    )
    # Verify finding exists
    await _get_or_404(finding_id, svc, repo, trace_id)
    await svc.link_case(finding_id, body.case_id, repo)
    detail = await _get_or_404(finding_id, svc, repo, trace_id)
    response.headers["X-Trace-ID"] = trace_id
    return detail
```

- [ ] **Step 2: Verify the module imports cleanly**

```bash
cd services/agent-orchestrator-service
python -c "from api.findings_router import router; print('✓ router imported OK')"
```

Expected: `✓ router imported OK`

- [ ] **Step 3: Commit**

```bash
git add api/findings_router.py
git commit -m "feat: add api/findings_router — 5 REST endpoints for findings UI"
```

---

## Task 5: Register router in `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add import near the other router imports at the top of `main.py`**

Find the block that imports the existing routers (around line 25-35). Add:

```python
from api.findings_router import router as findings_api_router
```

- [ ] **Step 2: Register the router after `threat_findings_router`**

Find the router registration block (around line 304-311):

```python
    app.include_router(sessions_router.router)
    from results.router import router as results_router
    app.include_router(results_router)
    app.include_router(cases_router)
    app.include_router(threat_findings_router)
    app.include_router(policies_router)
```

Add one line after `threat_findings_router`:

```python
    app.include_router(findings_api_router)
```

- [ ] **Step 3: Verify the app starts**

```bash
cd services/agent-orchestrator-service
python -c "from main import create_app; app = create_app(); print('✓ app starts OK')"
```

Expected: `✓ app starts OK`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: register findings_api_router in main.py"
```

---

## Task 6: Router integration tests

**Files:**
- Create: `tests/findings/__init__.py`
- Create: `tests/findings/conftest.py`
- Create: `tests/findings/test_findings_api.py`

### Test design

Tests use `AsyncClient` + ASGI transport with dependency overrides for service/repo (same pattern as `tests/threat_findings/test_router.py`). The service methods (`list_findings`, `count_findings`, `get_finding_by_id`, `mark_status`, `link_case`) are mocked with `AsyncMock`.

- [ ] **Step 1: Create `tests/findings/__init__.py`**

```python
```

- [ ] **Step 2: Create `tests/findings/conftest.py`**

```python
from __future__ import annotations
import pytest
from dataclasses import dataclass, field
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

from main import create_app
from api.findings_router import get_finding_repo, get_findings_service
from dependencies.rbac import require_session_read, require_session_override
from threat_findings.schemas import FindingRecord


@dataclass
class _MockIdentity:
    user_id: str = "test-analyst"
    roles:   list = field(default_factory=lambda: ["admin"])
    groups:  list = field(default_factory=list)


def _make_record(
    fid: str = "finding-1",
    severity: str = "high",
    status: str = "open",
    risk_score: float = 0.85,
    case_id: str = None,
) -> FindingRecord:
    return FindingRecord(
        id=fid,
        batch_hash=f"bh-{fid}",
        title=f"Test Finding {fid}",
        severity=severity,
        description="A test finding description.",
        evidence=["log line 1"],
        ttps=["T1059"],
        tenant_id="acme",
        status=status,
        risk_score=risk_score,
        case_id=case_id,
    )


@pytest.fixture
async def client():
    app = create_app()
    mock_repo = AsyncMock()
    mock_svc  = AsyncMock()

    app.dependency_overrides[get_finding_repo]       = lambda: mock_repo
    app.dependency_overrides[get_findings_service]   = lambda: mock_svc
    app.dependency_overrides[require_session_read]   = lambda: _MockIdentity()
    app.dependency_overrides[require_session_override] = lambda: _MockIdentity()

    app._mock_svc  = mock_svc
    app._mock_repo = mock_repo

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c._app = app
        yield c
```

- [ ] **Step 3: Create `tests/findings/test_findings_api.py`**

```python
import pytest
from tests.findings.conftest import _make_record


# ── GET /api/v1/findings ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_findings_empty(client):
    """Empty DB returns items=[], total=0."""
    client._app._mock_svc.list_findings.return_value = []
    client._app._mock_svc.count_findings.return_value = 0

    resp = await client.get("/api/v1/findings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_list_findings_returns_items(client):
    """Returns paginated list with correct total."""
    recs = [_make_record(f"f-{i}") for i in range(3)]
    client._app._mock_svc.list_findings.return_value = recs
    client._app._mock_svc.count_findings.return_value = 10  # more exist beyond limit

    resp = await client.get("/api/v1/findings?limit=3&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["total"] == 10
    assert data["limit"] == 3


@pytest.mark.asyncio
async def test_list_findings_passes_filters_to_service(client):
    """Query params are forwarded to the service as a FindingFilter."""
    client._app._mock_svc.list_findings.return_value = []
    client._app._mock_svc.count_findings.return_value = 0

    await client.get("/api/v1/findings?severity=high&status=open&min_risk_score=0.7")

    call_args = client._app._mock_svc.list_findings.call_args
    filters = call_args[0][0]   # first positional arg
    assert filters.severity == "high"
    assert filters.status == "open"
    assert filters.min_risk_score == 0.7


# ── GET /api/v1/findings/{id} ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_finding_returns_full_detail(client):
    """Returns all fields including evidence, ttps, hypothesis."""
    rec = _make_record("f-detail")
    client._app._mock_svc.get_finding_by_id.return_value = rec

    resp = await client.get("/api/v1/findings/f-detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "f-detail"
    assert data["evidence"] == ["log line 1"]
    assert data["ttps"] == ["T1059"]
    assert data["tenant_id"] == "acme"
    assert data["batch_hash"] == "bh-f-detail"


@pytest.mark.asyncio
async def test_get_finding_not_found_returns_404(client):
    """Missing finding_id returns 404 with FINDING_NOT_FOUND code."""
    client._app._mock_svc.get_finding_by_id.return_value = None

    resp = await client.get("/api/v1/findings/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "FINDING_NOT_FOUND"


# ── PATCH /api/v1/findings/{id}/status ───────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_status_returns_updated_finding(client):
    """Status update returns the finding with new status."""
    rec = _make_record("f-patch", status="open")
    updated = _make_record("f-patch", status="investigating")
    # get_finding_by_id: first call (existence check) returns original,
    # second call (re-fetch) returns updated
    client._app._mock_svc.get_finding_by_id.side_effect = [rec, updated]

    resp = await client.patch(
        "/api/v1/findings/f-patch/status",
        json={"status": "investigating"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "investigating"


@pytest.mark.asyncio
async def test_patch_status_invalid_value_returns_422(client):
    """A status value not matching the pattern returns 422 from Pydantic."""
    resp = await client.patch(
        "/api/v1/findings/f-any/status",
        json={"status": "unknown"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_status_not_found_returns_404(client):
    client._app._mock_svc.get_finding_by_id.return_value = None
    resp = await client.patch(
        "/api/v1/findings/missing/status",
        json={"status": "resolved"},
    )
    assert resp.status_code == 404


# ── POST /api/v1/findings/{id}/link-case ─────────────────────────────────────

@pytest.mark.asyncio
async def test_link_case_returns_updated_finding(client):
    rec = _make_record("f-link", case_id=None)
    updated = _make_record("f-link", case_id="case-xyz")
    client._app._mock_svc.get_finding_by_id.side_effect = [rec, updated]

    resp = await client.post(
        "/api/v1/findings/f-link/link-case",
        json={"case_id": "case-xyz"},
    )
    assert resp.status_code == 200
    assert resp.json()["case_id"] == "case-xyz"


# ── POST /api/v1/findings/query ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_query_with_body_filters(client):
    """POST /query with body filters returns paginated list."""
    recs = [_make_record("q-1", severity="critical")]
    client._app._mock_svc.list_findings.return_value = recs
    client._app._mock_svc.count_findings.return_value = 1

    resp = await client.post("/api/v1/findings/query", json={
        "severity": "critical",
        "limit": 10,
        "offset": 0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["severity"] == "critical"
```

- [ ] **Step 4: Run all new tests**

```bash
cd services/agent-orchestrator-service
pytest tests/findings/ -v
```

Expected: 10 PASSes, 0 failures

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all previously passing tests continue to pass; new tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/findings/__init__.py tests/findings/conftest.py \
        tests/findings/test_findings_api.py
git commit -m "test: add 10 integration tests for findings REST API"
```

---

## Final verification checklist

- [ ] All 5 endpoints are accessible: `GET /api/v1/findings`, `GET /api/v1/findings/{id}`, `PATCH /api/v1/findings/{id}/status`, `POST /api/v1/findings/{id}/link-case`, `POST /api/v1/findings/query`
- [ ] No route accesses the DB directly — all DB work goes through `ThreatFindingsService`
- [ ] 404 is returned for unknown `finding_id` on GET, PATCH, POST link-case
- [ ] 422 is returned for invalid `UpdateStatusRequest.status`
- [ ] Max `limit` is enforced at 200 via Pydantic field constraint
- [ ] `X-Trace-ID` header is set on all responses
- [ ] RBAC: GET endpoints require `session.read`; PATCH/mutation POST endpoints require `session.override`
- [ ] `POST /findings/query` is defined before `POST /findings/{id}/link-case` in the router
- [ ] Full test suite passes: `pytest tests/ -v`
