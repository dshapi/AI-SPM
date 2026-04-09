"""
clients/guard_client.py
────────────────────────
HTTP client for the guard_model /screen endpoint.

Primary:  POST {base_url}/screen    (when GUARD_MODEL_URL is configured)
Fallback: Regex-based classifier    (zero dependencies, dev/offline mode)

The fallback replicates the regex categories from guard_model/app.py so
the orchestrator behaves correctly even when the guard service is down.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Response model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScreenResult:
    verdict: str                            # allow | flag | block
    score: float
    categories: List[str] = field(default_factory=list)
    category_details: List[dict] = field(default_factory=list)
    backend: str = "unknown"
    processing_ms: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Regex fallback (mirrors guard_model/app.py _REGEX_CATEGORIES)
# ─────────────────────────────────────────────────────────────────────────────

_BLOCK_CATEGORIES = {"S1", "S3", "S4", "S9", "S14", "S15"}

_REGEX_RULES: List[tuple] = [
    ("S1", "block", [
        r"how\s+to\s+(make|build|create|synthesize)\s+(a\s+)?(bomb|explosive|weapon|poison)",
        r"instructions?\s+for\s+(killing|murder|assassination|bombing)",
    ]),
    ("S2", "flag", [
        r"how\s+to\s+(steal|shoplift|commit\s+fraud|launder\s+money)",
        r"(bypass|circumvent|evade)\s+(authentication|security\s+system|firewall|2fa)",
    ]),
    ("S14", "block", [
        r"(delete|remove|wipe|truncate|drop)\s+(all\s+)?(files?|database|tables?|data)",
        r"rm\s+-rf",
        r"(dump|export|reveal|exfiltrate)\s+(all\s+)?(credentials?|secrets?|api.?keys?)",
        r"/etc/(passwd|shadow)",
    ]),
    ("S15", "block", [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"(reveal|show|leak|print)\s+(the\s+)?system\s+prompt",
        r"developer\s+mode\s+(enabled|on|activated)",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"bypass\s+(safety|content\s+filter|guardrail|policy)",
        r"forget\s+(everything|all\s+previous|your\s+training)",
    ]),
]

_COMPILED_RULES = [
    (code, verdict, [re.compile(p, re.IGNORECASE) for p in patterns])
    for code, verdict, patterns in _REGEX_RULES
]


def _regex_screen(text: str) -> ScreenResult:
    triggered = [
        (code, verdict)
        for code, verdict, compiled in _COMPILED_RULES
        if any(rx.search(text) for rx in compiled)
    ]
    if not triggered:
        return ScreenResult(verdict="allow", score=0.0, backend="regex-fallback")
    codes = [c for c, _ in triggered]
    verdict = "block" if any(c in _BLOCK_CATEGORIES for c in codes) else "flag"
    score = min(round(len(triggered) * 0.30, 4), 1.0)
    return ScreenResult(
        verdict=verdict,
        score=score,
        categories=codes,
        backend="regex-fallback",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

class GuardClient:
    """
    Async guard-model client.

    Args:
        base_url: e.g. "http://guard-model:8095".
                  Pass None to always use the regex fallback.
        timeout:  HTTP timeout in seconds.
    """

    def __init__(self, base_url: Optional[str], timeout: float = 3.0):
        self._url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout

    async def screen(self, text: str, context: str = "user_input") -> ScreenResult:
        """
        Screen text for harmful content.
        Falls back to regex classifier on HTTP error or when base_url is None.
        """
        if self._url is None:
            return _regex_screen(text)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/screen",
                    json={"text": text, "context": context},
                )
                resp.raise_for_status()
                data = resp.json()
                return ScreenResult(
                    verdict=data.get("verdict", "allow"),
                    score=data.get("score", 0.0),
                    categories=data.get("categories", []),
                    category_details=data.get("category_details", []),
                    backend=data.get("backend", "guard-model"),
                    processing_ms=data.get("processing_ms", 0),
                )
        except httpx.TimeoutException:
            logger.warning("GuardClient timeout — falling back to regex")
        except Exception as exc:
            logger.warning("GuardClient error (%s) — falling back to regex", exc)

        return _regex_screen(text)
