"""
tools/guard_tool.py
────────────────────
LangChain-compatible tool for screening text through the guard model.

The threat-hunting agent uses this to re-score suspicious prompts or
outputs discovered during a hunt, confirming whether the guard model
would flag / block them under the current rule set.

An httpx-based screen client is injected at startup via set_guard_url().
Falls back to a simple regex classifier when the URL is not configured
(matching the orchestrator's GuardClient fallback behaviour).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_guard_url: Optional[str] = None
_timeout: float = 5.0

# ── Regex fallback ────────────────────────────────────────────────────────
# Mirrors the categories in services/agent-orchestrator-service/clients/guard_client.py
_BLOCK_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"(delete|remove|wipe|truncate|drop)\s+(all\s+)?(files?|database|tables?|data)",
    r"rm\s+-rf",
    r"(dump|export|reveal|exfiltrate)\s+(all\s+)?(credentials?|secrets?|api.?keys?)",
    r"/etc/(passwd|shadow)",
    r"how\s+to\s+(make|build|create|synthesize)\s+(a\s+)?(bomb|explosive|weapon|poison)",
]
_FLAG_PATTERNS = [
    r"(bypass|circumvent|evade)\s+(authentication|security\s+system|firewall|2fa)",
    r"how\s+to\s+(steal|shoplift|commit\s+fraud|launder\s+money)",
    r"(jailbreak|dan|do\s+anything\s+now)",
    r"pretend\s+you\s+(are|have\s+no\s+restrictions)",
    r"roleplay\s+as\s+(an?\s+)?(unrestricted|evil|unfiltered)",
]


def _regex_screen(text: str) -> dict:
    t = text.lower()
    for pat in _BLOCK_PATTERNS:
        if re.search(pat, t):
            return {"verdict": "block", "score": 0.95,
                    "categories": ["regex-block"], "backend": "regex-fallback"}
    for pat in _FLAG_PATTERNS:
        if re.search(pat, t):
            return {"verdict": "flag", "score": 0.6,
                    "categories": ["regex-flag"], "backend": "regex-fallback"}
    return {"verdict": "allow", "score": 0.1, "categories": [], "backend": "regex-fallback"}


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------

def set_guard_url(url: Optional[str], timeout: float = 5.0) -> None:
    """Configure the guard model base URL (called once at startup)."""
    global _guard_url, _timeout
    _guard_url = url or None
    _timeout = timeout


# ---------------------------------------------------------------------------
# Tool: screen_text
# ---------------------------------------------------------------------------

def screen_text(text: str) -> str:
    """
    Screen a text snippet through the guard model to detect threats.

    Use this to re-evaluate suspicious prompts or outputs found during
    a threat hunt, or to validate whether a pattern would be caught.

    Args:
        text: The text to screen (prompt, output, or log excerpt).

    Returns:
        JSON with keys: verdict ('allow'|'flag'|'block'), score (0-1),
        categories (list), backend ('guard-model' or 'regex-fallback').
    """
    if not _guard_url:
        result = _regex_screen(text)
        return json.dumps(result)

    try:
        resp = httpx.post(
            f"{_guard_url}/screen",
            json={"text": text},
            timeout=_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return json.dumps({
            "verdict":    data.get("verdict", "allow"),
            "score":      data.get("score", 0.0),
            "categories": data.get("categories", []),
            "backend":    "guard-model",
        })
    except httpx.TimeoutException:
        logger.warning("guard_tool: timeout — falling back to regex")
        return json.dumps(_regex_screen(text))
    except Exception as exc:
        logger.exception("screen_text failed: %s", exc)
        # Fail open for hunting use-case (we're analysing, not gating)
        result = _regex_screen(text)
        result["fallback_reason"] = str(exc)
        return json.dumps(result)
