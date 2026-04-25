"""agent hosting tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-25

Creates three tables to support customer-uploaded AI agents running in
sandboxed containers:

    agents                — agent metadata, code location, credentials
    agent_chat_sessions   — per-user-per-agent conversation sessions
    agent_chat_messages   — immutable message log per session

Also creates necessary enums for agent lifecycle (agent_type, runtime_state)
and chat modeling (chat_role).

The risk_level and policy_status enums are reused from existing tables
(ModelRegistry); they are created with idempotent guards since they may
already exist from prior migrations.

Seeds five mock agents (CustomerSupport-GPT, CodeReview-Assistant,
DataPipeline-Orchestrator, HRIntake-Bot, ThreatHunter-AI) so the Inventory
UI can switch from hardcoded mocks to live database rows without losing
existing rows.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AGENT_TYPE = ("langchain", "llamaindex", "autogpt", "openai_assistant", "custom")
RUNTIME_STATE = ("stopped", "starting", "running", "crashed")
RISK_LEVEL = ("low", "medium", "high", "critical")
POLICY_STATUS = ("covered", "partial", "none")
CHAT_ROLE = ("user", "agent")


def upgrade() -> None:
    # ── Create enums ────────────────────────────────────────────────────────
    op.execute("CREATE TYPE agent_type AS ENUM " + str(AGENT_TYPE))
    op.execute("CREATE TYPE runtime_state AS ENUM " + str(RUNTIME_STATE))
    op.execute("CREATE TYPE chat_role AS ENUM " + str(CHAT_ROLE))

    # risk_level / policy_status reuse existing if already present; idempotent guard:
    op.execute(
        "DO $$ BEGIN CREATE TYPE risk_level AS ENUM " + str(RISK_LEVEL)
        + "; EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE policy_status AS ENUM " + str(POLICY_STATUS)
        + "; EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # ── Create agents table ──────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column(
            "agent_type",
            sa.Enum(*AGENT_TYPE, name="agent_type", create_type=False),
            nullable=False,
        ),
        sa.Column("provider", sa.Text, nullable=False, server_default="internal"),
        sa.Column("owner", sa.Text),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column(
            "risk",
            sa.Enum(*RISK_LEVEL, name="risk_level", create_type=False),
            server_default="low",
        ),
        sa.Column(
            "policy_status",
            sa.Enum(*POLICY_STATUS, name="policy_status", create_type=False),
            server_default="none",
        ),
        sa.Column(
            "runtime_state",
            sa.Enum(*RUNTIME_STATE, name="runtime_state", create_type=False),
            nullable=False,
            server_default="stopped",
        ),
        sa.Column("code_path", sa.Text, nullable=False),
        sa.Column("code_sha256", sa.Text, nullable=False),
        sa.Column("mcp_token", sa.Text, nullable=False),
        sa.Column("llm_api_key", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Text, nullable=False, server_default="t1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", "version", "tenant_id", name="uq_agents_name_ver_tenant"),
    )
    op.create_index("ix_agents_tenant_state", "agents", ["tenant_id", "runtime_state"])

    # ── Create agent_chat_sessions table ─────────────────────────────────────
    op.create_table(
        "agent_chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_chat_sessions_agent", "agent_chat_sessions", ["agent_id"])
    op.create_index("ix_chat_sessions_user", "agent_chat_sessions", ["user_id"])

    # ── Create agent_chat_messages table ────────────────────────────────────
    op.create_table(
        "agent_chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum(*CHAT_ROLE, name="chat_role", create_type=False),
            nullable=False,
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("trace_id", sa.Text),
    )
    op.create_index("ix_chat_messages_session", "agent_chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_trace", "agent_chat_messages", ["trace_id"])

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
    op.execute("DROP TYPE chat_role")
    op.execute("DROP TYPE runtime_state")
    op.execute("DROP TYPE agent_type")
