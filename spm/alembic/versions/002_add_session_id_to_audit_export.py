"""add session_id to audit_export

Revision ID: 002
Revises: 001
Create Date: 2026-04-10

Adds an optional session_id column to audit_export so that audit events
can be correlated back to the agent-orchestrator session that produced them.

Migration is idempotent:
  - upgrade:   ADD COLUMN IF NOT EXISTS  +  CREATE INDEX IF NOT EXISTS
  - downgrade: DROP INDEX IF EXISTS       +  DROP COLUMN IF EXISTS
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add session_id column — safe even if the column already exists.
    # PostgreSQL 9.6+ supports IF NOT EXISTS on ALTER TABLE ADD COLUMN.
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE audit_export
                ADD COLUMN session_id VARCHAR(64);
        EXCEPTION
            WHEN duplicate_column THEN
                NULL;  -- column already present; nothing to do
        END
        $$;
        """
    )

    # Create index — IF NOT EXISTS prevents an error on re-run.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_export_session_id
            ON audit_export (session_id);
        """
    )


def downgrade() -> None:
    # Drop index first (required before dropping the column it references).
    op.execute(
        """
        DROP INDEX IF EXISTS idx_audit_export_session_id;
        """
    )

    # Drop column — safe even if it was never added.
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE audit_export
                DROP COLUMN session_id;
        EXCEPTION
            WHEN undefined_column THEN
                NULL;  -- column does not exist; nothing to do
        END
        $$;
        """
    )
