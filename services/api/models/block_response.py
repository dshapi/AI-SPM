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
    "S1":  "This request involves violent or harmful activity, which is not allowed.",
    "S2":  "This request involves chemical weapons or substances capable of causing serious harm, which is disallowed.",
    "S3":  "This request involves biological weapons or dangerous pathogens, which is strictly prohibited.",
    "S4":  "This request involves radiological or nuclear weapons capable of mass harm, which is strictly prohibited.",
    "S5":  "This request involves nuclear, chemical, or biological weapons capable of mass harm, which cannot be assisted with.",
    "S6":  "This request asks for specialized medical, legal, or professional advice that cannot be safely provided here.",
    "S7":  "This request involves fraud, illegal financial activity, or other harmful illegal conduct.",
    "S8":  "This request involves content that depicts or targets minors in an explicit or harmful way, which is strictly prohibited.",
    "S9":  "This request involves weapons or materials capable of causing mass harm, which is disallowed.",
    "S10": "This request includes hateful or abusive content directed at protected groups, which is not permitted.",
    "S11": "This request involves self-harm content. If you are in crisis, please seek professional support.",
    "S12": "This request involves explicit sexual adult content, which is not permitted on this platform.",
    "S13": "This request involves tracking, stalking, or privacy-violating activity, which is not permitted.",
    "S14": "This request involves potentially destructive code or system commands, which is not allowed.",
    "S15": "This request appears to attempt overriding system safety instructions, which is not permitted.",
}

_UNAVAILABLE_EXPLANATION = "The request could not be safely evaluated. Please try again later."
_POLICY_UNAVAILABLE_EXPLANATION = "Policy evaluation is temporarily unavailable. Request blocked for safety."

# ── Refusal message permutations ─────────────────────────────────────────────
# Shown in random order for lexical blocks, OPA policy blocks, and generic falls.
# Keep phrasing friendly but firm — never expose internal policy details.
_REFUSAL_PERMUTATIONS: list[str] = [
    (
        "No. This request will never be fulfilled, no matter how many times it is asked.\n\n"
        "If you are bored or frustrated, I genuinely would love to help you with something constructive instead! "
        "Here are some ideas:\n"
        "- 🎮 Game recommendations\n"
        "- 💡 Learn a new skill or hobby\n"
        "- 📚 Find something interesting to read\n"
        "- 🎵 Music or playlist suggestions\n"
        "- 💻 Help with a work or school project\n\n"
        "Is there something positive I can help you with today?"
    ),
    (
        "This request won't be fulfilled — not now, not ever, regardless of how it's rephrased.\n\n"
        "But I'd genuinely love to point you toward something useful! How about:\n"
        "- 🎮 Game or entertainment recommendations\n"
        "- 💡 Picking up a new skill or hobby\n"
        "- 📚 Finding something great to read\n"
        "- 🎵 Music and playlist ideas\n"
        "- 💻 A work or personal project\n\n"
        "What can I actually help you with today?"
    ),
    (
        "That's a no — and it will always be a no.\n\n"
        "If you're curious or just bored, here are some genuinely useful things I can help with instead:\n"
        "- 🎮 Games and entertainment ideas\n"
        "- 💡 Learning something new\n"
        "- 📚 Book or article recommendations\n"
        "- 🎵 Music discovery\n"
        "- 💻 Work, school, or personal projects\n\n"
        "Let's make this time worthwhile — what sounds interesting?"
    ),
    (
        "I won't help with this, and no amount of rephrasing will change that.\n\n"
        "On the bright side, I'm great at a lot of other things! For example:\n"
        "- 🎮 Game recommendations\n"
        "- 💡 New skills and hobbies to explore\n"
        "- 📚 Books and articles worth your time\n"
        "- 🎵 Music and playlists\n"
        "- 💻 Help with a project\n\n"
        "Seriously — what would you actually like to do today?"
    ),
]


def get_refusal_explanation() -> str:
    """Return a random refusal message from the approved permutations list."""
    import random
    return random.choice(_REFUSAL_PERMUTATIONS)


# Aliases used by explanation_mapper — resolved at call time via get_refusal_explanation()
_LEXICAL_EXPLANATION = _REFUSAL_PERMUTATIONS[0]   # default / import-time alias
_OPA_EXPLANATION     = _REFUSAL_PERMUTATIONS[0]   # default / import-time alias
_GENERIC_EXPLANATION = _REFUSAL_PERMUTATIONS[0]   # default / import-time alias


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
    matched_rule: Optional[str] = Field(None, description="The specific OPA rule or guard rule that triggered the block, e.g. 'posture score exceeds block threshold'.")
    session_id: Optional[str] = Field(None, description="Client-supplied session identifier")
    correlation_id: Optional[str] = Field(None, description="UUID for correlating this block across logs")
