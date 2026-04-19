# Structured Finding Output — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `run_hunt()`'s free-text string return with a validated `Finding` Pydantic object so the agent produces machine-readable threat intelligence ready for DB storage.

**Architecture:** Three new modules handle distinct concerns — `finding.py` owns the schema, `scorer.py` owns deterministic math (no LLM), and `parser.py` extracts the LLM's natural-language contribution from structured JSON fences. `run_hunt()` orchestrates them and always returns a `dict` (never raises). The LangChain agent and all existing tools are untouched.

**Tech Stack:** Python 3.11+, Pydantic v2, existing LangChain/Groq stack, pytest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `agent/finding.py` | `Finding` + `PolicySignal` Pydantic models, safe fallback factory |
| **Create** | `agent/scorer.py` | Deterministic `compute_risk_score()` + `compute_confidence()` |
| **Create** | `agent/parser.py` | `LLMFragment` model, JSON fence extractor, `parse_llm_output()` |
| **Modify** | `agent/prompts.py` | Append JSON output format block to `SYSTEM_PROMPT` |
| **Modify** | `agent/agent.py` | `run_hunt()` → returns `dict`; wire scorer + parser |
| **Modify** | `tools/case_tool.py` | Add `_compute_batch_hash()` + `create_threat_finding()` |
| **Modify** | `tools/__init__.py` | Export new `case_tool` symbols |
| **Modify** | `consumer/kafka_consumer.py` | Handle `dict` return from hunt agent |
| **Modify** | `app.py` | Update `_hunt` callback + `/hunt` response |
| **Create** | `tests/test_finding.py` | Finding model, validation, fallback |
| **Create** | `tests/test_scorer.py` | Scoring formula edge cases |
| **Create** | `tests/test_parser.py` | JSON extraction edge cases, fallback |
| **Create** | `tests/test_run_hunt.py` | End-to-end `run_hunt()` with mocked agent |

---

## Task 1: Finding + PolicySignal Pydantic models

**Files:**
- Create: `agent/finding.py`
- Create: `tests/test_finding.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_finding.py
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
```

- [ ] **Step 2: Run tests to confirm they fail**
```bash
cd /path/to/threat-hunting-agent
python -m pytest tests/test_finding.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'agent.finding'`

- [ ] **Step 3: Implement `agent/finding.py`**

```python
"""
agent/finding.py
─────────────────
Pydantic models for structured threat-hunt findings.

The Finding schema is the canonical output of run_hunt().
All fields are deterministically computed except those in the
LLM-controlled subset (title, hypothesis, severity, evidence, etc.).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


_VALID_SEVERITIES = ("low", "medium", "high", "critical")
_VALID_ACTIONS = ("monitor", "escalate", "block_session", "quarantine_agent")
_VALID_SIGNAL_TYPES = ("false_negative_candidate", "noisy_rule", "gap_detected")


class PolicySignal(BaseModel):
    """A signal that a policy may be misconfigured or have a gap."""
    type: Literal["false_negative_candidate", "noisy_rule", "gap_detected"]
    policy: str
    confidence: float = Field(ge=0.0, le=1.0)


class Finding(BaseModel):
    """
    Structured threat-hunt finding.  Always returned by run_hunt().
    Deterministic fields (risk_score, confidence) are computed by scorer.py.
    LLM-controlled fields (title, hypothesis, severity, evidence, …) come
    from the parsed agent output via parser.py.
    """
    # Identity
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Scores — deterministic (never from LLM)
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)

    # LLM narrative
    title: str
    hypothesis: str

    # Context
    asset: str = "unknown"
    environment: str = "production"

    # Evidence lists
    evidence: List[str] = Field(default_factory=list)
    correlated_events: List[str] = Field(default_factory=list)
    correlated_findings: List[str] = Field(default_factory=list)
    triggered_policies: List[str] = Field(default_factory=list)
    policy_signals: List[PolicySignal] = Field(default_factory=list)

    # Decisions
    recommended_actions: List[str] = Field(default_factory=list)
    should_open_case: bool = False


def safe_fallback_finding(tenant_id: str, event_count: int) -> dict:
    """
    Return a minimal safe Finding dict when agent invocation or parsing fails.
    should_open_case is always False in fallback — no false positives.
    """
    return Finding(
        severity="low",
        confidence=0.0,
        risk_score=0.0,
        title="Hunt completed — no finding produced",
        hypothesis=(
            f"Agent analysis of {event_count} event(s) for tenant '{tenant_id}' "
            "did not produce a parseable finding. Manual review may be required."
        ),
        should_open_case=False,
    ).model_dump()
```

- [ ] **Step 4: Run tests — expect PASS**
```bash
python -m pytest tests/test_finding.py -v
```
Expected: all green.

- [ ] **Step 5: Commit**
```bash
git add agent/finding.py tests/test_finding.py
git commit -m "feat(finding): add Finding + PolicySignal Pydantic models with safe fallback"
```

---

## Task 2: Deterministic scorer

**Files:**
- Create: `agent/scorer.py`
- Create: `tests/test_scorer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scorer.py
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
```

- [ ] **Step 2: Run tests to confirm they fail**
```bash
python -m pytest tests/test_scorer.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'agent.scorer'`

- [ ] **Step 3: Implement `agent/scorer.py`**

```python
"""
agent/scorer.py
────────────────
Deterministic scoring for threat-hunt findings.

These functions MUST NOT call the LLM.  They operate purely on the
raw event batch.  Both formulas follow the spec:

  risk_score  = min(1.0, severity_weight * frequency_factor * anomaly_factor)
  confidence  = min(1.0, evidence_strength * correlation_factor)
"""
from __future__ import annotations

from typing import Any, Dict, List

# Maps risk tier / severity labels → numeric weight
_TIER_WEIGHTS: Dict[str, float] = {
    "critical": 1.00,
    "high":     0.75,
    "medium":   0.50,
    "low":      0.25,
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_risk_score(event: Dict[str, Any]) -> float:
    """Pull a numeric risk score from various event shapes."""
    # Direct field (orchestrator sessions.blocked)
    direct = event.get("risk_score") or event.get("guard_score", 0.0)
    # Nested in details (audit events from session_service)
    nested = (event.get("details") or {}).get("risk_score", 0.0)
    return float(max(direct or 0.0, nested or 0.0))


def _extract_tier(event: Dict[str, Any]) -> str:
    """Pull a risk tier label from various event shapes."""
    direct = event.get("risk_tier", "") or event.get("guard_tier", "")
    nested = (event.get("details") or {}).get("risk_tier", "")
    return (direct or nested or "").lower()


def _is_blocked(event: Dict[str, Any]) -> bool:
    """Return True if this event represents a blocked / flagged session."""
    verdict = event.get("guard_verdict", "") or event.get("verdict", "")
    decision = event.get("policy_decision", "") or (event.get("details") or {}).get("policy_decision", "")
    return str(verdict).lower() in ("block", "blocked") or str(decision).lower() in ("block", "blocked")


def _has_evidence(event: Dict[str, Any]) -> bool:
    """Return True if the event carries any scoring signal."""
    return bool(
        _extract_risk_score(event) > 0
        or event.get("details")
        or event.get("guard_categories")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def compute_risk_score(events: List[Dict[str, Any]]) -> float:
    """
    risk_score = min(1.0, severity_weight * frequency_factor * anomaly_factor)

    severity_weight  — highest raw score or tier weight observed in the batch.
    frequency_factor — scales linearly from 0.5 (0 blocks) to 1.0 (≥3 blocks).
    anomaly_factor   — 1.5 if multiple distinct principals are involved, else 1.0.
                       Caps final score at 1.0.
    """
    if not events:
        return 0.0

    # severity_weight: max of direct risk scores and tier weights
    raw_scores   = [_extract_risk_score(e) for e in events]
    tier_weights = [_TIER_WEIGHTS.get(_extract_tier(e), 0.0) for e in events]
    severity_weight = max(max(raw_scores), max(tier_weights))

    # frequency_factor: 0.5 baseline, +0.5/6 per blocked event, capped at 1.0
    blocked_count    = sum(1 for e in events if _is_blocked(e))
    frequency_factor = min(1.0, 0.5 + blocked_count / 6.0)

    # anomaly_factor: cross-actor activity is more alarming
    principals    = {e.get("principal") or e.get("user_id", "") for e in events}
    principals.discard("")
    anomaly_factor = 1.5 if len(principals) > 1 else 1.0

    return min(1.0, severity_weight * frequency_factor * anomaly_factor)


def compute_confidence(events: List[Dict[str, Any]]) -> float:
    """
    confidence = min(1.0, evidence_strength * correlation_factor)

    evidence_strength  — fraction of events that carry a scoring signal.
    correlation_factor — 1.2 if events span multiple distinct sessions, else 1.0.
    """
    if not events:
        return 0.0

    evidence_count    = sum(1 for e in events if _has_evidence(e))
    evidence_strength = evidence_count / len(events)

    sessions = {e.get("session_id", "") for e in events}
    sessions.discard("")
    correlation_factor = 1.2 if len(sessions) > 1 else 1.0

    return min(1.0, evidence_strength * correlation_factor)
```

- [ ] **Step 4: Run tests — expect PASS**
```bash
python -m pytest tests/test_scorer.py -v
```

- [ ] **Step 5: Commit**
```bash
git add agent/scorer.py tests/test_scorer.py
git commit -m "feat(scorer): add deterministic risk_score and confidence computation"
```

---

## Task 3: LLM output parser

**Files:**
- Create: `agent/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_parser.py
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
```

- [ ] **Step 2: Run tests — expect failure**
```bash
python -m pytest tests/test_parser.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'agent.parser'`

- [ ] **Step 3: Implement `agent/parser.py`**

```python
"""
agent/parser.py
────────────────
Extracts the LLM's structured contribution from agent output text.

The LLM is instructed to return a JSON object inside ```json ... ``` fences.
This module:
  1. Tries to extract the JSON block (fence or bare).
  2. Validates it against LLMFragment (the LLM-controlled subset of Finding).
  3. Falls back to safe defaults if extraction or validation fails.

LLMFragment intentionally does NOT contain risk_score or confidence —
those are computed deterministically by scorer.py.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}
_DEFAULT_SEVERITY  = "medium"


class LLMFragment(BaseModel):
    """
    The subset of Finding fields that the LLM is allowed to populate.
    risk_score and confidence are deliberately excluded.
    """
    title:               str        = "Threat detected"
    hypothesis:          str        = "Suspicious activity observed requiring investigation."
    severity:            str        = _DEFAULT_SEVERITY
    asset:               str        = "unknown"
    environment:         str        = "production"
    evidence:            List[str]  = Field(default_factory=list)
    triggered_policies:  List[str]  = Field(default_factory=list)
    policy_signals:      List[Dict[str, Any]] = Field(default_factory=list)
    recommended_actions: List[str]  = Field(default_factory=list)
    should_open_case:    bool       = False

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, v: Any) -> str:
        if str(v).lower() in _VALID_SEVERITIES:
            return str(v).lower()
        logger.warning("LLM produced invalid severity %r — using default %r", v, _DEFAULT_SEVERITY)
        return _DEFAULT_SEVERITY

    model_config = {"extra": "ignore"}   # silently drop risk_score, confidence, etc.


# ─────────────────────────────────────────────────────────────────────────────
# JSON extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Try three strategies in order:
      1. JSON inside ```json ... ``` fences
      2. JSON inside ``` ... ``` fences (no language tag)
      3. First { ... } block in the entire text
    Returns None if nothing parses.
    """
    # Strategy 1 & 2: code fences
    fence_pattern = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    for m in fence_pattern.finditer(text):
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            continue

    # Strategy 3: bare JSON object anywhere in text
    brace_pattern = re.compile(r"\{.*\}", re.DOTALL)
    m = brace_pattern.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def parse_llm_output(text: str) -> LLMFragment:
    """
    Parse LLM output text into an LLMFragment.

    Always returns a valid LLMFragment — never raises.
    Falls back to safe defaults if parsing fails.
    """
    if not text or not text.strip():
        logger.warning("parse_llm_output: empty text — using defaults")
        return LLMFragment()

    raw = _extract_json(text)
    if raw is None:
        logger.warning("parse_llm_output: no JSON found in output — using defaults")
        return LLMFragment()

    try:
        return LLMFragment(**raw)
    except Exception as exc:
        logger.warning("parse_llm_output: fragment validation failed (%s) — using defaults", exc)
        return LLMFragment()
```

- [ ] **Step 4: Run tests — expect PASS**
```bash
python -m pytest tests/test_parser.py -v
```

- [ ] **Step 5: Commit**
```bash
git add agent/parser.py tests/test_parser.py
git commit -m "feat(parser): add LLMFragment model + JSON fence extractor with safe fallback"
```

---

## Task 4: Update SYSTEM_PROMPT with JSON output format

**Files:**
- Modify: `agent/prompts.py`

No new tests needed — the prompt is exercised by Task 6's integration test.

- [ ] **Step 1: Append JSON output block to SYSTEM_PROMPT in `agent/prompts.py`**

Replace the existing `SYSTEM_PROMPT` string with the version below. The new block is appended after the existing content (the reasoning protocol and thresholds are preserved):

```python
# agent/prompts.py

SYSTEM_PROMPT = """\
You are an AI Security Posture Management (AI-SPM) threat-hunting agent.
Your mission is to autonomously analyse a batch of security events and
determine whether they represent a genuine threat to the platform.

You have access to the following tools:

DATA COLLECTION
  query_audit_logs(tenant_id, event_type?, actor?, limit?)
      Fetch recent audit log entries from the SPM database.

  query_posture_history(tenant_id, model_id?, hours?, limit?)
      Fetch posture snapshot metrics (risk scores, block rates, drift) for a tenant or model.

  query_model_registry(tenant_id, risk_tier?, status?, limit?)
      Retrieve registered AI models and their risk classification.

  get_freeze_state(scope, target)
      Check whether a user / tenant / session is currently frozen in Redis.

  scan_session_memory(tenant_id, user_id, namespace?, max_keys?)
      Scan Redis for memory keys belonging to a user (detects anomalous memory usage).

THREAT INTELLIGENCE
  lookup_mitre_technique(technique_id)
      Look up a specific MITRE ATT&CK or ATLAS technique by ID (e.g. AML.T0051).

  search_mitre_techniques(query, max_results?)
      Search techniques by keyword (e.g. "prompt injection", "exfiltration").

POLICY & GUARD
  evaluate_opa_policy(policy_path, input_data)
      Evaluate an OPA Rego policy to understand why a decision was made.

  screen_text(text)
      Re-screen a suspicious prompt or output through the guard model.

FINDING CREATION
  create_case(title, severity, description, reason?, tenant_id?, ttps?)
      Open a new case in the Cases tab. Use this when you identify a credible threat
      that requires human review. The case appears immediately in the UI, sorted
      newest-first. severity must be one of: low, medium, high, critical.

REASONING PROTOCOL
───────────────────
1. Start by understanding the batch: what event types are present?
2. Identify anomalies — unusual actors, high risk scores, repeated blocks, or suspicious prompts.
3. Use MITRE lookup to map observed TTPs to known attack techniques.
4. Collect supporting evidence from Postgres and Redis.
5. Screen any suspicious text through the guard model ONLY if the raw content was not
   already captured in the event (the guard already ran at ingest time — do not duplicate work).
6. Apply the CASE CREATION THRESHOLD before calling create_case.
7. Output your structured finding JSON (see OUTPUT FORMAT below).

CASE CREATION THRESHOLD — you MUST meet at least one of these before calling create_case
or setting should_open_case to true:
  ✗ DO NOT create a case for:
      - A single blocked or flagged event (the guard already handled it — this is normal operation)
      - A single jailbreak keyword or obvious test phrase ("jailbreak", "DAN", "ignore instructions")
      - One-off low-confidence flags with no supporting pattern
      - Events where the guard blocked the prompt and there is no further suspicious activity

  ✓ DO create a case when you observe:
      - 3 or more blocked/flagged events from the same actor within the batch window
      - A progressive escalation pattern: low-risk → medium → high across sequential events
      - A blocked prompt that also triggered anomalous tool usage, memory access, or data queries
      - A prompt that bypassed the guard (verdict = allow) but contains genuinely harmful content
        confirmed by screen_text()
      - Coordinated activity across multiple sessions or users targeting the same model
      - Any event with risk_score ≥ 0.9 combined with a confirmed harmful category (S1, S4, S9)

SEVERITY GUIDELINES
  critical  — Active exploitation; immediate data loss or system compromise likely.
  high      — Credible attack pattern; significant risk if unmitigated.
  medium    — Suspicious behaviour that warrants investigation; multiple corroborating signals.
  low       — Anomaly observed; low probability of malicious intent; use sparingly.

OUTPUT FORMAT
─────────────
After completing your analysis, you MUST finish your response with a JSON object
inside ```json ... ``` fences.  Fill in ONLY the fields below — do NOT include
risk_score or confidence (those are computed externally).

```json
{
  "title": "<short threat summary, max 80 chars>",
  "hypothesis": "<1-2 sentences: what you observed and why it matters>",
  "severity": "low | medium | high | critical",
  "asset": "<agent/model/system name, or 'unknown'>",
  "environment": "<production | staging | dev, or 'unknown'>",
  "evidence": [
    "<string describing each piece of supporting evidence>"
  ],
  "triggered_policies": [
    "<policy name or OPA path that fired>"
  ],
  "policy_signals": [
    {
      "type": "false_negative_candidate | noisy_rule | gap_detected",
      "policy": "<policy name>",
      "confidence": 0.0
    }
  ],
  "recommended_actions": [
    "monitor | escalate | block_session | quarantine_agent"
  ],
  "should_open_case": true
}
```

If no credible threat was found, still output the JSON with should_open_case: false
and a brief hypothesis explaining why no threat was identified.
"""
```

- [ ] **Step 2: Commit**
```bash
git add agent/prompts.py
git commit -m "feat(prompts): add structured JSON output format block to SYSTEM_PROMPT"
```

---

## Task 5: Add `create_threat_finding` + `_compute_batch_hash` to case_tool

**Files:**
- Modify: `tools/case_tool.py`
- Modify: `tools/__init__.py`

The tests for these already exist in `tests/test_case_tool.py` (they import
`create_threat_finding` and `_compute_batch_hash`).

- [ ] **Step 1: Run the existing case_tool tests to see current failures**
```bash
python -m pytest tests/test_case_tool.py -v 2>&1 | head -30
```
Expected: `ImportError: cannot import name '_compute_batch_hash'`

- [ ] **Step 2: Add `_compute_batch_hash` and `create_threat_finding` to `tools/case_tool.py`**

Append the following AFTER the existing `create_case` function (do NOT remove `create_case`):

```python
# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------

def _compute_batch_hash(tenant_id: str, title: str, evidence: dict) -> str:
    """
    Deterministic SHA-256 hash used for server-side deduplication.

    Inputs are sorted before serialisation so key order doesn't affect output.
    """
    import hashlib
    canonical = json.dumps(
        {"tenant_id": tenant_id, "title": title, "evidence": evidence},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tool: create_threat_finding  (structured, deduplicated)
# ---------------------------------------------------------------------------

def create_threat_finding(
    tenant_id: str,
    title: str,
    severity: str,
    description: str,
    evidence: dict,
    ttps: Optional[List[str]] = None,
) -> str:
    """
    Submit a structured threat finding to the orchestrator.

    POSTs to /api/v1/threat-findings.  The server handles deduplication via
    batch_hash: a 200 response means the finding already exists (deduplicated=True);
    a 201 means it was newly created (deduplicated=False).

    Args:
        tenant_id:   Tenant scope.
        title:       Short descriptive title.
        severity:    One of 'low', 'medium', 'high', 'critical'.
        description: Narrative explanation from the agent.
        evidence:    Dict of supporting evidence facts.
        ttps:        Optional MITRE ATT&CK / ATLAS technique IDs.

    Returns:
        JSON string with keys: id, title, severity, status, created_at, deduplicated.
    """
    if severity not in ("low", "medium", "high", "critical"):
        return json.dumps({"error": f"Invalid severity '{severity}'. Must be low/medium/high/critical."})

    try:
        token = _fetch_dev_token()
    except Exception as exc:
        logger.exception("create_threat_finding: dev-token fetch failed: %s", exc)
        return json.dumps({"error": f"auth failure: {exc}"})

    batch_hash = _compute_batch_hash(tenant_id, title, evidence)
    payload = {
        "title":       title,
        "severity":    severity,
        "description": description,
        "evidence":    evidence,
        "tenant_id":   tenant_id,
        "ttps":        ttps or [],
        "batch_hash":  batch_hash,
    }

    try:
        client = _get_client()
        resp = client.post(
            f"{_orchestrator_url}/api/v1/threat-findings",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return json.dumps(resp.json())
    except httpx.HTTPStatusError as exc:
        logger.error(
            "create_threat_finding HTTP %d: %s",
            exc.response.status_code, exc.response.text,
        )
        return json.dumps({"error": f"HTTP {exc.response.status_code}: {exc.response.text}"})
    except Exception as exc:
        logger.exception("create_threat_finding failed: %s", exc)
        return json.dumps({"error": str(exc)})
```

- [ ] **Step 3: Update `tools/__init__.py`** — add exports:

```python
from tools.case_tool import (
    configure as configure_case_tool,
    create_case,
    create_threat_finding,        # ← new
    _compute_batch_hash,          # ← new (used in tests)
    set_http_client as set_case_http_client,
)

__all__ = [
    # ... existing ...
    "create_case",
    "create_threat_finding",
    "configure_case_tool",
    "set_case_http_client",
]
```

- [ ] **Step 4: Run the existing case_tool tests — expect PASS**
```bash
python -m pytest tests/test_case_tool.py -v
```

- [ ] **Step 5: Commit**
```bash
git add tools/case_tool.py tools/__init__.py
git commit -m "feat(case_tool): add create_threat_finding() + _compute_batch_hash() for structured findings"
```

---

## Task 6: Update `run_hunt()` in `agent/agent.py`

**Files:**
- Modify: `agent/agent.py`
- Create: `tests/test_run_hunt.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_run_hunt.py
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
```

- [ ] **Step 2: Run tests — expect failure**
```bash
python -m pytest tests/test_run_hunt.py -v 2>&1 | head -20
```
Expected: failures because `run_hunt` currently returns a string.

- [ ] **Step 3: Update `run_hunt()` in `agent/agent.py`**

Replace only the `run_hunt` function (keep everything else intact):

```python
def run_hunt(agent: Any, tenant_id: str, events: List[Dict[str, Any]]) -> dict:
    """
    Run a threat hunt over a batch of events.

    Args:
        agent:     Compiled LangChain agent graph from build_agent().
        tenant_id: Tenant the events belong to.
        events:    List of event dicts from Kafka (various shapes).

    Returns:
        Finding dict — always a dict, never raises, never returns a string.
        On any failure the safe fallback Finding is returned with
        should_open_case=False and risk_score=0.0.
    """
    from agent.finding import Finding, PolicySignal, safe_fallback_finding
    from agent.scorer  import compute_risk_score, compute_confidence
    from agent.parser  import parse_llm_output

    # ── 1. Deterministic scoring (no LLM involvement) ─────────────────────────
    risk_score = compute_risk_score(events)
    confidence = compute_confidence(events)

    # ── 2. Correlation — collect event/session IDs from batch ─────────────────
    correlated_events: List[str] = []
    for e in events:
        eid = str(e.get("event_id") or e.get("session_id") or "")
        if eid:
            correlated_events.append(eid)

    # ── 3. LLM invocation ─────────────────────────────────────────────────────
    llm_fragment = None
    try:
        event_summary = json.dumps(events, default=str, indent=2)
        prompt = (
            f"Threat hunt requested for tenant '{tenant_id}'.\n\n"
            f"Batch of {len(events)} events:\n{event_summary}\n\n"
            "Analyse these events for threats. Use your tools to gather additional "
            "context where useful. Then output your structured finding JSON as "
            "instructed in the system prompt."
        )
        result   = agent.invoke({"messages": [HumanMessage(content=prompt)]})
        messages = result.get("messages", [])
        if messages:
            raw_text     = getattr(messages[-1], "content", str(messages[-1]))
            llm_fragment = parse_llm_output(raw_text)
    except Exception as exc:
        logger.exception("run_hunt: agent invocation failed tenant=%s: %s", tenant_id, exc)
        return safe_fallback_finding(tenant_id, len(events))

    if llm_fragment is None:
        return safe_fallback_finding(tenant_id, len(events))

    # ── 4. Assemble Finding ────────────────────────────────────────────────────
    try:
        policy_signals = [
            PolicySignal(**ps)
            for ps in llm_fragment.policy_signals
            if isinstance(ps, dict) and "type" in ps and "policy" in ps
        ]
    except Exception:
        policy_signals = []

    try:
        finding = Finding(
            severity             = llm_fragment.severity,
            confidence           = confidence,
            risk_score           = risk_score,
            title                = llm_fragment.title,
            hypothesis           = llm_fragment.hypothesis,
            asset                = llm_fragment.asset,
            environment          = llm_fragment.environment,
            evidence             = llm_fragment.evidence,
            correlated_events    = correlated_events,
            triggered_policies   = llm_fragment.triggered_policies,
            policy_signals       = policy_signals,
            recommended_actions  = llm_fragment.recommended_actions,
            should_open_case     = llm_fragment.should_open_case,
        )
        return finding.model_dump()
    except Exception as exc:
        logger.exception("run_hunt: Finding assembly failed tenant=%s: %s", tenant_id, exc)
        return safe_fallback_finding(tenant_id, len(events))
```

Also update the return type annotation at the function signature from `-> str` to `-> dict`.

- [ ] **Step 4: Run all tests — expect PASS**
```bash
python -m pytest tests/test_run_hunt.py tests/test_finding.py tests/test_scorer.py tests/test_parser.py -v
```

- [ ] **Step 5: Commit**
```bash
git add agent/agent.py tests/test_run_hunt.py
git commit -m "feat(agent): run_hunt() now returns structured Finding dict instead of free-text summary"
```

---

## Task 7: Update Kafka consumer and app.py for dict return

**Files:**
- Modify: `consumer/kafka_consumer.py`
- Modify: `app.py`

- [ ] **Step 1: Update `consumer/kafka_consumer.py` `_fire_hunts` log line**

The only change needed is the logging line that calls `len(summary)`:

```python
# Before (line ~248):
summary = self._hunt_agent(tenant_id, events)
logger.info("Hunt complete: tenant=%s summary_len=%d", tenant_id, len(summary))

# After:
finding = self._hunt_agent(tenant_id, events)
if isinstance(finding, dict):
    logger.info(
        "Hunt complete: tenant=%s finding_id=%s severity=%s should_open_case=%s",
        tenant_id,
        finding.get("finding_id", "?"),
        finding.get("severity", "?"),
        finding.get("should_open_case", False),
    )
else:
    # Backward-compat: old string return (should not happen post-refactor)
    logger.info("Hunt complete: tenant=%s summary_len=%d", tenant_id, len(str(finding)))
```

- [ ] **Step 2: Update `app.py` `/hunt` endpoint response**

```python
# In the manual_hunt handler:
@application.post("/hunt", response_model=HuntResponse, ...)
async def manual_hunt(req: HuntRequest, ...) -> HuntResponse:
    finding = run_hunt(app_ref.state.agent, req.tenant_id, req.events)
    # finding is now a dict; use title as summary for HuntResponse
    summary = finding.get("title", str(finding)) if isinstance(finding, dict) else str(finding)
    return HuntResponse(
        tenant_id=req.tenant_id,
        summary=summary,
        event_count=len(req.events),
    )
```

- [ ] **Step 3: Run the full test suite**
```bash
python -m pytest tests/ -v
```
All tests should pass.

- [ ] **Step 4: Commit**
```bash
git add consumer/kafka_consumer.py app.py
git commit -m "feat(consumer): handle dict return from run_hunt(), log finding_id and severity"
```

---

## Task 8: Full test suite + example output verification

- [ ] **Step 1: Run the complete test suite**
```bash
python -m pytest tests/ -v --tb=short
```
Expected: all green, zero failures.

- [ ] **Step 2: Verify the example output manually**

Create `tests/example_finding_output.py` and run it as a script:

```python
"""
Example: what run_hunt() now returns given a realistic jailbreak batch.
Run with: python tests/example_finding_output.py
"""
import json
from unittest.mock import MagicMock
from agent.agent import run_hunt

_LLM_OUTPUT = '''
After analysing the 7-event batch I observed a clear jailbreak escalation pattern.

```json
{
  "title": "Repeated Jailbreak Pattern — dany.shapiro",
  "hypothesis": "User dany.shapiro submitted 7 jailbreak prompts within a 30-second window. All were blocked with risk_score=1.0. This is consistent with ATLAS AML.T0054 (Prompt Injection / Jailbreak).",
  "severity": "high",
  "asset": "chat-agent",
  "environment": "production",
  "evidence": [
    "7 sessions blocked, all with risk_score=1.0",
    "All events from principal dany.shapiro",
    "guard_verdict=block on all events",
    "policy_decision=block in all audit details"
  ],
  "triggered_policies": ["block_rule_v1.4.2"],
  "policy_signals": [
    {
      "type": "gap_detected",
      "policy": "jailbreak_rate_limit",
      "confidence": 0.75
    }
  ],
  "recommended_actions": ["block_session", "escalate"],
  "should_open_case": true
}
```
'''

events = [
    {
        "guard_verdict": "block", "risk_score": 1.0, "risk_tier": "critical",
        "principal": "dany.shapiro", "session_id": f"session-{i}",
        "details": {"policy_decision": "block", "risk_score": 1.0, "risk_tier": "critical"}
    }
    for i in range(7)
]

msg = MagicMock(); msg.content = _LLM_OUTPUT
agent = MagicMock(); agent.invoke.return_value = {"messages": [msg]}

finding = run_hunt(agent, "t1", events)
print(json.dumps(finding, indent=2))
```

Expected output shape:
```json
{
  "finding_id": "<uuid>",
  "timestamp": "2026-04-12T...",
  "severity": "high",
  "confidence": 1.0,
  "risk_score": 1.0,
  "title": "Repeated Jailbreak Pattern — dany.shapiro",
  "hypothesis": "User dany.shapiro submitted 7 jailbreak prompts ...",
  "asset": "chat-agent",
  "environment": "production",
  "evidence": ["7 sessions blocked, all with risk_score=1.0", "..."],
  "correlated_events": ["session-0", "session-1", ..., "session-6"],
  "correlated_findings": [],
  "triggered_policies": ["block_rule_v1.4.2"],
  "policy_signals": [{"type": "gap_detected", "policy": "jailbreak_rate_limit", "confidence": 0.75}],
  "recommended_actions": ["block_session", "escalate"],
  "should_open_case": true
}
```

- [ ] **Step 3: Final commit**
```bash
git add tests/example_finding_output.py
git commit -m "test: add example_finding_output.py to demonstrate structured Finding output"
```

---

## Summary of changes

| File | Change |
|------|--------|
| `agent/finding.py` | **NEW** — `Finding`, `PolicySignal`, `safe_fallback_finding` |
| `agent/scorer.py` | **NEW** — `compute_risk_score()`, `compute_confidence()` |
| `agent/parser.py` | **NEW** — `LLMFragment`, `parse_llm_output()`, `_extract_json()` |
| `agent/prompts.py` | **MOD** — JSON output format block appended |
| `agent/agent.py` | **MOD** — `run_hunt()` returns `dict`; wires scorer + parser |
| `tools/case_tool.py` | **MOD** — adds `_compute_batch_hash()`, `create_threat_finding()` |
| `tools/__init__.py` | **MOD** — exports new case_tool symbols |
| `consumer/kafka_consumer.py` | **MOD** — logs `finding_id`/`severity` instead of `len(summary)` |
| `app.py` | **MOD** — `/hunt` handler extracts title from finding dict |

**Invariants preserved:**
- All existing tools (`create_case`, all query tools) remain unchanged
- Kafka consumer flow is unbroken
- External APIs are untouched
- `run_hunt()` never raises — always returns a dict
