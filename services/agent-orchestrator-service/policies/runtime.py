"""
policies/runtime.py
────────────────────
Runtime policy resolution — answers: "what policy version is active right now?"

Used by the session creation pipeline to determine how to treat a request:
  • ENFORCED version → inline enforcement (can block)
  • MONITOR  version → shadow evaluation (log only, never block)
  • None             → no active policy → allow by default

This module is read-only — it never writes to the DB.
"""
from __future__ import annotations

import logging
from typing import Optional

from policies.db_models import PolicyVersionORM
from policies.lifecycle import PolicyState

logger = logging.getLogger(__name__)


def get_runtime_policy(policy_id: str) -> Optional[PolicyVersionORM]:
    """
    Return the is_runtime_active version for this policy, or None.

    Callers should inspect .state to determine enforcement mode:
        PolicyState.ENFORCED → block/allow decisions apply
        PolicyState.MONITOR  → shadow evaluation only
    """
    try:
        from policies import store as _store
        sess = _store._get_or_new_session()
        try:
            return (
                sess.query(PolicyVersionORM)
                .filter_by(policy_id=policy_id, is_runtime_active=1)
                .first()
            )
        finally:
            try:
                sess.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("get_runtime_policy failed policy_id=%s: %s", policy_id, exc)
        return None


def get_all_enforced() -> list[PolicyVersionORM]:
    """Return all is_runtime_active=1 + state=enforced versions across all policies."""
    try:
        from policies import store as _store
        sess = _store._get_or_new_session()
        try:
            return (
                sess.query(PolicyVersionORM)
                .filter_by(is_runtime_active=1, state=PolicyState.ENFORCED.value)
                .all()
            )
        finally:
            try:
                sess.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("get_all_enforced failed: %s", exc)
        return []


def get_all_monitor() -> list[PolicyVersionORM]:
    """Return all is_runtime_active=1 + state=monitor versions across all policies."""
    try:
        from policies import store as _store
        sess = _store._get_or_new_session()
        try:
            return (
                sess.query(PolicyVersionORM)
                .filter_by(is_runtime_active=1, state=PolicyState.MONITOR.value)
                .all()
            )
        finally:
            try:
                sess.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("get_all_monitor failed: %s", exc)
        return []
