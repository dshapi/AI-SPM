"""add agent_kind enum + agents.kind column

Revision ID: 010
Revises: 009
Create Date: 2026-05-05

The SQLAlchemy ``Agent`` model in spm/db/models.py declares::

    kind = Column(Enum(AgentKind, name="agent_kind"),
                  nullable=False, default=AgentKind.customer)

with ``AgentKind`` = {customer, system}. This column distinguishes
customer-uploaded agents (rendered with a Chat surface in the admin UI)
from platform-internal system services that need an ``agents`` row to
mint llm_api_keys but should NOT show a Chat button.

The column was added to the ORM but no migration ever shipped to create
the matching Postgres enum type or the column itself. Result: agent
registration via /admin/agents fails with::

    asyncpg.exceptions.UndefinedObjectError:
        type "agent_kind" does not exist

…because the SQLAlchemy INSERT casts ``$11::agent_kind``.

Documented incident: May 2026. Two manual hotfixes were tried before
this migration:
  1. ``ALTER TABLE agents ADD COLUMN IF NOT EXISTS kind text`` —
     resolved the "column does not exist" error but kept the cast
     failing because the *type* still didn't exist.
  2. ``CREATE TYPE agent_kind … ; ALTER TABLE agents ALTER COLUMN kind
     TYPE agent_kind USING kind::agent_kind`` — resolved registration
     but is local-only to that one DB.

This migration is the proper fix and is idempotent. It safely handles
all three pre-states:

  A. Fresh DB from the alembic chain (no kind column, no enum type).
     → Creates enum, adds column with default 'customer', NOT NULL.

  B. DB where someone hand-patched ``kind`` as ``text`` (hotfix #1).
     → Creates enum, ALTERs column type from text to agent_kind via
       ``USING kind::agent_kind``, sets default + NOT NULL.

  C. DB where the full hotfix #2 already ran, OR this migration has
     run before. → Each DO block is no-op-on-conflict; ALTER is
     no-op when the column is already agent_kind.

Downgrade drops the column but leaves the enum type in place (other
tables may grow to use it later).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create the enum type if it doesn't already exist.
    #    duplicate_object catches the case where it was created by a
    #    prior hotfix or a previous run of this migration.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE agent_kind AS ENUM ('customer', 'system');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # 2. Add the column if absent. We add it as agent_kind directly so
    #    a fresh DB lands in the right shape immediately.
    #    Default 'customer' covers existing rows (the operational
    #    population is overwhelmingly customer agents; system rows are
    #    seeded explicitly by seed_all.py:seed_system_agents()).
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS kind agent_kind
            NOT NULL DEFAULT 'customer';
    """)

    # 3. If the column was hand-patched as TEXT (hotfix #1), migrate it
    #    to agent_kind. This is a no-op when the column is already the
    #    enum type — pg_attribute will skip the ALTER if the target
    #    type matches. We use a DO block + format-string lookup so we
    #    can detect the current type and only ALTER when it's text.
    op.execute("""
        DO $$
        DECLARE
            current_type text;
        BEGIN
            SELECT format_type(atttypid, atttypmod) INTO current_type
              FROM pg_attribute
             WHERE attrelid = 'public.agents'::regclass
               AND attname  = 'kind'
               AND NOT attisdropped;

            IF current_type = 'text' THEN
                EXECUTE 'UPDATE agents SET kind = ''customer''
                            WHERE kind IS NULL OR kind = ''''';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN kind DROP DEFAULT';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN kind TYPE agent_kind
                            USING kind::agent_kind';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN kind SET DEFAULT ''customer''';
                EXECUTE 'ALTER TABLE agents
                            ALTER COLUMN kind SET NOT NULL';
            END IF;
        END$$;
    """)


def downgrade() -> None:
    # Drop only the column. The enum type stays — once added it's
    # cheap to keep, and if any future migration starts using it, a
    # bare downgrade of THIS revision shouldn't pull the rug out.
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS kind;")
