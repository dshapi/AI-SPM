"""
security.adapters.policy_adapter
──────────────────────────────────
Async adapter for OPA (Open Policy Agent) prompt policy evaluation.

Fail-closed contract:
  - HTTP timeout / network error → block with reason="policy_unavailable"
  - OPA returns non-200         → block with reason="policy_unavailable"
  - OPA decision == "block"     → block with reason="policy_block"
  - All other cases             → allow

The adapter is stateless — a new httpx.AsyncClient is created per call to
support concurrent requests safely.
"""
from __future__ import annotations

import logging
from typing import Tuple

import httpx

from security.models import (
    ScreeningContext,
    REASON_POLICY_BLOCK,
    REASON_POLICY_UNAVAILABLE,
)

log = logging.getLogger("security.policy_adapter")


class OPAAdapter:
    """
    Evaluates prompt data against the OPA ``spm/prompt/allow`` policy.

    Parameters
    ----------
    opa_url : str
        Base URL of the OPA service, e.g. "http://opa:8181".
    timeout : float
        HTTP timeout in seconds (default 2.0).
    """

    def __init__(self, opa_url: str, *, timeout: float = 2.0, enabled: bool = True) -> None:
        self._url     = opa_url
        self._timeout = timeout
        self._enabled = enabled

    async def evaluate(
        self,
        guard_score: float,
        guard_categories: list,
        context: ScreeningContext,
    ) -> Tuple[bool, str, str]:
        """
        Query OPA and return (blocked, reason, opa_rule).

        Parameters
        ----------
        guard_score      : Risk score from the guard model (0.0–1.0).
        guard_categories : Category codes from the guard model, e.g. [].
        context          : ScreeningContext with tenant/user/role data.

        Returns
        -------
        (blocked: bool, reason: str, opa_rule: str)
            reason    — one of REASON_POLICY_BLOCK or REASON_POLICY_UNAVAILABLE.
            opa_rule  — the human-readable rule description from OPA (e.g.
                        "posture score exceeds block threshold"), or "" if N/A.
        """
        if not self._enabled:
            return False, "", ""

        payload = {
            "posture_score":      min(guard_score, 1.0),
            "signals":            guard_categories,
            "behavioral_signals": guard_categories,
            "retrieval_trust":    1.0,
            "intent_drift":       guard_score,
            "guard_verdict":      "allow",    # guard already passed at this point
            "guard_score":        guard_score,
            "guard_categories":   guard_categories,
            "auth_context": {
                "sub":       context.user_id,
                "tenant_id": context.tenant_id,
                "roles":     context.roles,
                "scopes":    context.scopes,
                "claims":    context.extra,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/v1/data/spm/prompt/allow",
                    json={"input": payload},
                )
                if resp.status_code != 200:
                    raise Exception(f"OPA returned HTTP {resp.status_code}")

                result = resp.json().get("result", {})
                if isinstance(result, dict) and result.get("decision") == "block":
                    # Extract the human-readable rule description OPA provides
                    opa_rule = result.get("reason", "")
                    return True, REASON_POLICY_BLOCK, opa_rule

                return False, "", ""

        except Exception as exc:
            log.warning("OPA prompt policy unavailable: %s — failing CLOSED", exc)
            return True, REASON_POLICY_UNAVAILABLE, ""
