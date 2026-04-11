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

from sqlalchemy import Column, DateTime, Integer, String
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
    agents           = Column(JSON, nullable=False, default=list)
    tools            = Column(JSON, nullable=False, default=list)
    data_sources     = Column(JSON, nullable=False, default=list)
    environments     = Column(JSON, nullable=False, default=list)
    exceptions       = Column(JSON, nullable=False, default=list)
    impact           = Column(JSON, nullable=False,
                              default=lambda: {"blocked": 0, "flagged": 0,
                                               "unchanged": 0, "total": 100})
    history          = Column(JSON, nullable=False, default=list)
    logic            = Column(JSON, nullable=False, default=list)

    # ── Raw logic code ────────────────────────────────────────────────────────
    logic_code       = Column(String, nullable=False, default="")
    logic_language   = Column(String, nullable=False, default="rego")

    # ── Snapshots for version restore ─────────────────────────────────────────
    snapshots        = Column(JSON, nullable=False, default=dict)

    # ── Audit timestamps ──────────────────────────────────────────────────────
    created_at       = Column(DateTime(timezone=True), nullable=False,
                              default=_utcnow)
    updated_at       = Column(DateTime(timezone=True), nullable=False,
                              default=_utcnow, onupdate=_utcnow)
