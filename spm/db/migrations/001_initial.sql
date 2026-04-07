-- 001_initial.sql
-- AI SPM Platform — Initial Schema

-- ── Enums ────────────────────────────────────────────────────────────────────

CREATE TYPE model_provider AS ENUM ('local', 'openai', 'anthropic', 'other');
CREATE TYPE model_risk_tier AS ENUM ('minimal', 'limited', 'high', 'unacceptable');
CREATE TYPE model_status AS ENUM ('registered', 'under_review', 'approved', 'deprecated', 'retired');
CREATE TYPE compliance_status AS ENUM ('satisfied', 'partial', 'not_satisfied');

-- ── Tables ───────────────────────────────────────────────────────────────────

CREATE TABLE model_registry (
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

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER model_registry_updated_at
    BEFORE UPDATE ON model_registry
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE posture_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    model_id         UUID,  -- NULL = unknown model, SET NULL on model deletion
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

CREATE INDEX idx_snapshots_model_tenant_time
    ON posture_snapshots (model_id, tenant_id, snapshot_at DESC);

CREATE INDEX idx_snapshots_model ON posture_snapshots (model_id);

CREATE TABLE compliance_evidence (
    id               SERIAL PRIMARY KEY,
    framework        TEXT NOT NULL DEFAULT 'NIST_AI_RMF',
    function         TEXT NOT NULL,
    category         TEXT NOT NULL,
    subcategory      TEXT,
    cpm_control      TEXT NOT NULL,
    status           compliance_status NOT NULL DEFAULT 'not_satisfied',
    evidence_ref     JSONB DEFAULT '{}',
    last_evaluated_at TIMESTAMPTZ
);

CREATE INDEX idx_compliance_framework_function
    ON compliance_evidence (framework, function);

CREATE TABLE audit_export (
    event_id   TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor      TEXT,
    timestamp  TIMESTAMPTZ NOT NULL,
    payload    JSONB NOT NULL
);

CREATE INDEX idx_audit_tenant_time ON audit_export (tenant_id, timestamp DESC);

-- ── Immutability trigger on audit_export ─────────────────────────────────────

CREATE OR REPLACE FUNCTION audit_export_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_export is append-only: UPDATE and DELETE are not permitted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_export_immutable_trg
    BEFORE UPDATE OR DELETE ON audit_export
    FOR EACH ROW EXECUTE FUNCTION audit_export_immutable();

-- ── Read-only role for Grafana ────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'spm_ro') THEN
        CREATE ROLE spm_ro NOLOGIN;
    END IF;
END $$;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO spm_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO spm_ro;
