"""
policies/migration_util.py
───────────────────────────
Idempotent backfill: for every existing PolicyORM row that has NO
corresponding PolicyVersionORM rows, create one version row that
reflects the policy's current state.

Called from seed.py after seed_policies() so it runs once on first
boot and is a no-op on subsequent boots.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from policies.db_models import PolicyORM, PolicyVersionORM
from policies.lifecycle import derive_is_runtime_active, map_mode_to_state

logger = logging.getLogger(__name__)


def backfill_policy_versions(session: Session) -> int:
    """
    Create a PolicyVersionORM row for every PolicyORM that has none.
    Returns the number of policies backfilled (0 if already done).
    """
    policies: list[PolicyORM] = session.query(PolicyORM).all()
    backfilled = 0

    for policy in policies:
        existing = (
            session.query(PolicyVersionORM.id)
            .filter_by(policy_id=policy.policy_id)
            .first()
        )
        if existing:
            continue  # already has version rows — skip

        state = map_mode_to_state(policy.mode)
        is_active = derive_is_runtime_active(state, legacy_status=policy.status)

        try:
            version_number = int(policy.version.lstrip("v"))
        except (ValueError, AttributeError):
            version_number = 1

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        row = PolicyVersionORM(
            id=uuid.uuid4().hex,
            policy_id=policy.policy_id,
            version_number=version_number,
            version_str=policy.version or "v1",
            state=state.value,
            is_runtime_active=1 if is_active else 0,
            created_by=policy.created_by or "migration",
            created_at=policy.created_at if policy.created_at else now,
            change_summary="Backfilled from legacy policy row",
            restored_from_version=None,
            logic_code=policy.logic_code or "",
            logic_language=policy.logic_language or "rego",
        )
        session.add(row)
        backfilled += 1
        logger.info(
            "backfill: policy_id=%s version=%s state=%s active=%s",
            policy.policy_id, row.version_str, state.value, is_active,
        )

    if backfilled:
        session.commit()
        logger.info("backfill_policy_versions: backfilled %d policies", backfilled)
    return backfilled
