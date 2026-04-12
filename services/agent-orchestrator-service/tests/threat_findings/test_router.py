import pytest
from dataclasses import dataclass, field
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

from main import create_app
from threat_findings.router import get_case_repo, get_finding_repo, get_findings_service
from threat_findings.schemas import FindingRecord
from dependencies.rbac import require_session_override


# ── Minimal stub IdentityContext for tests ────────────────────────────────────
@dataclass
class _MockIdentity:
    user_id: str = "threat-hunter-svc"
    roles:   list = field(default_factory=lambda: ["admin"])
    groups:  list = field(default_factory=list)


def _make_record(deduplicated: bool = False) -> FindingRecord:
    return FindingRecord(
        id="test-id", batch_hash="h1", title="T", severity="high",
        description="D", evidence={}, ttps=[], tenant_id="t1",
        deduplicated=deduplicated,
    )


@pytest.fixture
async def client():
    app = create_app()

    mock_repo      = AsyncMock()
    mock_case_repo = AsyncMock()
    mock_svc       = AsyncMock()

    # Override all injected dependencies — correct FastAPI pattern
    app.dependency_overrides[get_finding_repo]         = lambda: mock_repo
    app.dependency_overrides[get_case_repo]            = lambda: mock_case_repo
    app.dependency_overrides[get_findings_service]     = lambda: mock_svc
    app.dependency_overrides[require_session_override] = lambda: _MockIdentity()

    app._mock_svc       = mock_svc
    app._mock_repo      = mock_repo
    app._mock_case_repo = mock_case_repo

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c._app = app
        yield c


@pytest.mark.asyncio
async def test_create_finding_201(client):
    client._app._mock_svc.create_finding.return_value = _make_record(deduplicated=False)

    resp = await client.post("/api/v1/threat-findings", json={
        "title": "T", "severity": "high", "description": "D",
        "evidence": {}, "ttps": [], "tenant_id": "t1", "batch_hash": "h1",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "test-id"
    assert data["deduplicated"] is False


@pytest.mark.asyncio
async def test_create_finding_200_deduplicated(client):
    """Duplicate batch_hash returns HTTP 200 with the existing record."""
    client._app._mock_svc.create_finding.return_value = _make_record(deduplicated=True)

    resp = await client.post("/api/v1/threat-findings", json={
        "title": "T", "severity": "high", "description": "D",
        "evidence": {}, "ttps": [], "tenant_id": "t1", "batch_hash": "h1",
    })
    assert resp.status_code == 200
    assert resp.json()["deduplicated"] is True


@pytest.mark.asyncio
async def test_create_finding_401_no_token(client):
    """Without the auth override, a missing token returns 401."""
    del client._app.dependency_overrides[require_session_override]

    resp = await client.post("/api/v1/threat-findings", json={
        "title": "T", "severity": "high", "description": "D",
        "evidence": {}, "ttps": [], "tenant_id": "t1", "batch_hash": "h1",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_finding_422_bad_severity(client):
    resp = await client.post("/api/v1/threat-findings", json={
        "title": "T", "severity": "extreme", "description": "D",
        "evidence": {}, "ttps": [], "tenant_id": "t1", "batch_hash": "h1",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_finding_passes_case_repo_to_service(client):
    """Router must pass case_repo so the service can open a case."""
    client._app._mock_svc.create_finding.return_value = _make_record(deduplicated=False)

    await client.post("/api/v1/threat-findings", json={
        "title": "T", "severity": "high", "description": "D",
        "evidence": {}, "ttps": [], "tenant_id": "t1", "batch_hash": "h1",
    })
    # Service was called with (body, repo, case_repo)
    call_args = client._app._mock_svc.create_finding.call_args
    assert call_args is not None
    # Third positional arg should be the case_repo mock
    _, kwargs = call_args
    positional = call_args[0]
    assert len(positional) == 3, "create_finding must receive (req, repo, case_repo)"
