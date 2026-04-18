"""
security.rules.lexical_scanner
────────────────────────────────
Fast synchronous scanning combining the obfuscation and lexical screens.

Wraps the existing screen_obfuscation() and screen_lexical() functions so
that the PromptSecurityService has a single entry-point for both layers.

No I/O, no side effects, deterministic output.
"""
from __future__ import annotations

from typing import Optional, Tuple

from models.obfuscation_screen import screen_obfuscation
from models.lexical_screen import screen_lexical


class LexicalScanner:
    """
    Combines the obfuscation screen and the lexical (regex) injection screen.

    Evaluation order:
    1. Obfuscation screen — catches encoded / steganographic attacks (unicode
       invisibles, base64, hex, ROT13, leetspeak).
    2. Lexical screen — catches direct instruction-override / jailbreak patterns.

    The first screen to fire short-circuits; subsequent screens are not run.
    """

    def scan(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Scan *text* and return (blocked, label).

        Parameters
        ----------
        text : str
            Normalized prompt text to evaluate.

        Returns
        -------
        blocked : bool
            True if either screen fired.
        label : str | None
            Composite label "screen:category", e.g.
            "obfuscation:base64_payload" or "lexical:prompt_injection",
            "lexical:jailbreak_attempt", "lexical:exfiltration", etc.
            Category names align with PROMPT_PATTERNS keys in
            platform_shared/lexical_patterns.py.
            None when not blocked.
        """
        if not text or not text.strip():
            return False, None

        # ── 1. Obfuscation screen ─────────────────────────────────────────
        obf_blocked, obf_label = screen_obfuscation(text)
        if obf_blocked:
            return True, f"obfuscation:{obf_label}"

        # ── 2. Lexical (regex injection) screen ───────────────────────────
        lex_blocked, lex_label = screen_lexical(text)
        if lex_blocked:
            return True, f"lexical:{lex_label}"

        return False, None
