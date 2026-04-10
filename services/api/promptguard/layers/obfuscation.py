"""
promptguard.layers.obfuscation
──────────────────────────────
Detects encoding and obfuscation tricks used to smuggle malicious payloads
past text-based safety classifiers.

Checks (in order):
  1. Unicode control / invisible characters
  2. Base64-encoded payload (≥ 20 decodable bytes)
  3. Hex-encoded payload (≥ 8 hex pairs)
  4. ROT13-encoded text (detect known attack phrases after decode)
  5. Leetspeak substitution (detect known attack phrases after normalisation)

Each check is independent; the first hit returns a BLOCK immediately.
"""
from __future__ import annotations
import base64
import binascii
import codecs
import re
import unicodedata
from typing import Optional

from promptguard.layers.base import BaseLayer, LayerResult

# ── Unicode control / invisible character detection ───────────────────────────
# Categories that are invisible or direction-overriding in rendered text.
# Cc (control) is excluded — it includes legitimate \n, \r, \t.
# Cf (format) covers zero-width spaces, RLO/LRO, and other invisible tricks.
_INVISIBLE_CATEGORIES = frozenset({
    "Cf",  # Format characters: zero-width non-joiner, RLO, bidirectional marks, etc.
})
_MIN_INVISIBLE = 3   # require at least this many to avoid false-positives on normal text


# ── Base64 detection ──────────────────────────────────────────────────────────
_B64_RE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_MIN_B64_DECODED_BYTES = 20


# ── Hex encoding detection ────────────────────────────────────────────────────
_HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2}[ \-:]?){8,}")


# ── ROT13 known-bad phrases (after decoding) ──────────────────────────────────
_ROT13_TRIGGERS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"ignore\s+(all\s+)?previous",
        r"system\s+prompt",
        r"jailbreak",
        r"act\s+as",
        r"DAN\b",
    ]
]


# ── Leetspeak normalisation map ───────────────────────────────────────────────
_LEET: dict[str, str] = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "@": "a", "$": "s", "!": "i", "+": "t",
}
_LEET_RE = re.compile("|".join(re.escape(k) for k in _LEET))

_LEET_TRIGGERS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"ignore\s+(all\s+)?previous",
        r"jailbreak",
        r"system\s+prompt",
        r"act\s+as",
    ]
]


class ObfuscationLayer(BaseLayer):
    """
    Detects encoding / obfuscation attacks that attempt to bypass text classifiers.

    Parameters
    ----------
    check_unicode:  Enable invisible/control-character detection (default True)
    check_base64:   Enable base64 payload detection (default True)
    check_hex:      Enable hex-encoded payload detection (default True)
    check_rot13:    Enable ROT13 decode + re-screen (default True)
    check_leet:     Enable leetspeak normalisation + re-screen (default True)
    """

    name = "obfuscation"

    def __init__(
        self,
        check_unicode: bool = True,
        check_base64: bool = True,
        check_hex: bool = True,
        check_rot13: bool = True,
        check_leet: bool = True,
    ) -> None:
        self._check_unicode = check_unicode
        self._check_base64 = check_base64
        self._check_hex = check_hex
        self._check_rot13 = check_rot13
        self._check_leet = check_leet

    # ── Public interface ──────────────────────────────────────────────────────

    def _screen(self, text: str) -> LayerResult:
        if self._check_unicode:
            r = self._check_invisible_chars(text)
            if r:
                return r

        if self._check_base64:
            r = self._check_base64_payload(text)
            if r:
                return r

        if self._check_hex:
            r = self._check_hex_payload(text)
            if r:
                return r

        if self._check_rot13:
            r = self._check_rot13_payload(text)
            if r:
                return r

        if self._check_leet:
            r = self._check_leet_payload(text)
            if r:
                return r

        return LayerResult.allow()

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_invisible_chars(self, text: str) -> Optional[LayerResult]:
        invisible = [ch for ch in text if unicodedata.category(ch) in _INVISIBLE_CATEGORIES]
        if len(invisible) >= _MIN_INVISIBLE:
            return LayerResult.block(
                label="unicode_invisible",
                reason=f"{len(invisible)} invisible/control characters detected",
                score=0.9,
                invisible_count=len(invisible),
            )
        return None

    def _check_base64_payload(self, text: str) -> Optional[LayerResult]:
        for match in _B64_RE.finditer(text):
            candidate = match.group(0)
            # Pad to valid base64 length
            padded = candidate + "=" * (-len(candidate) % 4)
            try:
                decoded_bytes = base64.b64decode(padded, validate=True)
            except (binascii.Error, ValueError):
                continue
            if len(decoded_bytes) >= _MIN_B64_DECODED_BYTES:
                # Try to decode as UTF-8 text; if it looks like printable text,
                # it's more likely to be a payload than a random binary blob
                try:
                    decoded_text = decoded_bytes.decode("utf-8")
                    if decoded_text.isprintable():
                        return LayerResult.block(
                            label="base64_payload",
                            reason="Base64-encoded text payload detected",
                            score=0.85,
                            decoded_length=len(decoded_bytes),
                        )
                except UnicodeDecodeError:
                    pass
        return None

    def _check_hex_payload(self, text: str) -> Optional[LayerResult]:
        for match in _HEX_RE.finditer(text):
            hex_str = re.sub(r"[ \-:]", "", match.group(0))
            if len(hex_str) >= 16:   # at least 8 bytes
                try:
                    decoded = bytes.fromhex(hex_str).decode("utf-8", errors="ignore")
                    if len(decoded.strip()) >= 4:
                        return LayerResult.block(
                            label="hex_payload",
                            reason="Hex-encoded text payload detected",
                            score=0.8,
                            hex_length=len(hex_str),
                        )
                except ValueError:
                    pass
        return None

    def _check_rot13_payload(self, text: str) -> Optional[LayerResult]:
        decoded = codecs.decode(text, "rot_13")
        for pat in _ROT13_TRIGGERS:
            if pat.search(decoded):
                return LayerResult.block(
                    label="rot13_payload",
                    reason=f"ROT13-decoded text matched pattern: {pat.pattern}",
                    score=0.95,
                )
        return None

    def _check_leet_payload(self, text: str) -> Optional[LayerResult]:
        normalised = _LEET_RE.sub(lambda m: _LEET[m.group(0)], text.lower())
        for pat in _LEET_TRIGGERS:
            if pat.search(normalised):
                return LayerResult.block(
                    label="leet_payload",
                    reason=f"Leetspeak-normalised text matched pattern: {pat.pattern}",
                    score=0.85,
                )
        return None
