"""Integration tests for ThreatFindingRepository against SQLite in-memory."""
from __future__ import annotations
import pytest
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
