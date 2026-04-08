"""
Guard Model Service — pre-LLM content screening.

Primary backend: Groq llama-guard-3-8b (fast cloud inference).
Fallback:        Regex/keyword classifier (runs if GROQ_API_KEY is unset
                 or Groq returns an error).

Endpoints:
  POST /screen        { text, context? } → ScreenResult
  POST /screen/batch  [{ text }]         → [ScreenResult]
  GET  /health
  GET  /inventory
  GET  /categories
"""
from __future__ import annotations

import os
import re
import time
import logging
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

log = logging.getLogger("guard-model")
_start_time = time.time()
app = FastAPI(title="CPM Guard Model v3", version="3.0.0")

# ─────────────────────────────────────────────────────────────────────────────
# Groq client (optional — gracefully absent if key not set)
# ─────────────────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-guard-3-8b")

_groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
        log.info("Groq client initialised — model: %s", GROQ_MODEL)
    except ImportError:
        log.warning("groq package not installed; falling back to regex classifier")

# ─────────────────────────────────────────────────────────────────────────────
# Llama Guard 3 category taxonomy (S1–S15)
# ─────────────────────────────────────────────────────────────────────────────

LLAMA_GUARD_CATEGORIES = """
S1: Violent Crimes — content that enables serious physical harm or death.
S2: Non-Violent Crimes — fraud, theft, hacking, other illegal activity.
S3: Sex Crimes — non-consensual sexual content or facilitation.
S4: Child Safety — sexual content involving minors, grooming, exploitation.
S5: Defamation — false statements of fact presented as true about real people.
S6: Specialized Advice — dangerous medical, legal, or financial advice.
S7: Privacy — doxxing, PII exposure, tracking without consent.
S8: Intellectual Property — reproducing copyrighted content verbatim.
S9: Indiscriminate Weapons — CBRN weapons capable of mass casualties.
S10: Hate — content dehumanising protected groups.
S11: Suicide & Self-Harm — methods, encouragement, or glorification.
S12: Sexual Content — explicit adult content.
S13: Elections — voter suppression or election integrity interference.
S14: Code Interpreter Abuse — malicious code, sandbox escape, data exfil.
S15: Prompt Injection — instructions designed to override system behaviour.
"""

# Human-readable names for each code
CATEGORY_NAMES: dict[str, str] = {
    "S1":  "Violent Crimes",
    "S2":  "Non-Violent Crimes",
    "S3":  "Sex Crimes",
    "S4":  "Child Safety",
    "S5":  "Defamation",
    "S6":  "Specialized Advice",
    "S7":  "Privacy",
    "S8":  "Intellectual Property",
    "S9":  "Indiscriminate Weapons",
    "S10": "Hate",
    "S11": "Suicide & Self-Harm",
    "S12": "Sexual Content",
    "S13": "Elections",
    "S14": "Code Interpreter Abuse",
    "S15": "Prompt Injection",
}

# Categories that result in "block" (others → "flag")
BLOCK_CATEGORIES = {"S1", "S3", "S4", "S9", "S14", "S15"}

# ─────────────────────────────────────────────────────────────────────────────
# Regex fallback classifier (used when Groq is unavailable)
# ─────────────────────────────────────────────────────────────────────────────

class _RegexCategory:
    def __init__(self, code: str, verdict: str, patterns: list[str], weight: float = 1.0):
        self.code = code
        self.verdict = verdict
        self.weight = weight
        self.compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.compiled)


_REGEX_CATEGORIES: list[_RegexCategory] = [
    _RegexCategory("S1", "block", weight=1.0, patterns=[
        r"how\s+to\s+(make|build|create|synthesize)\s+(a\s+)?(bomb|explosive|weapon|poison)",
        r"instructions?\s+for\s+(killing|murder|assassination|bombing)",
    ]),
    _RegexCategory("S2", "flag", weight=0.7, patterns=[
        r"how\s+to\s+(steal|shoplift|commit\s+fraud|launder\s+money)",
        r"(bypass|circumvent|evade)\s+(authentication|security\s+system|firewall|2fa)",
        r"phish(ing)?\s+(email|attack|campaign)",
    ]),
    _RegexCategory("S4", "block", weight=1.0, patterns=[
        r"(child|minor|underage)\s+(sex|nude|sexual|intimate)",
        r"csam",
        r"(lure|groom)\s+(a\s+)?(child|minor|kid)",
    ]),
    _RegexCategory("S9", "block", weight=1.0, patterns=[
        r"how\s+to\s+(make|synthesize|produce)\s+(nerve\s+agent|sarin|vx|mustard\s+gas|anthrax)",
        r"(biological|chemical|nuclear|radiological)\s+weapon",
    ]),
    _RegexCategory("S14", "block", weight=1.0, patterns=[
        r"(delete|remove|wipe|truncate|drop)\s+(all\s+)?(files?|database|tables?|data)",
        r"rm\s+-rf",
        r"(dump|export|print|show|reveal|exfiltrate)\s+(all\s+)?(credentials?|secrets?|passwords?|api.?keys?)",
        r"/etc/(passwd|shadow|sudoers)",
    ]),
    _RegexCategory("S15", "block", weight=1.0, patterns=[
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"(reveal|show|leak|print)\s+(the\s+)?system\s+prompt",
        r"developer\s+mode\s+(enabled|on|activated)",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"bypass\s+(safety|content\s+filter|guardrail|policy)",
        r"forget\s+(everything|all\s+previous|your\s+training)",
    ]),
]


def _regex_screen(text: str) -> "ScreenResult":
    t0 = time.time()
    triggered = [c for c in _REGEX_CATEGORIES if c.matches(text)]
    if not triggered:
        return ScreenResult(
            verdict="allow", score=0.0, categories=[],
            backend="regex-fallback",
            processing_ms=int((time.time() - t0) * 1000),
        )
    verdict = "block" if any(c.verdict == "block" for c in triggered) else "flag"
    score = min(round(sum(c.weight * 0.30 for c in triggered), 4), 1.0)
    codes = [c.code for c in triggered]
    details = [{"code": c, "name": CATEGORY_NAMES.get(c, c), "verdict": "block" if c in BLOCK_CATEGORIES else "flag"} for c in codes]
    return ScreenResult(
        verdict=verdict, score=score, categories=codes,
        category_details=details, backend="regex-fallback",
        processing_ms=int((time.time() - t0) * 1000),
    )

# ─────────────────────────────────────────────────────────────────────────────
# Groq / Llama Guard 3 screener
# ─────────────────────────────────────────────────────────────────────────────

_LLAMA_GUARD_SYSTEM = (
    "You are a content safety classifier. Assess the following message "
    "against the Llama Guard 3 safety taxonomy:\n"
    + LLAMA_GUARD_CATEGORIES
    + "\nRespond with exactly 'safe' OR 'unsafe' followed by a newline and "
    "the violated category codes (e.g. 'unsafe\\nS1,S15'). No other text."
)


def _groq_screen(text: str) -> "ScreenResult":
    t0 = time.time()
    try:
        response = _groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": _LLAMA_GUARD_SYSTEM},
                {"role": "user",   "content": text},
            ],
            temperature=0,
            max_tokens=64,
        )
        raw = response.choices[0].message.content.strip().lower()
    except Exception as exc:
        log.warning("Groq call failed (%s); falling back to regex", exc)
        return _regex_screen(text)

    elapsed = int((time.time() - t0) * 1000)

    if raw.startswith("safe"):
        return ScreenResult(
            verdict="allow", score=0.0, categories=[],
            backend=f"groq/{GROQ_MODEL}",
            processing_ms=elapsed,
        )

    # Parse "unsafe\nS1,S15" or "unsafe\ns1\ns15" etc.
    lines = raw.splitlines()
    codes: list[str] = []
    for line in lines[1:]:
        for token in re.split(r"[\s,]+", line):
            code = token.strip().upper()
            if re.match(r"^S\d{1,2}$", code):
                codes.append(code)

    if not codes:
        # Groq said unsafe but gave no codes — treat conservatively
        codes = ["S1"]

    verdict = "block" if any(c in BLOCK_CATEGORIES for c in codes) else "flag"
    score   = min(round(len(codes) * 0.35, 4), 1.0)
    details = [{"code": c, "name": CATEGORY_NAMES.get(c, c), "verdict": "block" if c in BLOCK_CATEGORIES else "flag"} for c in codes]

    return ScreenResult(
        verdict=verdict, score=score, categories=codes,
        category_details=details, backend=f"groq/{GROQ_MODEL}",
        processing_ms=elapsed,
    )

# ─────────────────────────────────────────────────────────────────────────────
# Unified screen function
# ─────────────────────────────────────────────────────────────────────────────

def _screen_text(text: str, context: str = "user_input") -> "ScreenResult":
    if _groq_client:
        return _groq_screen(text)
    return _regex_screen(text)

# ─────────────────────────────────────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────────────────────────────────────

class ScreenRequest(BaseModel):
    text: str
    context: str = "user_input"


class ScreenResult(BaseModel):
    verdict: str                        # allow | flag | block
    score: float
    categories: List[str]
    category_details: List[dict] = []
    backend: str = "unknown"
    processing_ms: int = 0

# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    backend = f"groq/{GROQ_MODEL}" if _groq_client else "regex-fallback"
    return {
        "status": "ok",
        "service": "guard_model",
        "version": "3.0.0",
        "backend": backend,
        "groq_enabled": bool(_groq_client),
        "uptime_seconds": int(time.time() - _start_time),
    }


@app.get("/inventory")
def inventory():
    backend = f"groq/{GROQ_MODEL}" if _groq_client else "regex-fallback"
    return {
        "service": "cpm-guard-model",
        "version": "3.0.0",
        "model": GROQ_MODEL if _groq_client else "keyword-classifier-v1",
        "backend": backend,
        "categories": [{"code": k, "name": v} for k, v in CATEGORY_NAMES.items()],
        "capabilities": ["content_screening", "category_classification", "batch_screening"],
    }


@app.get("/categories")
def categories():
    return {
        "categories": [
            {"code": k, "name": v, "verdict": "block" if k in BLOCK_CATEGORIES else "flag"}
            for k, v in CATEGORY_NAMES.items()
        ]
    }


@app.post("/screen", response_model=ScreenResult)
def screen(req: ScreenRequest):
    return _screen_text(req.text, req.context)


@app.post("/screen/batch")
def screen_batch(requests_list: List[ScreenRequest]):
    return [_screen_text(r.text, r.context) for r in requests_list]
