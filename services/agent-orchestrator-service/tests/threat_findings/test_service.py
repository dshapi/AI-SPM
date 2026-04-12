import pytest
from unittest.mock import AsyncMock, MagicMock, call
from threat_findings.service import ThreatFindingsService
from threat_findings.schemas import CreateFindingRequest, FindingRecord
from threat_findings.models import ThreatFindingRepository


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
async def test_create_finding_opens_a_case_when_flagged(svc):
    """A finding with should_open_case=True must insert a CaseRecord."""
    finding_repo, case_repo = _make_repos()

    req = CreateFindingRequest(
        title="Prompt injection detected",
        severity="critical",
        description="desc",
        evidence=[],
        ttps=["AML.T0051"],
        tenant_id="t1",
        batch_hash="hash-critical",
        should_open_case=True,
    )
    result = await svc.create_finding(req, finding_repo, case_repo)

    # Case must be inserted and linked
    case_repo.insert.assert_called_once()
    inserted_case = case_repo.insert.call_args[0][0]
    assert inserted_case.session_id.startswith("threat-hunt:")
    assert "CRITICAL" in inserted_case.reason
    assert "Prompt injection detected" in inserted_case.reason
    assert inserted_case.risk_score == 0.95
    assert inserted_case.decision == "block"
    # case_id must be linked back
    assert result.case_id == inserted_case.case_id


@pytest.mark.asyncio
async def test_create_finding_no_case_when_not_flagged(svc):
    """A finding with should_open_case=False must NOT insert a CaseRecord."""
    finding_repo, case_repo = _make_repos()

    req = CreateFindingRequest(
        title="Low signal event",
        severity="low",
        description="desc",
        evidence=[],
        ttps=[],
        tenant_id="t1",
        batch_hash="hash-low",
        should_open_case=False,
    )
    await svc.create_finding(req, finding_repo, case_repo)
    case_repo.insert.assert_not_called()


@pytest.mark.asyncio
async def test_severity_maps_to_correct_risk_score(svc):
    """Each severity maps to the expected risk score (with should_open_case=True)."""
    expected = {"low": 0.25, "medium": 0.55, "high": 0.80, "critical": 0.95}
    for severity, score in expected.items():
        finding_repo, case_repo = _make_repos()
        req = CreateFindingRequest(
            title="T", severity=severity, description="D",
            evidence=[], ttps=[], tenant_id="t1",
            batch_hash=f"hash-{severity}",
            should_open_case=True,
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


# ── Tests for new ThreatFindingsService methods ──────────────────────────────

def _new_repo(existing=None):
    """Return a ThreatFindingRepository mock for new service methods."""
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
        repo = _new_repo(existing=None)
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
        repo = _new_repo(existing=existing_rec)
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
        repo = _new_repo()
        await svc.link_case("fid1", "case-x", repo)
        repo.attach_case.assert_called_once_with("fid1", "case-x")

    @pytest.mark.asyncio
    async def test_mark_status_calls_update(self):
        svc = ThreatFindingsService()
        repo = _new_repo()
        await svc.mark_status("fid1", "investigating", repo)
        repo.update_status.assert_called_once_with("fid1", "investigating")


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


@pytest.mark.asyncio
async def test_create_finding_stores_source_and_is_proactive(svc):
    """source and is_proactive from request must reach the inserted FindingRecord."""
    finding_repo, case_repo = _make_repos()
    req = CreateFindingRequest(
        title="ThreatHunting AI proactive finding",
        severity="medium",
        description="desc",
        evidence=[],
        ttps=[],
        tenant_id="t1",
        batch_hash="hash-threathunting-ai",
        source="threathunting_ai",
        is_proactive=True,
    )
    await svc.create_finding(req, finding_repo, case_repo)
    inserted = finding_repo.insert.call_args[0][0]
    assert inserted.source == "threathunting_ai"
    assert inserted.is_proactive is True
