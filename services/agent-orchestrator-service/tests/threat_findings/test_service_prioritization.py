"""
tests/threat_findings/test_service_prioritization.py
─────────────────────────────────────────────────────
Integration tests verifying that persist_finding_from_dict() runs
the PrioritizationEngine and stores dedup/group/rank/suppress fields.

All SQLAlchemy I/O is mocked; no live DB required.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from threat_findings.service import ThreatFindingsService
from threat_findings.schemas import FindingRecord


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_finding_dict(**overrides) -> dict:
    base = {
        "title": "Unusual exfil attempt",
        "severity": "high",
        "hypothesis": "Actor is probing for PII",
        "evidence": [{"key": "val"}],
        "triggered_policies": ["data_leakage_scan"],
        "risk_score": 0.80,
        "confidence": 0.75,
        "asset": "actor-99",
        "should_open_case": False,
        "timestamp": "2026-04-12T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _make_mock_repo(prior: FindingRecord | None = None):
    repo = AsyncMock()
    repo.get_by_batch_hash = AsyncMock(return_value=None)   # always new batch
    repo.get_by_dedup_key = AsyncMock(return_value=prior)
    repo.insert = AsyncMock(return_value=None)
    repo.attach_case = AsyncMock(return_value=None)
    return repo


# ─── tests ──────────────────────────────────────────────────────────────────

class TestPersistFindingPrioritizationFields:
    """persist_finding_from_dict() attaches prioritization fields before insert."""

    @pytest.mark.asyncio
    async def test_new_finding_has_dedup_key_and_priority_score(self):
        svc = ThreatFindingsService()
        repo = _make_mock_repo(prior=None)

        rec = await svc.persist_finding_from_dict(
            _make_finding_dict(), tenant_id="t1", repo=repo
        )

        assert rec.dedup_key is not None and len(rec.dedup_key) == 64
        assert rec.priority_score is not None and 0.0 <= rec.priority_score <= 1.0
        assert rec.group_id is not None and len(rec.group_id) == 64
        assert rec.occurrence_count == 1
        # should have called insert exactly once
        repo.insert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_revisited_finding_increments_occurrence_count(self):
        svc = ThreatFindingsService()

        # Simulate a prior occurrence stored in DB
        prior = FindingRecord(
            id="prior-id",
            batch_hash="x" * 64,
            title="Unusual exfil attempt",
            severity="high",
            description="Actor is probing for PII",
            evidence=[{"key": "val"}],
            ttps=["data_leakage_scan"],
            tenant_id="t1",
            dedup_key="a" * 64,       # engine will recompute & look this up
            occurrence_count=3,
            first_seen="2026-04-12T09:00:00+00:00",
            last_seen="2026-04-12T09:30:00+00:00",
        )
        repo = _make_mock_repo(prior=prior)

        rec = await svc.persist_finding_from_dict(
            _make_finding_dict(), tenant_id="t1", repo=repo
        )

        # occurrence_count must be 4 (3 + 1)
        assert rec.occurrence_count == 4
        assert rec.first_seen == "2026-04-12T09:00:00+00:00"
        assert rec.last_seen is not None

    @pytest.mark.asyncio
    async def test_low_score_finding_is_suppressed(self):
        svc = ThreatFindingsService()
        repo = _make_mock_repo(prior=None)

        # Very low risk/confidence → priority_score well below 0.30
        rec = await svc.persist_finding_from_dict(
            _make_finding_dict(
                risk_score=0.01,
                confidence=0.01,
                severity="low",
            ),
            tenant_id="t1",
            repo=repo,
        )

        assert rec.suppressed is True
        # Should still be persisted even if suppressed
        repo.insert.assert_awaited_once()
