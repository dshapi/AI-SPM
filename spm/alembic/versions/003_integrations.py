"""integrations module

Revision ID: 003
Revises: 002
Create Date: 2026-04-23

Creates the 8 tables that back the Integrations admin page:

    integrations              — top-level row per connector
    integration_credentials   — encrypted secret(s) per integration
    integration_connections   — last-sync / health telemetry
    integration_auth          — scopes, missing scopes, token-expiry metadata
    integration_coverage      — capability matrix (label + enabled flag)
    integration_activity      — recent-activity feed
    integration_workflows     — linked playbooks / alerts / policies / cases
    integration_logs          — append-only audit log

All tables use UUID PKs (gen_random_uuid()) and TIMESTAMPTZ timestamps to
match the existing 001 baseline.  Guards (IF NOT EXISTS / duplicate_object)
keep the migration idempotent when re-applied on a partially-seeded db.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ─────────────────────────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE integration_status AS ENUM (
                'Healthy', 'Warning', 'Error', 'Not Configured',
                'Disabled', 'Partial'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE integration_auth_method AS ENUM (
                'API Key', 'OAuth', 'IAM Role', 'Service Account'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE integration_activity_result AS ENUM (
                'Success', 'Warning', 'Error', 'Info'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # ── integrations ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS integrations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            external_id     TEXT UNIQUE,                -- stable 'int-003' slug
            name            TEXT NOT NULL,
            abbrev          TEXT,
            category        TEXT NOT NULL,
            status          integration_status NOT NULL DEFAULT 'Not Configured',
            auth_method     integration_auth_method NOT NULL DEFAULT 'API Key',
            owner           TEXT,
            owner_display   TEXT,
            environment     TEXT NOT NULL DEFAULT 'Production',
            enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            description     TEXT,
            vendor          TEXT,
            tags            JSONB NOT NULL DEFAULT '[]',
            config          JSONB NOT NULL DEFAULT '{}',  -- non-secret knobs (e.g. model name)
            tenant_id       TEXT NOT NULL DEFAULT 'global',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TRIGGER integrations_updated_at
                BEFORE UPDATE ON integrations
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_integrations_category ON integrations (category);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_integrations_status   ON integrations (status);")

    # ── integration_credentials ───────────────────────────────────────────────
    # Stores the actual secret value.  `value_enc` is the at-rest envelope —
    # the seed script base64-encodes the raw secret today; a real deployment
    # would swap this for KMS / Vault-backed encryption.
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_credentials (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id  UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
            credential_type TEXT NOT NULL,         -- 'api_key' | 'oauth_token' | 'iam_role_arn' | 'service_account_json'
            name            TEXT NOT NULL,         -- human label, e.g. 'Primary API key'
            value_enc       TEXT,                  -- encoded secret; NULL if not yet configured
            value_hint      TEXT,                  -- last-4 / masked preview
            is_configured   BOOLEAN NOT NULL DEFAULT FALSE,
            rotated_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TRIGGER integration_credentials_updated_at
                BEFORE UPDATE ON integration_credentials
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_integration_credentials_int
            ON integration_credentials (integration_id);
    """)

    # ── integration_connections ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_connections (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id    UUID NOT NULL UNIQUE REFERENCES integrations(id) ON DELETE CASCADE,
            last_sync         TEXT,             -- relative display, e.g. '4m ago'
            last_sync_full    TEXT,
            last_failed_sync  TEXT,
            avg_latency       TEXT,             -- '218ms' etc.
            uptime            TEXT,             -- '99.98%'
            health_history    JSONB NOT NULL DEFAULT '[]',
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TRIGGER integration_connections_updated_at
                BEFORE UPDATE ON integration_connections
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # ── integration_auth ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_auth (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id  UUID NOT NULL UNIQUE REFERENCES integrations(id) ON DELETE CASCADE,
            token_expiry    TEXT,
            scopes          JSONB NOT NULL DEFAULT '[]',
            missing_scopes  JSONB NOT NULL DEFAULT '[]',
            setup_progress  JSONB,                           -- nullable; for wizard state
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TRIGGER integration_auth_updated_at
                BEFORE UPDATE ON integration_auth
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # ── integration_coverage ──────────────────────────────────────────────────
    # One row per (integration, capability) — label + enabled flag.
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_coverage (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id  UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
            position        INTEGER NOT NULL DEFAULT 0,
            label           TEXT NOT NULL,
            enabled         BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_integration_coverage_int_pos
            ON integration_coverage (integration_id, position);
    """)

    # ── integration_activity ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_activity (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id  UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
            ts_display      TEXT NOT NULL,          -- 'Apr 8 · 14:28 UTC'
            event_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            event           TEXT NOT NULL,
            result          integration_activity_result NOT NULL DEFAULT 'Info',
            actor           TEXT
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_integration_activity_int_time
            ON integration_activity (integration_id, event_at DESC);
    """)

    # ── integration_workflows ─────────────────────────────────────────────────
    # Single row per integration; JSONB arrays for each workflow bucket keeps
    # the seed data faithful to the mock shape without introducing many link
    # tables.
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_workflows (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id  UUID NOT NULL UNIQUE REFERENCES integrations(id) ON DELETE CASCADE,
            playbooks       JSONB NOT NULL DEFAULT '[]',
            alerts          JSONB NOT NULL DEFAULT '[]',
            policies        JSONB NOT NULL DEFAULT '[]',
            cases           JSONB NOT NULL DEFAULT '[]',
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TRIGGER integration_workflows_updated_at
                BEFORE UPDATE ON integration_workflows
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # ── integration_logs ──────────────────────────────────────────────────────
    # Append-only — every Configure / Test / Disable / Rotate / Sync action
    # writes here so the Logs tab has something to render.
    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_logs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id  UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
            event_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            action          TEXT NOT NULL,        -- 'configure' | 'test' | 'disable' | 'enable' | 'rotate' | 'sync' | 'create' | 'update' | 'delete'
            actor           TEXT,
            result          integration_activity_result NOT NULL DEFAULT 'Info',
            message         TEXT,
            detail          JSONB NOT NULL DEFAULT '{}'
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_integration_logs_int_time
            ON integration_logs (integration_id, event_at DESC);
    """)

    # Grant read on all new tables to the shared RO role
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO spm_ro;")


def downgrade() -> None:
    # The Integrations module owns its tables in isolation — dropping them is
    # safe (unlike the 001 baseline).  Order matters: drop children first.
    for t in (
        "integration_logs",
        "integration_workflows",
        "integration_activity",
        "integration_coverage",
        "integration_auth",
        "integration_connections",
        "integration_credentials",
        "integrations",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for enum_name in (
        "integration_activity_result",
        "integration_auth_method",
        "integration_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name};")
