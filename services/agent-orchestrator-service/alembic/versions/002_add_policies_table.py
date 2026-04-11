"""Add policies table

Revision ID: 002
Revises: 001
Create Date: 2026-04-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("policy_id",       sa.String,  primary_key=True),
        sa.Column("name",            sa.String,  nullable=False),
        sa.Column("version",         sa.String,  nullable=False),
        sa.Column("type",            sa.String,  nullable=False),
        sa.Column("mode",            sa.String,  nullable=False),
        sa.Column("status",          sa.String,  nullable=False),
        sa.Column("scope",           sa.String,  nullable=False, server_default=""),
        sa.Column("owner",           sa.String,  nullable=False, server_default=""),
        sa.Column("created_by",      sa.String,  nullable=False, server_default=""),
        sa.Column("created",         sa.String,  nullable=False, server_default=""),
        sa.Column("updated",         sa.String,  nullable=False, server_default=""),
        sa.Column("updated_full",    sa.String,  nullable=False, server_default=""),
        sa.Column("description",     sa.String,  nullable=False, server_default=""),
        sa.Column("affected_assets", sa.Integer, nullable=False, server_default="0"),
        sa.Column("related_alerts",  sa.Integer, nullable=False, server_default="0"),
        sa.Column("linked_sims",     sa.Integer, nullable=False, server_default="0"),
        sa.Column("agents",        sa.JSON, nullable=False),
        sa.Column("tools",         sa.JSON, nullable=False),
        sa.Column("data_sources",  sa.JSON, nullable=False),
        sa.Column("environments",  sa.JSON, nullable=False),
        sa.Column("exceptions",    sa.JSON, nullable=False),
        sa.Column("impact",        sa.JSON, nullable=False),
        sa.Column("history",       sa.JSON, nullable=False),
        sa.Column("logic",         sa.JSON, nullable=False),
        sa.Column("logic_code",    sa.String, nullable=False, server_default=""),
        sa.Column("logic_language",sa.String, nullable=False, server_default="rego"),
        sa.Column("snapshots",     sa.JSON, nullable=False),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",    sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_policies_policy_id", "policies", ["policy_id"])
    op.create_index("ix_policies_type",      "policies", ["type"])
    op.create_index("ix_policies_mode",      "policies", ["mode"])
    op.create_index("ix_policies_status",    "policies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_policies_status",    "policies")
    op.drop_index("ix_policies_mode",      "policies")
    op.drop_index("ix_policies_type",      "policies")
    op.drop_index("ix_policies_policy_id", "policies")
    op.drop_table("policies")
