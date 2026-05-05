"""consolidate agents.policy_status onto policy_coverage enum + extend model_provider

Revision ID: 012
Revises: 011
Create Date: 2026-05-05

Two related schema-drift fixes:

1. agents.policy_status enum unification
   ────────────────────────────────────────
   Migration 005 created enum ``policy_status (covered, partial, none)``
   for ``agents.policy_status``.
   Migration 009 created enum ``policy_coverage (full, partial, none)``
   for ``model_registry.policy_status``.

   The ORM in spm/db/models.py:444 unified both columns onto
   ``Enum(PolicyCoverage, name="policy_coverage")`` but no migration
   ever altered the ``agents`` column. INSERT into agents fails with::

       asyncpg.exceptions.DatatypeMismatchError:
           column "policy_status" is of type policy_status
           but expression is of type policy_coverage
           HINT: You will need to rewrite or cast the expression.

   Value mapping:  covered → full,  partial → partial,  none → none.

2. model_provider enum extension
   ────────────────────────────────────────
   Migration 001 created ``model_provider`` with the conceptual values
   ``(local, openai, anthropic, other)``. The ORM enum in
   ``spm/db/models.py:21`` later added cloud-provider values
   ``(aws, azure, gcp)`` for the admin Inventory UI, and the agent
   Register dialog can submit ``provider=internal``. None of those
   ever landed in Postgres, so a Register payload that picks any of
   them fails at INSERT-time with ``invalid input value for enum
   model_provider``.

   We add ``aws, azure, gcp, internal`` defensively. Existing rows are
   untouched; only inserts of those values become legal.

Documented incident: May 2026. Both bugs were hit consecutively while
debugging the same custom-agent registration path. Fixing both in one
migration so the next bootstrap doesn't have to play whack-a-mole.

Idempotent across:
  A. Fresh DB from the alembic chain (column already typed
     policy_coverage if migration 009 ran AFTER 005-era schema reset;
     ALTER is no-op).
  B. DB where someone hand-fixed it via SQL hotfix earlier in May 2026.
  C. DBs straight off the 005-era schema (column is policy_status enum;
     migration converts and maps values).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extend model_provider with cloud + internal values. ALTER TYPE
    #    ADD VALUE cannot run inside a transaction, so use autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE model_provider ADD VALUE IF NOT EXISTS 'aws'")
        op.execute("ALTER TYPE model_provider ADD VALUE IF NOT EXISTS 'azure'")
        op.execute("ALTER TYPE model_provider ADD VALUE IF NOT EXISTS 'gcp'")
        op.execute("ALTER TYPE model_provider ADD VALUE IF NOT EXISTS 'internal'")

    # 2. Migrate agents.policy_status from policy_status enum →
    #    policy_coverage enum, mapping 'covered' → 'full'. No-op if the
    #    column is already on policy_coverage.
    op.execute("""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            SELECT format_type(atttypid, atttypmod) INTO current_type
              FROM pg_attribute
             WHERE attrelid = 'public.agents'::regclass
               AND attname  = 'policy_status'
               AND NOT attisdropped;

            IF current_type = 'policy_status' THEN
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN policy_status DROP DEFAULT';
                EXECUTE $cast$
                    ALTER TABLE agents
                       ALTER COLUMN policy_status TYPE policy_coverage
                       USING (
                         CASE policy_status::text
                           WHEN 'covered' THEN 'full'::policy_coverage
                           WHEN 'partial' THEN 'partial'::policy_coverage
                           WHEN 'none'    THEN 'none'::policy_coverage
                           ELSE 'none'::policy_coverage
                         END
                       )
                $cast$;
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN policy_status SET DEFAULT ''none''';
            END IF;
        END$$;
    """)


def downgrade() -> None:
    # Roll the agents column back to the policy_status enum (still
    # exists; never dropped) with the inverse mapping.
    op.execute("""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            SELECT format_type(atttypid, atttypmod) INTO current_type
              FROM pg_attribute
             WHERE attrelid = 'public.agents'::regclass
               AND attname  = 'policy_status'
               AND NOT attisdropped;

            IF current_type = 'policy_coverage' THEN
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN policy_status DROP DEFAULT';
                EXECUTE $cast$
                    ALTER TABLE agents
                       ALTER COLUMN policy_status TYPE policy_status
                       USING (
                         CASE policy_status::text
                           WHEN 'full'    THEN 'covered'::policy_status
                           WHEN 'partial' THEN 'partial'::policy_status
                           WHEN 'none'    THEN 'none'::policy_status
                           ELSE 'none'::policy_status
                         END
                       )
                $cast$;
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN policy_status SET DEFAULT ''none''';
            END IF;
        END$$;
    """)

    # ALTER TYPE … DROP VALUE is unsupported. The added model_provider
    # values stay; harmless extra dictionary entries.
