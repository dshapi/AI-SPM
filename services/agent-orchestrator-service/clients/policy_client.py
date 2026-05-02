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
from policies.evaluator import EvalContext, evaluate_policy, merge_results
from policies.runtime import get_applicable_enforced_policies
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
    # ── Named-policy + score attribution ─────────────────────────────────────
    # These fields mirror the /internal/probe contract on the api side so the
    # Runtime page (Event Stream + Control panel) can attribute every chat
    # decision to the named policy that fired and surface the real score
    # operators can act on, instead of falling back to "Unresolved Policy" /
    # "v1.4.2 — Allowed".
    #
    # policy_name uses the OPA-style ``ai.<domain>.<rule>`` namespace so the
    # ui's policyResolution.js renders it as "Ai Domain Rule" out of the box.
    # guard_score is the numeric risk score the rule based its decision on
    # (typically risk.score), so the Control panel can show "score 0.85" not
    # "score 0.07" on a blocked session.
    policy_name: str = ""
    guard_score: float = 0.0

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
                policy_name="ai.identity.suspension",
                guard_score=1.0,
            )

        # Rule 2 — Critical risk score → hard block
        if risk.score >= _BLOCK_SCORE_THRESHOLD or risk.tier == RiskTier.CRITICAL:
            result = PolicyResult(
                decision=PolicyDecision.BLOCK,
                reason=(
                    f"Risk score {risk.score:.2f} exceeds block threshold "
                    f"({_BLOCK_SCORE_THRESHOLD}). Signals: {'; '.join(risk.signals[:3])}."
                ),
                policy_name="ai.risk.critical_block",
                guard_score=float(risk.score),
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
                policy_name="ai.risk.escalation",
                guard_score=float(risk.score),
            )
            result.should_create_case = _check_case_threshold(identity.user_id)
            return result

        # Rule 4 — Enforce active Policy Library rules (tool-scope, write-approval)
        policy_result = self._run_policy_library(identity, risk, agent_id, tools)
        if policy_result is not None:
            # _run_policy_library may not have set policy_name/guard_score on
            # older library entries — fall back to a sensible default so the
            # Runtime page never shows "Unresolved Policy" for a real library hit.
            if not policy_result.policy_name:
                policy_result.policy_name = "ai.policy.library"
            if not policy_result.guard_score:
                policy_result.guard_score = float(risk.score)
            return policy_result

        # Rule 5 — Default allow
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason=f"Risk score {risk.score:.2f} within acceptable range. Session approved.",
            policy_name="ai.risk.default_allow",
            guard_score=float(risk.score),
        )

    def _run_policy_library(
        self,
        identity: IdentityContext,
        risk: RiskResult,
        agent_id: str,
        tools: list[str],
    ) -> Optional[PolicyResult]:
        """
        Load all active enforced policies that apply to agent_id, evaluate the
        ones we can resolve at session-creation time, and return the most
        restrictive result — or None if everything passes.
        """
        applicable = get_applicable_enforced_policies(agent_id)
        if not applicable:
            logger.debug("No applicable enforced policies for agent_id=%s", agent_id)
            return None

        scopes  = list(getattr(identity, "permissions", None) or [])
        signals = list(risk.signals or [])

        results = []
        for ver, meta in applicable:
            ctx = EvalContext(
                agent_id=agent_id,
                tools=tools,
                posture=risk.score,
                signals=signals,
                scopes=scopes,
                policy=meta,
                version=ver,
            )
            eval_result = evaluate_policy(ctx)
            if eval_result is not None:
                results.append(eval_result)

        worst = merge_results(results)
        if worst is None or worst.decision == PolicyDecision.ALLOW:
            return None

        should_case = _check_case_threshold(identity.user_id)
        return PolicyResult(
            decision=worst.decision,
            reason=f"[Policy: {worst.policy_name}] {worst.reason}",
            should_create_case=should_case,
        )
