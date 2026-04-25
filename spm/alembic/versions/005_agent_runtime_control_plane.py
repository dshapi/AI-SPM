"""agent runtime control plane tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-25

Creates three tables to support customer-uploaded AI agents running in
sandboxed containers:

    agents                — agent metadata, code location, credentials
    agent_chat_sessions   — per-user-per-agent conversation sessions
    agent_chat_messages   — immutable message log per session

Idempotency
───────────
ENUM creation uses postgresql.ENUM with create_type=False on every
column. Why postgresql.ENUM and not the generic sa.Enum? Because
SQLAlchemy 2.x adapts sa.Enum to postgresql.ENUM at execution time
WITHOUT preserving create_type=False — the adapted instance defaults
back to create_type=True and fires duplicate CREATE TYPE during
before_create. Using postgresql.ENUM directly bypasses the adaptation
and the flag sticks.

We then create each enum exactly once via an explicit op.execute()
wrapped in DO $$ EXCEPTION WHEN duplicate_object so the migration is
idempotent on retries against a partially-applied DB.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AGENT_TYPE    = ("langchain", "llamaindex", "autogpt", "openai_assistant", "custom")
RUNTIME_STATE = ("stopped", "starting", "running", "crashed")
RISK_LEVEL    = ("low", "medium", "high", "critical")
POLICY_STATUS = ("covered", "partial", "none")
CHAT_ROLE     = ("user", "agent")

# postgresql.ENUM instances with create_type=False — SQLAlchemy will
# NOT auto-create these when it sees them in column definitions. The
# DDL is emitted explicitly in upgrade() via op.execute() with
# duplicate_object guards so the migration is idempotent.
agent_type_enum    = PgEnum(*AGENT_TYPE,    name="agent_type",    create_type=False)
runtime_state_enum = PgEnum(*RUNTIME_STATE, name="runtime_state", create_type=False)
risk_level_enum    = PgEnum(*RISK_LEVEL,    name="risk_level",    create_type=False)
policy_status_enum = PgEnum(*POLICY_STATUS, name="policy_status", create_type=False)
chat_role_enum     = PgEnum(*CHAT_ROLE,     name="chat_role",     create_type=False)


def _create_enum_if_missing(name: str, values: tuple[str, ...]) -> None:
    """Idempotent CREATE TYPE — safe on partial-apply retries."""
    op.execute(
        "DO $$ BEGIN CREATE TYPE " + name + " AS ENUM " + str(values)
        + "; EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )


def upgrade() -> None:
    # ── Create all enums up-front, idempotently ─────────────────────────────
    _create_enum_if_missing("agent_type",    AGENT_TYPE)
    _create_enum_if_missing("runtime_state", RUNTIME_STATE)
    _create_enum_if_missing("chat_role",     CHAT_ROLE)
    # risk_level / policy_status are reused from earlier migrations.
    _create_enum_if_missing("risk_level",    RISK_LEVEL)
    _create_enum_if_missing("policy_status", POLICY_STATUS)

    # ── Create agents table ─────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("agent_type",    agent_type_enum,    nullable=False),
        sa.Column("provider", sa.Text, nullable=False, server_default="internal"),
        sa.Column("owner", sa.Text),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("risk",          risk_level_enum,    server_default="low"),
        sa.Column("policy_status", policy_status_enum, server_default="none"),
        sa.Column("runtime_state", runtime_state_enum,
                   nullable=False, server_default="stopped"),
        sa.Column("code_path", sa.Text, nullable=False),
        sa.Column("code_sha256", sa.Text, nullable=False),
        sa.Column("mcp_token", sa.Text, nullable=False),
        sa.Column("llm_api_key", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Text, nullable=False, server_default="t1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                   server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                   server_default=sa.func.now()),
        sa.UniqueConstraint("name", "version", "tenant_id",
                             name="uq_agents_name_ver_tenant"),
    )
    op.create_index("ix_agents_tenant_state", "agents",
                     ["tenant_id", "runtime_state"])

    # ── Create agent_chat_sessions table ────────────────────────────────────
    op.create_table(
        "agent_chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True),
                   sa.ForeignKey("agents.id", ondelete="CASCADE"),
                   nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True),
                   server_default=sa.func.now()),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("message_count", sa.Integer, nullable=False,
                   server_default="0"),
    )
    op.create_index("ix_chat_sessions_agent", "agent_chat_sessions", ["agent_id"])
    op.create_index("ix_chat_sessions_user",  "agent_chat_sessions", ["user_id"])

    # ── Create agent_chat_messages table ────────────────────────────────────
    op.create_table(
        "agent_chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True),
                   sa.ForeignKey("agent_chat_sessions.id", ondelete="CASCADE"),
                   nullable=False),
        sa.Column("role", chat_role_enum, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True),
                   server_default=sa.func.now()),
        sa.Column("trace_id", sa.Text),
    )
    op.create_index("ix_chat_messages_session", "agent_chat_messages",
                     ["session_id"])
    op.create_index("ix_chat_messages_trace",   "agent_chat_messages",
                     ["trace_id"])

    # ── Seed the 5 mock agents ──────────────────────────────────────────────
    op.execute(
        """
        INSERT INTO agents (id, name, version, agent_type, provider, owner, description,
                             risk, policy_status, runtime_state, code_path, code_sha256,
                             mcp_token, llm_api_key, tenant_id)
        VALUES
          (gen_random_uuid(), 'CustomerSupport-GPT', '1.0', 'langchain', 'aws',
           'ml-platform', 'Tier-1 ticket triage', 'high','partial','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'CodeReview-Assistant', '1.0', 'openai_assistant', 'azure',
           'devex-team', '', 'medium','covered','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'DataPipeline-Orchestrator', '1.0', 'autogpt', 'gcp',
           'data-eng', '', 'critical','none','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'HRIntake-Bot', '1.0', 'llamaindex', 'aws',
           'people-ops', '', 'low','covered','stopped','-','-','-','-','t1'),
          (gen_random_uuid(), 'ThreatHunter-AI', '1.0', 'langchain', 'internal',
           'security-ops', '', 'high','partial','running','-','-','-','-','t1');
        """
    )


def downgrade() -> None:
    op.drop_table("agent_chat_messages")
    op.drop_table("agent_chat_sessions")
    op.drop_table("agents")
    bind = op.get_bind()
    chat_role_enum.drop(bind,     checkfirst=True)
    runtime_state_enum.drop(bind, checkfirst=True)
    agent_type_enum.drop(bind,    checkfirst=True)