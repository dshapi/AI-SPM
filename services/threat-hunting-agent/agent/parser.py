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


_STRING_KEY_PRIORITY = (
    "description", "detail", "details", "text", "message",
    "evidence", "summary", "action", "policy", "name",
)


def _coerce_item_to_string(item: Any) -> Optional[str]:
    """
    Coerce one list element into a non-empty string.

    Small instruction-tuned models (e.g. llama3.2:3b) like to "help" by wrapping
    string entries in {"description": "..."} or {"action": "..."} objects even
    when the prompt asks for plain strings.  Rather than rejecting the whole
    payload and falling back to generic defaults, accept any reasonable shape
    and extract the most string-like field.

    Returns None if no usable string can be produced, so the caller can drop
    empty entries instead of surfacing '{}'.
    """
    if item is None:
        return None
    if isinstance(item, str):
        s = item.strip()
        return s or None
    if isinstance(item, dict):
        # If the dict uses a known string-priority key, honor its value — even
        # an empty value means "operator had nothing to say here", so we drop
        # the item rather than falling through to JSON-stringify the whole
        # dict.  Only when NO known string-priority key is present do we fall
        # back to stringifying the dict.
        for key in _STRING_KEY_PRIORITY:
            if key in item:
                v = item.get(key)
                if isinstance(v, str):
                    s = v.strip()
                    return s if s else None
                # Non-string value under a string-priority key — treat as drop.
                return None
        # No known key — try any string value before stringifying the dict.
        for v in item.values():
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Last resort: compact JSON so we preserve some information instead of
        # dropping the entry entirely.
        try:
            return json.dumps(item, separators=(",", ":"), ensure_ascii=False)[:500]
        except Exception:
            return None
    # Numbers, bools, etc. — stringify.
    try:
        s = str(item).strip()
        return s or None
    except Exception:
        return None


def _coerce_string_list(v: Any) -> List[str]:
    """Coerce whatever the LLM emitted into a list[str], dropping empties."""
    if v is None:
        return []
    if isinstance(v, (str, dict)):
        # Single value emitted instead of a list — wrap it.
        coerced = _coerce_item_to_string(v)
        return [coerced] if coerced else []
    if isinstance(v, list):
        out: List[str] = []
        for item in v:
            coerced = _coerce_item_to_string(item)
            if coerced:
                out.append(coerced)
        return out
    # Fallback — anything else, stringify.
    coerced = _coerce_item_to_string(v)
    return [coerced] if coerced else []


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

    @field_validator("evidence", "triggered_policies", "recommended_actions", mode="before")
    @classmethod
    def _coerce_string_list_fields(cls, v: Any) -> List[str]:
        # Small models (llama3.2:3b) sometimes emit list-of-dicts where a
        # list-of-strings is expected.  Coerce instead of rejecting — losing
        # the narrative in a fallback is worse than accepting a slightly
        # messier string.
        return _coerce_string_list(v)

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
