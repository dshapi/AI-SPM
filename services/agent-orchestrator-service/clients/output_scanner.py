"""
clients/output_scanner.py
──────────────────────────
Two-pass output scanner: regex (PII + secrets) → optional LLM semantic scan.

Ported from output_guard/app.py into an injectable async-compatible class
so session_service.py can call it directly without spawning a Kafka consumer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Regex pattern banks (mirrors output_guard/app.py exactly)
# ─────────────────────────────────────────────────────────────────────────────

_PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                              "ssn"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"),                             "credit_card"),
    (re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"), "email"),
    (re.compile(r"\b(\+?\d[\d\s\-().]{7,14}\d)\b"),                      "phone"),
    (re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),                               "passport"),
    (re.compile(r"\b\d{9}\b"),                                            "national_id"),
    (re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b"), "date_of_birth"),
]

_SECRET_PATTERNS = [
    (re.compile(r"(?i)api[_ -]?key\s*[:=]\s*\S+"),                       "api_key"),
    (re.compile(r"(?i)secret\s*[:=]\s*\S+"),                             "secret"),
    (re.compile(r"(?i)(?<!\w)token\s*[:=]\s*\S+"),                       "token"),
    (re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),             "pem_private_key"),
    (re.compile(r"-----BEGIN\s+CERTIFICATE-----"),                        "pem_certificate"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "jwt_token"),
    (re.compile(r"(?i)(mysql|postgres|postgresql|mongodb|redis|mssql)://[^\s]+"), "connection_string"),
    (re.compile(r"(?i)password\s*[:=]\s*\S+"),                           "password"),
    (re.compile(r"(?i)passwd\s*[:=]\s*\S+"),                             "password"),
    (re.compile(r"AKIA[0-9A-Z]{16}"),                                     "aws_access_key"),
    (re.compile(r"(?i)sk-[a-zA-Z0-9]{20,}"),                             "openai_api_key"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"),                        "github_pat"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    verdict: str                                 # allow | flag | block
    pii_types: List[str] = field(default_factory=list)
    secret_types: List[str] = field(default_factory=list)
    llm_verdict: str = "allow"
    llm_categories: List[str] = field(default_factory=list)
    scan_notes: List[str] = field(default_factory=list)

    @property
    def has_pii(self) -> bool:
        return len(self.pii_types) > 0

    @property
    def has_secrets(self) -> bool:
        return len(self.secret_types) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Scanner
# ─────────────────────────────────────────────────────────────────────────────

class OutputScanner:
    """
    Async-compatible output scanner.

    Args:
        guard_base_url:   URL of guard_model service (None = skip LLM scan).
        llm_scan_enabled: Feature flag — set False in tests/dev.
        timeout:          HTTP timeout for guard_model calls.
    """

    def __init__(
        self,
        guard_base_url: Optional[str] = None,
        llm_scan_enabled: bool = True,
        timeout: float = 3.0,
    ):
        self._guard_url = guard_base_url.rstrip("/") if guard_base_url else None
        self._llm_enabled = llm_scan_enabled and guard_base_url is not None
        self._timeout = timeout

    def scan(self, text: str) -> ScanResult:
        """
        Synchronous scan (regex only).
        Use scan_async() when calling from async contexts with LLM enabled.
        """
        pii_types = [label for pat, label in _PII_PATTERNS if pat.search(text)]
        secret_types = [label for pat, label in _SECRET_PATTERNS if pat.search(text)]
        scan_notes = (
            [f"pii:{t}" for t in pii_types] +
            [f"secret:{t}" for t in secret_types]
        )
        verdict = "block" if secret_types else ("flag" if pii_types else "allow")
        return ScanResult(
            verdict=verdict,
            pii_types=pii_types,
            secret_types=secret_types,
            scan_notes=scan_notes,
        )

    async def scan_async(self, text: str) -> ScanResult:
        """
        Full two-pass async scan: regex first, then optional guard_model LLM.
        """
        result = self.scan(text)

        if not self._llm_enabled or not self._guard_url:
            return result

        # Pass 2: LLM semantic scan
        llm_verdict, llm_categories = await self._llm_scan(text)
        if llm_categories:
            result.scan_notes.extend([f"llm:{c}" for c in llm_categories])
            if llm_verdict == "block":
                result.secret_types.append("llm_detected")
                result.verdict = "block"
            elif llm_verdict == "flag" and result.verdict == "allow":
                result.verdict = "flag"
        result.llm_verdict = llm_verdict
        result.llm_categories = llm_categories
        return result

    async def _llm_scan(self, text: str) -> tuple:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._guard_url}/screen",
                    json={"text": text, "context": "tool_output"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("verdict", "allow"), data.get("categories", [])
        except httpx.TimeoutException:
            logger.warning("OutputScanner: guard_model timeout — skipping LLM scan")
        except Exception as exc:
            logger.warning("OutputScanner: guard_model error (%s) — skipping", exc)
        return "allow", []

    @staticmethod
    def redact_pii(text: str) -> str:
        """Replace PII pattern matches with [REDACTED] placeholders."""
        for pattern, label in _PII_PATTERNS:
            text = pattern.sub(f"[REDACTED:{label.upper()}]", text)
        return text
