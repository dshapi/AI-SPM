"""
Unit tests for the prioritization pipeline.
All functions are pure / deterministic — no DB, no network, no LLM.
"""
import asyncio
import pytest
from threat_findings.prioritization.dedup import compute_dedup_key, merge_occurrence
from threat_findings.prioritization.grouping import compute_group_id
from threat_findings.prioritization.ranking import compute_priority_score
from threat_findings.prioritization.suppression import should_suppress
from threat_findings.prioritization.engine import PrioritizationEngine
from threat_findings.schemas import FindingRecord


# ── dedup ────────────────────────────────────────────────────────────────────

class TestComputeDedupKey:
    def test_same_inputs_produce_same_key(self):
        k1 = compute_dedup_key("title", "asset-1", "secrets", ["ev1"])
        k2 = compute_dedup_key("title", "asset-1", "secrets", ["ev1"])
        assert k1 == k2

    def test_different_title_different_key(self):
        k1 = compute_dedup_key("title-A", "asset", "secrets", [])
        k2 = compute_dedup_key("title-B", "asset", "secrets", [])
        assert k1 != k2

    def test_none_asset_handled(self):
        k = compute_dedup_key("title", None, "scan", [])
        assert isinstance(k, str) and len(k) == 64

    def test_evidence_order_independent(self):
        k1 = compute_dedup_key("t", "a", "s", [{"b": 2, "a": 1}])
        k2 = compute_dedup_key("t", "a", "s", [{"a": 1, "b": 2}])
        assert k1 == k2

    def test_key_is_64_char_hex(self):
        k = compute_dedup_key("t", "a", "s", [])
        assert len(k) == 64
        int(k, 16)  # must be valid hex


class TestMergeOccurrence:
    def test_first_occurrence_sets_first_seen(self):
        result = merge_occurrence(None, "2026-01-01T00:00:00+00:00", 0)
        assert result["first_seen"] == "2026-01-01T00:00:00+00:00"
        assert result["occurrence_count"] == 1

    def test_subsequent_occurrence_increments_count(self):
        result = merge_occurrence("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00", 3)
        assert result["occurrence_count"] == 4
        assert result["first_seen"] == "2026-01-01T00:00:00+00:00"
        assert result["last_seen"] == "2026-01-02T00:00:00+00:00"


# ── grouping ─────────────────────────────────────────────────────────────────

class TestComputeGroupId:
    def test_same_asset_scan_bucket_gives_same_id(self):
        g1 = compute_group_id("host-1", "secrets", "2026-01-01T10:30:00+00:00")
        g2 = compute_group_id("host-1", "secrets", "2026-01-01T10:45:00+00:00")
        assert g1 == g2  # same hour bucket

    def test_different_hour_gives_different_id(self):
        g1 = compute_group_id("host-1", "secrets", "2026-01-01T10:00:00+00:00")
        g2 = compute_group_id("host-1", "secrets", "2026-01-01T11:00:00+00:00")
        assert g1 != g2

    def test_different_asset_gives_different_id(self):
        g1 = compute_group_id("host-A", "secrets", "2026-01-01T10:00:00+00:00")
        g2 = compute_group_id("host-B", "secrets", "2026-01-01T10:00:00+00:00")
        assert g1 != g2

    def test_none_asset_handled(self):
        gid = compute_group_id(None, "network", "2026-01-01T10:00:00+00:00")
        assert isinstance(gid, str) and len(gid) == 64

    def test_output_is_64_char_hex(self):
        gid = compute_group_id("asset", "scan", "2026-01-01T10:00:00+00:00")
        assert len(gid) == 64
        int(gid, 16)


# ── ranking ──────────────────────────────────────────────────────────────────

class TestComputePriorityScore:
    def test_critical_recent_frequent_gives_high_score(self):
        score = compute_priority_score(
            risk_score=0.9, confidence=0.9, severity="critical",
            age_hours=0.5, occurrence_count=10,
        )
        assert score > 0.85

    def test_low_everything_gives_low_score(self):
        score = compute_priority_score(
            risk_score=0.1, confidence=0.1, severity="low",
            age_hours=500, occurrence_count=1,
        )
        assert score < 0.4

    def test_none_inputs_treated_as_zero(self):
        score = compute_priority_score(
            risk_score=None, confidence=None, severity="low",
            age_hours=500, occurrence_count=1,
        )
        assert 0.0 <= score <= 1.0

    def test_output_clamped_to_unit_interval(self):
        score = compute_priority_score(
            risk_score=2.0, confidence=2.0, severity="critical",
            age_hours=0, occurrence_count=100,
        )
        assert score == 1.0

    def test_severity_weights_ordered(self):
        base = dict(risk_score=0.5, confidence=0.5, age_hours=24, occurrence_count=1)
        scores = {sev: compute_priority_score(severity=sev, **base)
                  for sev in ("low", "medium", "high", "critical")}
        assert scores["low"] < scores["medium"] < scores["high"] < scores["critical"]


# ── suppression ──────────────────────────────────────────────────────────────

class TestShouldSuppress:
    def test_below_threshold_suppressed(self):
        assert should_suppress(0.29) is True

    def test_at_threshold_not_suppressed(self):
        assert should_suppress(0.30) is False

    def test_above_threshold_not_suppressed(self):
        assert should_suppress(0.80) is False

    def test_none_score_suppressed(self):
        assert should_suppress(None) is True

    def test_zero_score_suppressed(self):
        assert should_suppress(0.0) is True


# ── engine ───────────────────────────────────────────────────────────────────

def _make_record(**kwargs) -> FindingRecord:
    defaults = dict(
        id="test-id", batch_hash="bh1", title="Test Finding",
        severity="high", description="desc", evidence=[], ttps=[],
        tenant_id="t1", risk_score=0.7, confidence=0.8,
        asset="host-1", source="threathunting_ai",
    )
    defaults.update(kwargs)
    return FindingRecord(**defaults)


class TestPrioritizationEngine:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_engine_sets_dedup_key(self):
        async def _lookup(key): return None
        result = self._run(PrioritizationEngine.run(_make_record(), _lookup))
        assert result.dedup_key is not None
        assert len(result.dedup_key) == 64

    def test_engine_sets_group_id(self):
        async def _lookup(key): return None
        result = self._run(PrioritizationEngine.run(_make_record(), _lookup))
        assert result.group_id is not None
        assert result.group_size == 1

    def test_engine_sets_priority_score(self):
        async def _lookup(key): return None
        result = self._run(PrioritizationEngine.run(
            _make_record(risk_score=0.8, confidence=0.9, severity="critical"), _lookup))
        assert result.priority_score is not None
        assert 0.0 <= result.priority_score <= 1.0

    def test_engine_increments_occurrence_on_revisit(self):
        async def _lookup(key):
            return {"first_seen": "2026-01-01T00:00:00+00:00", "occurrence_count": 5}
        result = self._run(PrioritizationEngine.run(_make_record(), _lookup))
        assert result.occurrence_count == 6
        assert result.first_seen == "2026-01-01T00:00:00+00:00"

    def test_engine_suppresses_low_score(self):
        async def _lookup(key): return None
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        result = self._run(PrioritizationEngine.run(
            _make_record(risk_score=0.05, confidence=0.05, severity="low",
                         created_at=old_ts), _lookup))
        assert result.suppressed is True

    def test_engine_does_not_suppress_high_score(self):
        async def _lookup(key): return None
        result = self._run(PrioritizationEngine.run(
            _make_record(risk_score=0.9, confidence=0.9, severity="critical"), _lookup))
        assert result.suppressed is False
