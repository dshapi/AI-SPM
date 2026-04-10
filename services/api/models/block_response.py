"""
models/block_response.py
─────────────────────────
Structured response schema for all blocked-request paths.

Rules enforced here:
- Explanations come ONLY from this mapping (never raw model output)
- No internal policy rules, system prompts, or model internals exposed
- User-facing language is plain English

Exports:
  BlockedResponse              — Pydantic model for all block-path HTTP 400 details
  map_categories_to_explanation — Maps S-codes to user-facing explanation string
  _UNAVAILABLE_EXPLANATION     — Guard timeout/unavailable explanation
  _LEXICAL_EXPLANATION         — Lexical/regex block explanation
  _OPA_EXPLANATION             — OPA policy block explanation
  _POLICY_UNAVAILABLE_EXPLANATION — OPA unavailable explanation
"""
from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

# ── Per-category user-facing explanations ────────────────────────────────────
# Derived from Llama Guard 3 S1–S15 taxonomy.
# NEVER expose: raw model output, policy rule names, system prompt details.
_CATEGORY_EXPLANATIONS: Dict[str, str] = {
    "S1":  "This request involves violent activity, which is not allowed.",
    "S2":  "This request involves illegal activity, which cannot be assisted with.",
    "S3":  "This request involves sexual crimes content, which is strictly prohibited.",
    "S4":  "This request involves content that endangers children, which is strictly prohibited.",
    "S5":  "This request involves potentially defamatory content about real people.",
    "S6":  "This request asks for specialized or potentially harmful advice that cannot be provided.",
    "S7":  "This request involves private or personal information in a way that is not permitted.",
    "S8":  "This request involves reproducing protected intellectual property.",
    "S9":  "This request involves weapons or materials capable of mass harm, which is disallowed.",
    "S10": "This request includes hateful or abusive content, which is not permitted.",
    "S11": "This request involves self-harm content. If you are struggling, please seek professional support.",
    "S12": "This request involves explicit sexual content, which is not permitted on this platform.",
    "S13": "This request involves content that could interfere with elections or voting processes.",
    "S14": "This request involves potentially destructive code or system commands, which is not allowed.",
    "S15": "This request appears to attempt overriding system safety instructions, which is not permitted.",
}

_GENERIC_EXPLANATION    = "This request was blocked because it could not be safely processed."
_UNAVAILABLE_EXPLANATION = "The request could not be safely evaluated. Please try again later."
_LEXICAL_EXPLANATION    = "The request contains disallowed or dangerous instructions."
_OPA_EXPLANATION        = "This request was blocked by the platform's security policy."
_POLICY_UNAVAILABLE_EXPLANATION = "Policy evaluation is temporarily unavailable. Request blocked for safety."


def map_categories_to_explanation(categories: Optional[List[str]]) -> str:
    """
    Map a list of Llama Guard category codes → a single user-facing explanation.

    - Picks the most severe / first recognised category.
    - Combines up to two explanations if multiple categories present.
    - Falls back to generic if no known category matched.
    - NEVER returns raw model text (input must be category codes only).
    """
    if not categories:
        return _GENERIC_EXPLANATION
    known = [c for c in categories if c in _CATEGORY_EXPLANATIONS]
    if not known:
        return _GENERIC_EXPLANATION
    if len(known) == 1:
        return _CATEGORY_EXPLANATIONS[known[0]]
    # Two most prominent categories — join into one sentence
    parts = [_CATEGORY_EXPLANATIONS[c].rstrip(".") for c in known[:2]]
    return ". ".join(parts) + "."


# ── Response schema ───────────────────────────────────────────────────────────

class BlockedResponse(BaseModel):
    """Returned as HTTP 400 detail on every blocked request."""
    error: str = Field(default="blocked_by_policy", description="Always 'blocked_by_policy'")
    reason: str = Field(
        ...,
        description="Why the request was blocked. One of: "
                    "llama_guard_unsafe_category | lexical_block | policy_block | "
                    "guard_unavailable | policy_unavailable",
    )
    categories: List[str] = Field(default_factory=list, description="Llama Guard S-codes that triggered block, e.g. ['S9']")
    explanation: str = Field(..., description="User-facing plain English explanation. Never exposes raw model output.")
    session_id: Optional[str] = Field(None, description="Client-supplied session identifier")
    correlation_id: Optional[str] = Field(None, description="UUID for correlating this block across logs")
