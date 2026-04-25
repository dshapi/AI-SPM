"""agents.code_blob

Revision ID: 007
Revises: 006
Create Date: 2026-04-25

Adds ``agents.code_blob`` — the full text of the customer's agent.py
stored in the DB at registration time. Phase 1 only stored the path
(``code_path``), which made the agent silently broken if anyone
deleted the file from the host volume. Phase 4 self-heals by
rewriting the bind-mount source from ``code_blob`` on every spawn.

Backwards compatibility
───────────────────────
Existing rows have ``code_blob = NULL``. The chat / start path falls
back to reading from the disk path when the blob is empty (legacy
behavior); only newly-registered agents benefit from the self-heal
path until those legacy agents are re-uploaded.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("code_blob", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "code_blob")
