"""
models/lexical_screen.py
────────────────────────
Fast lexical screening for known jailbreak / prompt-injection patterns.
Runs BEFORE the Llama Guard call to catch cheap, obvious attacks instantly.

Patterns are now sourced from the canonical registry in
platform_shared/lexical_patterns.py so that:
  - Every phrase in PROMPT_PATTERNS is checked here (full parity with the
    risk-scoring path in the processor / agent-orchestrator).
  - Every regex in LEXICAL_REGEX_PATTERNS is also checked here (variation
    handling that substring matching alone cannot provide).
  - Adding a new attack class to the registry automatically covers both the
    API fast-block layer and the downstream risk-scoring pipeline.

Public API is unchanged:
    screen_lexical(text) -> (blocked: bool, matched_category: Optional[str])

The returned category string now matches a key from PROMPT_PATTERNS
(e.g. "prompt_injection", "jailbreak_attempt") rather than the previous
generic "lexical_injection_pattern", giving callers richer context.

Never surfaces raw pattern text to the user — callers use _LEXICAL_EXPLANATION.
"""
from __future__ import annotations

from typing import Optional, Tuple

from platform_shared.lexical_patterns import (
    PROMPT_PATTERNS,
    LEXICAL_REGEX_PATTERNS,
)

# Human-readable explanation returned in 400 responses.  The raw pattern that
# fired is intentionally omitted so adversaries cannot observe exactly what
# triggered the block and tune their evasion accordingly.
_LEXICAL_EXPLANATION = (
    "This request was blocked because it matched a known attack pattern. "
    "If you believe this is a false positive, contact your administrator."
)


def screen_lexical(text: str) -> Tuple[bool, Optional[str]]:
    """
    Screen *text* against known jailbreak / prompt-injection patterns.

    Evaluation order (first match short-circuits):
    1. Regex scan — LEXICAL_REGEX_PATTERNS handles natural-language variation
       (optional whitespace, common synonyms, alternate phrasings).
    2. Substring scan — PROMPT_PATTERNS provides exhaustive coverage of
       precise phrases that regexes would need many entries to replicate.

    Returns:
        (blocked: bool, category: Optional[str])
        *category* is the signal label (e.g. "prompt_injection") or None.
    """
    if not text or not text.strip():
        return False, None

    # ── Pass 1: compiled regex scan ──────────────────────────────────────────
    for category, pattern in LEXICAL_REGEX_PATTERNS:
        if pattern.search(text):
            return True, category

    # ── Pass 2: substring scan against full PROMPT_PATTERNS registry ─────────
    text_lower = text.lower()
    for category, phrases in PROMPT_PATTERNS.items():
        for phrase in phrases:
            if phrase in text_lower:
                return True, category

    return False, None
