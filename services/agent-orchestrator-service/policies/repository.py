"""
policies/repository.py
───────────────────────
VersionRepository: all database operations for PolicyVersionORM and
PolicyLifecycleAuditORM.

Design rules
────────────
• Takes a SQLAlchemy Session as constructor argument — caller manages
  the session lifecycle (open/commit/close). This makes unit testing
  straightforward (inject a test session, no global state).
• All public methods commit() before returning. If you need multi-step
  transactions, call the methods then commit once at the end — pass
  commit=False to suppress the auto-commit.
• is_runtime_active invariant: at most ONE row per policy_id may be 1.
  set_runtime_active() enforces this by zeroing all other rows first.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from policies.db_models import PolicyLifecycleAuditORM, PolicyVersionORM
from policies.lifecycle import (
    PolicyState,
    TransitionError,
    can_be_runtime_active,
    validate_transition,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex


class VersionRepository:
    """DB operations for PolicyVersionORM + PolicyLifecycleAuditORM."""

    def __init__(self, session: Session) -> None:
        self._s = session

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _next_version_number(self, policy_id: str) -> int:
        existing = (
            self._s.query(PolicyVersionORM.version_number)
            .filter_by(policy_id=policy_id)
            .all()
        )
        return max((row[0] for row in existing), default=0) + 1

    def _get_version(self, policy_id: str, version_number: int) -> PolicyVersionORM:
        row = (
            self._s.query(PolicyVersionORM)
            .filter_by(policy_id=policy_id, version_number=version_number)
            .first()
        )
        if row is None:
            raise ValueError(
                f"PolicyVersion not found: policy_id={repr(policy_id)} version={version_number}"
            )
        return row

    def _write_audit(
        self,
        policy_id: str,
        version_number: int,
        action: str,
        to_state: str,
        actor: str,
        reason: str = "",
        from_state: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        self._s.add(PolicyLifecycleAuditORM(
            id=_uid(),
            policy_id=policy_id,
            version_number=version_number,
            action=action,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            reason=reason,
            timestamp=_now(),
            extra=extra or {},
        ))

    # ── Public API ────────────────────────────────────────────────────────────

    def create_version(
        self,
        policy_id: str,
        *,
        logic_code: str = "",
        logic_language: str = "rego",
        actor: str = "system",
        change_summary: str = "",
        restored_from_version: Optional[int] = None,
        commit: bool = True,
    ) -> PolicyVersionORM:
        """Create a new version in DRAFT state."""
        num = self._next_version_number(policy_id)
        row = PolicyVersionORM(
            id=_uid(),
            policy_id=policy_id,
            version_number=num,
            version_str=f"v{num}",
            state=PolicyState.DRAFT.value,
            is_runtime_active=0,
            created_by=actor,
            created_at=_now(),
            change_summary=change_summary,
            restored_from_version=restored_from_version,
            logic_code=logic_code,
            logic_language=logic_language,
        )
        self._s.add(row)
        self._write_audit(
            policy_id=policy_id,
            version_number=num,
            action="create_draft",
            to_state=PolicyState.DRAFT.value,
            actor=actor,
            reason=change_summary,
        )
        if commit:
            self._s.commit()
            self._s.refresh(row)
        return row

    def get_current_version(self, policy_id: str) -> Optional[PolicyVersionORM]:
        """Return the version with the highest version_number (not necessarily active)."""
        return (
            self._s.query(PolicyVersionORM)
            .filter_by(policy_id=policy_id)
            .order_by(PolicyVersionORM.version_number.desc())
            .first()
        )

    def get_current_versions_bulk(self, policy_ids: list[str]) -> dict[str, PolicyVersionORM]:
        """Fetch the highest-version row for every policy_id in ``policy_ids``
        with a SINGLE query instead of N round-trips.

        Used by the GET /api/v1/policies list endpoint to avoid the
        N+1 pattern that made the Policies page take ~5s to load:
        before this, ``_enrich()`` was called once per policy and each
        call opened a new session + ran an indexed lookup. With the
        chart's CNPG cluster sitting on a per-roundtrip latency of
        ~300-500 ms, 11 policies = ~5 seconds of pure DB wait time.

        Implementation: window function ROW_NUMBER OVER (PARTITION BY
        policy_id ORDER BY version_number DESC) selects the row per
        policy_id with the highest version_number — equivalent to running
        get_current_version once per id, but in one query plan.

        Returns a dict keyed by policy_id; policies with no version row
        (newly-created with no draft yet) are simply absent — caller
        handles that the same way ``get_current_version`` returning None
        is handled.
        """
        if not policy_ids:
            return {}
        from sqlalchemy import func, and_

        # Subquery: for each policy_id, the max version_number we have.
        max_versions = (
            self._s.query(
                PolicyVersionORM.policy_id.label("pid"),
                func.max(PolicyVersionORM.version_number).label("vmax"),
            )
            .filter(PolicyVersionORM.policy_id.in_(policy_ids))
            .group_by(PolicyVersionORM.policy_id)
            .subquery()
        )

        # Join back to PolicyVersionORM to get the full row at that version.
        rows = (
            self._s.query(PolicyVersionORM)
            .join(
                max_versions,
                and_(
                    PolicyVersionORM.policy_id      == max_versions.c.pid,
                    PolicyVersionORM.version_number == max_versions.c.vmax,
                ),
            )
            .all()
        )
        return {r.policy_id: r for r in rows}

    def get_runtime_policy(self, policy_id: str) -> Optional[PolicyVersionORM]:
        """Return the is_runtime_active=1 version, or None."""
        return (
            self._s.query(PolicyVersionORM)
            .filter_by(policy_id=policy_id, is_runtime_active=1)
            .first()
        )

    def list_versions(self, policy_id: str) -> list[PolicyVersionORM]:
        """Return all versions ordered oldest-first."""
        return (
            self._s.query(PolicyVersionORM)
            .filter_by(policy_id=policy_id)
            .order_by(PolicyVersionORM.version_number)
            .all()
        )

    def promote_version(
        self,
        policy_id: str,
        version_number: int,
        target_state: PolicyState,
        *,
        actor: str,
        reason: str = "",
        commit: bool = True,
    ) -> PolicyVersionORM:
        """Transition a version to target_state. Validates transition rules."""
        row = self._get_version(policy_id, version_number)
        current_state = PolicyState(row.state)
        validate_transition(current_state, target_state)
        from_state = row.state
        row.state = target_state.value
        self._write_audit(
            policy_id=policy_id,
            version_number=version_number,
            action="promote",
            from_state=from_state,
            to_state=target_state.value,
            actor=actor,
            reason=reason,
        )
        if commit:
            self._s.commit()
            self._s.refresh(row)
        return row

    def _clear_runtime_active(
        self,
        policy_id: str,
        *,
        actor: str = "system",
        commit: bool = True,
    ) -> int:
        """Zero ``is_runtime_active`` on every version of ``policy_id``.

        Used by ``opa_sync.activate_with_opa_sync`` to roll back when the
        ConfigMap patch fails AND there was no previous active version
        to restore (the activation we just performed was the very first
        for this policy).  Returns the count of rows updated.

        Writes an audit record so the rollback is traceable separately
        from the failed forward transition.
        """
        n = (
            self._s.query(PolicyVersionORM)
            .filter_by(policy_id=policy_id, is_runtime_active=1)
            .update({"is_runtime_active": 0})
        )
        if n > 0:
            self._write_audit(
                policy_id=policy_id,
                version_number=0,           # no specific target — clearing all
                action="clear_active",
                to_state="(cleared)",
                actor=actor,
                reason="rollback after OPA ConfigMap patch failure",
            )
        if commit:
            self._s.commit()
        return n


    def set_runtime_active(
        self,
        policy_id: str,
        version_number: int,
        *,
        actor: str = "system",
        commit: bool = True,
    ) -> PolicyVersionORM:
        """Mark exactly one version as is_runtime_active=1, clearing all others."""
        row = self._get_version(policy_id, version_number)
        if not can_be_runtime_active(PolicyState(row.state)):
            raise ValueError(
                f"Version {version_number} of policy {repr(policy_id)} "
                f"(state={repr(row.state)}) cannot be runtime-active. "
                "Only monitor or enforced versions may be activated."
            )
        # Clear all existing active flags for this policy
        (
            self._s.query(PolicyVersionORM)
            .filter_by(policy_id=policy_id, is_runtime_active=1)
            .update({"is_runtime_active": 0})
        )
        row.is_runtime_active = 1
        self._write_audit(
            policy_id=policy_id,
            version_number=version_number,
            action="set_active",
            to_state=row.state,
            actor=actor,
        )
        if commit:
            self._s.commit()
            self._s.refresh(row)
        return row

    def restore_version(
        self,
        policy_id: str,
        *,
        from_version_number: int,
        actor: str,
        reason: str = "",
        commit: bool = True,
    ) -> PolicyVersionORM:
        """Clone a prior version into a new DRAFT version. Never mutates history."""
        source = self._get_version(policy_id, from_version_number)
        num = self._next_version_number(policy_id)
        row = PolicyVersionORM(
            id=_uid(),
            policy_id=policy_id,
            version_number=num,
            version_str=f"v{num}",
            state=PolicyState.DRAFT.value,
            is_runtime_active=0,
            created_by=actor,
            created_at=_now(),
            change_summary=f"Restored from v{from_version_number}. Reason: {reason}",
            restored_from_version=from_version_number,
            logic_code=source.logic_code,
            logic_language=source.logic_language,
        )
        self._s.add(row)
        self._write_audit(
            policy_id=policy_id,
            version_number=num,
            action="restore",
            to_state=PolicyState.DRAFT.value,
            actor=actor,
            reason=reason,
            extra={"restored_from_version": from_version_number},
        )
        if commit:
            self._s.commit()
            self._s.refresh(row)
        return row

    def list_audit(self, policy_id: str) -> list[dict]:
        """Return all audit records for a policy, newest first."""
        rows = (
            self._s.query(PolicyLifecycleAuditORM)
            .filter_by(policy_id=policy_id)
            .order_by(PolicyLifecycleAuditORM.timestamp.desc())
            .all()
        )
        return [
            {
                "policy_id":      r.policy_id,
                "version_number": r.version_number,
                "action":         r.action,
                "from_state":     r.from_state,
                "to_state":       r.to_state,
                "actor":          r.actor,
                "reason":         r.reason,
                "timestamp":      r.timestamp.isoformat(),
                "extra":          r.extra,
            }
            for r in rows
        ]
