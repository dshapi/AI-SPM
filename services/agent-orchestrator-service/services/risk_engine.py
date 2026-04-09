"""
services/risk_engine.py
────────────────────────
Upgraded RiskEngine — delegates to platform_shared.risk for all scoring
functions so signal taxonomy stays consistent across the whole platform.

New dimensions vs the previous version:
  • identity_risk    — roles/scopes scoring via score_identity()
  • guard_risk       — guard model verdict contribution via score_guard()
  • intent_drift     — session-level semantic drift via compute_intent_drift()
  • retrieval_trust  — RAG context trust via compute_retrieval_trust()
  • ttps             — MITRE ATLAS TTP codes via map_ttps()
  • fused_score      — fuse_risks() replaces manual accumulator

Backward compatibility: all new params are keyword-only with safe defaults.
Existing callers using score(prompt, tools, agent_id, context) work unchanged.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from platform_shared.risk import (
    extract_signals,
    score_prompt,
    score_identity,
    score_guard,
    compute_retrieval_trust,
    compute_intent_drift,
    fuse_risks,
    map_ttps,
)

from schemas.session import RiskSummary, RiskTier

logger = logging.getLogger(__name__)


@dataclass
class RiskResult:
    score: float
    tier: RiskTier
    signals: List[str] = field(default_factory=list)
    ttps: List[str] = field(default_factory=list)
    prompt_hash: str = ""

    def to_schema(self) -> RiskSummary:
        return RiskSummary(score=self.score, tier=self.tier, signals=self.signals)


class RiskEngine:
    """
    Stateless risk scorer backed by platform_shared.risk functions.
    Thread-safe; no mutable state.
    """

    _TIER_MAP = [
        (0.75, RiskTier.CRITICAL),
        (0.50, RiskTier.HIGH),
        (0.25, RiskTier.MEDIUM),
        (0.00, RiskTier.LOW),
    ]

    def score(
        self,
        prompt: str,
        tools: List[str],
        agent_id: str,
        context: dict,
        *,
        roles: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        guard_verdict: str = "allow",
        guard_score: float = 0.0,
        baseline_prompts: Optional[List[str]] = None,
        retrieved_items: Optional[list] = None,
    ) -> RiskResult:
        roles = roles or []
        scopes = scopes or []
        baseline_prompts = baseline_prompts or []
        retrieved_items = retrieved_items or []

        # ── Prompt risk ──────────────────────────────────────────────────────
        signals = extract_signals(prompt)
        prompt_risk = score_prompt(prompt, signals)

        # ── Identity risk ────────────────────────────────────────────────────
        identity_risk = score_identity(roles, scopes)

        # ── Guard risk ───────────────────────────────────────────────────────
        guard_risk = score_guard(guard_verdict, guard_score)

        # ── Retrieval trust ──────────────────────────────────────────────────
        retrieval_trust = compute_retrieval_trust(retrieved_items) if retrieved_items else 1.0

        # ── Intent drift ─────────────────────────────────────────────────────
        intent_drift = compute_intent_drift(baseline_prompts, prompt)

        # ── Behavioral / memory risk (placeholders — 0.0 without Redis) ─────
        behavioral_risk = 0.0
        memory_risk = 0.0

        # ── Fuse all dimensions ──────────────────────────────────────────────
        fused = fuse_risks(
            prompt_risk=prompt_risk,
            behavioral_risk=behavioral_risk,
            identity_risk=identity_risk,
            memory_risk=memory_risk,
            retrieval_trust_score=retrieval_trust,
            guard_risk=guard_risk,
            intent_drift=intent_drift,
        )

        tier = self._score_to_tier(fused)
        ttps = map_ttps(signals)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        human_signals = signals if signals else ["No elevated risk signals detected"]

        logger.info(
            "RiskEngine: agent=%s score=%.4f tier=%s signals=%s ttps=%s",
            agent_id, fused, tier.value, signals, ttps,
        )

        return RiskResult(
            score=fused,
            tier=tier,
            signals=human_signals,
            ttps=ttps,
            prompt_hash=prompt_hash,
        )

    def _score_to_tier(self, score: float) -> RiskTier:
        for threshold, tier in self._TIER_MAP:
            if score >= threshold:
                return tier
        return RiskTier.LOW
