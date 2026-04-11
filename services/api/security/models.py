"""
security.models
───────────────
Data classes for prompt security evaluation.

PromptDecision  — result returned by PromptSecurityService.evaluate()
ScreeningContext — caller-supplied request context passed into evaluate()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

DecisionType = Literal["allow", "block", "escalate"]

# Reason codes — matches the "reason" field in BlockedResponse
REASON_LEXICAL_BLOCK        = "lexical_block"
REASON_GUARD_UNSAFE         = "llama_guard_unsafe_category"
REASON_GUARD_UNAVAILABLE    = "guard_unavailable"
REASON_POLICY_BLOCK         = "policy_block"
REASON_POLICY_UNAVAILABLE   = "policy_unavailable"
REASON_ALLOW                = "allow"

# Which layer produced the decision
LAYER_LEXICAL  = "lexical"
LAYER_GUARD    = "guard"
LAYER_POLICY   = "opa"
LAYER_NONE     = ""


@dataclass
class PromptDecision:
    """
    The outcome of a full prompt security evaluation.

    Fields
    ------
    decision        : "allow" | "block" | "escalate"
    categories      : Llama Guard S-codes that triggered a block, e.g. ["S9"]
    explanation     : User-facing plain-English explanation (never raw model text)
    signals         : Internal diagnostic dict (guard score, labels, etc.)
    risk_score      : Normalised 0.0–1.0 risk confidence
    reason          : Machine-readable block reason (REASON_* constants above)
    correlation_id  : UUID for cross-log correlation
    blocked_by      : Which layer produced the block ("lexical" | "guard" | "opa" | "")
    """
    decision:       DecisionType
    categories:     List[str]
    explanation:    str
    signals:        Dict[str, Any]
    risk_score:     float
    reason:         str = REASON_ALLOW
    correlation_id: str = ""
    blocked_by:     str = LAYER_NONE

    # ── Convenience helpers ───────────────────────────────────────────────────

    @property
    def is_blocked(self) -> bool:
        """True for both 'block' and 'escalate' decisions."""
        return self.decision in ("block", "escalate")

    def to_block_detail(self, session_id: Optional[str] = None) -> dict:
        """
        Serialise to the dict shape expected by BlockedResponse / HTTPException detail.
        Only call this when decision is 'block' or 'escalate'.
        """
        from models.block_response import BlockedResponse  # noqa: PLC0415
        return BlockedResponse(
            error="blocked_by_policy",
            reason=self.reason,
            categories=self.categories,
            explanation=self.explanation,
            session_id=session_id,
            correlation_id=self.correlation_id,
        ).model_dump()

    # ── Factory helpers ───────────────────────────────────────────────────────

    @classmethod
    def allow(
        cls,
        *,
        risk_score: float = 0.0,
        signals: Optional[Dict[str, Any]] = None,
        correlation_id: str = "",
    ) -> "PromptDecision":
        return cls(
            decision="allow",
            categories=[],
            explanation="",
            signals=signals or {},
            risk_score=risk_score,
            reason=REASON_ALLOW,
            correlation_id=correlation_id,
            blocked_by=LAYER_NONE,
        )

    @classmethod
    def block(
        cls,
        *,
        reason: str,
        categories: Optional[List[str]] = None,
        explanation: str = "",
        risk_score: float = 1.0,
        signals: Optional[Dict[str, Any]] = None,
        correlation_id: str = "",
        blocked_by: str = LAYER_NONE,
    ) -> "PromptDecision":
        return cls(
            decision="block",
            categories=categories or [],
            explanation=explanation,
            signals=signals or {},
            risk_score=risk_score,
            reason=reason,
            correlation_id=correlation_id,
            blocked_by=blocked_by,
        )


@dataclass
class ScreeningContext:
    """
    Caller-supplied context for PromptSecurityService.evaluate().

    Must be constructed fresh per request — never reuse across requests.
    """
    tenant_id:        str = "default"
    user_id:          str = "unknown"
    session_id:       Optional[str] = None
    roles:            List[str] = field(default_factory=list)
    scopes:           List[str] = field(default_factory=list)
    # Populated by the service during evaluation (output fields)
    guard_score:      float = 0.0
    guard_categories: List[str] = field(default_factory=list)
    # Caller-supplied arbitrary extras forwarded to OPA
    extra:            Dict[str, Any] = field(default_factory=dict)
