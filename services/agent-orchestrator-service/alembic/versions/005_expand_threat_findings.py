"""Expand threat_findings with full Finding schema fields.

Revision ID: 005
Revises: 004
Create Date: 2026-04-12
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: str | None = "004"
branch_labels = None
depends_on = None

_NEW_COLS = [
    ("timestamp",           sa.String,  True),
    ("confidence",          sa.Float,   True),
    ("risk_score",          sa.Float,   True),
    ("hypothesis",          sa.Text,    True),
    ("asset",               sa.String,  True),
    ("environment",         sa.String,  True),
    ("correlated_events",   sa.Text,    True),
    ("correlated_findings", sa.Text,    True),
    ("triggered_policies",  sa.Text,    True),
    ("policy_signals",      sa.Text,    True),
    ("recommended_actions", sa.Text,    True),
    ("should_open_case",    sa.Boolean, True),
    ("case_id",             sa.String,  True),
    ("source",              sa.String,  True),
    ("updated_at",          sa.String,  True),
]

def upgrade() -> None:
    with op.batch_alter_table("threat_findings") as batch_op:
        for col_name, col_type, nullable in _NEW_COLS:
            batch_op.add_column(sa.Column(col_name, col_type, nullable=nullable))

def downgrade() -> None:
    with op.batch_alter_table("threat_findings") as batch_op:
        for col_name, _, _ in _NEW_COLS:
            batch_op.drop_column(col_name)
