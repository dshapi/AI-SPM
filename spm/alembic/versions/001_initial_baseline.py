"""initial baseline

Revision ID: 001
Revises:
Create Date: 2026-04-10

Creates the base schema (model_registry, posture_snapshots,
compliance_evidence, audit_export) using CREATE … IF NOT EXISTS guards
so the migration is idempotent on databases that were already
bootstrapped with the raw-SQL script (spm/db/migrations/001_initial.sql).
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
    # Create enums (IF NOT EXISTS supported in PostgreSQL 9.6+)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE model_provider AS ENUM ('local', 'openai', 'anthropic', 'other');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE model_risk_tier AS ENUM ('minimal', 'limited', 'high', 'unacceptable');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE model_status AS ENUM ('registered', 'under_review', 'approved', 'deprecated', 'retired');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE compliance_status AS ENUM ('satisfied', 'partial', 'not_satisfied');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # model_registry
    op.execute("""
        CREATE TABLE IF NOT EXISTS model_registry (
            model_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name         TEXT NOT NULL,
            version      TEXT NOT NULL,
            provider     model_provider NOT NULL DEFAULT 'local',
            purpose      TEXT,
            risk_tier    model_risk_tier NOT NULL DEFAULT 'limited',
            tenant_id    TEXT NOT NULL DEFAULT 'global',
            status       model_status NOT NULL DEFAULT 'registered',
            approved_by  TEXT,
            approved_at  TIMESTAMPTZ,
            ai_sbom      JSONB DEFAULT '{}',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_model_name_version_tenant UNIQUE (name, version, tenant_id)
        );
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TRIGGER model_registry_updated_at
                BEFORE UPDATE ON model_registry
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # posture_snapshots
    op.execute("""
        CREATE TABLE IF NOT EXISTS posture_snapshots (
            id               BIGSERIAL PRIMARY KEY,
            model_id         UUID,
            tenant_id        TEXT NOT NULL,
            snapshot_at      TIMESTAMPTZ NOT NULL,
            request_count    INT NOT NULL DEFAULT 0,
            block_count      INT NOT NULL DEFAULT 0,
            escalation_count INT NOT NULL DEFAULT 0,
            avg_risk_score   FLOAT NOT NULL DEFAULT 0,
            max_risk_score   FLOAT NOT NULL DEFAULT 0,
            intent_drift_avg FLOAT NOT NULL DEFAULT 0,
            ttp_hit_count    INT NOT NULL DEFAULT 0,
            CONSTRAINT uq_snapshot UNIQUE NULLS DISTINCT (model_id, tenant_id, snapshot_at),
            CONSTRAINT fk_posture_model FOREIGN KEY (model_id)
                REFERENCES model_registry(model_id) ON DELETE SET NULL
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_model_tenant_time
            ON posture_snapshots (model_id, tenant_id, snapshot_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_model
            ON posture_snapshots (model_id);
    """)

    # compliance_evidence
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance_evidence (
            id                SERIAL PRIMARY KEY,
            framework         TEXT NOT NULL DEFAULT 'NIST_AI_RMF',
            function          TEXT NOT NULL,
            category          TEXT NOT NULL,
            subcategory       TEXT,
            cpm_control       TEXT NOT NULL,
            status            compliance_status NOT NULL DEFAULT 'not_satisfied',
            evidence_ref      JSONB DEFAULT '{}',
            last_evaluated_at TIMESTAMPTZ
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_compliance_framework_function
            ON compliance_evidence (framework, function);
    """)

    # audit_export
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_export (
            event_id   TEXT PRIMARY KEY,
            tenant_id  TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor      TEXT,
            timestamp  TIMESTAMPTZ NOT NULL,
            payload    JSONB NOT NULL
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_tenant_time
            ON audit_export (tenant_id, timestamp DESC);
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_export_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_export is append-only: UPDATE and DELETE are not permitted';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TRIGGER audit_export_immutable_trg
                BEFORE UPDATE OR DELETE ON audit_export
                FOR EACH ROW EXECUTE FUNCTION audit_export_immutable();
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # Read-only role for Grafana
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'spm_ro') THEN
                CREATE ROLE spm_ro NOLOGIN;
            END IF;
        END $$;
    """)
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO spm_ro;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO spm_ro;")


def downgrade() -> None:
    # Dropping the initial schema is out of scope for Alembic management.
    pass
