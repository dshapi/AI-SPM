"""initial baseline — squashed

Revision ID: 001
Revises:
Create Date: 2026-05-09

Single squashed migration replacing what used to be 12 separate files
(001 through 012).  The platform is dev-only and every reset starts from
a blank Postgres, so chained incremental migrations were pure overhead
and produced the 008→009→010→011→012 drift we kept tripping over.

The full schema is materialised from the SQLAlchemy ORM via
``Base.metadata.create_all(connection)``.  Source of truth is the ORM
model code in ``spm/db/models.py``; this migration is just a thin
wrapper that runs it under alembic's connection context so future
migrations (002+) can downstream from this revision.

Adding new schema changes
─────────────────────────
NEVER add another standalone migration that munges ALTER statements
unless you genuinely need an incremental upgrade path.  Instead:
  1. Update the ORM model in ``spm/db/models.py``.
  2. Bump the dev cluster:
     ``./deploy/scripts/bootstrap-cluster.sh`` → pick `[d]` at the prompt.
  3. If you really need an incremental migration, only then add 002.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the full schema from the ORM models.

    Idempotent — ``create_all`` skips tables that already exist, so this
    migration is safe to re-apply against a partially-bootstrapped DB.
    """
    # Lazy import: env.py inserts spm/ into sys.path, so the correct
    # import is `db.models` (not `spm.db.models`, which requires the
    # project root on sys.path instead of the spm/ dir itself).
    from db.models import Base  # type: ignore

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop every table create_all() created.

    Used by ``alembic downgrade base`` for full-reset flows.  In practice
    we recreate the cluster instead, but the inverse keeps alembic's
    downgrade chain intact.
    """
    from db.models import Base  # type: ignore

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
