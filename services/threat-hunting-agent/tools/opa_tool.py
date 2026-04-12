"""
tools/opa_tool.py
──────────────────
LangChain-compatible tool for evaluating scenarios against OPA policies.

The agent can call this to check whether a user action would be blocked
under the current policy set, or to explain why a past decision was made.

An OPA HTTP client is injected at startup via set_opa_client().
In tests the client is replaced with a fake.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_opa_client: Optional[Any] = None


def set_opa_client(client: Any) -> None:
    """Inject an OPA HTTP client (called once at service startup)."""
    global _opa_client
    _opa_client = client


def _get_opa() -> Any:
    if _opa_client is None:
        raise RuntimeError("OPA client not initialised — call set_opa_client() first")
    return _opa_client


# ---------------------------------------------------------------------------
# Tool: evaluate_opa_policy
# ---------------------------------------------------------------------------

def evaluate_opa_policy(
    policy_path: str,
    input_data: Dict[str, Any],
) -> str:
    """
    Evaluate an OPA Rego policy and return the result.

    Use this to understand why a session was blocked or escalated,
    or to check whether a hypothetical scenario would be permitted.

    Args:
        policy_path: OPA policy path, e.g. '/v1/data/spm/authz/decision'
                     or '/v1/data/spm/posture/risk_level'.
        input_data: Dict of input facts passed to the policy.

    Returns:
        JSON with the policy evaluation result, or an error message.
    """
    try:
        client = _get_opa()
        result = client.eval(policy_path, input_data)
        return json.dumps({"policy_path": policy_path, "result": result})
    except Exception as exc:
        logger.exception("evaluate_opa_policy failed: %s", exc)
        return json.dumps({"error": str(exc)})
