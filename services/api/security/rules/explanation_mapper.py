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
    _UNAVAILABLE_EXPLANATION,
    _LEXICAL_EXPLANATION,
    _OPA_EXPLANATION,
    _POLICY_UNAVAILABLE_EXPLANATION,
)
from security.models import (
    REASON_GUARD_UNAVAILABLE,
    REASON_LEXICAL_BLOCK,
    REASON_POLICY_BLOCK,
    REASON_POLICY_UNAVAILABLE,
)

# Map reason code → pre-approved explanation constant
_REASON_TO_EXPLANATION = {
    REASON_GUARD_UNAVAILABLE:  _UNAVAILABLE_EXPLANATION,
    REASON_LEXICAL_BLOCK:      _LEXICAL_EXPLANATION,
    REASON_POLICY_BLOCK:       _OPA_EXPLANATION,
    REASON_POLICY_UNAVAILABLE: _POLICY_UNAVAILABLE_EXPLANATION,
    "obfuscation_block":       _LEXICAL_EXPLANATION,   # obfuscation is a sub-type of lexical
}


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
        reason     : Block reason code (REASON_* constants from security.models).
        categories : Llama Guard S-codes, e.g. ["S9"] or [].

        Returns
        -------
        str — never empty, never contains raw model output.
        """
        if reason in _REASON_TO_EXPLANATION:
            return _REASON_TO_EXPLANATION[reason]
        # Guard-identified unsafe categories → use the category mapping
        if categories:
            return map_categories_to_explanation(categories)
        # Final fallback
        return map_categories_to_explanation([])
