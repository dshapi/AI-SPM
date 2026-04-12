from __future__ import annotations
import pytest
from agent.finding import Finding, PolicySignal, safe_fallback_finding


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
