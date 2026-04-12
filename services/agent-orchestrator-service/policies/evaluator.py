"""
policies/evaluator.py
──────────────────────
Python evaluation of policies that can be enforced at session-creation time.

Only two policy types have enough context at this stage:
  • tool-scope     — we know which tools the session will use
  • write-approval — we know if any write-category tools are requested

Policies that require a prompt (prompt-guard, jailbreak-detect) or an LLM
output (pii-mask, output-filter) are evaluated at message-time and are
intentionally skipped here.

Design
──────
Each evaluator receives an EvalContext and returns an EvalResult.
The dispatcher (_EVALUATORS map) routes by PolicyORM.type.
Unknown types return a PASS (allow) result so new policy types
never accidentally block production traffic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from policies.db_models import PolicyORM, PolicyVersionORM
from schemas.session import PolicyDecision

logger = logging.getLogger(__name__)

# ── Context passed to every evaluator ────────────────────────────────────────

@dataclass
class EvalContext:
    agent_id:    str
    tools:       list[str]
    posture:     float          # risk.score — 0.0 … 1.0
    signals:     list[str]      # risk.signals, e.g. ["exfiltration", "anomaly"]
    scopes:      list[str]      # identity.scopes / permissions
    policy:      PolicyORM
    version:     PolicyVersionORM


# ── Result returned by each evaluator ────────────────────────────────────────

@dataclass
class EvalResult:
    decision:       PolicyDecision          # ALLOW | BLOCK | ESCALATE
    reason:         str
    policy_id:      str
    policy_name:    str
    monitor_only:   bool = False            # True → log but never block


PASS = PolicyDecision.ALLOW

# ── Write-category tool patterns ──────────────────────────────────────────────

_WRITE_VERBS = {"write", "send", "create", "delete", "update", "insert",
                "post", "put", "patch", "exec", "run", "deploy"}

def _is_write_tool(tool_name: str) -> bool:
    parts = tool_name.lower().replace("-", ".").split(".")
    return any(p in _WRITE_VERBS for p in parts)


# ── Individual evaluators ─────────────────────────────────────────────────────

def _eval_tool_scope(ctx: EvalContext) -> EvalResult:
    """
    Python translation of spm.tools Rego policy.

    Rules (first match wins):
      1. Exfiltration signal present → BLOCK all non-security tools
      2. Posture ≥ 0.50 + side-effect tool → BLOCK
      3. Otherwise → ALLOW
    """
    has_exfil   = "exfiltration" in ctx.signals
    high_posture = ctx.posture >= 0.50

    for tool in ctx.tools:
        if tool == "security.review":
            continue  # always permitted

        if has_exfil:
            return EvalResult(
                decision=PolicyDecision.BLOCK,
                reason=f"tool-scope: exfiltration signal blocks tool '{tool}'",
                policy_id=ctx.policy.policy_id,
                policy_name=ctx.policy.name,
            )

        if high_posture and _is_write_tool(tool):
            return EvalResult(
                decision=PolicyDecision.BLOCK,
                reason=(
                    f"tool-scope: posture {ctx.posture:.2f} ≥ 0.50 blocks "
                    f"side-effect tool '{tool}'"
                ),
                policy_id=ctx.policy.policy_id,
                policy_name=ctx.policy.name,
            )

    return EvalResult(
        decision=PASS,
        reason="tool-scope: all requested tools permitted",
        policy_id=ctx.policy.policy_id,
        policy_name=ctx.policy.name,
    )


def _eval_write_approval(ctx: EvalContext) -> EvalResult:
    """
    Python translation of write-approval JSON policy.

    Rules:
      • posture ≥ 0.60 + any tool → BLOCK
      • posture ≥ 0.20 + write tool → ESCALATE (human approval required)
      • otherwise → ALLOW
    """
    write_tools = [t for t in ctx.tools if _is_write_tool(t)]

    if not write_tools:
        return EvalResult(
            decision=PASS,
            reason="write-approval: no write-category tools requested",
            policy_id=ctx.policy.policy_id,
            policy_name=ctx.policy.name,
        )

    if ctx.posture >= 0.60:
        return EvalResult(
            decision=PolicyDecision.BLOCK,
            reason=(
                f"write-approval: critical posture {ctx.posture:.2f} ≥ 0.60 "
                f"— all write ops suspended ({', '.join(write_tools)})"
            ),
            policy_id=ctx.policy.policy_id,
            policy_name=ctx.policy.name,
        )

    if ctx.posture >= 0.20:
        return EvalResult(
            decision=PolicyDecision.ESCALATE,
            reason=(
                f"write-approval: posture {ctx.posture:.2f} ≥ 0.20 "
                f"— write tools require human approval ({', '.join(write_tools)})"
            ),
            policy_id=ctx.policy.policy_id,
            policy_name=ctx.policy.name,
        )

    return EvalResult(
        decision=PASS,
        reason="write-approval: low posture, write tools permitted",
        policy_id=ctx.policy.policy_id,
        policy_name=ctx.policy.name,
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────

EvaluatorFn = Callable[[EvalContext], EvalResult]

_EVALUATORS: dict[str, EvaluatorFn] = {
    "tool-access":    _eval_tool_scope,
    "write-approval": _eval_write_approval,
    # prompt-safety, pii-masking, output-filter, token-budget, egress-control,
    # rag-retrieval → evaluated at message/output time, not session creation.
}


def evaluate_policy(ctx: EvalContext) -> Optional[EvalResult]:
    """
    Dispatch to the right evaluator for ctx.policy.type.
    Returns None if this policy type is not evaluated at session-creation time.
    """
    fn = _EVALUATORS.get(ctx.policy.type)
    if fn is None:
        logger.debug(
            "policy type '%s' not evaluated at session-creation time — skipped",
            ctx.policy.type,
        )
        return None
    try:
        result = fn(ctx)
        logger.info(
            "policy %s (%s) → %s: %s",
            ctx.policy.policy_id, ctx.policy.type,
            result.decision.value, result.reason,
        )
        return result
    except Exception as exc:
        logger.error(
            "evaluator error policy=%s: %s", ctx.policy.policy_id, exc, exc_info=True,
        )
        # Fail open — a broken evaluator must never block all traffic
        return EvalResult(
            decision=PASS,
            reason=f"evaluator error (fail-open): {exc}",
            policy_id=ctx.policy.policy_id,
            policy_name=ctx.policy.name,
        )


def merge_results(results: list[EvalResult]) -> Optional[EvalResult]:
    """
    Return the most restrictive result: BLOCK > ESCALATE > ALLOW.
    Returns None when the list is empty (caller uses its own default).
    """
    if not results:
        return None
    priority = {PolicyDecision.BLOCK: 2, PolicyDecision.ESCALATE: 1, PASS: 0}
    return max(results, key=lambda r: priority.get(r.decision, 0))
