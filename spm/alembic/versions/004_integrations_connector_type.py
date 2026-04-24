"""integrations: add connector_type column + backfill by name

Revision ID: 004
Revises: 003
Create Date: 2026-04-24

The connector_type column is the stable registry key used by the
schema-driven Add / Configure modal and by the probe dispatcher in
connector_registry.py.  It replaces the fragile
``name.lower() + category`` heuristic the UI was using to pick a form
archetype.

Backfill strategy — the 19 pre-existing seed rows have deterministic
names (``Anthropic``, ``Kafka``, …) so we map them via a small inline
CASE statement.  Any row whose name doesn't match (custom integrations
added by operators) gets NULL, which the runtime treats as
"fall back to name-based dispatch" — so this migration is safe to
apply before the seed file has been updated.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (lowercased integration.name, connector_type key)
_BACKFILL_MAP = [
    ("openai",              "openai"),
    ("azure openai",        "azure_openai"),
    ("anthropic",           "anthropic"),
    ("amazon bedrock",      "bedrock"),
    ("google vertex ai",    "vertex"),
    ("splunk",              "splunk"),
    ("microsoft sentinel",  "sentinel"),
    ("jira",                "jira"),
    ("servicenow",          "servicenow"),
    ("slack",               "slack"),
    ("okta",                "okta"),
    ("entra id",            "entra"),
    ("amazon s3",           "s3"),
    ("confluence",          "confluence"),
    ("kafka",               "kafka"),
    ("tavily",              "tavily"),
    ("ollama",              "ollama"),
    ("garak",               "garak"),
    ("apache flink",        "flink"),
    ("flink",               "flink"),
    ("postgresql",          "postgres"),
    ("postgres",            "postgres"),
    ("redis",               "redis"),
]


def upgrade() -> None:
    # ── Add column (idempotent — ADD COLUMN IF NOT EXISTS on PG ≥ 9.6) ────────
    op.execute("""
        ALTER TABLE integrations
        ADD COLUMN IF NOT EXISTS connector_type TEXT;
    """)

    # ── Backfill by lowercased name ──────────────────────────────────────────
    for name_lower, ctype in _BACKFILL_MAP:
        op.execute(f"""
            UPDATE integrations
               SET connector_type = '{ctype}'
             WHERE connector_type IS NULL
               AND LOWER(name) = '{name_lower}';
        """)

    # ── Index for dispatcher lookups ─────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_integrations_connector_type
            ON integrations (connector_type);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_integrations_connector_type;")
    op.execute("ALTER TABLE integrations DROP COLUMN IF EXISTS connector_type;")
