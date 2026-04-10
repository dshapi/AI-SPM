"""
db/models.py
────────────
SQLAlchemy ORM table definitions.

Two tables:
  agent_sessions  — one row per AI agent session
  session_events  — lifecycle events emitted during a session

Both are imported in alembic/env.py so autogenerate picks them up.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from db.base import Base


class AgentSessionORM(Base):
    """
    Persistent record for one agent session.

    Column naming note: the ORM column is named 'decision' (concise SQL-friendly
    name) but maps to SessionRecord.policy_decision in the domain layer.
    The mapping helper _orm_to_record() converts 'orm.decision' → 'policy_decision'
    and the insert() method maps 'rec.policy_decision' → 'decision=...' explicitly.
    This is intentional; do not rename without updating both sides.

    JSON fields (tools, context, risk_signals) are stored as JSON-serialised strings
    because SQLite has no native JSON column type.
    """
    __tablename__ = "agent_sessions"

    id             = Column(String,               primary_key=True)
    user_id        = Column(String,               nullable=False)
    agent_id       = Column(String,               nullable=False)
    tenant_id      = Column(String,               nullable=True)
    status         = Column(String,               nullable=False)
    risk_score     = Column(Float,                nullable=False)
    decision       = Column(String,               nullable=False)   # maps to SessionRecord.policy_decision
    # ── Extended metadata ─────────────────────────────────────────────
    prompt_hash    = Column(String,               nullable=False)
    risk_tier      = Column(String,               nullable=False)
    risk_signals   = Column(Text,                 nullable=False)   # JSON array
    tools          = Column(Text,                 nullable=False)   # JSON array
    context        = Column(Text,                 nullable=False)   # JSON object
    policy_reason  = Column(String,               nullable=False)
    policy_version = Column(String,               nullable=False)
    trace_id       = Column(String,               nullable=False)
    created_at     = Column(DateTime(timezone=True), nullable=False)
    updated_at     = Column(DateTime(timezone=True), nullable=False)

    events = relationship(
        "SessionEventORM",
        back_populates="session",
        lazy="select",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_agent_sessions_user_id",   "user_id"),
        Index("ix_agent_sessions_agent_id",  "agent_id"),
        Index("ix_agent_sessions_tenant_id", "tenant_id"),
    )


class SessionEventORM(Base):
    """
    One row per lifecycle event emitted during a session.
    payload is a JSON string (the event's domain payload dict).
    """
    __tablename__ = "session_events"

    id         = Column(String,               primary_key=True)
    session_id = Column(
        String,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String,               nullable=False)
    payload    = Column(Text,                 nullable=False)   # JSON string
    timestamp  = Column(DateTime(timezone=True), nullable=False)

    session = relationship("AgentSessionORM", back_populates="events")

    __table_args__ = (
        Index("ix_session_events_session_id", "session_id"),
        Index("ix_session_events_event_type", "event_type"),
    )


class CaseORM(Base):
    """
    Persistent record for one escalated AI security case.
    Replaces the former in-memory dict in CasesService.
    """
    __tablename__ = "agent_cases"

    case_id    = Column(String,               primary_key=True)
    session_id = Column(String,               nullable=False)
    reason     = Column(String,               nullable=False)
    summary    = Column(Text,                 nullable=False)
    risk_score = Column(Float,                nullable=False)
    decision   = Column(String,               nullable=False)
    status     = Column(String,               nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_agent_cases_session_id", "session_id"),
        Index("ix_agent_cases_created_at", "created_at"),
    )
