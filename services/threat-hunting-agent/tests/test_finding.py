from __future__ import annotations
import pytest
from agent.finding import Finding, PolicySignal, safe_fallback_finding

# ── Contract: minimum required fields ─────────────────────────────────────────
# These are the fields that downstream consumers (DB layer, API, UI) MUST
# always receive.  Any schema change that removes one of these will fail here.

REQUIRED_FIELDS = {
    "finding_id",
    "timestamp",
    "severity",
    "confidence",
    "risk_score",
    "title",
    "hypothesis",
    "evidence",
    "correlated_events",
    "triggered_policies",
    "policy_signals",
    "recommended_actions",
    "should_open_case",
}


class TestFindingContract:
    """Pins the minimum output contract for Finding.model_dump()."""

    def _minimal_finding(self) -> Finding:
        return Finding(
            severity="high",
            confidence=0.7,
            risk_score=0.8,
            title="Contract test",
            hypothesis="Verifying required fields are present.",
        )

    def test_all_required_fields_present_in_model_dump(self):
        d = self._minimal_finding().model_dump()
        missing = REQUIRED_FIELDS - d.keys()
        assert not missing, f"Missing required fields: {missing}"

    def test_all_required_fields_present_in_fallback(self):
        d = safe_fallback_finding("t1", 0)
        missing = REQUIRED_FIELDS - d.keys()
        assert not missing, f"Fallback missing required fields: {missing}"

    def test_evidence_is_list(self):
        d = self._minimal_finding().model_dump()
        assert isinstance(d["evidence"], list)

    def test_correlated_events_is_list(self):
        d = self._minimal_finding().model_dump()
        assert isinstance(d["correlated_events"], list)

    def test_triggered_policies_is_list(self):
        d = self._minimal_finding().model_dump()
        assert isinstance(d["triggered_policies"], list)

    def test_policy_signals_is_list(self):
        d = self._minimal_finding().model_dump()
        assert isinstance(d["policy_signals"], list)

    def test_recommended_actions_is_list(self):
        d = self._minimal_finding().model_dump()
        assert isinstance(d["recommended_actions"], list)

    def test_should_open_case_is_bool(self):
        d = self._minimal_finding().model_dump()
        assert isinstance(d["should_open_case"], bool)

    def test_finding_id_is_uuid_string(self):
        import re
        d = self._minimal_finding().model_dump()
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            d["finding_id"],
        ), f"finding_id is not a UUID: {d['finding_id']}"

    def test_timestamp_is_iso8601(self):
        from datetime import datetime
        d = self._minimal_finding().model_dump()
        # Should not raise
        datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))

    def test_severity_is_valid_literal(self):
        d = self._minimal_finding().model_dump()
        assert d["severity"] in ("low", "medium", "high", "critical")

    def test_confidence_in_bounds(self):
        d = self._minimal_finding().model_dump()
        assert 0.0 <= d["confidence"] <= 1.0

    def test_risk_score_in_bounds(self):
        d = self._minimal_finding().model_dump()
        assert 0.0 <= d["risk_score"] <= 1.0


class TestPolicySignal:
    def test_valid(self):
        ps = PolicySignal(type="gap_detected", policy="block_rule", confidence=0.8)
        assert ps.confidence == 0.8

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            PolicySignal(type="INVALID", policy="p", confidence=0.5)

    def test_confidence_clamped(self):
        with pytest.raises(Exception):
            PolicySignal(type="noisy_rule", policy="p", confidence=1.5)


class TestFinding:
    def test_minimal_valid(self):
        f = Finding(
            severity="high",
            confidence=0.8,
            risk_score=0.9,
            title="Test",
            hypothesis="Something bad happened.",
        )
        assert f.finding_id  # UUID auto-generated
        assert f.timestamp   # ISO8601 auto-generated
        assert f.should_open_case is False

    def test_finding_id_is_unique(self):
        f1 = Finding(severity="low", confidence=0.1, risk_score=0.1,
                     title="T", hypothesis="H")
        f2 = Finding(severity="low", confidence=0.1, risk_score=0.1,
                     title="T", hypothesis="H")
        assert f1.finding_id != f2.finding_id

    def test_invalid_severity_raises(self):
        with pytest.raises(Exception):
            Finding(severity="extreme", confidence=0.5, risk_score=0.5,
                    title="T", hypothesis="H")

    def test_risk_score_bounds(self):
        with pytest.raises(Exception):
            Finding(severity="low", confidence=0.5, risk_score=1.5,
                    title="T", hypothesis="H")

    def test_model_dump_has_all_keys(self):
        f = Finding(severity="critical", confidence=0.9, risk_score=0.95,
                    title="Attack", hypothesis="Evidence of attack.")
        d = f.model_dump()
        required = {"finding_id", "timestamp", "severity", "confidence", "risk_score",
                    "title", "hypothesis", "asset", "environment", "evidence",
                    "correlated_events", "correlated_findings", "triggered_policies",
                    "policy_signals", "recommended_actions", "should_open_case"}
        assert required.issubset(d.keys())

    def test_policy_signals_nested(self):
        f = Finding(
            severity="medium", confidence=0.5, risk_score=0.5,
            title="T", hypothesis="H",
            policy_signals=[PolicySignal(type="gap_detected", policy="p", confidence=0.7)],
        )
        d = f.model_dump()
        assert d["policy_signals"][0]["type"] == "gap_detected"


class TestSafeFallbackFinding:
    def test_returns_dict(self):
        d = safe_fallback_finding("t1", 3)
        assert isinstance(d, dict)
        assert d["severity"] == "low"
        assert d["should_open_case"] is False
        assert "finding_id" in d
