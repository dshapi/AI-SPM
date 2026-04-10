"""initial baseline

Revision ID: 001
Revises:
Create Date: 2026-04-10

Baseline revision that represents the schema created by the raw-SQL
bootstrap script (spm/db/migrations/001_initial.sql).

upgrade() is intentionally a no-op: the tables already exist in any
database that was initialised with the SQL script.  Running
`alembic upgrade head` on a fresh-SQL database is safe because all
subsequent migrations use IF NOT EXISTS guards.

downgrade() is a no-op for the same reason — we do not drop the
original tables here; real rollback is handled by each delta migration.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op   # noqa: F401  (imported for convention; unused here)

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tables were created by spm/db/migrations/001_initial.sql.
    # Nothing to do here; Alembic just stamps the version.
    pass


def downgrade() -> None:
    # Dropping the initial schema is out of scope for Alembic management.
    pass
