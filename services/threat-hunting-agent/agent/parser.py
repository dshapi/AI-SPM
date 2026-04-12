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
    asset:               str        = "Threat Hunting AI Agent"
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
