"""
services/prompt_processor.py
──────────────────────────────
PromptProcessor: coordinates pre-LLM guard screening and
post-LLM output scanning.

session_service delegates all content inspection to this class,
keeping the pipeline orchestration readable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from clients.guard_client import GuardClient, ScreenResult
from clients.output_scanner import OutputScanner, ScanResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-screen result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PreScreenResult:
    verdict: str                            # allow | flag | block
    score: float
    categories: List[str] = field(default_factory=list)
    backend: str = "unknown"

    @property
    def allowed(self) -> bool:
        return self.verdict != "block"


# ─────────────────────────────────────────────────────────────────────────────
# Post-scan result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PostScanResult:
    verdict: str                            # allow | flag | block
    pii_types: List[str] = field(default_factory=list)
    secret_types: List[str] = field(default_factory=list)
    scan_notes: List[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def has_sensitive_data(self) -> bool:
        return bool(self.pii_types or self.secret_types)


# ─────────────────────────────────────────────────────────────────────────────
# Processor
# ─────────────────────────────────────────────────────────────────────────────

class PromptProcessor:
    """
    Stateless coordinator for content inspection steps.

    Injected with GuardClient and OutputScanner so each can be
    swapped independently (real HTTP vs regex fallback vs mock).
    """

    def __init__(
        self,
        guard_client: GuardClient,
        output_scanner: OutputScanner,
    ):
        self._guard = guard_client
        self._scanner = output_scanner

    async def pre_screen(self, prompt: str) -> PreScreenResult:
        """
        Guard-model screen before LLM call.
        Returns PreScreenResult with allowed=False if verdict is "block".
        """
        logger.debug("PromptProcessor.pre_screen prompt_len=%d", len(prompt))
        result: ScreenResult = await self._guard.screen(prompt, context="user_input")
        logger.info(
            "pre_screen verdict=%s score=%.4f categories=%s backend=%s",
            result.verdict, result.score, result.categories, result.backend,
        )
        return PreScreenResult(
            verdict=result.verdict,
            score=result.score,
            categories=result.categories,
            backend=result.backend,
        )

    def post_scan(self, text: str) -> PostScanResult:
        """
        Synchronous regex-only output scan.
        Call post_scan_async() for full two-pass scan with LLM.
        """
        scan: ScanResult = self._scanner.scan(text)
        return PostScanResult(
            verdict=scan.verdict,
            pii_types=scan.pii_types,
            secret_types=scan.secret_types,
            scan_notes=scan.scan_notes,
        )

    async def post_scan_async(self, text: str) -> PostScanResult:
        """Full two-pass async scan (regex + optional LLM semantic scan)."""
        scan: ScanResult = await self._scanner.scan_async(text)
        return PostScanResult(
            verdict=scan.verdict,
            pii_types=scan.pii_types,
            secret_types=scan.secret_types,
            scan_notes=scan.scan_notes,
        )
