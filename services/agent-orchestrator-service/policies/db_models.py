"""
policies/db_models.py
─────────────────────
SQLAlchemy ORM table for the policies store.

Column design rationale
───────────────────────
• Simple scalar fields (name, version, mode …) → individual String/Integer columns
  so queries can filter/sort without JSON path expressions.
• Structured / variable-length data (history, logic tokens, scope arrays, impact
  counters, snapshots) → JSON columns.  PostgreSQL stores these as JSONB; SQLite
  serialises them as text via SQLAlchemy's JSON type.
• `snapshots` is a dict[version_str, full_policy_dict] used by restore_policy().
  Stored on the same row to avoid a separate table.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.types import JSON

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PolicyORM(Base):
    __tablename__ = "policies"

    # ── Identity ─────────────────────────────────────────────────────────────
    policy_id        = Column(String,  primary_key=True, index=True)
    name             = Column(String,  nullable=False)
    version          = Column(String,  nullable=False, default="v1")
    type             = Column(String,  nullable=False)
    mode             = Column(String,  nullable=False, default="Monitor")
    status           = Column(String,  nullable=False, default="Active")

    # ── Display / meta ────────────────────────────────────────────────────────
    scope            = Column(String,  nullable=False, default="")
    owner            = Column(String,  nullable=False, default="")
    created_by       = Column(String,  nullable=False, default="")
    created          = Column(String,  nullable=False, default="")
    updated          = Column(String,  nullable=False, default="")
    updated_full     = Column(String,  nullable=False, default="")
    description      = Column(String,  nullable=False, default="")

    # ── Stats ─────────────────────────────────────────────────────────────────
    affected_assets  = Column(Integer, nullable=False, default=0)
    related_alerts   = Column(Integer, nullable=False, default=0)
    linked_sims      = Column(Integer, nullable=False, default=0)

    # ── JSON payload columns ──────────────────────────────────────────────────
    agents           = Column(JSON, nullable=False, default=lambda: [])
    tools            = Column(JSON, nullable=False, default=lambda: [])
    data_sources     = Column(JSON, nullable=False, default=lambda: [])
    environments     = Column(JSON, nullable=False, default=lambda: [])
    exceptions       = Column(JSON, nullable=False, default=lambda: [])
    impact           = Column(JSON, nullable=False,
                              default=lambda: {"blocked": 0, "flagged": 0,
                                               "unchanged": 0, "total": 100})
    history          = Column(JSON, nullable=False, default=lambda: [])
    logic            = Column(JSON, nullable=False, default=lambda: [])

    # ── Raw logic code ────────────────────────────────────────────────────────
    logic_code       = Column(String, nullable=False, default="")
    logic_language   = Column(String, nullable=False, default="rego")

    # ── Snapshots for version restore ─────────────────────────────────────────
    snapshots        = Column(JSON, nullable=False, default=lambda: {})

    # ── Audit timestamps ──────────────────────────────────────────────────────
    created_at       = Column(DateTime(timezone=True), nullable=False,
                              default=_utcnow)
    updated_at       = Column(DateTime(timezone=True), nullable=False,
                              default=_utcnow, onupdate=_utcnow)


class PolicyVersionORM(Base):
    """
    One row per policy version — the authoritative lifecycle store.

    Design notes
    ────────────
    • PolicyORM continues to serve the current-view for UI backward compat.
    • This table is the source of truth for state, is_runtime_active, and
      audit history; PolicyORM is a denormalised read cache.
    • Exactly ONE row per policy_id may have is_runtime_active=True.
      This invariant is enforced in VersionRepository.set_runtime_active().
    • version_number is an integer (1, 2, 3 …); version_str is the display
      label ("v1", "v2" …) kept in sync automatically.
    """
    __tablename__ = "policy_versions"

    id                    = Column(String,  primary_key=True)
    policy_id             = Column(String,  nullable=False, index=True)
    version_number        = Column(Integer, nullable=False)
    version_str           = Column(String,  nullable=False)

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    state                 = Column(String,  nullable=False, default="draft")
    is_runtime_active     = Column(Integer, nullable=False, default=0)
    #   SQLite has no BOOLEAN; 0=False, 1=True.
    #   CONSTRAINT: at most one row per policy_id may have value 1.

    # ── Provenance ────────────────────────────────────────────────────────────
    created_by            = Column(String,  nullable=False, default="")
    created_at            = Column(DateTime(timezone=True), nullable=False,
                                   default=_utcnow)
    change_summary        = Column(String,  nullable=False, default="")
    restored_from_version = Column(Integer, nullable=True)

    # ── Snapshot of logic at this version ─────────────────────────────────────
    logic_code            = Column(String,  nullable=False, default="")
    logic_language        = Column(String,  nullable=False, default="rego")

    __table_args__ = (
        Index("ix_pv_policy_id",  "policy_id"),
        Index("ix_pv_state",      "state"),
        Index("ix_pv_active",     "policy_id", "is_runtime_active"),
    )


class PolicyLifecycleAuditORM(Base):
    """
    Immutable audit log for every lifecycle state transition.
    Append-only — rows are never updated or deleted.
    """
    __tablename__ = "policy_lifecycle_audit"

    id             = Column(String,  primary_key=True)
    policy_id      = Column(String,  nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    action         = Column(String,  nullable=False)
    #   create_draft | promote | deprecate | restore | set_active
    from_state     = Column(String,  nullable=True)
    to_state       = Column(String,  nullable=False)
    actor          = Column(String,  nullable=False, default="system")
    reason         = Column(String,  nullable=False, default="")
    timestamp      = Column(DateTime(timezone=True), nullable=False,
                            default=_utcnow)
    extra          = Column(JSON,    nullable=False, default=lambda: {})

    __table_args__ = (
        Index("ix_pla_policy_id", "policy_id"),
        Index("ix_pla_timestamp", "timestamp"),
    )
