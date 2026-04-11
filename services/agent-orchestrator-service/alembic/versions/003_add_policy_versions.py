"""Add policy_versions and policy_lifecycle_audit tables

Revision ID: 003
Revises: 002
Create Date: 2026-04-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "policy_versions",
        sa.Column("id",                    sa.String,  primary_key=True),
        sa.Column("policy_id",             sa.String,  nullable=False),
        sa.Column("version_number",        sa.Integer, nullable=False),
        sa.Column("version_str",           sa.String,  nullable=False),
        sa.Column("state",                 sa.String,  nullable=False, server_default="draft"),
        sa.Column("is_runtime_active",     sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by",            sa.String,  nullable=False, server_default=""),
        sa.Column("created_at",            sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("change_summary",        sa.String,  nullable=False, server_default=""),
        sa.Column("restored_from_version", sa.Integer, nullable=True),
        sa.Column("logic_code",            sa.String,  nullable=False, server_default=""),
        sa.Column("logic_language",        sa.String,  nullable=False, server_default="rego"),
    )
    op.create_index("ix_pv_policy_id", "policy_versions", ["policy_id"])
    op.create_index("ix_pv_state",     "policy_versions", ["state"])
    op.create_index("ix_pv_active",    "policy_versions", ["policy_id", "is_runtime_active"])

    op.create_table(
        "policy_lifecycle_audit",
        sa.Column("id",             sa.String,  primary_key=True),
        sa.Column("policy_id",      sa.String,  nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("action",         sa.String,  nullable=False),
        sa.Column("from_state",     sa.String,  nullable=True),
        sa.Column("to_state",       sa.String,  nullable=False),
        sa.Column("actor",          sa.String,  nullable=False, server_default="system"),
        sa.Column("reason",         sa.String,  nullable=False, server_default=""),
        sa.Column("timestamp",      sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("extra",          sa.JSON,    nullable=True),
    )
    op.create_index("ix_pla_policy_id", "policy_lifecycle_audit", ["policy_id"])
    op.create_index("ix_pla_timestamp", "policy_lifecycle_audit", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_pla_timestamp", "policy_lifecycle_audit")
    op.drop_index("ix_pla_policy_id", "policy_lifecycle_audit")
    op.drop_table("policy_lifecycle_audit")
    op.drop_index("ix_pv_active",    "policy_versions")
    op.drop_index("ix_pv_state",     "policy_versions")
    op.drop_index("ix_pv_policy_id", "policy_versions")
    op.drop_table("policy_versions")
