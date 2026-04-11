import pytest
from unittest.mock import AsyncMock
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
    repo.insert.assert_called_once()


@pytest.mark.asyncio
async def test_create_finding_deduplicates(svc):
    from threat_findings.schemas import FindingRecord
    from datetime import datetime, timezone
    existing = FindingRecord(
        id="existing-id", batch_hash="abc123", title="old",
        severity="low", description="d", evidence={}, ttps=[],
        tenant_id="t1", status="open",
        created_at=datetime.now(timezone.utc).isoformat(),
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
