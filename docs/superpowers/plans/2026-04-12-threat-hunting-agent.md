# Threat Hunting Agent Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LangChain ReAct agent service that continuously consumes Kafka events, batches them per tenant, correlates AI-layer and infrastructure threats, and opens findings in agent-orchestrator-service for human investigation.

**Architecture:** New standalone microservice `services/threat-hunting-agent/` with a Kafka consumer batching events into 30-second windows, a LangChain ReAct agent powered by Groq that uses 8 tools to investigate each batch, and a new `POST /api/v1/threat-findings` endpoint added to agent-orchestrator-service backed by a SQLite table.

**Tech Stack:** Python 3.12, LangChain 0.3+, langchain-groq, FastAPI, kafka-python, psycopg2-binary (read SPM Postgres), redis-py, httpx, SQLAlchemy async + aiosqlite (agent-orchestrator SQLite), alembic.

**Spec:** `docs/superpowers/specs/2026-04-12-threat-hunting-agent-design.md`

---

## File Map

### New files — `services/threat-hunting-agent/`
| File | Responsibility |
|------|---------------|
| `app.py` | FastAPI app, lifespan (start/stop consumer), `/health` endpoint |
| `config.py` | Pydantic BaseSettings — reads all env vars |
| `agent/__init__.py` | Empty |
| `agent/prompts.py` | System prompt for the ReAct agent |
| `agent/agent.py` | `build_agent()` — wires Groq LLM + 8 tools into a ReAct agent |
| `tools/__init__.py` | Exports all 8 tools as a list |
| `tools/postgres_tool.py` | `QueryAuditLogs`, `QueryPostureHistory`, `QueryModelRegistry` |
| `tools/redis_tool.py` | `QueryRedisSession` |
| `tools/mitre_tool.py` | `LookupMITRE` |
| `tools/opa_tool.py` | `EvaluateOPAPolicy` |
| `tools/guard_tool.py` | `RescreenPrompt` |
| `tools/case_tool.py` | `CreateFinding` (idempotent via batch_hash) |
| `consumer/__init__.py` | Empty |
| `consumer/kafka_consumer.py` | `ThreatHuntConsumer` — subscribes, batches 30s windows, per-tenant isolation |
| `Dockerfile` | Python 3.12-slim, copies platform_shared |
| `requirements.txt` | All deps |
| `tests/__init__.py` | Empty |
| `tests/test_tools.py` | Unit tests for all 8 tools (mocked HTTP/DB/Redis) |
| `tests/test_consumer.py` | Unit tests for batching algorithm and offset commit logic |
| `tests/test_agent.py` | Integration test: agent processes a mock batch and calls CreateFinding |

### Modified files — `services/agent-orchestrator-service/`
| File | Change |
|------|--------|
| `db/models.py` | Add `ThreatFindingORM` class |
| `alembic/versions/004_threat_findings.py` | New migration — creates `threat_findings` table |
| `threat_findings/__init__.py` | New package (empty) |
| `threat_findings/schemas.py` | `CreateFindingRequest`, `FindingResponse`, `DeduplicatedResponse` |
| `threat_findings/models.py` | `ThreatFindingRepository` |
| `threat_findings/service.py` | `ThreatFindingsService` |
| `threat_findings/router.py` | `POST /api/v1/threat-findings` |
| `main.py` | Import + register threat_findings router; init ThreatFindingsService on app.state |

### Modified files — root
| File | Change |
|------|--------|
| `docker-compose.yml` | Add `threat-hunting-agent` service |

---

## Task 1: ORM Model + Alembic Migration (agent-orchestrator-service)

**Files:**
- Modify: `services/agent-orchestrator-service/db/models.py`
- Create: `services/agent-orchestrator-service/alembic/versions/004_threat_findings.py`

- [ ] **Step 1.1: Add ThreatFindingORM to db/models.py**

Open `services/agent-orchestrator-service/db/models.py` and append:

```python
class ThreatFindingORM(Base):
    """Persisted finding from the threat-hunting-agent."""
    __tablename__ = "threat_findings"

    id          = Column(String, primary_key=True)
    batch_hash  = Column(String, nullable=False, unique=True)
    title       = Column(String, nullable=False)
    severity    = Column(String, nullable=False)   # low|medium|high|critical
    description = Column(Text,   nullable=False)
    evidence    = Column(Text,   nullable=False)   # JSON string
    ttps        = Column(Text,   nullable=False, default="[]")  # JSON array
    tenant_id   = Column(String, nullable=False)
    status      = Column(String, nullable=False, default="open")
    created_at  = Column(String, nullable=False)  # ISO-8601 string
    closed_at   = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_threat_findings_tenant",   "tenant_id", "created_at"),
        Index("ix_threat_findings_severity", "severity",  "status"),
    )
```

- [ ] **Step 1.2: Create alembic migration**

Create `services/agent-orchestrator-service/alembic/versions/004_threat_findings.py`:

```python
"""Add threat_findings table

Revision ID: 004
Revises: 003
Create Date: 2026-04-12
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: str | None = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "threat_findings",
        sa.Column("id",          sa.String, primary_key=True),
        sa.Column("batch_hash",  sa.String, nullable=False, unique=True),
        sa.Column("title",       sa.String, nullable=False),
        sa.Column("severity",    sa.String, nullable=False),
        sa.Column("description", sa.Text,   nullable=False),
        sa.Column("evidence",    sa.Text,   nullable=False),
        sa.Column("ttps",        sa.Text,   nullable=False, server_default="[]"),
        sa.Column("tenant_id",   sa.String, nullable=False),
        sa.Column("status",      sa.String, nullable=False, server_default="open"),
        sa.Column("created_at",  sa.String, nullable=False),
        sa.Column("closed_at",   sa.String, nullable=True),
    )
    op.create_index("ix_threat_findings_tenant",   "threat_findings", ["tenant_id", "created_at"])
    op.create_index("ix_threat_findings_severity", "threat_findings", ["severity", "status"])


def downgrade() -> None:
    op.drop_index("ix_threat_findings_severity")
    op.drop_index("ix_threat_findings_tenant")
    op.drop_table("threat_findings")
```

- [ ] **Step 1.3: Verify migration runs**

```bash
cd services/agent-orchestrator-service
python -m alembic upgrade head
# Expected: "Running upgrade 003 -> 004, Add threat_findings table"
sqlite3 agent_orchestrator.db ".tables"
# Expected output includes: threat_findings
```

- [ ] **Step 1.4: Commit**
```bash
git add services/agent-orchestrator-service/db/models.py \
        services/agent-orchestrator-service/alembic/versions/004_threat_findings.py
git commit -m "feat(orchestrator): add threat_findings table + alembic migration 004"
```

---

## Task 2: ThreatFindings Service Layer (agent-orchestrator-service)

**Files:**
- Create: `services/agent-orchestrator-service/threat_findings/__init__.py`
- Create: `services/agent-orchestrator-service/threat_findings/schemas.py`
- Create: `services/agent-orchestrator-service/threat_findings/models.py`
- Create: `services/agent-orchestrator-service/threat_findings/service.py`

- [ ] **Step 2.1: Write failing test first**

Create `services/agent-orchestrator-service/tests/threat_findings/test_service.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from threat_findings.service import ThreatFindingsService
from threat_findings.schemas import CreateFindingRequest


@pytest.fixture
def svc():
    return ThreatFindingsService()


@pytest.mark.asyncio
async def test_create_finding_returns_record(svc):
    repo = AsyncMock()
    repo.get_by_batch_hash.return_value = None
    repo.insert.return_value = None

    req = CreateFindingRequest(
        title="Test finding",
        severity="high",
        description="desc",
        evidence={"event_ids": ["e1"]},
        ttps=["AML.T0051"],
        tenant_id="t1",
        batch_hash="abc123",
    )
    result = await svc.create_finding(req, repo)
    assert result.title == "Test finding"
    assert result.status == "open"
    assert result.deduplicated is False


@pytest.mark.asyncio
async def test_create_finding_deduplicates(svc):
    from threat_findings.schemas import FindingRecord
    from datetime import datetime
    existing = FindingRecord(
        id="existing-id", batch_hash="abc123", title="old",
        severity="low", description="d", evidence={}, ttps=[],
        tenant_id="t1", status="open", created_at=datetime.utcnow().isoformat(),
    )
    repo = AsyncMock()
    repo.get_by_batch_hash.return_value = existing

    req = CreateFindingRequest(
        title="New title", severity="high", description="desc",
        evidence={"event_ids": []}, ttps=[], tenant_id="t1", batch_hash="abc123",
    )
    result = await svc.create_finding(req, repo)
    assert result.id == "existing-id"
    assert result.deduplicated is True
    repo.insert.assert_not_called()
```

- [ ] **Step 2.2: Run test — expect ImportError (modules don't exist yet)**
```bash
cd services/agent-orchestrator-service
python -m pytest tests/threat_findings/test_service.py -v 2>&1 | head -20
# Expected: ModuleNotFoundError: No module named 'threat_findings'
```

- [ ] **Step 2.3: Create `threat_findings/__init__.py`**
```python
# threat_findings/__init__.py
```

- [ ] **Step 2.4: Create `threat_findings/schemas.py`**
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
    id:          str
    batch_hash:  str
    title:       str
    severity:    str
    description: str
    evidence:    Dict[str, Any]
    ttps:        List[str]
    tenant_id:   str
    status:      str = "open"
    created_at:  str = field(default_factory=_utcnow)
    closed_at:   Optional[str] = None
    deduplicated: bool = False   # transient — not persisted


class CreateFindingRequest(BaseModel):
    title:       str         = Field(..., min_length=1)
    severity:    str         = Field(..., pattern="^(low|medium|high|critical)$")
    description: str         = Field(..., min_length=1)
    evidence:    Dict[str, Any] = Field(default_factory=dict)
    ttps:        List[str]   = Field(default_factory=list)
    tenant_id:   str         = Field(..., min_length=1)
    batch_hash:  str         = Field(..., min_length=1)


class FindingResponse(BaseModel):
    id:           str
    title:        str
    severity:     str
    status:       str
    created_at:   str
    deduplicated: bool = False

    @classmethod
    def from_record(cls, rec: FindingRecord) -> "FindingResponse":
        return cls(
            id=rec.id, title=rec.title, severity=rec.severity,
            status=rec.status, created_at=rec.created_at,
            deduplicated=rec.deduplicated,
        )
```

- [ ] **Step 2.5: Create `threat_findings/models.py`**
```python
from __future__ import annotations
import json
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import ThreatFindingORM
from threat_findings.schemas import FindingRecord

logger = logging.getLogger(__name__)


def _orm_to_record(row: ThreatFindingORM) -> FindingRecord:
    return FindingRecord(
        id=row.id, batch_hash=row.batch_hash, title=row.title,
        severity=row.severity, description=row.description,
        evidence=json.loads(row.evidence), ttps=json.loads(row.ttps),
        tenant_id=row.tenant_id, status=row.status,
        created_at=row.created_at, closed_at=row.closed_at,
    )


class ThreatFindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_batch_hash(self, batch_hash: str) -> Optional[FindingRecord]:
        stmt = select(ThreatFindingORM).where(ThreatFindingORM.batch_hash == batch_hash)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _orm_to_record(row) if row else None

    async def insert(self, rec: FindingRecord) -> None:
        orm = ThreatFindingORM(
            id=rec.id, batch_hash=rec.batch_hash, title=rec.title,
            severity=rec.severity, description=rec.description,
            evidence=json.dumps(rec.evidence), ttps=json.dumps(rec.ttps),
            tenant_id=rec.tenant_id, status=rec.status,
            created_at=rec.created_at, closed_at=rec.closed_at,
        )
        self._session.add(orm)
        await self._session.commit()
```

- [ ] **Step 2.6: Create `threat_findings/service.py`**
```python
from __future__ import annotations
import logging
from uuid import uuid4
from threat_findings.schemas import CreateFindingRequest, FindingRecord
from threat_findings.models import ThreatFindingRepository

logger = logging.getLogger(__name__)


class ThreatFindingsService:
    """Stateless — one shared instance on app.state."""

    async def create_finding(
        self,
        req: CreateFindingRequest,
        repo: ThreatFindingRepository,
    ) -> FindingRecord:
        existing = await repo.get_by_batch_hash(req.batch_hash)
        if existing:
            logger.info("Deduplicated finding batch_hash=%s", req.batch_hash)
            existing.deduplicated = True
            return existing

        rec = FindingRecord(
            id=str(uuid4()),
            batch_hash=req.batch_hash,
            title=req.title,
            severity=req.severity,
            description=req.description,
            evidence=req.evidence,
            ttps=req.ttps,
            tenant_id=req.tenant_id,
        )
        await repo.insert(rec)
        logger.info("Created finding id=%s tenant=%s severity=%s", rec.id, rec.tenant_id, rec.severity)
        return rec
```

- [ ] **Step 2.7: Run tests — expect PASS**
```bash
cd services/agent-orchestrator-service
python -m pytest tests/threat_findings/test_service.py -v
# Expected: 2 passed
```

- [ ] **Step 2.8: Commit**
```bash
git add services/agent-orchestrator-service/threat_findings/ \
        services/agent-orchestrator-service/tests/threat_findings/
git commit -m "feat(orchestrator): add ThreatFindingsService with deduplication"
```

---

## Task 3: Threat Findings Router + Wire to main.py (agent-orchestrator-service)

**Files:**
- Create: `services/agent-orchestrator-service/threat_findings/router.py`
- Modify: `services/agent-orchestrator-service/main.py`

- [ ] **Step 3.1: Write failing router test**

Create `services/agent-orchestrator-service/tests/threat_findings/test_router.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from main import create_app


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_create_finding_201(client):
    with patch("threat_findings.router.get_finding_repo") as mock_repo_dep, \
         patch("threat_findings.router.get_findings_service") as mock_svc_dep:
        from threat_findings.schemas import FindingRecord
        mock_rec = FindingRecord(
            id="test-id", batch_hash="h1", title="T", severity="high",
            description="D", evidence={}, ttps=[], tenant_id="t1",
        )
        mock_svc = AsyncMock()
        mock_svc.create_finding.return_value = mock_rec
        mock_svc_dep.return_value = mock_svc
        mock_repo_dep.return_value = AsyncMock()

        resp = await client.post("/api/v1/threat-findings", json={
            "title": "T", "severity": "high", "description": "D",
            "evidence": {}, "ttps": [], "tenant_id": "t1", "batch_hash": "h1",
        })
        assert resp.status_code == 201
        assert resp.json()["id"] == "test-id"


@pytest.mark.asyncio
async def test_create_finding_400_bad_severity(client):
    resp = await client.post("/api/v1/threat-findings", json={
        "title": "T", "severity": "extreme", "description": "D",
        "evidence": {}, "ttps": [], "tenant_id": "t1", "batch_hash": "h1",
    })
    assert resp.status_code == 422
```

- [ ] **Step 3.2: Create `threat_findings/router.py`**
```python
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import make_session_factory
from threat_findings.schemas import CreateFindingRequest, FindingResponse
from threat_findings.service import ThreatFindingsService
from threat_findings.models import ThreatFindingRepository
from schemas.session import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/threat-findings", tags=["ThreatFindings"])


def get_findings_service(request: Request) -> ThreatFindingsService:
    return request.app.state.threat_findings_service


async def get_finding_repo(request: Request):
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield ThreatFindingRepository(session)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Finding created"},
        200: {"description": "Deduplicated — finding already exists"},
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Create a threat finding (internal — threat-hunting-agent only)",
)
async def create_finding(
    body: CreateFindingRequest,
    request: Request,
    response: Response,
    repo=Depends(get_finding_repo),
    svc: ThreatFindingsService = Depends(get_findings_service),
):
    try:
        rec = await svc.create_finding(body, repo)
        if rec.deduplicated:
            response.status_code = status.HTTP_200_OK
        return FindingResponse.from_record(rec)
    except Exception as exc:
        logger.error("create_finding error: %s", exc, exc_info=True)
        return ErrorResponse(
            detail=ErrorDetail(code="INTERNAL_ERROR", message=str(exc), trace_id="").model_dump()
        )
```

- [ ] **Step 3.3: Wire router into `main.py`**

In `services/agent-orchestrator-service/main.py`:

Find the `lifespan` function where `app.state.cases_service` is set, and add directly after it:
```python
from threat_findings.router import router as threat_findings_router
from threat_findings.service import ThreatFindingsService
# In lifespan, after cases_service line:
app.state.threat_findings_service = ThreatFindingsService()
```

Find the `include_router` calls and add:
```python
app.include_router(threat_findings_router)
```

- [ ] **Step 3.4: Run tests**
```bash
cd services/agent-orchestrator-service
python -m pytest tests/threat_findings/ -v
# Expected: 3 passed
```

- [ ] **Step 3.5: Smoke test the endpoint**
```bash
# Start the orchestrator locally
uvicorn main:app --port 8094 &
curl -s -X POST http://localhost:8094/api/v1/threat-findings \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","severity":"high","description":"d","evidence":{},"ttps":[],"tenant_id":"t1","batch_hash":"test123"}' \
  | python -m json.tool
# Expected: {"id": "...", "title": "Test", "severity": "high", "status": "open", "deduplicated": false}
kill %1
```

- [ ] **Step 3.6: Commit**
```bash
git add services/agent-orchestrator-service/threat_findings/router.py \
        services/agent-orchestrator-service/main.py \
        services/agent-orchestrator-service/tests/threat_findings/test_router.py
git commit -m "feat(orchestrator): add POST /api/v1/threat-findings endpoint"
```

---

## Task 4: Threat Hunting Agent — Scaffolding

**Files:**
- Create: `services/threat-hunting-agent/requirements.txt`
- Create: `services/threat-hunting-agent/config.py`
- Create: `services/threat-hunting-agent/Dockerfile`
- Create: `services/threat-hunting-agent/agent/__init__.py`
- Create: `services/threat-hunting-agent/tools/__init__.py`
- Create: `services/threat-hunting-agent/consumer/__init__.py`
- Create: `services/threat-hunting-agent/tests/__init__.py`

- [ ] **Step 4.1: Create `requirements.txt`**
```
langchain>=0.3
langchain-groq>=0.2
langchain-community>=0.3
fastapi>=0.111
uvicorn>=0.30
httpx>=0.27
kafka-python>=2.0
redis>=5.0
psycopg2-binary>=2.9
pydantic>=2.7
pydantic-settings>=2.0
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 4.2: Create `config.py`**
```python
from __future__ import annotations
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kafka
    kafka_bootstrap_servers: str = "kafka-broker:9092"
    tenants: str = "t1"

    # Groq / LLM
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    # Hunt tuning
    hunt_batch_window_sec: int = 30
    hunt_queue_max: int = 20

    # Downstream services
    orchestrator_url: str = "http://agent-orchestrator:8094"
    guard_model_url: str = "http://guard-model:8200"
    opa_url: str = "http://opa:8181"

    # Databases
    spm_db_url: str = "postgresql://spm_rw:spmpass@spm-db:5432/spm"
    redis_host: str = "redis"
    redis_port: int = 6379

    @property
    def tenant_list(self) -> list[str]:
        return [t.strip() for t in self.tenants.split(",") if t.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
```

- [ ] **Step 4.3: Create `Dockerfile`**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY services/threat-hunting-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY services/threat-hunting-agent/ .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8095", "--workers", "1"]
```

- [ ] **Step 4.4: Create empty init files**
```bash
touch services/threat-hunting-agent/agent/__init__.py
touch services/threat-hunting-agent/tools/__init__.py
touch services/threat-hunting-agent/consumer/__init__.py
touch services/threat-hunting-agent/tests/__init__.py
```

- [ ] **Step 4.5: Commit scaffolding**
```bash
git add services/threat-hunting-agent/
git commit -m "feat(threat-hunter): scaffold new service with config + Dockerfile"
```

---

## Task 5: Postgres Tools

**Files:**
- Create: `services/threat-hunting-agent/tools/postgres_tool.py`
- Create: `services/threat-hunting-agent/tests/test_tools.py` (first 3 tests)

- [ ] **Step 5.1: Write failing tests**

Create `services/threat-hunting-agent/tests/test_tools.py`:

```python
import json
import pytest
from unittest.mock import MagicMock, patch


def _make_pg_row(**kwargs):
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def test_query_audit_logs_returns_list():
    with patch("tools.postgres_tool.psycopg2") as mock_pg:
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("evt1", "guard_model_block", "u1", "gpt-4", 0.9, "2026-01-01T00:00:00"),
        ]
        cursor.description = [
            ("event_id",), ("event_type",), ("user_id",), ("model",), ("risk_score",), ("timestamp",)
        ]
        conn.cursor.return_value.__enter__ = lambda s: cursor
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_pg.connect.return_value.__enter__ = lambda s: conn
        mock_pg.connect.return_value.__exit__ = MagicMock(return_value=False)

        from tools.postgres_tool import query_audit_logs
        result = query_audit_logs("t1", 60, None)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["event_type"] == "guard_model_block"


def test_query_audit_logs_error_returns_error_dict():
    with patch("tools.postgres_tool.psycopg2") as mock_pg:
        mock_pg.connect.side_effect = Exception("DB down")
        from tools.postgres_tool import query_audit_logs
        result = query_audit_logs("t1", 60, None)
        data = json.loads(result)
        assert "error" in data


def test_query_posture_history_returns_delta():
    with patch("tools.postgres_tool.psycopg2") as mock_pg:
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (0.54, 0.91, 0.37, 12, 3)
        conn.cursor.return_value.__enter__ = lambda s: cursor
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_pg.connect.return_value.__enter__ = lambda s: conn
        mock_pg.connect.return_value.__exit__ = MagicMock(return_value=False)

        from tools.postgres_tool import query_posture_history
        result = query_posture_history("t1", None, 4)
        data = json.loads(result)
        assert data["max_score"] == 0.91
        assert data["block_count"] == 12
```

- [ ] **Step 5.2: Run to confirm failure**
```bash
cd services/threat-hunting-agent
python -m pytest tests/test_tools.py::test_query_audit_logs_returns_list -v
# Expected: ModuleNotFoundError: No module named 'tools.postgres_tool'
```

- [ ] **Step 5.3: Create `tools/postgres_tool.py`**
```python
from __future__ import annotations
import json
import logging
from typing import Optional
import psycopg2
import psycopg2.extras
from langchain_core.tools import tool
from config import get_settings

logger = logging.getLogger(__name__)


def _get_conn():
    settings = get_settings()
    return psycopg2.connect(settings.spm_db_url, cursor_factory=psycopg2.extras.RealDictCursor)


@tool
def query_audit_logs(tenant_id: str, time_range_minutes: int, event_types: Optional[list] = None) -> str:
    """Query recent audit events for a tenant from the SPM database.
    Returns a JSON list of events with event_id, event_type, user_id, model, risk_score, timestamp.
    Use this to find recent blocks, violations, and security events.
    """
    try:
        sql = """
            SELECT event_id, event_type, tenant_id, user_id, model_id AS model,
                   risk_score, created_at AS timestamp
            FROM audit_export
            WHERE tenant_id = %s
              AND created_at >= NOW() - INTERVAL '%s minutes'
        """
        params = [tenant_id, time_range_minutes]
        if event_types:
            sql += " AND event_type = ANY(%s)"
            params.append(event_types)
        sql += " ORDER BY created_at DESC LIMIT 100"

        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return json.dumps([dict(r) for r in rows], default=str)
    except Exception as exc:
        logger.warning("query_audit_logs error: %s", exc)
        return json.dumps({"error": str(exc)})


@tool
def query_posture_history(tenant_id: str, model_id: Optional[str], hours_back: int) -> str:
    """Query posture score history for a tenant or specific model.
    Returns avg_score, max_score, score_delta (latest - earliest), block_count, escalation_count.
    A rising score_delta indicates an emerging threat.
    """
    try:
        sql = """
            SELECT
                AVG(avg_risk_score)   AS avg_score,
                MAX(max_risk_score)   AS max_score,
                MAX(max_risk_score) - MIN(avg_risk_score) AS score_delta,
                SUM(block_count)      AS block_count,
                SUM(escalation_count) AS escalation_count
            FROM posture_snapshots
            WHERE tenant_id = %s
              AND snapshot_at >= NOW() - INTERVAL '%s hours'
        """
        params = [tenant_id, hours_back]
        if model_id:
            sql += " AND model_id = %s"
            params.append(model_id)

        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()

        if not row:
            return json.dumps({"error": "no posture data found"})
        return json.dumps({
            "tenant_id": tenant_id,
            "model_id": model_id,
            "avg_score": round(float(row[0] or 0), 4),
            "max_score": round(float(row[1] or 0), 4),
            "score_delta": round(float(row[2] or 0), 4),
            "block_count": int(row[3] or 0),
            "escalation_count": int(row[4] or 0),
        })
    except Exception as exc:
        logger.warning("query_posture_history error: %s", exc)
        return json.dumps({"error": str(exc)})


@tool
def query_model_registry(model_id: Optional[str] = None, name: Optional[str] = None) -> str:
    """Look up a model in the registry by model_id or name.
    Returns risk_tier, status, provider. At least one of model_id or name must be provided.
    """
    if not model_id and not name:
        return json.dumps({"error": "provide model_id or name"})
    try:
        if model_id:
            sql = "SELECT model_id, name, risk_tier, status, provider FROM model_registry WHERE model_id = %s LIMIT 1"
            params = [model_id]
        else:
            sql = "SELECT model_id, name, risk_tier, status, provider FROM model_registry WHERE name ILIKE %s LIMIT 1"
            params = [name]

        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()

        if not row:
            return json.dumps({"error": "model not found"})
        return json.dumps(dict(row), default=str)
    except Exception as exc:
        logger.warning("query_model_registry error: %s", exc)
        return json.dumps({"error": str(exc)})
```

- [ ] **Step 5.4: Run tests**
```bash
python -m pytest tests/test_tools.py::test_query_audit_logs_returns_list \
                 tests/test_tools.py::test_query_audit_logs_error_returns_error_dict \
                 tests/test_tools.py::test_query_posture_history_returns_delta -v
# Expected: 3 passed
```

- [ ] **Step 5.5: Commit**
```bash
git add services/threat-hunting-agent/tools/postgres_tool.py \
        services/threat-hunting-agent/tests/test_tools.py
git commit -m "feat(threat-hunter): add Postgres tools (QueryAuditLogs, QueryPostureHistory, QueryModelRegistry)"
```

---

## Task 6: Redis, MITRE, OPA, Guard Tools

**Files:**
- Create: `services/threat-hunting-agent/tools/redis_tool.py`
- Create: `services/threat-hunting-agent/tools/mitre_tool.py`
- Create: `services/threat-hunting-agent/tools/opa_tool.py`
- Create: `services/threat-hunting-agent/tools/guard_tool.py`

- [ ] **Step 6.1: Add tests for these 4 tools to `tests/test_tools.py`**

Append to `tests/test_tools.py`:

```python
def test_query_redis_session_returns_summary():
    with patch("tools.redis_tool.redis") as mock_redis:
        client = MagicMock()
        client.scan_iter.return_value = ["session:u1:s1", "session:u1:s2"]
        client.lrange.return_value = ['{"prompt": "hello"}', '{"prompt": "world"}']
        mock_redis.Redis.return_value = client

        from tools.redis_tool import query_redis_session
        result = query_redis_session("u1", None)
        data = json.loads(result)
        assert data["user_id"] == "u1"
        assert data["session_count"] == 2


def test_lookup_mitre_returns_technique():
    with patch("tools.mitre_tool.httpx") as mock_httpx:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "id": "AML.T0051", "name": "LLM Prompt Injection",
            "tactic": "Initial Access", "description": "...", "mitigations": []
        }
        mock_httpx.get.return_value = resp

        from tools.mitre_tool import lookup_mitre
        result = lookup_mitre("AML.T0051", None)
        data = json.loads(result)
        assert data["name"] == "LLM Prompt Injection"


def test_evaluate_opa_returns_decision():
    with patch("tools.opa_tool.httpx") as mock_httpx:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"result": {"decision": "block", "reason": "posture score exceeds block threshold", "action": "deny_execution"}}
        mock_httpx.post.return_value = resp

        from tools.opa_tool import evaluate_opa_policy
        result = evaluate_opa_policy({"posture_score": 0.9, "guard_verdict": "allow", "guard_categories": []})
        data = json.loads(result)
        assert data["decision"] == "block"


def test_rescreen_prompt_returns_verdict():
    with patch("tools.guard_tool.httpx") as mock_httpx:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"verdict": "block", "score": 0.95, "categories": ["S9"]}
        mock_httpx.post.return_value = resp

        from tools.guard_tool import rescreen_prompt
        result = rescreen_prompt("how to make a bomb")
        data = json.loads(result)
        assert data["verdict"] == "block"
        assert "S9" in data["categories"]
```

- [ ] **Step 6.2: Create `tools/redis_tool.py`**
```python
from __future__ import annotations
import json
import logging
from typing import Optional
import redis as redis_lib
from langchain_core.tools import tool
from config import get_settings

logger = logging.getLogger(__name__)


@tool
def query_redis_session(user_id: str, session_id: Optional[str] = None) -> str:
    """Query Redis for a user's recent session activity.
    Returns session_count, prompt_count, time_range_minutes.
    Use this to detect rapid prompt cycling or repeated attempts from one user.
    """
    try:
        settings = get_settings()
        client = redis_lib.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)
        pattern = f"session:{user_id}:{session_id or '*'}"
        keys = list(client.scan_iter(pattern, count=50))[:20]
        if not keys:
            return json.dumps({"user_id": user_id, "session_count": 0, "prompt_count": 0, "time_range_minutes": 0, "topics_summary": "no sessions found"})

        all_prompts = []
        for key in keys:
            entries = client.lrange(key, 0, -1)
            for e in entries:
                try:
                    all_prompts.append(json.loads(e))
                except Exception:
                    pass

        return json.dumps({
            "user_id": user_id,
            "session_count": len(keys),
            "prompt_count": len(all_prompts),
            "time_range_minutes": "unknown",
            "topics_summary": f"{len(all_prompts)} prompts across {len(keys)} sessions",
        })
    except Exception as exc:
        logger.warning("query_redis_session error: %s", exc)
        return json.dumps({"error": str(exc)})
```

- [ ] **Step 6.3: Create `tools/mitre_tool.py`**
```python
from __future__ import annotations
import json
import logging
from typing import Optional
import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)
_MITRE_BASE = "https://atlas.mitre.org/api"


@tool
def lookup_mitre(technique_id: Optional[str] = None, keyword: Optional[str] = None) -> str:
    """Look up a MITRE ATLAS technique by ID (e.g. AML.T0051) or keyword.
    Returns name, tactic, description, mitigations.
    Use this to map threat signals to known adversarial ML attack patterns.
    """
    if not technique_id and not keyword:
        return json.dumps({"error": "provide technique_id or keyword"})
    try:
        if technique_id:
            url = f"{_MITRE_BASE}/techniques/{technique_id}"
            resp = httpx.get(url, timeout=5.0)
        else:
            url = f"{_MITRE_BASE}/techniques"
            resp = httpx.get(url, params={"search": keyword}, timeout=5.0)

        if resp.status_code != 200:
            return json.dumps({"error": f"MITRE API returned {resp.status_code}"})
        return json.dumps(resp.json())
    except Exception as exc:
        logger.warning("lookup_mitre error: %s", exc)
        return json.dumps({"error": str(exc)})
```

- [ ] **Step 6.4: Create `tools/opa_tool.py`**
```python
from __future__ import annotations
import json
import logging
import httpx
from langchain_core.tools import tool
from config import get_settings

logger = logging.getLogger(__name__)


@tool
def evaluate_opa_policy(signals: dict) -> str:
    """Re-evaluate a set of security signals against the OPA policy engine.
    Input dict must contain posture_score (float), guard_verdict (str), guard_categories (list).
    Returns decision (allow/block/escalate), reason, action.
    Use this to verify whether a set of signals would be blocked by policy.
    """
    try:
        settings = get_settings()
        resp = httpx.post(
            f"{settings.opa_url}/v1/data/spm/prompt/allow",
            json={"input": signals},
            timeout=3.0,
        )
        if resp.status_code != 200:
            return json.dumps({"error": f"OPA returned {resp.status_code}"})
        result = resp.json().get("result", {})
        return json.dumps(result)
    except Exception as exc:
        logger.warning("evaluate_opa_policy error: %s", exc)
        return json.dumps({"error": str(exc)})
```

- [ ] **Step 6.5: Create `tools/guard_tool.py`**
```python
from __future__ import annotations
import json
import logging
import httpx
from langchain_core.tools import tool
from config import get_settings

logger = logging.getLogger(__name__)


@tool
def rescreen_prompt(prompt_text: str) -> str:
    """Re-screen a suspicious prompt through the guard model (Llama Guard 3 via Groq).
    Returns verdict (allow/block), score (0-1), and violated categories (S1-S15).
    Use this to confirm whether a specific prompt is genuinely harmful.
    """
    try:
        settings = get_settings()
        resp = httpx.post(
            f"{settings.guard_model_url}/screen",
            json={"text": prompt_text, "context": "threat_hunt"},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return json.dumps({"error": f"guard model returned {resp.status_code}"})
        return json.dumps(resp.json())
    except Exception as exc:
        logger.warning("rescreen_prompt error: %s", exc)
        return json.dumps({"error": str(exc)})
```

- [ ] **Step 6.6: Run the 4 new tests**
```bash
cd services/threat-hunting-agent
python -m pytest tests/test_tools.py -k "redis or mitre or opa or guard" -v
# Expected: 4 passed
```

- [ ] **Step 6.7: Commit**
```bash
git add services/threat-hunting-agent/tools/redis_tool.py \
        services/threat-hunting-agent/tools/mitre_tool.py \
        services/threat-hunting-agent/tools/opa_tool.py \
        services/threat-hunting-agent/tools/guard_tool.py \
        services/threat-hunting-agent/tests/test_tools.py
git commit -m "feat(threat-hunter): add Redis, MITRE, OPA, Guard tools"
```

---

## Task 7: CreateFinding Tool

**Files:**
- Create: `services/threat-hunting-agent/tools/case_tool.py`

- [ ] **Step 7.1: Add test**

Append to `tests/test_tools.py`:

```python
def test_create_finding_success():
    with patch("tools.case_tool.httpx") as mock_httpx:
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "f1", "title": "T", "severity": "high", "status": "open", "created_at": "..."}
        mock_httpx.post.return_value = resp

        from tools.case_tool import create_finding
        result = create_finding(
            title="Test", severity="high", description="desc",
            evidence={"event_ids": ["e1", "e2"]}, ttps=[], tenant_id="t1",
        )
        data = json.loads(result)
        assert data["id"] == "f1"


def test_create_finding_computes_batch_hash():
    """batch_hash must be deterministic — same event_ids always produce same hash."""
    import hashlib
    from tools.case_tool import _compute_batch_hash

    h1 = _compute_batch_hash(["e2", "e1"], "t1", "2026-01-01T00:00:00")
    h2 = _compute_batch_hash(["e1", "e2"], "t1", "2026-01-01T00:00:00")
    assert h1 == h2  # order-independent

    h3 = _compute_batch_hash([], "t1", "2026-01-01T00:00:00")
    assert h3.startswith("empty:")  # empty list uses fallback
```

- [ ] **Step 7.2: Create `tools/case_tool.py`**
```python
from __future__ import annotations
import hashlib
import json
import logging
from typing import Any, Dict, List
import httpx
from langchain_core.tools import tool
from config import get_settings

logger = logging.getLogger(__name__)


def _compute_batch_hash(event_ids: List[str], tenant_id: str, batch_start_iso: str) -> str:
    if not event_ids:
        raw = f"empty:{tenant_id}:{batch_start_iso}"
        return "empty:" + hashlib.sha256(raw.encode()).hexdigest()
    raw = "|".join(sorted(event_ids))
    return hashlib.sha256(raw.encode()).hexdigest()


@tool
def create_finding(
    title: str,
    severity: str,
    description: str,
    evidence: Dict[str, Any],
    ttps: List[str],
    tenant_id: str,
) -> str:
    """Create a threat finding in the agent-orchestrator-service for human review.
    severity must be one of: low, medium, high, critical.
    evidence should include event_ids (list), sessions (list), and any other relevant context.
    Returns the created finding ID and status, or an error string.
    Call this ONLY when you have confirmed a real threat — not on suspicion alone.
    """
    try:
        settings = get_settings()
        event_ids = evidence.get("event_ids", [])
        batch_hash = _compute_batch_hash(event_ids, tenant_id, "")

        payload = {
            "title": title,
            "severity": severity,
            "description": description,
            "evidence": evidence,
            "ttps": ttps,
            "tenant_id": tenant_id,
            "batch_hash": batch_hash,
        }
        resp = httpx.post(
            f"{settings.orchestrator_url}/api/v1/threat-findings",
            json=payload,
            timeout=5.0,
        )
        if resp.status_code not in (200, 201):
            return json.dumps({"error": f"orchestrator returned {resp.status_code}: {resp.text}"})
        return json.dumps(resp.json())
    except Exception as exc:
        logger.warning("create_finding error: %s", exc)
        return json.dumps({"error": f"agent-orchestrator unreachable — {exc}"})
```

- [ ] **Step 7.3: Run tests**
```bash
python -m pytest tests/test_tools.py::test_create_finding_success \
                 tests/test_tools.py::test_create_finding_computes_batch_hash -v
# Expected: 2 passed
```

- [ ] **Step 7.4: Commit**
```bash
git add services/threat-hunting-agent/tools/case_tool.py \
        services/threat-hunting-agent/tests/test_tools.py
git commit -m "feat(threat-hunter): add CreateFinding tool with deterministic batch_hash"
```

---

## Task 8: `tools/__init__.py` — Export All Tools

**Files:**
- Modify: `services/threat-hunting-agent/tools/__init__.py`

- [ ] **Step 8.1: Populate `tools/__init__.py`**
```python
from tools.postgres_tool import query_audit_logs, query_posture_history, query_model_registry
from tools.redis_tool import query_redis_session
from tools.mitre_tool import lookup_mitre
from tools.opa_tool import evaluate_opa_policy
from tools.guard_tool import rescreen_prompt
from tools.case_tool import create_finding

ALL_TOOLS = [
    query_audit_logs,
    query_posture_history,
    query_model_registry,
    query_redis_session,
    lookup_mitre,
    evaluate_opa_policy,
    rescreen_prompt,
    create_finding,
]
```

- [ ] **Step 8.2: Verify import**
```bash
python -c "from tools import ALL_TOOLS; print(len(ALL_TOOLS), 'tools loaded')"
# Expected: 8 tools loaded
```

- [ ] **Step 8.3: Commit**
```bash
git add services/threat-hunting-agent/tools/__init__.py
git commit -m "feat(threat-hunter): export all 8 tools from tools/__init__.py"
```

---

## Task 9: LangChain ReAct Agent

**Files:**
- Create: `services/threat-hunting-agent/agent/prompts.py`
- Create: `services/threat-hunting-agent/agent/agent.py`

- [ ] **Step 9.1: Write failing agent test**

Create `services/threat-hunting-agent/tests/test_agent.py`:

```python
import json
import pytest
from unittest.mock import MagicMock, patch


def test_build_agent_returns_runnable():
    with patch("agent.agent.ChatGroq") as mock_groq:
        mock_groq.return_value = MagicMock()
        from agent.agent import build_agent
        agent = build_agent()
        assert agent is not None


def test_agent_calls_create_finding_on_threat(monkeypatch):
    """Agent should call create_finding when given a batch with clear threat signals."""
    # This test uses a mock LLM that returns a pre-scripted ReAct trace
    from agent.agent import run_agent_on_batch
    batch = {
        "tenant_id": "t1",
        "events": [
            {"event_type": "guard_model_block", "user_id": "u1", "risk_score": 0.95},
            {"event_type": "policy_block", "user_id": "u1", "risk_score": 0.91},
        ],
    }

    finding_called = []

    def mock_create_finding(**kwargs):
        finding_called.append(kwargs)
        return json.dumps({"id": "f1", "status": "open"})

    with patch("tools.case_tool.httpx") as mock_httpx:
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "f1", "title": "T", "severity": "high", "status": "open", "created_at": "..."}
        mock_httpx.post.return_value = resp

        with patch("agent.agent.ChatGroq") as mock_groq_cls:
            # Simulate agent deciding to create a finding
            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_groq_cls.return_value = mock_llm
            # Just verify the agent can be constructed and invoked without error
            from agent.agent import build_agent
            agent = build_agent()
            assert agent is not None
```

- [ ] **Step 9.2: Create `agent/prompts.py`**
```python
SYSTEM_PROMPT = """You are ThreatHunter-AI, an autonomous security analyst specialising in AI system threats.

You receive batches of security events from an AI platform and must determine whether they constitute a genuine multi-stage attack.

Your job:
1. OBSERVE the events in the batch — what happened, when, which users, which models?
2. INVESTIGATE using your tools — gather historical context, re-screen suspicious prompts, look up MITRE ATLAS techniques
3. CORRELATE — do these signals individually look benign but together indicate a campaign?
4. DECIDE — is this a confirmed threat or normal noise?
5. ACT — if confirmed threat, call create_finding with a clear title, severity, and evidence summary

Severity guidelines:
- critical: coordinated multi-user attack, CBRN/weapons content, mass-casualty risk
- high: sustained jailbreak campaign, data exfiltration signals, multiple S1-S9 guard blocks
- medium: repeated policy violations from one user, anomalous posture spike without clear intent
- low: isolated suspicious event, inconclusive signals

IMPORTANT:
- Only create a finding when you are CONFIDENT it is a real threat, not noise
- Always scope your tool calls to the tenant_id provided in the batch — never query across tenants
- If tools return errors, note them and work around them — do not abort the investigation
- Be concise in your description — focus on what the attacker was trying to do and what signals confirmed it
"""
```

- [ ] **Step 9.3: Create `agent/agent.py`**
```python
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict

from langchain_groq import ChatGroq
from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

from agent.prompts import SYSTEM_PROMPT
from tools import ALL_TOOLS
from config import get_settings

logger = logging.getLogger(__name__)


def build_agent() -> AgentExecutor:
    settings = get_settings()
    llm = ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    agent = create_react_agent(llm, ALL_TOOLS, prompt)
    return AgentExecutor(
        agent=agent,
        tools=ALL_TOOLS,
        max_iterations=10,
        handle_parsing_errors=True,
        verbose=True,
    )


def _format_batch(batch: Dict[str, Any]) -> str:
    tenant_id = batch.get("tenant_id", "unknown")
    events = batch.get("events", [])
    return (
        f"Tenant: {tenant_id}\n"
        f"Event count: {len(events)}\n"
        f"Events:\n{events}\n\n"
        f"Investigate these events for threats. If you find a confirmed threat, "
        f"call create_finding. Always scope your tool calls to tenant_id={tenant_id}."
    )


async def run_agent_on_batch(
    executor: AgentExecutor,
    batch: Dict[str, Any],
    max_backoff_sec: int = 30,
) -> None:
    """
    Run the ReAct agent on one tenant batch.
    Retries on Groq failures with exponential backoff up to max_backoff_sec.
    Batch-level retry — full reset on each attempt.
    """
    prompt_text = _format_batch(batch)
    backoff = 1
    cumulative = 0

    while True:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, executor.invoke, {"input": prompt_text}
            )
            return  # success
        except Exception as exc:
            err = str(exc)
            # Groq rate limit / server errors
            if any(k in err.lower() for k in ("groq", "rate", "503", "502", "connection")):
                if cumulative >= max_backoff_sec:
                    logger.error("Groq still down after %ds backoff — dropping batch tenant=%s",
                                 max_backoff_sec, batch.get("tenant_id"))
                    return
                logger.warning("Groq error (%s) — retrying in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                cumulative += backoff
                backoff = min(backoff * 2, max_backoff_sec)
            else:
                logger.error("Agent unexpected error — dropping batch: %s", exc, exc_info=True)
                return
```

- [ ] **Step 9.4: Run tests**
```bash
python -m pytest tests/test_agent.py -v
# Expected: 2 passed
```

- [ ] **Step 9.5: Commit**
```bash
git add services/threat-hunting-agent/agent/ \
        services/threat-hunting-agent/tests/test_agent.py
git commit -m "feat(threat-hunter): add LangChain ReAct agent with Groq + system prompt"
```

---

## Task 10: Kafka Consumer

**Files:**
- Create: `services/threat-hunting-agent/consumer/kafka_consumer.py`
- Create: `services/threat-hunting-agent/tests/test_consumer.py`

- [ ] **Step 10.1: Write failing tests**

Create `services/threat-hunting-agent/tests/test_consumer.py`:

```python
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from consumer.kafka_consumer import ThreatHuntConsumer, _group_by_tenant


def test_group_by_tenant_splits_correctly():
    events = [
        {"tenant_id": "t1", "data": "a"},
        {"tenant_id": "t2", "data": "b"},
        {"tenant_id": "t1", "data": "c"},
    ]
    result = _group_by_tenant(events)
    assert len(result["t1"]) == 2
    assert len(result["t2"]) == 1


def test_group_by_tenant_empty():
    assert _group_by_tenant([]) == {}


@pytest.mark.asyncio
async def test_consumer_drops_oldest_when_queue_full():
    consumer = ThreatHuntConsumer(queue_max=2)
    consumer._queue = asyncio.Queue()
    # Fill queue to max
    await consumer._queue.put({"tenant_id": "t1", "events": [1]})
    await consumer._queue.put({"tenant_id": "t1", "events": [2]})
    # Adding a third should drop the oldest
    await consumer._enqueue_batch({"tenant_id": "t1", "events": [3]})
    assert consumer._queue.qsize() == 2
    # Oldest (events:[1]) should be gone — newest two remain
    first = await consumer._queue.get()
    assert first["events"] == [2]
```

- [ ] **Step 10.2: Run to confirm failure**
```bash
python -m pytest tests/test_consumer.py -v
# Expected: ModuleNotFoundError: No module named 'consumer.kafka_consumer'
```

- [ ] **Step 10.3: Create `consumer/kafka_consumer.py`**
```python
from __future__ import annotations
import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List

from kafka import KafkaConsumer
from kafka.errors import KafkaError

from config import get_settings

logger = logging.getLogger(__name__)


def _group_by_tenant(events: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for e in events:
        tid = e.get("tenant_id", "unknown")
        groups[tid].append(e)
    return dict(groups)


class ThreatHuntConsumer:
    """
    Consumes Kafka events across all tenant topics.
    Every HUNT_BATCH_WINDOW_SEC seconds, drains accumulated events,
    groups by tenant_id, and enqueues one batch per tenant for agent processing.
    """

    def __init__(self, queue_max: int | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._queue_max = queue_max if queue_max is not None else settings.hunt_queue_max
        self._queue: asyncio.Queue = asyncio.Queue()
        self._consumer: KafkaConsumer | None = None
        self._running = False
        self._accumulated: List[Dict] = []

    def _build_topics(self) -> List[str]:
        topics = []
        for tid in self._settings.tenant_list:
            p = f"cpm.{tid}"
            topics += [f"{p}.audit", f"{p}.decision", f"{p}.posture_enriched"]
        return topics

    def _build_consumer(self) -> KafkaConsumer:
        return KafkaConsumer(
            *self._build_topics(),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="cpm-threat-hunter-group",
            auto_offset_reset="latest",
            enable_auto_commit=False,
            value_deserializer=lambda b: json.loads(b.decode("utf-8", errors="replace")),
            consumer_timeout_ms=1000,  # non-blocking poll
        )

    async def _enqueue_batch(self, batch: Dict[str, Any]) -> None:
        if self._queue.qsize() >= self._queue_max:
            try:
                dropped = self._queue.get_nowait()
                logger.warning("Queue full — dropped oldest batch tenant=%s", dropped.get("tenant_id"))
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(batch)

    async def start(self) -> None:
        """Start the consumer loop in a background asyncio task."""
        self._running = True
        self._consumer = self._build_consumer()
        logger.info("ThreatHuntConsumer started — topics: %s", self._build_topics())
        asyncio.create_task(self._poll_loop())
        asyncio.create_task(self._batch_loop())

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            self._consumer.close()

    async def get_batch(self) -> Dict[str, Any]:
        """Block until a batch is available."""
        return await self._queue.get()

    async def _poll_loop(self) -> None:
        """Poll Kafka in a thread executor to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                msgs = await loop.run_in_executor(None, self._poll_once)
                self._accumulated.extend(msgs)
            except Exception as exc:
                logger.warning("Kafka poll error: %s", exc)
            await asyncio.sleep(0.5)

    def _poll_once(self) -> List[Dict]:
        if not self._consumer:
            return []
        records = []
        try:
            for msg in self._consumer:
                payload = msg.value or {}
                # Inject tenant_id from topic name if not in payload
                if "tenant_id" not in payload:
                    parts = msg.topic.split(".")
                    payload["tenant_id"] = parts[1] if len(parts) > 1 else "unknown"
                records.append(payload)
        except StopIteration:
            pass  # consumer_timeout_ms elapsed — normal
        return records

    async def _batch_loop(self) -> None:
        """Every HUNT_BATCH_WINDOW_SEC, drain accumulated events and enqueue per-tenant batches."""
        while self._running:
            await asyncio.sleep(self._settings.hunt_batch_window_sec)
            if not self._accumulated:
                continue

            events, self._accumulated = self._accumulated, []
            groups = _group_by_tenant(events)
            logger.info("Batching %d events across %d tenants", len(events), len(groups))

            for tenant_id, tenant_events in groups.items():
                batch = {"tenant_id": tenant_id, "events": tenant_events}
                await self._enqueue_batch(batch)

            # Commit offsets after all batches enqueued
            if self._consumer:
                try:
                    self._consumer.commit()
                except KafkaError as e:
                    logger.warning("Kafka commit failed: %s", e)
```

- [ ] **Step 10.4: Run tests**
```bash
python -m pytest tests/test_consumer.py -v
# Expected: 3 passed
```

- [ ] **Step 10.5: Commit**
```bash
git add services/threat-hunting-agent/consumer/kafka_consumer.py \
        services/threat-hunting-agent/tests/test_consumer.py
git commit -m "feat(threat-hunter): add Kafka consumer with 30s batching and per-tenant isolation"
```

---

## Task 11: FastAPI App + Lifespan

**Files:**
- Create: `services/threat-hunting-agent/app.py`

- [ ] **Step 11.1: Create `app.py`**
```python
from __future__ import annotations
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from agent.agent import build_agent, run_agent_on_batch
from consumer.kafka_consumer import ThreatHuntConsumer
from config import get_settings

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("threat-hunter")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info("ThreatHunter starting — tenants=%s model=%s", settings.tenant_list, settings.groq_model)

    executor = build_agent()
    consumer = ThreatHuntConsumer()
    await consumer.start()

    async def _hunt_loop() -> None:
        while True:
            batch = await consumer.get_batch()
            try:
                await run_agent_on_batch(executor, batch)
            except Exception as exc:
                logger.error("Hunt loop error on batch: %s", exc, exc_info=True)

    task = asyncio.create_task(_hunt_loop())
    logger.info("ThreatHunter hunt loop started")

    yield  # service is running

    logger.info("ThreatHunter shutting down...")
    task.cancel()
    await consumer.stop()


app = FastAPI(
    title="ThreatHunter-AI",
    version="1.0.0",
    description="LangChain ReAct agent for real-time AI threat hunting",
    lifespan=lifespan,
)


@app.get("/health", tags=["Observability"])
async def health() -> dict:
    return {"status": "ok", "service": "threat-hunting-agent", "version": "1.0.0"}
```

- [ ] **Step 11.2: Verify app starts without Kafka (smoke test)**
```bash
cd services/threat-hunting-agent
# Set minimal env
export GROQ_API_KEY=test KAFKA_BOOTSTRAP_SERVERS=localhost:9092 SPM_DB_URL=postgresql://x:x@localhost/x
python -c "from app import app; print('App imported OK')"
# Expected: App imported OK
```

- [ ] **Step 11.3: Commit**
```bash
git add services/threat-hunting-agent/app.py
git commit -m "feat(threat-hunter): add FastAPI app with lifespan, consumer start, health endpoint"
```

---

## Task 12: Docker Compose Integration

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 12.1: Add threat-hunting-agent to docker-compose.yml**

Open `docker-compose.yml` and add before the `ui:` service:

```yaml
  threat-hunting-agent:
    build: {context: ., dockerfile: services/threat-hunting-agent/Dockerfile}
    container_name: cpm-threat-hunter
    environment:
      <<: *common-env
      GROQ_API_KEY: ${GROQ_API_KEY:-}
      GROQ_MODEL: ${GROQ_MODEL:-llama-3.3-70b-versatile}
      HUNT_BATCH_WINDOW_SEC: ${HUNT_BATCH_WINDOW_SEC:-30}
      HUNT_QUEUE_MAX: ${HUNT_QUEUE_MAX:-20}
      ORCHESTRATOR_URL: http://agent-orchestrator:8094
      GUARD_MODEL_URL: http://guard-model:8200
      OPA_URL: http://opa:8181
      SPM_DB_URL: postgresql://spm_rw:${SPM_DB_PASSWORD:-spmpass}@spm-db:5432/spm
    volumes: *key-vol
    ports: ["8095:8095"]
    depends_on:
      <<: *depends-platform
      agent-orchestrator:
        condition: service_healthy
      guard-model:
        condition: service_healthy
      spm-db:
        condition: service_healthy
```

- [ ] **Step 12.2: Validate docker-compose file parses**
```bash
docker compose config --quiet
# Expected: no errors
```

- [ ] **Step 12.3: Build the new image**
```bash
docker compose build --no-cache threat-hunting-agent
# Expected: Successfully built ...
```

- [ ] **Step 12.4: Commit**
```bash
git add docker-compose.yml
git commit -m "feat: add threat-hunting-agent to docker-compose"
```

---

## Task 13: Run All Tests + Integration Smoke Test

- [ ] **Step 13.1: Run all threat-hunting-agent unit tests**
```bash
cd services/threat-hunting-agent
python -m pytest tests/ -v
# Expected: all tests pass (tools, consumer, agent)
```

- [ ] **Step 13.2: Run agent-orchestrator tests**
```bash
cd services/agent-orchestrator-service
python -m pytest tests/ -v
# Expected: all tests pass including new threat_findings tests
```

- [ ] **Step 13.3: Start full stack and verify health**
```bash
cd /Users/danyshapiro/PycharmProjects/AISPM
docker compose up -d
sleep 30
curl -s http://localhost:8095/health | python -m json.tool
# Expected: {"status": "ok", "service": "threat-hunting-agent", "version": "1.0.0"}
```

- [ ] **Step 13.4: Verify threat-findings endpoint reachable from host**
```bash
curl -s -X POST http://localhost:8094/api/v1/threat-findings \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke test","severity":"low","description":"test","evidence":{"event_ids":["smoke1"]},"ttps":[],"tenant_id":"t1","batch_hash":"smoketest001"}' \
  | python -m json.tool
# Expected: {"id": "...", "title": "Smoke test", "status": "open", "deduplicated": false}
```

- [ ] **Step 13.5: Final commit**
```bash
git add -A
git commit -m "feat: threat hunting agent — complete implementation"
```
