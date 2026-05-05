"""consolidate agents.risk onto model_risk_tier enum

Revision ID: 011
Revises: 010
Create Date: 2026-05-05

Two enums historically existed for agent/model risk:

  - model_risk_tier (created in migration 001) — values
    (minimal, limited, high, unacceptable). Used by
    model_registry.risk_tier.
  - risk_level     (created in migration 005) — values
    (low, medium, high, critical). Used by agents.risk and a few
    runtime tables.

The ORM in spm/db/models.py:34 unified both into a single Python enum
``ModelRiskTier`` with all 7 values, and `agents.risk` was rebound to
``Enum(ModelRiskTier, name="model_risk_tier")``. But no DB migration
shipped the corresponding ALTER, so:

  - The 3 UI-taxonomy values (low, medium, critical) never landed in
    Postgres's ``model_risk_tier`` type.
  - ``agents.risk`` continues to be typed as ``risk_level``.

Symptom (May 2026): registering a custom agent in the admin UI fails
with::

    asyncpg.exceptions.DatatypeMismatchError:
        column "risk" is of type risk_level
        but expression is of type model_risk_tier
        HINT: You will need to rewrite or cast the expression.

…because SQLAlchemy generates ``$8::model_risk_tier`` and Postgres
won't implicitly cross-cast between two unrelated enum types.

This migration:
  1. Adds (low, medium, critical) to ``model_risk_tier`` if absent.
  2. Migrates ``agents.risk`` from ``risk_level`` to
     ``model_risk_tier`` via a text round-trip (the value strings are
     identical for the overlap, so the cast is lossless).
  3. Restores the 'low' default that the ORM declares.

The ``risk_level`` type itself is left in place — other tables (e.g.
agent_policies, runtime_session, agent_alerts) still reference it and
their ORM models haven't been re-targeted yet. A future migration can
consolidate those once their ORM bindings are also flipped.

Idempotent across:
  A. Fresh DB from the alembic chain (column already typed
     model_risk_tier after this lands; ALTER is no-op).
  B. DB where someone hand-fixed it via SQL hotfix earlier in May 2026
     (column already model_risk_tier; ALTER is no-op).
  C. DBs straight off the 005-era schema (column is risk_level;
     migration converts).

Notes on ALTER TYPE ADD VALUE:
  - Cannot run inside a transaction block. We use
    ``op.execute(...)`` inside ``with op.get_context().autocommit_block():``
    to force-commit each ADD VALUE before the subsequent ALTER COLUMN
    USING references the new values. (Postgres rejects use of an enum
    value in the same statement that added it.)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extend model_risk_tier with the UI-taxonomy values. Each ADD
    #    VALUE must be its own implicit transaction — autocommit_block
    #    handles that.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE model_risk_tier ADD VALUE IF NOT EXISTS 'low'")
        op.execute("ALTER TYPE model_risk_tier ADD VALUE IF NOT EXISTS 'medium'")
        op.execute("ALTER TYPE model_risk_tier ADD VALUE IF NOT EXISTS 'critical'")

    # 2. Convert agents.risk from risk_level → model_risk_tier (or
    #    leave it alone if it's already on model_risk_tier).
    op.execute("""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            SELECT format_type(atttypid, atttypmod) INTO current_type
              FROM pg_attribute
             WHERE attrelid = 'public.agents'::regclass
               AND attname  = 'risk'
               AND NOT attisdropped;

            IF current_type = 'risk_level' THEN
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN risk DROP DEFAULT';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN risk TYPE model_risk_tier
                            USING risk::text::model_risk_tier';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN risk SET DEFAULT ''low''';
            END IF;
        END$$;
    """)


def downgrade() -> None:
    # Rolling back to risk_level requires the type to still exist
    # (migration 005 created it; we never drop it). Cast back via text.
    op.execute("""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            SELECT format_type(atttypid, atttypmod) INTO current_type
              FROM pg_attribute
             WHERE attrelid = 'public.agents'::regclass
               AND attname  = 'risk'
               AND NOT attisdropped;

            IF current_type = 'model_risk_tier' THEN
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN risk DROP DEFAULT';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN risk TYPE risk_level
                            USING risk::text::risk_level';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN risk SET DEFAULT ''low''';
            END IF;
        END$$;
    """)

    # ALTER TYPE … DROP VALUE doesn't exist in Postgres, so we leave
    # 'low'/'medium'/'critical' on model_risk_tier even after a
    # downgrade. Harmless; just enum-dictionary noise.
