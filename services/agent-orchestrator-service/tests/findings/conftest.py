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
