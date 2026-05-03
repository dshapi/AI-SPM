"""backfill posture_snapshots.uq_snapshot constraint

Revision ID: 008
Revises: 007
Create Date: 2026-05-03

Backfills the `uq_snapshot UNIQUE NULLS DISTINCT (model_id, tenant_id,
snapshot_at)` constraint on `posture_snapshots` for clusters bootstrapped
before the constraint was added to the SQLAlchemy model.

Background: the raw bootstrap SQL had this constraint, the SQLAlchemy
model didn't, and clusters bootstrapped via `Base.metadata.create_all`
ended up missing it.  Result: every `INSERT … ON CONFLICT (model_id,
tenant_id, snapshot_at) DO UPDATE` in `spm_aggregator.upsert_snapshot`
errored `42P10  there is no unique or exclusion constraint matching the
ON CONFLICT specification`.

Idempotent: pg_constraint guard checks for existence before adding.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_snapshot'
                  AND conrelid = 'posture_snapshots'::regclass
            ) THEN
                ALTER TABLE posture_snapshots
                    ADD CONSTRAINT uq_snapshot
                    UNIQUE NULLS DISTINCT (model_id, tenant_id, snapshot_at);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE posture_snapshots DROP CONSTRAINT IF EXISTS uq_snapshot;")
