"""Add threat_findings table

Revision ID: 004
Revises: 003
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: str | None = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "threat_findings",
        sa.Column("id",          sa.String, primary_key=True),
        sa.Column("batch_hash",  sa.String, nullable=False, unique=True),
        sa.Column("title",       sa.String, nullable=False),
        sa.Column("severity",    sa.String, nullable=False),
        sa.Column("description", sa.Text,   nullable=False),
        sa.Column("evidence",    sa.Text,   nullable=False),
        sa.Column("ttps",        sa.Text,   nullable=False, server_default="[]"),
        sa.Column("tenant_id",   sa.String, nullable=False),
        sa.Column("status",      sa.String, nullable=False, server_default="open"),
        sa.Column("created_at",  sa.String, nullable=False),
        sa.Column("closed_at",   sa.String, nullable=True),
    )
    op.create_index("ix_threat_findings_tenant",   "threat_findings", ["tenant_id", "created_at"])
    op.create_index("ix_threat_findings_severity", "threat_findings", ["severity", "status"])


def downgrade() -> None:
    op.drop_index("ix_threat_findings_severity")
    op.drop_index("ix_threat_findings_tenant")
    op.drop_table("threat_findings")
