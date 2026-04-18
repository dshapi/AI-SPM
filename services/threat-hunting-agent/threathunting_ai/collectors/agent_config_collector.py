"""
threathunting_ai/collectors/agent_config_collector.py
──────────────────────────────────────────────────────
Query the model registry for dangerous or misconfigured AI agents.

Detects:
  - Models with risk_tier='unacceptable' still in active status
  - High-risk models missing mandatory approved_by
  - Models never approved (no approved_at) at non-minimal risk tier

Read-only. Uses existing Postgres query helper. Deterministic.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_APPROVAL_REQUIRED_TIERS = {"high", "unacceptable"}
_FORBIDDEN_ACTIVE_TIERS  = {"unacceptable"}
_ACTIVE_STATUSES         = {"approved", "registered"}


def collect() -> List[Dict[str, Any]]:
    """
    Query model registry and return a list of unsafe_config items.
    Returns [] if Postgres is unavailable (non-fatal).
    """
    try:
        import tools.postgres_tool as pt
        if pt._connection_factory is None:
            logger.debug("agent_config_collector: Postgres not initialised — skipping")
            return []
    except Exception:
        return []

    from config import TENANT_ID
    results: List[Dict[str, Any]] = []

    try:
        raw    = pt.query_model_registry(tenant_id=TENANT_ID, limit=200)
        models = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(models, dict) and "error" in models:
            logger.warning("agent_config_collector: registry query error: %s", models["error"])
            return []
    except Exception as exc:
        logger.warning("agent_config_collector: query failed: %s", exc)
        return []

    for model in models:
        model_id    = str(model.get("model_id", ""))
        name        = model.get("name", "unknown")
        risk_tier   = (model.get("risk_tier") or "").lower()
        status      = (model.get("status") or "").lower()
        approved_by = model.get("approved_by")
        approved_at = model.get("approved_at")

        if risk_tier in _FORBIDDEN_ACTIVE_TIERS and status in _ACTIVE_STATUSES:
            results.append({
                "type":       "unsafe_config",
                "model_id":   model_id,
                "model_name": name,
                "risk_tier":  risk_tier,
                "status":     status,
                "issue": (
                    f"Model '{name}' has risk_tier='{risk_tier}' but is still "
                    f"in status='{status}'. Unacceptable-risk models must be retired."
                ),
            })
        elif risk_tier in _APPROVAL_REQUIRED_TIERS and not approved_by:
            results.append({
                "type":       "unsafe_config",
                "model_id":   model_id,
                "model_name": name,
                "risk_tier":  risk_tier,
                "status":     status,
                "issue": (
                    f"Model '{name}' has risk_tier='{risk_tier}' but "
                    f"approved_by is empty — mandatory approval is missing."
                ),
            })
        elif status == "registered" and approved_at is None and risk_tier not in ("minimal", "limited"):
            results.append({
                "type":       "unsafe_config",
                "model_id":   model_id,
                "model_name": name,
                "risk_tier":  risk_tier,
                "status":     status,
                "issue": (
                    f"Model '{name}' (risk_tier='{risk_tier}') is in 'registered' "
                    f"status with no approval record — review required."
                ),
            })

    return results
