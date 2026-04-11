"""
security.rules.normalizer
──────────────────────────
Text normalization before security evaluation.

Normalization is intentionally minimal: we collapse redundant whitespace and
apply Unicode NFC form.  We do NOT lowercase (case can be semantically
significant for guard models and pattern matching).

The normalizer is a pure function with no I/O and no side effects.
"""
from __future__ import annotations

import re
import unicodedata


class Normalizer:
    """
    Normalize raw prompt text for security evaluation.

    Operations (in order):
    1. Unicode NFC normalization — ensures canonical character forms.
    2. Collapse consecutive horizontal whitespace — ≥2 spaces/tabs → single space.
    3. Strip leading and trailing whitespace.

    Newlines are deliberately preserved (they are semantically meaningful in
    multi-line prompts and structured injection attempts).
    """

    # Collapse 2+ horizontal whitespace chars (space or tab) into a single space.
    # Newlines (\n, \r) are NOT affected.
    _WS_RE = re.compile(r"[ \t]{2,}")

    def normalize(self, text: str) -> str:
        """
        Return a normalized copy of *text*.  Returns empty string if *text* is
        None, empty, or whitespace-only.
        """
        if not text:
            return ""
        # 1. Unicode NFC
        text = unicodedata.normalize("NFC", text)
        # 2. Collapse horizontal whitespace runs
        text = self._WS_RE.sub(" ", text)
        # 3. Strip
        return text.strip()
