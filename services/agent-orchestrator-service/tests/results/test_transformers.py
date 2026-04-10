"""Unit tests for results/transformers.py — all pure, no I/O."""
import json
from datetime import datetime, timezone, timedelta
import pytest
from results.transformers import canonicalise, transform_session_events
from results.schemas import SessionResults


# ── canonicalise ──────────────────────────────────────────────────────────────

def test_canonicalise_passthrough_canonical():
    assert canonicalise({"event_type": "risk.calculated"}) == "risk.calculated"

def test_canonicalise_legacy_risk_scored():
    assert canonicalise({"event_type": "risk.scored"}) == "risk.calculated"

def test_canonicalise_policy_allow():
    ev = {"event_type": "policy.decision", "payload": {"decision": "allow"}}
    assert canonicalise(ev) == "policy.allowed"

def test_canonicalise_policy_block():
    ev = {"event_type": "policy.decision", "payload": {"decision": "block"}}
    assert canonicalise(ev) == "policy.blocked"

def test_canonicalise_policy_escalate():
    ev = {"event_type": "policy.decision", "payload": {"decision": "escalate"}}
    assert canonicalise(ev) == "policy.escalated"

def test_canonicalise_unknown_passthrough():
    assert canonicalise({"event_type": "some.unknown"}) == "some.unknown"


# ── transform_session_events — minimal happy path ─────────────────────────────

def _make_event(event_type, payload=None, ts_offset_s=0):
    base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ts = (base + timedelta(seconds=ts_offset_s)).isoformat()
    return {
        "event_type": event_type,
        "session_id": "sess-1",
        "correlation_id": "corr-1",
        "timestamp": ts,
        "step": ts_offset_s + 1,
        "status": "ok",
        "summary": f"Step {ts_offset_s}",
        "payload": payload or {},
    }


MINIMAL_ALLOW_EVENTS = [
    _make_event("prompt.received", {"agent_id": "FinanceBot", "prompt_len": 100, "tools": []}, 0),
    _make_event("risk.calculated", {"risk_score": 0.2, "risk_tier": "low", "signals": []}, 1),
    _make_event("policy.decision", {"decision": "allow", "reason": "low risk", "policy_version": "v1", "risk_score_at_decision": 0.2}, 2),
    _make_event("session.created", {"risk_score": 0.2, "risk_tier": "low", "policy_decision": "allow", "policy_version": "v1"}, 3),
    _make_event("session.completed", {"final_status": "active", "policy_decision": "allow", "risk_score": 0.2, "duration_ms": 400, "event_count": 5}, 4),
]


def test_transform_returns_session_results():
    result = transform_session_events(MINIMAL_ALLOW_EVENTS)
    assert isinstance(result, SessionResults)


def test_transform_allow_decision():
    result = transform_session_events(MINIMAL_ALLOW_EVENTS)
    assert result.decision == "allow"
    assert result.status == "completed"


def test_transform_risk_fields():
    result = transform_session_events(MINIMAL_ALLOW_EVENTS)
    assert result.risk.score == pytest.approx(0.2)
    assert result.risk.tier == "low"


def test_transform_policy_fields():
    result = transform_session_events(MINIMAL_ALLOW_EVENTS)
    assert result.policy.decision == "allow"
    assert result.policy.policy_version == "v1"


def test_transform_decision_trace_ordered():
    result = transform_session_events(MINIMAL_ALLOW_EVENTS)
    types = [s.event_type for s in result.decision_trace]
    assert "prompt.received" in types
    assert "risk.calculated" in types


def test_transform_partial_when_no_terminal_event():
    events = MINIMAL_ALLOW_EVENTS[:3]  # no session.created / completed
    result = transform_session_events(events)
    assert result.meta.partial is True
    assert result.status in ("unknown", "pending", "active")


def test_transform_blocked_session():
    events = [
        _make_event("prompt.received", {"agent_id": "Bot", "prompt_len": 50, "tools": []}, 0),
        _make_event("risk.calculated", {"risk_score": 0.9, "risk_tier": "critical", "signals": ["injection_detected"]}, 1),
        _make_event("policy.decision", {"decision": "block", "reason": "injection", "policy_version": "v1", "risk_score_at_decision": 0.9}, 2),
        _make_event("session.blocked", {"reason": "injection", "risk_score": 0.9}, 3),
        _make_event("session.completed", {"final_status": "blocked", "policy_decision": "block", "risk_score": 0.9, "duration_ms": 200, "event_count": 4}, 4),
    ]
    result = transform_session_events(events)
    assert result.decision == "block"
    assert result.status == "blocked"


def test_transform_injection_signal_generates_urgent_rec():
    events = [
        _make_event("prompt.received", {"agent_id": "Bot", "prompt_len": 50, "tools": []}, 0),
        _make_event("risk.calculated", {"risk_score": 0.95, "risk_tier": "critical", "signals": ["injection_detected"]}, 1),
        _make_event("policy.decision", {"decision": "block", "reason": "injection", "policy_version": "v1", "risk_score_at_decision": 0.95}, 2),
        _make_event("session.blocked", {"reason": "injection", "risk_score": 0.95}, 3),
        _make_event("session.completed", {"final_status": "blocked", "policy_decision": "block", "risk_score": 0.95, "duration_ms": 200, "event_count": 4}, 4),
    ]
    result = transform_session_events(events)
    urgent = [r for r in result.recommendations if r.priority == "urgent"]
    assert any("injection" in r.id for r in urgent)


def test_transform_deduplicates_repeated_events():
    duped = MINIMAL_ALLOW_EVENTS + [MINIMAL_ALLOW_EVENTS[1]]  # duplicate risk event
    result = transform_session_events(duped)
    risk_steps = [s for s in result.decision_trace if s.event_type == "risk.calculated"]
    assert len(risk_steps) == 1


def test_transform_empty_events():
    result = transform_session_events([])
    assert result.meta.partial is True
    assert result.meta.event_count == 0


def test_transform_first_policy_decision_wins():
    """When two conflicting policy events arrive, the first one wins."""
    events = [
        _make_event("prompt.received", {"agent_id": "Bot", "prompt_len": 50, "tools": []}, 0),
        _make_event("risk.calculated", {"risk_score": 0.5, "risk_tier": "medium", "signals": []}, 1),
        _make_event("policy.decision", {"decision": "allow", "reason": "first", "policy_version": "v1", "risk_score_at_decision": 0.5}, 2),
        _make_event("policy.decision", {"decision": "block", "reason": "second", "policy_version": "v1", "risk_score_at_decision": 0.5}, 3),
        _make_event("session.completed", {"final_status": "completed", "policy_decision": "allow", "risk_score": 0.5, "duration_ms": 300, "event_count": 4}, 4),
    ]
    result = transform_session_events(events)
    assert result.decision == "allow", f"Expected 'allow' (first policy), got '{result.decision}'"


def test_transform_pii_detection_no_false_positives():
    """pii_detected check should not fire on string values containing the substring."""
    events = [
        _make_event("prompt.received", {"agent_id": "Bot", "prompt_len": 50, "tools": []}, 0),
        _make_event("risk.calculated", {"risk_score": 0.1, "risk_tier": "low", "signals": [], "scan_notes": ["no pii_detected issues found"]}, 1),
        _make_event("session.completed", {"final_status": "completed", "policy_decision": "allow", "risk_score": 0.1, "duration_ms": 100, "event_count": 2}, 2),
    ]
    result = transform_session_events(events)
    pii_recs = [r for r in result.recommendations if r.id == "pii-redacted"]
    assert len(pii_recs) == 0, "PII redacted recommendation should not fire on false positive"
