"""
security.service
─────────────────
PromptSecurityService — the canonical, reusable prompt evaluation service.

Architecture
------------
Every prompt passes through four ordered layers:

  1. Normalizer          — Unicode NFC + whitespace collapse (pure, no I/O)
  2. LexicalScanner      — Obfuscation + regex injection screen (pure, no I/O)
  3. LlamaGuardAdapter   — Llama Guard 3 HTTP call (async, fail-closed)
  4. OPAAdapter          — OPA policy evaluation (async, fail-closed)

The first layer to return "block" short-circuits — subsequent layers are
NOT called, saving latency and avoiding redundant I/O.

Fail-closed guarantee
---------------------
  • LlamaGuardAdapter timeout/exception → block (reason=guard_unavailable)
  • OPAAdapter timeout/exception        → block (reason=policy_unavailable)
  • Any internal exception in evaluate() itself → block (reason=guard_unavailable)
    (logged as ERROR; never silently allows)

Reusability
-----------
The service has no dependency on FastAPI or any HTTP framework.  Construct it
with the desired adapters, call ``await service.evaluate(prompt, context)``,
and act on the returned PromptDecision.

Integration points:
  • /chat endpoint         — main API ingress
  • /chat/stream endpoint  — streaming SSE ingress
  • /api/v1/simulation/screen — admin simulation endpoint
  • Future pipelines       — any async Python context
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from prompt_security.models import (
    PromptDecision,
    ScreeningContext,
    REASON_LEXICAL_BLOCK,
    REASON_GUARD_UNSAFE,
    REASON_GUARD_UNAVAILABLE,
    REASON_POLICY_UNAVAILABLE,
    LAYER_LEXICAL,
    LAYER_GUARD,
    LAYER_POLICY,
)
from prompt_security.rules.normalizer import Normalizer
from prompt_security.rules.lexical_scanner import LexicalScanner
from prompt_security.rules.explanation_mapper import ExplanationMapper
from prompt_security.adapters.guard_adapter import LlamaGuardAdapter
from prompt_security.adapters.policy_adapter import OPAAdapter

log = logging.getLogger("security.service")


class PromptSecurityService:
    """
    Evaluates a prompt against all security layers and returns a PromptDecision.

    Parameters
    ----------
    normalizer       : Normalizer instance (default: Normalizer())
    lexical_scanner  : LexicalScanner instance (default: LexicalScanner())
    guard_adapter    : LlamaGuardAdapter (default: disabled adapter)
    policy_engine    : OPAAdapter (default: localhost OPA)
    explanation_mapper : ExplanationMapper (default: ExplanationMapper())
    """

    def __init__(
        self,
        normalizer:         Optional[Normalizer]         = None,
        lexical_scanner:    Optional[LexicalScanner]     = None,
        guard_adapter:      Optional[LlamaGuardAdapter]  = None,
        policy_engine:      Optional[OPAAdapter]         = None,
        explanation_mapper: Optional[ExplanationMapper]  = None,
    ) -> None:
        self._normalizer  = normalizer         or Normalizer()
        self._lexical     = lexical_scanner    or LexicalScanner()
        self._guard       = guard_adapter      or LlamaGuardAdapter(enabled=False)
        self._policy      = policy_engine      or OPAAdapter(opa_url="http://opa:8181")
        self._mapper      = explanation_mapper or ExplanationMapper()

    # ── Public API ────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        prompt: str,
        context: ScreeningContext,
    ) -> PromptDecision:
        """
        Evaluate *prompt* through all security layers in order.

        Parameters
        ----------
        prompt  : Raw user-supplied prompt text.
        context : Per-request context (tenant, user, roles, session).

        Returns
        -------
        PromptDecision — never raises; fail-closed on any internal error.
        """
        correlation_id = str(uuid.uuid4())
        signals: dict = {"correlation_id": correlation_id}

        # Outer try/except: any unexpected error → fail CLOSED
        try:
            return await self._evaluate_layers(prompt, context, correlation_id, signals)
        except Exception as exc:
            log.error(
                "PromptSecurityService internal error — failing CLOSED: %s",
                exc, exc_info=True,
            )
            return PromptDecision.block(
                reason=REASON_GUARD_UNAVAILABLE,
                explanation=self._mapper.map(REASON_GUARD_UNAVAILABLE, []),
                risk_score=1.0,
                signals={**signals, "internal_error": str(exc)},
                correlation_id=correlation_id,
                blocked_by="service_error",
            )

    # ── Private pipeline ──────────────────────────────────────────────────────

    async def _evaluate_layers(
        self,
        prompt: str,
        context: ScreeningContext,
        correlation_id: str,
        signals: dict,
    ) -> PromptDecision:

        # ── Layer 1: Normalization ────────────────────────────────────────
        normalized = self._normalizer.normalize(prompt)
        signals["normalized_length"] = len(normalized)

        if not normalized:
            # Empty / whitespace-only prompt — allow (no content to classify)
            return PromptDecision.allow(
                risk_score=0.0,
                signals=signals,
                correlation_id=correlation_id,
            )

        # ── Layer 2: Lexical / obfuscation screening ──────────────────────
        lex_blocked, lex_label = self._lexical.scan(normalized)
        if lex_blocked:
            signals["lexical_label"] = lex_label
            log.info(
                "prompt blocked by lexical screen [label=%s tenant=%s cid=%s]",
                lex_label, context.tenant_id, correlation_id,
            )
            return PromptDecision.block(
                reason=REASON_LEXICAL_BLOCK,
                categories=[],
                explanation=self._mapper.map(REASON_LEXICAL_BLOCK, []),
                risk_score=1.0,
                signals=signals,
                correlation_id=correlation_id,
                blocked_by=LAYER_LEXICAL,
            )

        # ── Layer 2.5: Encoded-payload extraction ─────────────────────────
        # See services/api/security/service.py for full rationale —
        # mirrored here because the package layout has two parallel
        # PromptSecurityService implementations (security/ and
        # prompt_security/) that must stay in lockstep.
        try:
            from models.obfuscation_screen import extract_decoded_payloads
            decoded_payloads = extract_decoded_payloads(normalized)
        except Exception as exc:
            log.warning("decoded-payload extraction failed (%s) — continuing", exc)
            decoded_payloads = []
        if decoded_payloads:
            signals["decoded_payloads_count"] = len(decoded_payloads)

        # ── Layer 3: Llama Guard classification ───────────────────────────
        guard_verdict, guard_score, guard_categories = await self._guard.evaluate(normalized)
        signals["guard_verdict"]    = guard_verdict
        signals["guard_score"]      = guard_score
        signals["guard_categories"] = guard_categories

        # Re-screen each decoded payload via Llama Guard. If guard flags
        # any decoded payload as unsafe, escalate the prompt's verdict to
        # block — this catches the encoding-bypass class where the raw
        # prompt looks innocuous but contains an encoded malicious payload.
        for decoded in decoded_payloads:
            try:
                d_verdict, d_score, d_cats = await self._guard.evaluate(decoded)
            except Exception as exc:
                log.warning("decoded-payload re-screen failed (%s) — failing closed",
                            exc)
                d_verdict, d_score, d_cats = "block", 1.0, ["unavailable"]
            if d_verdict == "block":
                # Distinguish "guard said this content is unsafe" from
                # "guard itself is down/timed out".  Both produce a
                # block verdict here, but the reason MUST differ — a
                # guard-outage block is REASON_GUARD_UNAVAILABLE so
                # operators see the right error and fail-closed
                # telemetry routes through the right alerting channel.
                # Same check as the main-guard branch below; without
                # this mirror, a timeout on the re-screen path silently
                # surfaces as ``llama_guard_unsafe_category``.
                d_unavailable = bool(set(d_cats) & {"timeout", "unavailable"})
                d_reason = REASON_GUARD_UNAVAILABLE if d_unavailable else REASON_GUARD_UNSAFE
                log.info(
                    "prompt blocked: decoded payload re-screen verdict=block "
                    "[reason=%s cats=%s score=%.3f tenant=%s cid=%s]",
                    d_reason, d_cats, d_score, context.tenant_id, correlation_id,
                )
                signals["decoded_block_categories"] = d_cats
                return PromptDecision.block(
                    reason=d_reason,
                    categories=d_cats,
                    explanation=self._mapper.map(d_reason, d_cats),
                    risk_score=max(guard_score, d_score, 0.7),
                    signals=signals,
                    correlation_id=correlation_id,
                    blocked_by=LAYER_GUARD,
                )
        # Mark "obfuscation" on guard_categories so OPA can see encoding
        # was present even though guard cleared the decoded content.
        if decoded_payloads and "obfuscation" not in guard_categories:
            guard_categories = list(guard_categories) + ["obfuscation"]
            signals["guard_categories"] = guard_categories

        # Write back onto context for downstream OPA / audit use
        context.guard_score      = guard_score
        context.guard_categories = guard_categories

        if guard_verdict == "block":
            is_unavailable = bool(set(guard_categories) & {"timeout", "unavailable"})
            reason = REASON_GUARD_UNAVAILABLE if is_unavailable else REASON_GUARD_UNSAFE
            log.warning(
                "prompt blocked by guard [reason=%s cats=%s score=%.3f tenant=%s cid=%s]",
                reason, guard_categories, guard_score, context.tenant_id, correlation_id,
            )
            return PromptDecision.block(
                reason=reason,
                categories=guard_categories,
                explanation=self._mapper.map(reason, guard_categories),
                risk_score=guard_score,
                signals=signals,
                correlation_id=correlation_id,
                blocked_by=LAYER_GUARD,
            )

        # ── Layer 4: OPA policy evaluation ───────────────────────────────
        try:
            opa_blocked, opa_reason, opa_rule = await self._policy.evaluate(
                guard_score, guard_categories, context
            )
        except Exception as exc:
            log.warning("OPA evaluation raised unexpectedly — failing CLOSED: %s", exc)
            opa_blocked, opa_reason, opa_rule = True, REASON_POLICY_UNAVAILABLE, ""
        signals["opa_reason"] = opa_reason

        if opa_blocked:
            log.warning(
                "prompt blocked by OPA [reason=%s rule=%s tenant=%s cid=%s]",
                opa_reason, opa_rule, context.tenant_id, correlation_id,
            )
            return PromptDecision.block(
                reason=opa_reason,
                categories=guard_categories,
                explanation=self._mapper.map(opa_reason, guard_categories),
                risk_score=max(guard_score, 0.5),
                signals=signals,
                correlation_id=correlation_id,
                blocked_by=LAYER_POLICY,
                matched_rule=opa_rule,
            )

        # ── All layers passed → allow ─────────────────────────────────────
        log.debug(
            "prompt allowed [score=%.3f tenant=%s cid=%s]",
            guard_score, context.tenant_id, correlation_id,
        )
        return PromptDecision.allow(
            risk_score=guard_score,
            signals=signals,
            correlation_id=correlation_id,
        )
