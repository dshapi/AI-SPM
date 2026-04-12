from __future__ import annotations
import pytest
from agent.parser import LLMFragment, parse_llm_output


VALID_JSON = """\
```json
{
  "title": "Jailbreak Pattern Detected",
  "hypothesis": "User dany.shapiro made 7 injection attempts in 30 seconds.",
  "severity": "high",
  "asset": "chat-agent",
  "environment": "production",
  "evidence": ["7 blocked sessions", "risk_score=1.0 on all events"],
  "triggered_policies": ["block_rule_v1.4"],
  "policy_signals": [
    {"type": "gap_detected", "policy": "jailbreak_filter", "confidence": 0.85}
  ],
  "recommended_actions": ["block_session", "escalate"],
  "should_open_case": true
}
```"""


class TestParseValidOutput:
    def test_extracts_title(self):
        f = parse_llm_output(VALID_JSON)
        assert f.title == "Jailbreak Pattern Detected"

    def test_extracts_severity(self):
        f = parse_llm_output(VALID_JSON)
        assert f.severity == "high"

    def test_should_open_case_true(self):
        f = parse_llm_output(VALID_JSON)
        assert f.should_open_case is True

    def test_evidence_list(self):
        f = parse_llm_output(VALID_JSON)
        assert len(f.evidence) == 2

    def test_policy_signals_list(self):
        f = parse_llm_output(VALID_JSON)
        assert f.policy_signals[0]["type"] == "gap_detected"

    def test_recommended_actions(self):
        f = parse_llm_output(VALID_JSON)
        assert "block_session" in f.recommended_actions


class TestParseEdgeCases:
    def test_bare_json_no_fences(self):
        raw = '{"title": "X", "hypothesis": "Y", "severity": "low", "should_open_case": false}'
        f = parse_llm_output(raw)
        assert f.title == "X"

    def test_json_buried_in_prose(self):
        raw = 'I found a threat.\n\n```json\n{"title": "T", "hypothesis": "H", "severity": "medium", "should_open_case": false}\n```\n\nIn summary...'
        f = parse_llm_output(raw)
        assert f.title == "T"

    def test_no_json_returns_defaults(self):
        f = parse_llm_output("No threats detected. Everything looks fine.")
        assert f.title == "Threat detected"  # default
        assert f.should_open_case is False

    def test_malformed_json_returns_defaults(self):
        f = parse_llm_output("```json\n{broken json here\n```")
        assert f.severity == "medium"  # default

    def test_invalid_severity_coerced_to_default(self):
        raw = '```json\n{"title":"T","hypothesis":"H","severity":"extreme","should_open_case":false}\n```'
        f = parse_llm_output(raw)
        assert f.severity == "medium"  # fallback

    def test_extra_fields_ignored(self):
        # LLM should not sneak in risk_score — parser must strip it
        raw = '```json\n{"title":"T","hypothesis":"H","severity":"low","risk_score":0.9,"should_open_case":false}\n```'
        f = parse_llm_output(raw)
        assert not hasattr(f, "risk_score")  # LLMFragment has no risk_score

    def test_empty_string_returns_defaults(self):
        f = parse_llm_output("")
        assert f.should_open_case is False
