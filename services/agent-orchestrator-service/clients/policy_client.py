"""
clients/policy_client.py
─────────────────────────
PolicyClient: evaluates whether a session should be allowed, blocked,
or escalated given an IdentityContext and a RiskResult.

Architecture note
─────────────────
In production this client calls the OPA (Open Policy Agent) HTTP API:

    POST http://opa:8181/v1/data/cpm/session/decision
    body: {"input": { ... }}

For local development the same logic is replicated as a pure-Python
function so the service starts with zero external dependencies.

The client is injected via FastAPI DI and is designed to be replaced
with an httpx-based real client without touching any service code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from dependencies.auth import IdentityContext
from schemas.session import PolicyDecision
from services.risk_engine import RiskResult, RiskTier

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Policy configuration
# These would be loaded from OPA / environment in production.
# ─────────────────────────────────────────────────────────────────────────────

POLICY_VERSION = "v1.4.2"

# Hard-block thresholds
_BLOCK_SCORE_THRESHOLD       = 0.75   # CRITICAL tier → always block
_ESCALATE_SCORE_THRESHOLD    = 0.50   # HIGH tier → always escalate


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PolicyResult:
    decision: PolicyDecision
    reason: str
    policy_version: str = POLICY_VERSION

    @property
    def is_allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

class PolicyClient:
    """
    Evaluates session-creation policy.

    Evaluation order (first match wins):
      1. Suspended identities → BLOCK
      2. CRITICAL risk score  → BLOCK
      3. HIGH risk            → ESCALATE (no role exemptions)
      4. Everything else      → ALLOW
    """

    async def evaluate(
        self,
        identity: IdentityContext,
        risk: RiskResult,
        agent_id: str,
        tools: list[str],
    ) -> PolicyResult:
        """
        Returns a PolicyResult.  This method is async so it can be
        swapped for an awaited httpx call without changing call-sites.
        """
        logger.debug(
            "PolicyClient.evaluate: user=%s score=%.4f tier=%s agent=%s",
            identity.user_id, risk.score, risk.tier.value, agent_id,
        )

        # Rule 1 — Suspended identity
        if identity.is_suspended():
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason="Identity is suspended; session creation denied.",
            )

        # Rule 2 — Critical risk score → hard block
        if risk.score >= _BLOCK_SCORE_THRESHOLD or risk.tier == RiskTier.CRITICAL:
            return PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason=(
                    f"Risk score {risk.score:.2f} exceeds block threshold "
                    f"({_BLOCK_SCORE_THRESHOLD}). Signals: {'; '.join(risk.signals[:3])}."
                ),
            )

        # Rule 3 — High risk → always escalate, no role exemptions
        if risk.score >= _ESCALATE_SCORE_THRESHOLD or risk.tier == RiskTier.HIGH:
            return PolicyResult(
                decision=PolicyDecision.ESCALATE,
                reason=(
                    f"Risk score {risk.score:.2f} exceeds escalation threshold "
                    f"({_ESCALATE_SCORE_THRESHOLD}). Manual approval required."
                ),
            )

        # Rule 4 — Default allow
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason=f"Risk score {risk.score:.2f} within acceptable range. Session approved.",
        )
