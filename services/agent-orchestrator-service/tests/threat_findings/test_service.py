import pytest
from unittest.mock import AsyncMock, call
from threat_findings.service import ThreatFindingsService
from threat_findings.schemas import CreateFindingRequest


@pytest.fixture
def svc():
    return ThreatFindingsService()


def _make_repos():
    """Return (finding_repo, case_repo) mocks."""
    finding_repo = AsyncMock()
    finding_repo.get_by_batch_hash.return_value = None
    finding_repo.insert.return_value = None
    case_repo = AsyncMock()
    case_repo.insert.return_value = None
    return finding_repo, case_repo


@pytest.mark.asyncio
async def test_create_finding_returns_record(svc):
    finding_repo, case_repo = _make_repos()

    req = CreateFindingRequest(
        title="Test finding",
        severity="high",
        description="desc",
        evidence=["e1"],
        ttps=["AML.T0051"],
        tenant_id="t1",
        batch_hash="abc123",
    )
    result = await svc.create_finding(req, finding_repo, case_repo)
    assert result.title == "Test finding"
    assert result.status == "open"
    assert result.deduplicated is False
    finding_repo.insert.assert_called_once()


@pytest.mark.asyncio
async def test_create_finding_opens_a_case(svc):
    """A new finding must also insert a CaseRecord so the notification bell fires."""
    finding_repo, case_repo = _make_repos()

    req = CreateFindingRequest(
        title="Prompt injection detected",
        severity="critical",
        description="desc",
        evidence=[],
        ttps=["AML.T0051"],
        tenant_id="t1",
        batch_hash="hash-critical",
    )
    await svc.create_finding(req, finding_repo, case_repo)

    # Case must be inserted
    case_repo.insert.assert_called_once()
    inserted_case = case_repo.insert.call_args[0][0]
    assert inserted_case.session_id.startswith("threat-hunt:")
    assert "CRITICAL" in inserted_case.reason
    assert "Prompt injection detected" in inserted_case.reason
    assert inserted_case.risk_score == 0.95
    assert inserted_case.decision == "block"


@pytest.mark.asyncio
async def test_severity_maps_to_correct_risk_score(svc):
    """Each severity maps to the expected risk score."""
    expected = {"low": 0.25, "medium": 0.55, "high": 0.80, "critical": 0.95}
    for severity, score in expected.items():
        finding_repo, case_repo = _make_repos()
        req = CreateFindingRequest(
            title="T", severity=severity, description="D",
            evidence=[], ttps=[], tenant_id="t1",
            batch_hash=f"hash-{severity}",
        )
        await svc.create_finding(req, finding_repo, case_repo)
        case = case_repo.insert.call_args[0][0]
        assert case.risk_score == score, f"severity={severity}"


@pytest.mark.asyncio
async def test_create_finding_deduplicates(svc):
    """A duplicate finding must NOT create a new case."""
    from threat_findings.schemas import FindingRecord
    from datetime import datetime, timezone
    existing = FindingRecord(
        id="existing-id", batch_hash="abc123", title="old",
        severity="low", description="d", evidence=[], ttps=[],
        tenant_id="t1", status="open",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    finding_repo = AsyncMock()
    finding_repo.get_by_batch_hash.return_value = existing
    case_repo = AsyncMock()

    req = CreateFindingRequest(
        title="New title", severity="high", description="desc",
        evidence=[], ttps=[], tenant_id="t1", batch_hash="abc123",
    )
    result = await svc.create_finding(req, finding_repo, case_repo)
    assert result.id == "existing-id"
    assert result.deduplicated is True
    finding_repo.insert.assert_not_called()
    # No new case for a deduplicated finding
    case_repo.insert.assert_not_called()
