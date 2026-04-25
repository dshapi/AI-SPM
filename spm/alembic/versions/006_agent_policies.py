"""agent policies join table

Revision ID: 006
Revises: 005
Create Date: 2026-04-25

Adds the ``agent_policies`` join table so operators can attach the
existing CPM policy registry to an agent. The agent-runtime chat
pipeline (Phase 4) reads this set when calling policy-decider, and
the UI's PreviewPanel exposes an editable "Linked Policies" selector
sourced from it.

policy_id is plain TEXT — not an FK — because the source-of-truth
policy registry lives in CPM (orchestrator), not spm-db. The UI
fetches policy metadata (name, coverage, etc.) from
``GET /api/v1/policies``; this table just records which policy IDs
are attached to which agent.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_policies",
        sa.Column("agent_id", UUID(as_uuid=True),
                   sa.ForeignKey("agents.id", ondelete="CASCADE"),
                   nullable=False),
        sa.Column("policy_id",   sa.Text, nullable=False),
        sa.Column("attached_at", sa.DateTime(timezone=True),
                   nullable=False, server_default=sa.func.now()),
        sa.Column("attached_by", sa.Text),
        sa.PrimaryKeyConstraint("agent_id", "policy_id",
                                 name="pk_agent_policies"),
    )
    op.create_index(
        "ix_agent_policies_policy", "agent_policies", ["policy_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_policies_policy", table_name="agent_policies")
    op.drop_table("agent_policies")
