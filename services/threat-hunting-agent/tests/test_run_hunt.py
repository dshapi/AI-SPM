"""
Tests for the updated run_hunt() function.

The LangChain agent is mocked — no Groq API key required.
"""
from __future__ import annotations

from typing import Any, List, Dict
from unittest.mock import MagicMock

import pytest

from agent.agent import run_hunt


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_agent(llm_text: str) -> Any:
    """Fake LangChain agent that returns a fixed final message."""
    msg = MagicMock()
    msg.content = llm_text

    agent = MagicMock()
    agent.invoke.return_value = {"messages": [msg]}
    return agent


_GOOD_JSON = """\
Analysis complete.

```json
{
  "title": "Repeated Jailbreak Attempts",
  "hypothesis": "User alice sent 5 jailbreak prompts in 30 seconds.",
  "severity": "high",
  "asset": "chat-agent",
  "environment": "production",
  "evidence": ["5 blocked sessions", "risk_score=1.0"],
  "triggered_policies": ["block_rule_v1"],
  "policy_signals": [],
  "recommended_actions": ["block_session", "escalate"],
  "should_open_case": true
}
```
"""

_EVENTS = [
    {
        "guard_verdict": "block",
        "risk_score": 1.0,
        "risk_tier": "critical",
        "principal": "alice",
        "session_id": f"s{i}",
        "details": {"policy_decision": "block"},
    }
    for i in range(5)
]


class TestRunHuntReturnType:
    def test_returns_dict(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        required = {"finding_id", "timestamp", "severity", "confidence", "risk_score",
                    "title", "hypothesis", "should_open_case"}
        assert required.issubset(result.keys())

    def test_finding_id_is_string(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert isinstance(result["finding_id"], str)
        assert len(result["finding_id"]) == 36  # UUID format

    def test_timestamp_is_iso8601(self):
        from datetime import datetime
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        # Should not raise
        datetime.fromisoformat(result["timestamp"].replace("Z", "+00:00"))


class TestRunHuntDeterministicScoring:
    def test_risk_score_not_from_llm(self):
        # LLM text has no risk_score field — scorer computes it
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert 0.0 <= result["risk_score"] <= 1.0
        assert result["risk_score"] > 0  # 5 critical blocks → high score

    def test_confidence_not_from_llm(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_llm_cannot_override_risk_score(self):
        # Even if LLM tries to sneak in risk_score, it must be ignored
        sneaky = _GOOD_JSON.replace('"should_open_case": true', '"risk_score": 0.001, "should_open_case": true')
        result = run_hunt(_make_agent(sneaky), "t1", _EVENTS)
        # Deterministic scorer with 5 critical blocks → should be >> 0.001
        assert result["risk_score"] > 0.5


class TestRunHuntLLMFields:
    def test_title_from_llm(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert result["title"] == "Repeated Jailbreak Attempts"

    def test_hypothesis_from_llm(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert "alice" in result["hypothesis"]

    def test_should_open_case_from_llm(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert result["should_open_case"] is True


class TestRunHuntCorrelation:
    def test_correlated_events_populated(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        # 5 events each with a session_id → 5 correlated events
        assert len(result["correlated_events"]) == 5

    def test_correlated_events_are_strings(self):
        result = run_hunt(_make_agent(_GOOD_JSON), "t1", _EVENTS)
        assert all(isinstance(e, str) for e in result["correlated_events"])


class TestRunHuntFallback:
    def test_agent_exception_returns_fallback_dict(self):
        agent = MagicMock()
        agent.invoke.side_effect = RuntimeError("Groq API unavailable")
        result = run_hunt(agent, "t1", _EVENTS)
        assert isinstance(result, dict)
        assert result["should_open_case"] is False
        assert result["risk_score"] == 0.0  # fallback = safe zero

    def test_empty_events_returns_fallback(self):
        result = run_hunt(_make_agent(""), "t1", [])
        assert isinstance(result, dict)
        assert result["risk_score"] == 0.0

    def test_no_json_in_llm_output_uses_defaults(self):
        result = run_hunt(_make_agent("No threats found."), "t1", _EVENTS)
        assert isinstance(result, dict)
        assert result["severity"] == "medium"  # LLMFragment default
