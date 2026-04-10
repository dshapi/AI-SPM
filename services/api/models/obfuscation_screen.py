"""
models/obfuscation_screen.py
────────────────────────────
Detects encoding / obfuscation tricks used to smuggle malicious payloads
past text-based safety classifiers.

Returns (blocked: bool, label: Optional[str]) — same contract as screen_lexical.
No external dependencies beyond the Python standard library.

Checks (in order, first match wins):
  1. Unicode format / invisible characters  (Cf category — RLO, zero-width, etc.)
  2. Base64-encoded printable payload       (≥ 20 decoded bytes)
  3. Hex-encoded payload                    (≥ 8 hex pairs)
  4. ROT13-encoded attack phrases
  5. Leetspeak-normalised attack phrases
"""
from __future__ import annotations
import base64
import binascii
import codecs
import re
import unicodedata
from typing import Optional, Tuple

# ── Unicode invisible / format characters ─────────────────────────────────────
# Cf = Unicode "Format" category: zero-width spaces, RLO/LRO, bidirectional marks.
# Cc (control) is intentionally excluded — it includes legitimate \n, \r, \t.
_MIN_INVISIBLE = 3   # fewer than this → likely accidental, not an attack

# ── Base64 ────────────────────────────────────────────────────────────────────
_B64_RE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_MIN_B64_BYTES = 20

# ── Hex encoding ──────────────────────────────────────────────────────────────
_HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2}[ \-:]?){8,}")

# ── ROT13 trigger phrases (checked after decode) ──────────────────────────────
_ROT13_TRIGGERS = [re.compile(p, re.IGNORECASE) for p in [
    r"ignore\s+(all\s+)?previous",
    r"system\s+prompt",
    r"jailbreak",
    r"act\s+as",
    r"DAN\b",
]]

# ── Leetspeak normalisation ───────────────────────────────────────────────────
_LEET_MAP = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
             "7": "t", "@": "a", "$": "s", "!": "i", "+": "t"}
_LEET_RE  = re.compile("|".join(re.escape(k) for k in _LEET_MAP))
_LEET_TRIGGERS = [re.compile(p, re.IGNORECASE) for p in [
    r"ignore\s+(all\s+)?previous",
    r"jailbreak",
    r"system\s+prompt",
    r"act\s+as",
]]


def screen_obfuscation(text: str) -> Tuple[bool, Optional[str]]:
    """
    Screen *text* for encoding / obfuscation attacks.

    Returns:
        (blocked, label) where label is a short machine tag or None.
    """
    if not text or not text.strip():
        return False, None

    # 1. Unicode invisible / format characters
    invisible = [ch for ch in text if unicodedata.category(ch) == "Cf"]
    if len(invisible) >= _MIN_INVISIBLE:
        return True, "unicode_invisible"

    # 2. Base64 payload
    for m in _B64_RE.finditer(text):
        candidate = m.group(0)
        padded = candidate + "=" * (-len(candidate) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True)
            if len(decoded) >= _MIN_B64_BYTES:
                decoded_text = decoded.decode("utf-8", errors="ignore")
                if decoded_text.isprintable() and len(decoded_text.strip()) >= 8:
                    return True, "base64_payload"
        except (binascii.Error, ValueError):
            pass

    # 3. Hex payload
    for m in _HEX_RE.finditer(text):
        hex_str = re.sub(r"[ \-:]", "", m.group(0))
        if len(hex_str) >= 16:
            try:
                decoded = bytes.fromhex(hex_str).decode("utf-8", errors="ignore")
                if len(decoded.strip()) >= 4:
                    return True, "hex_payload"
            except ValueError:
                pass

    # 4. ROT13
    rot13 = codecs.decode(text, "rot_13")
    for pat in _ROT13_TRIGGERS:
        if pat.search(rot13):
            return True, "rot13_payload"

    # 5. Leetspeak
    normalised = _LEET_RE.sub(lambda m: _LEET_MAP[m.group(0)], text.lower())
    for pat in _LEET_TRIGGERS:
        if pat.search(normalised):
            return True, "leet_payload"

    return False, None
