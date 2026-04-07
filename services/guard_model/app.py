"""
Guard Model Service — pre-LLM content screening.

Implements Llama Guard 3 safety categories (S1-S13) as a keyword/regex
classifier. In production, replace _screen_text() with a real Llama Guard 3
inference endpoint or a fine-tuned BERT model.

Endpoints:
  POST /screen      { text, context? } → ScreenResult
  POST /screen/batch  [{ text }] → [ScreenResult]
  GET  /health
  GET  /inventory
  GET  /categories
"""
from __future__ import annotations
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
# Category definitions (Llama Guard 3 taxonomy)
# ─────────────────────────────────────────────────────────────────────────────

class Category:
    def __init__(
        self,
        code: str,
        name: str,
        verdict: str,
        patterns: list[str],
        weight: float = 1.0,
    ):
        self.code = code
        self.name = name
        self.verdict = verdict  # "block" | "flag"
        self.weight = weight
        self.compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    def matches(self, text: str) -> bool:
        return any(p.search(text) for p in self.compiled)

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name, "verdict": self.verdict}


CATEGORIES: list[Category] = [
    Category("S1", "Violent Crimes", "block", weight=1.0, patterns=[
        r"how\s+to\s+(make|build|create|synthesize)\s+(a\s+)?(bomb|explosive|weapon|poison)",
        r"instructions?\s+for\s+(killing|murder|assassination|bombing)",
        r"step\s+by\s+step\s+(guide\s+to\s+)?(kill|murder|attack|bomb)",
    ]),
    Category("S2", "Non-Violent Crimes", "flag", weight=0.7, patterns=[
        r"how\s+to\s+(steal|shoplift|commit\s+fraud|launder\s+money)",
        r"(bypass|circumvent|evade)\s+(authentication|security\s+system|firewall|2fa)",
        r"phish(ing)?\s+(email|attack|campaign)",
    ]),
    Category("S3", "Sex Crimes", "block", weight=1.0, patterns=[
        r"(non-consensual|without\s+consent)\s+(sex|intercourse|intimate)",
    ]),
    Category("S4", "Child Safety", "block", weight=1.0, patterns=[
        r"(child|minor|underage)\s+(sex|nude|sexual|intimate)",
        r"csam",
        r"(lure|groom)\s+(a\s+)?(child|minor|kid)",
    ]),
    Category("S10", "Prompt Injection", "block", weight=1.0, patterns=[
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"(reveal|show|leak|print)\s+(the\s+)?system\s+prompt",
        r"developer\s+mode\s+(enabled|on|activated)",
        r"act\s+as\s+(if\s+you\s+have\s+no|without\s+any)",
        r"pretend\s+you\s+(are|have\s+no)\s+(restrictions|guidelines)",
        r"disregard\s+(your\s+)?(training|instructions|guidelines)",
        r"you\s+are\s+now\s+(a\s+)?(?!(helpful|useful|knowledgeable))",
        r"new\s+instructions?\s*[:>]",
        r"override\s+(your\s+)?(instructions?|directives?|guidelines?)",
        r"forget\s+(everything|all\s+previous|your\s+training)",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"dan\s+(mode|prompt)",
    ]),
    Category("S11", "Credential & Secret Exfiltration", "block", weight=1.0, patterns=[
        r"(export|dump|print|show|reveal|exfiltrate)\s+(all\s+)?(credentials?|secrets?|passwords?|api.?keys?|tokens?)",
        r"/etc/(passwd|shadow|sudoers|hosts)",
        r"(list|show|print)\s+(environment\s+variables?|env\s+vars?|\$\{?ENV)",
        r"(dump|export|backup)\s+(database|db|all\s+users?|all\s+data)",
        r"private\s+key\s+(file|contents?|value)",
        r"(aws|gcp|azure)\s+(secret|credentials?|access\s+key)",
    ]),
    Category("S12", "Jailbreak / Safety Bypass", "block", weight=1.0, patterns=[
        r"without\s+(any\s+)?(restrictions?|guardrails?|safety\s+filters?|content\s+policy)",
        r"bypass\s+(safety|content\s+filter|guardrail|policy|restriction)",
        r"(ignore|disable|turn\s+off)\s+(safety|your\s+guidelines|ethical\s+constraints?)",
        r"god\s+mode",
        r"unrestricted\s+(mode|access|response)",
        r"no\s+restrictions?\s+(mode|enabled)",
    ]),
    Category("S13", "Tool & System Abuse", "block", weight=0.9, patterns=[
        r"(delete|remove|wipe|truncate|drop)\s+(all\s+)?(files?|database|tables?|users?|data)",
        r"rm\s+-rf",
        r"shutdown\s+(the\s+)?(system|server|service)",
        r"run\s+(shell|bash|powershell)\s+(command|script|code)",
        r"(call|invoke|execute)\s+(the\s+)?admin\s+(api|endpoint|function)",
        r"(disable|deactivate)\s+(all\s+)?user\s+accounts?",
        r"format\s+(the\s+)?(disk|drive|volume)",
    ]),
    Category("S14", "Privilege Escalation", "block", weight=0.9, patterns=[
        r"(grant|give|elevate)\s+(me\s+)?(admin|root|superuser)\s+(access|privileges?|rights?|role)",
        r"(become|switch\s+to|run\s+as)\s+(admin|root|superuser)",
        r"sudo\s+(su|bash|sh|command)",
        r"impersonate\s+(an?\s+)?(admin|administrator|system|root)",
    ]),
    Category("S15", "Social Engineering", "flag", weight=0.5, patterns=[
        r"(my\s+boss|ceo|management|security\s+team)\s+(told|asked|authorized|requires?)\s+me\s+to",
        r"(it'?s?\s+an\s+)?(urgent|emergency)\s+(please\s+)?(bypass|ignore|skip)",
        r"authorized\s+by\s+(management|security|cto|ciso)",
        r"don'?t\s+(tell|inform|alert)\s+(anyone|the\s+security\s+team)",
    ]),
]

# Map code → Category for fast lookup
CATEGORY_INDEX = {c.code: c for c in CATEGORIES}


# ─────────────────────────────────────────────────────────────────────────────
# Screening logic
# ─────────────────────────────────────────────────────────────────────────────

class ScreenRequest(BaseModel):
    text: str
    context: str = "user_input"  # user_input | tool_output | retrieved_context


class ScreenResult(BaseModel):
    verdict: str
    score: float
    categories: List[str]
    category_details: List[dict] = []
    processing_ms: int = 0


def _screen_text(text: str, context: str = "user_input") -> ScreenResult:
    """
    Screen text against all safety categories.
    Returns worst-case verdict across all triggered categories.
    Score is a weighted sum capped at 1.0.
    """
    t0 = time.time()
    triggered: list[Category] = []

    for category in CATEGORIES:
        if category.matches(text):
            triggered.append(category)

    if not triggered:
        return ScreenResult(
            verdict="allow",
            score=0.0,
            categories=[],
            processing_ms=int((time.time() - t0) * 1000),
        )

    # Worst verdict wins
    verdict = "block" if any(c.verdict == "block" for c in triggered) else "flag"

    # Score = weighted count, normalised
    raw_score = sum(c.weight * 0.30 for c in triggered)
    score = min(round(raw_score, 4), 1.0)

    category_codes = [c.code for c in triggered]
    details = [
        {"code": c.code, "name": c.name, "verdict": c.verdict}
        for c in triggered
    ]

    return ScreenResult(
        verdict=verdict,
        score=score,
        categories=category_codes,
        category_details=details,
        processing_ms=int((time.time() - t0) * 1000),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "guard_model",
        "version": "3.0.0",
        "backend": "keyword-classifier (stub — replace with Llama Guard 3 in production)",
        "categories_loaded": len(CATEGORIES),
        "uptime_seconds": int(time.time() - _start_time),
    }


@app.get("/inventory")
def inventory():
    return {
        "service": "cpm-guard-model",
        "version": "3.0.0",
        "model": "keyword-classifier-v1",
        "production_note": "Replace _screen_text() with Llama Guard 3 or fine-tuned BERT",
        "categories": [c.to_dict() for c in CATEGORIES],
        "capabilities": ["content_screening", "category_classification", "batch_screening"],
    }


@app.get("/categories")
def categories():
    return {"categories": [c.to_dict() for c in CATEGORIES]}


@app.post("/screen", response_model=ScreenResult)
def screen(req: ScreenRequest):
    return _screen_text(req.text, req.context)


@app.post("/screen/batch")
def screen_batch(requests_list: List[ScreenRequest]):
    return [_screen_text(r.text, r.context) for r in requests_list]
