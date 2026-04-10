"""Initial schema: agent_sessions and session_events

Revision ID: 001
Revises:
Create Date: 2026-04-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id",             sa.String,               primary_key=True),
        sa.Column("user_id",        sa.String,               nullable=False),
        sa.Column("agent_id",       sa.String,               nullable=False),
        sa.Column("tenant_id",      sa.String,               nullable=True),
        sa.Column("status",         sa.String,               nullable=False),
        sa.Column("risk_score",     sa.Float,                nullable=False),
        sa.Column("decision",       sa.String,               nullable=False),
        sa.Column("prompt_hash",    sa.String,               nullable=False),
        sa.Column("risk_tier",      sa.String,               nullable=False),
        sa.Column("risk_signals",   sa.Text,                 nullable=False),
        sa.Column("tools",          sa.Text,                 nullable=False),
        sa.Column("context",        sa.Text,                 nullable=False),
        sa.Column("policy_reason",  sa.String,               nullable=False),
        sa.Column("policy_version", sa.String,               nullable=False),
        sa.Column("trace_id",       sa.String,               nullable=False),
        sa.Column("created_at",     sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_sessions_user_id",   "agent_sessions", ["user_id"])
    op.create_index("ix_agent_sessions_agent_id",  "agent_sessions", ["agent_id"])
    op.create_index("ix_agent_sessions_tenant_id", "agent_sessions", ["tenant_id"])

    op.create_table(
        "session_events",
        sa.Column("id",         sa.String,                  primary_key=True),
        sa.Column("session_id", sa.String,
                  sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event_type", sa.String,                  nullable=False),
        sa.Column("payload",    sa.Text,                    nullable=False),
        sa.Column("timestamp",  sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_session_events_session_id", "session_events", ["session_id"])
    op.create_index("ix_session_events_event_type", "session_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("session_events")
    op.drop_table("agent_sessions")
