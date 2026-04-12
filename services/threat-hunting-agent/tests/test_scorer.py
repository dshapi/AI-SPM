from __future__ import annotations
import pytest
from agent.scorer import compute_risk_score, compute_confidence


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _blocked(risk_score=0.9, risk_tier="critical", principal="alice", session_id="s1"):
    return {
        "guard_verdict": "block",
        "risk_score": risk_score,
        "risk_tier": risk_tier,
        "principal": principal,
        "session_id": session_id,
        "details": {"policy_decision": "block"},
    }

def _allowed(risk_score=0.2, principal="bob", session_id="s2"):
    return {
        "guard_verdict": "allow",
        "risk_score": risk_score,
        "principal": principal,
        "session_id": session_id,
    }

def _audit(principal="alice", session_id="s1"):
    return {
        "_topic": "cpm.t1.audit",
        "event_type": "session_lifecycle_complete",
        "severity": "warning",
        "principal": principal,
        "session_id": session_id,
        "details": {"policy_decision": "block", "risk_score": 0.85, "risk_tier": "critical"},
    }


class TestComputeRiskScore:
    def test_empty_batch_returns_zero(self):
        assert compute_risk_score([]) == 0.0

    def test_single_critical_block(self):
        score = compute_risk_score([_blocked(risk_score=1.0, risk_tier="critical")])
        assert 0.0 < score <= 1.0

    def test_capped_at_one(self):
        events = [_blocked(risk_score=1.0, risk_tier="critical")] * 10
        assert compute_risk_score(events) <= 1.0

    def test_multiple_blocks_higher_than_single(self):
        single = compute_risk_score([_blocked()])
        multi  = compute_risk_score([_blocked(), _blocked(principal="bob"), _blocked(principal="carol")])
        assert multi >= single

    def test_allow_events_score_lower_than_blocks(self):
        block_score = compute_risk_score([_blocked()] * 3)
        allow_score = compute_risk_score([_allowed()] * 3)
        assert block_score > allow_score

    def test_audit_event_reads_details(self):
        score = compute_risk_score([_audit()])
        assert score > 0.0

    def test_multiple_actors_anomaly_boost(self):
        same_actor = compute_risk_score([_blocked(principal="alice")] * 3)
        diff_actors = compute_risk_score([
            _blocked(principal="alice"),
            _blocked(principal="bob"),
            _blocked(principal="carol"),
        ])
        assert diff_actors >= same_actor


class TestComputeConfidence:
    def test_empty_batch_returns_zero(self):
        assert compute_confidence([]) == 0.0

    def test_capped_at_one(self):
        events = [_blocked()] * 20
        assert compute_confidence(events) <= 1.0

    def test_events_with_evidence_higher_confidence(self):
        no_evidence = [{"guard_verdict": "block"}]
        with_evidence = [_blocked()]
        assert compute_confidence(with_evidence) >= compute_confidence(no_evidence)

    def test_multiple_sessions_boosts_confidence(self):
        one_session = compute_confidence([_blocked(session_id="s1")] * 3)
        multi_session = compute_confidence([
            _blocked(session_id="s1"),
            _blocked(session_id="s2"),
            _blocked(session_id="s3"),
        ])
        assert multi_session >= one_session

    def test_non_negative(self):
        assert compute_confidence([_allowed()]) >= 0.0
