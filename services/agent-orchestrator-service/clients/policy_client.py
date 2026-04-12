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

# Case-creation policy: open one case per N blocked/escalated sessions per user.
# Prevents flooding the Cases tab with one case per message.
CASE_CREATION_THRESHOLD = 3

# Per-user block counters (in-memory; resets on service restart)
_block_counters: dict[str, int] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PolicyResult:
    decision: PolicyDecision
    reason: str
    policy_version: str = POLICY_VERSION
    should_create_case: bool = False  # Set by case-creation rule in evaluate()

    @property
    def is_allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

def _check_case_threshold(user_id: str) -> bool:
    """
    Increment the per-user block counter and return True every
    CASE_CREATION_THRESHOLD blocks — i.e. open one case per N blocked sessions.
    """
    _block_counters[user_id] = _block_counters.get(user_id, 0) + 1
    count = _block_counters[user_id]
    logger.debug("Case threshold check: user=%s count=%d threshold=%d", user_id, count, CASE_CREATION_THRESHOLD)
    return count % CASE_CREATION_THRESHOLD == 0


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
                should_create_case=True,
            )

        # Rule 2 — Critical risk score → hard block
        if risk.score >= _BLOCK_SCORE_THRESHOLD or risk.tier == RiskTier.CRITICAL:
            result = PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason=(
                    f"Risk score {risk.score:.2f} exceeds block threshold "
                    f"({_BLOCK_SCORE_THRESHOLD}). Signals: {'; '.join(risk.signals[:3])}."
                ),
            )
            result.should_create_case = _check_case_threshold(identity.user_id)
            return result

        # Rule 3 — High risk → always escalate, no role exemptions
        if risk.score >= _ESCALATE_SCORE_THRESHOLD or risk.tier == RiskTier.HIGH:
            result = PolicyResult(
                decision=PolicyDecision.ESCALATE,
                reason=(
                    f"Risk score {risk.score:.2f} exceeds escalation threshold "
                    f"({_ESCALATE_SCORE_THRESHOLD}). Manual approval required."
                ),
            )
            result.should_create_case = _check_case_threshold(identity.user_id)
            return result

        # Rule 4 — Default allow
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason=f"Risk score {risk.score:.2f} within acceptable range. Session approved.",
        )
