"""add inventory columns to model_registry

Revision ID: 009
Revises: 008
Create Date: 2026-05-03

The SQLAlchemy `ModelRegistry` model in `spm/db/models.py` declares six
columns that the Alembic baseline (001) doesn't create:

  - model_type     Enum(ModelType, name="model_type")     nullable
  - owner          Text                                   nullable
  - policy_status  Enum(PolicyCoverage, name="policy_coverage") nullable
  - alerts_count   Integer NOT NULL DEFAULT 0
  - last_seen_at   TIMESTAMPTZ                            nullable
  - notes          Text                                   nullable

These were added to the model over time (Inventory-table fields
surfaced as Owner / Policy / Alerts columns in the UI) but no Alembic
migration ever shipped to add them.  Result: a fresh DB seeded by the
alembic chain can't be SELECTed against by `seed_models` because
`model_registry.model_type` doesn't exist — the seed_db Job dies with
`asyncpg.UndefinedColumnError` and bootstrap fails.  Documented
incident: May 2026.

This migration is idempotent — `ADD COLUMN IF NOT EXISTS` for every
column, and the enum types use DO blocks with `duplicate_object`
suppression.  Safe on:

  - Fresh DBs from the alembic chain (adds all 6 columns)
  - Older DBs bootstrapped via Base.metadata.create_all (no-op for
    columns that already exist; same for enum types)
  - Re-runs of this migration

Downgrade drops the 6 columns but leaves the enum types in place
(other tables may use them — e.g., agents.policy_status).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum types — create only if absent.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE model_type AS ENUM (
                'llm', 'open_source_llm', 'embedding_model',
                'audio_model', 'vision_model', 'multimodal', 'other'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE policy_coverage AS ENUM ('full', 'partial', 'none');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # Columns — IF NOT EXISTS makes each step idempotent.
    op.execute("""
        ALTER TABLE model_registry
            ADD COLUMN IF NOT EXISTS model_type model_type;
    """)
    op.execute("""
        ALTER TABLE model_registry
            ADD COLUMN IF NOT EXISTS owner TEXT;
    """)
    op.execute("""
        ALTER TABLE model_registry
            ADD COLUMN IF NOT EXISTS policy_status policy_coverage;
    """)
    op.execute("""
        ALTER TABLE model_registry
            ADD COLUMN IF NOT EXISTS alerts_count INTEGER NOT NULL DEFAULT 0;
    """)
    op.execute("""
        ALTER TABLE model_registry
            ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
    """)
    op.execute("""
        ALTER TABLE model_registry
            ADD COLUMN IF NOT EXISTS notes TEXT;
    """)


def downgrade() -> None:
    # Drop columns first, then leave enum types in place (other tables
    # may use them).  Each DROP is IF EXISTS so the migration is safe
    # to apply against a DB where these columns were never added.
    for col in ("model_type", "owner", "policy_status",
                "alerts_count", "last_seen_at", "notes"):
        op.execute(f'ALTER TABLE model_registry DROP COLUMN IF EXISTS {col};')
