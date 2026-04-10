"""
models/lexical_screen.py
────────────────────────
Fast regex-based lexical screening for known jailbreak / prompt-injection patterns.
Runs BEFORE the Llama Guard call to catch cheap, obvious attacks instantly.

Returns True (blocked) or False (pass).
Never surfaces raw pattern text to the user — callers use _LEXICAL_EXPLANATION.
"""
from __future__ import annotations
import re
from typing import Optional

# ── Compiled pattern list ─────────────────────────────────────────────────────
# Each entry is a compiled regex that, if matched, triggers an immediate block.
# Patterns are intentionally broad (false-positives are acceptable; LLM guard
# handles borderline cases). Keep patterns case-insensitive.

_PATTERNS: list[re.Pattern] = [p for p in (re.compile(r, re.IGNORECASE | re.DOTALL) for r in [
    # ── Direct instruction-override attempts ─────────────────────────────────
    r"ignore\s+(all\s+)?(previous|prior|above|system|your)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|prior|above|system|your)\s+instructions?",
    r"forget\s+(all\s+)?(previous|prior|above|your)\s+instructions?",
    r"override\s+(all\s+)?(previous|prior|system|your)?\s*instructions?",
    r"you\s+are\s+now\s+(in\s+)?(DAN|jailbreak|unrestricted|developer|god)\s+mode",
    r"(enter|activate|enable)\s+(DAN|jailbreak|developer|god|unrestricted)\s+mode",
    r"pretend\s+(you\s+have\s+no\s+restrictions|you\s+are\s+unrestricted)",

    # ── Persona-hijack / role-play escapes ───────────────────────────────────
    r"act\s+as\s+(an?\s+)?(unrestricted|uncensored|unfiltered|evil|malicious)\s+AI",
    r"you\s+are\s+now\s+(an?\s+)?(unrestricted|uncensored|unfiltered|evil|malicious)\s+(AI|assistant|chatbot)",
    r"roleplay\s+as\s+(an?\s+)?(unrestricted|uncensored|unfiltered)\s+(AI|assistant)",
    r"simulate\s+(an?\s+)?(unrestricted|uncensored|evil|malicious)\s+(AI|assistant|chatbot)",
    r"DAN\s*:\s*",        # DAN: prefix
    r"\[DAN\]",           # [DAN] tag
    r"jailbreak",

    # ── System-prompt exfiltration ────────────────────────────────────────────
    r"(show|reveal|print|output|repeat|tell me)\s+(your\s+)?(system\s+prompt|initial\s+instructions?|base\s+prompt)",
    r"what\s+(are|were)\s+your\s+(original|initial|base|system)\s+instructions?",
    r"(output|print|repeat)\s+everything\s+(above|before)\s+this",
    r"ignore\s+the\s+above\s+and\s+",

    # ── Prompt injection markers ──────────────────────────────────────────────
    r"<\s*/?system\s*>",              # <system> / </system> tags
    r"\[\s*SYSTEM\s*\]",              # [SYSTEM] tag
    r"###\s*SYSTEM",                  # ### SYSTEM header
    r"---\s*SYSTEM\s*---",
    r"<\s*/?instructions?\s*>",       # <instructions> tags
    r"\[\s*INST\s*\]",                # Llama-style [INST]
    r"<\|im_start\|>",                # ChatML injection
    r"<\|im_end\|>",

    # ── Token-smuggling / encoding tricks ────────────────────────────────────
    r"base64\s*:\s*[A-Za-z0-9+/=]{20,}",          # inline base64 payload
    r"hex\s*:\s*([0-9a-fA-F]{2}\s*){8,}",         # inline hex payload

    # ── Goal hijacking ────────────────────────────────────────────────────────
    r"your\s+(new\s+|true\s+|real\s+|actual\s+)?goal\s+is\s+(now\s+)?to",
    r"your\s+(new\s+|true\s+|real\s+|actual\s+)?purpose\s+is\s+(now\s+)?to",
    r"from\s+now\s+on\s+(you\s+)?(must|will|should|are\s+to)\s+",
    r"respond\s+only\s+(with|as|in)",

    # ── Adversarial suffixes / many-shot patterns ────────────────────────────
    r"(repeat|say|write)\s+the\s+word[s]?\s+.{1,30}\s+100\s+times",
    r"(assistant|ai)\s*:\s*sure[,!]?\s+here",      # fake assistant turn start
])]


def screen_lexical(text: str) -> tuple[bool, Optional[str]]:
    """
    Screen *text* against known jailbreak / prompt-injection patterns.

    Returns:
        (blocked: bool, matched_pattern_label: Optional[str])
        *matched_pattern_label* is a generic label (never the raw pattern text).
    """
    if not text or not text.strip():
        return False, None
    for pat in _PATTERNS:
        if pat.search(text):
            return True, "lexical_injection_pattern"
    return False, None
