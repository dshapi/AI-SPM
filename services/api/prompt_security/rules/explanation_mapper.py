"""
security.rules.explanation_mapper
───────────────────────────────────
Maps block reasons and Llama Guard category codes to user-facing explanation
strings.

Rules:
- Explanations come ONLY from the pre-approved mapping in models/block_response.py.
- Raw model output, policy rule names, and system internals are NEVER exposed.
- Unknown/empty categories fall back to a generic safe message.
"""
from __future__ import annotations

from typing import List

from models.block_response import (
    map_categories_to_explanation,
    get_refusal_explanation,
    _UNAVAILABLE_EXPLANATION,
    _POLICY_UNAVAILABLE_EXPLANATION,
)
from prompt_security.models import (
    REASON_GUARD_UNAVAILABLE,
    REASON_LEXICAL_BLOCK,
    REASON_POLICY_BLOCK,
    REASON_POLICY_UNAVAILABLE,
)

# Reason codes that use a fixed system message (not the random refusal)
_FIXED_EXPLANATIONS = {
    REASON_GUARD_UNAVAILABLE:  _UNAVAILABLE_EXPLANATION,
    REASON_POLICY_UNAVAILABLE: _POLICY_UNAVAILABLE_EXPLANATION,
}

# Reason codes that use a random refusal permutation
_REFUSAL_REASONS = {REASON_LEXICAL_BLOCK, REASON_POLICY_BLOCK, "obfuscation_block"}


class ExplanationMapper:
    """
    Maps a block reason + category list to a user-facing explanation string.

    Priority:
    1. Reason code has a dedicated explanation → use it directly.
    2. Categories are known S-codes → delegate to map_categories_to_explanation().
    3. Fallback → generic safe message.
    """

    def map(self, reason: str, categories: List[str]) -> str:
        """
        Return a safe, user-facing explanation string.

        Parameters
        ----------
        reason     : Block reason code (REASON_* constants from prompt_security.models).
        categories : Llama Guard S-codes, e.g. ["S9"] or [].

        Returns
        -------
        str — never empty, never contains raw model output.
        """
        # Fixed system messages for availability/timeout reasons
        if reason in _FIXED_EXPLANATIONS:
            return _FIXED_EXPLANATIONS[reason]
        # Lexical / OPA / obfuscation → random refusal permutation
        if reason in _REFUSAL_REASONS:
            return get_refusal_explanation()
        # Guard-identified unsafe categories → use the category mapping
        if categories:
            return map_categories_to_explanation(categories)
        # Final fallback → random refusal
        return get_refusal_explanation()
