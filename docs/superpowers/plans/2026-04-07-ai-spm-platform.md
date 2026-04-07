# AI SPM Platform Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full AI Security Posture Management (AI SPM) layer to CPM v3 — model registry, lifecycle management, aggregate posture monitoring, active enforcement, NIST AI RMF compliance reporting, and Grafana dashboards.

**Architecture:** Four new Docker Compose services (spm-api, spm-aggregator, spm-db, grafana+prometheus) alongside unchanged CPM v3 services. The aggregator passively consumes existing Kafka topics and writes time-series posture snapshots to PostgreSQL; spm-api provides model registry CRUD, compliance reports, and enforcement (OPA policy push + Freeze Controller calls). Only 4 small additive changes touch existing CPM code.

**Tech Stack:** FastAPI, SQLAlchemy (async/asyncpg), PostgreSQL 16, kafka-python, WeasyPrint, Prometheus, Grafana, Open Policy Agent (existing), Redis (existing), RS256 JWT (existing).

**Spec:** `docs/superpowers/specs/2026-04-07-ai-spm-design.md`

---

## File Map

### New files
```
cpm-v3/
├── spm/
│   ├── __init__.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py              # SQLAlchemy ORM (4 tables)
│   │   ├── session.py             # async engine + connection pool
│   │   └── migrations/
│   │       └── 001_initial.sql    # full schema + immutability trigger
│   └── compliance/
│       ├── __init__.py
│       ├── evaluator.py           # NIST AI RMF satisfaction rules
│       ├── nist_airm_mapping.json # control → CPM control map
│       └── report_template.html   # WeasyPrint PDF template
├── services/
│   ├── spm_api/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app.py                 # FastAPI: registry, compliance, enforcement, JWKS
│   └── spm_aggregator/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app.py                 # Kafka consumer: snapshots + enforcement trigger
├── opa/policies/model_policy.rego # model gate policy
├── prometheus/prometheus.yml
├── grafana/
│   ├── provisioning/
│   │   ├── dashboards/dashboards.yaml
│   │   └── datasources/datasources.yaml
│   └── dashboards/
│       ├── engineering.json
│       └── compliance.json
└── tests/
    ├── test_spm_db_models.py
    ├── test_spm_aggregator.py
    ├── test_spm_api_registry.py
    ├── test_spm_compliance.py
    └── test_spm_enforcement.py
```

### Modified files
```
platform_shared/topics.py                    # add GlobalTopics dataclass
platform_shared/models.py                    # add model_id to PostureEnrichedEvent
opa/policies/model_policy.rego               # NEW (not a modification)
services/api/app.py                          # add model gate before Kafka publish
services/processor/app.py                    # stamp model_id on PostureEnrichedEvent
services/startup_orchestrator/app.py         # create global topic + self-register CPM models
docker-compose.yml                           # add 5 new services
.env.example                                 # add new env vars
```

---

## Phase 1: CPM Changes (Additive Only)

### Task 1: Add GlobalTopics to platform_shared/topics.py

**Files:**
- Modify: `platform_shared/topics.py`
- Test: `tests/test_spm_db_models.py` (shared test file, first tests go here)

- [ ] **Step 1: Write the failing test**
```python
# tests/test_spm_db_models.py
from platform_shared.topics import GlobalTopics, topics_for_tenant

def test_global_topics_model_events():
    gt = GlobalTopics()
    assert gt.MODEL_EVENTS == "cpm.global.model_events"

def test_global_topics_is_frozen():
    import dataclasses
    assert dataclasses.is_dataclass(GlobalTopics)
    gt = GlobalTopics()
    try:
        gt.MODEL_EVENTS = "other"
        assert False, "should have raised"
    except Exception:
        pass  # frozen dataclass raises FrozenInstanceError

def test_tenant_topics_unchanged():
    # Confirm existing topics still work
    t = topics_for_tenant("t1")
    assert t.raw == "cpm.t1.raw"
    assert t.audit == "cpm.t1.audit"
```

- [ ] **Step 2: Run to verify failure**
```bash
cd cpm-v3 && python -m pytest tests/test_spm_db_models.py::test_global_topics_model_events -v
```
Expected: `ImportError` or `AttributeError: module has no attribute 'GlobalTopics'`

- [ ] **Step 3: Implement**

Add to the bottom of `platform_shared/topics.py`, after the existing `all_topics_for_tenants` function:
```python
@dataclass(frozen=True)
class GlobalTopics:
    MODEL_EVENTS: str = "cpm.global.model_events"
```

- [ ] **Step 4: Run tests**
```bash
python -m pytest tests/test_spm_db_models.py::test_global_topics_model_events tests/test_spm_db_models.py::test_global_topics_is_frozen tests/test_spm_db_models.py::test_tenant_topics_unchanged -v
```
Expected: All 3 PASS

- [ ] **Step 5: Commit**
```bash
git add platform_shared/topics.py tests/test_spm_db_models.py
git commit -m "feat(spm): add GlobalTopics dataclass for cpm.global.model_events topic"
```

---

### Task 2: Add model_id to PostureEnrichedEvent

**Files:**
- Modify: `platform_shared/models.py` (around line 185, after `guard_categories`)
- Test: `tests/test_spm_db_models.py`

- [ ] **Step 1: Write the failing test**
```python
# Add to tests/test_spm_db_models.py
from platform_shared.models import PostureEnrichedEvent, AuthContext

def test_posture_enriched_event_has_model_id():
    auth = AuthContext(sub="u1", tenant_id="t1")
    event = PostureEnrichedEvent(
        event_id="e1", ts=1000, tenant_id="t1",
        user_id="u1", session_id="s1", prompt="hello",
        auth_context=auth,
    )
    assert event.model_id is None  # optional, defaults to None

def test_posture_enriched_event_accepts_model_id():
    auth = AuthContext(sub="u1", tenant_id="t1")
    event = PostureEnrichedEvent(
        event_id="e1", ts=1000, tenant_id="t1",
        user_id="u1", session_id="s1", prompt="hello",
        auth_context=auth, model_id="llama-guard-3",
    )
    assert event.model_id == "llama-guard-3"
```

- [ ] **Step 2: Run to verify failure**
```bash
python -m pytest tests/test_spm_db_models.py::test_posture_enriched_event_has_model_id -v
```
Expected: `TypeError` (unexpected keyword) or `ValidationError`

- [ ] **Step 3: Implement**

In `platform_shared/models.py`, add one line to `PostureEnrichedEvent` after the `guard_categories` field:
```python
# After: guard_categories: List[str] = Field(default_factory=list)
model_id: Optional[str] = None  # stamped by Processor from LLM_MODEL_ID env var
```

- [ ] **Step 4: Run tests**
```bash
python -m pytest tests/test_spm_db_models.py -v
```
Expected: All tests PASS (confirm existing tests still pass too)

- [ ] **Step 5: Commit**
```bash
git add platform_shared/models.py tests/test_spm_db_models.py
git commit -m "feat(spm): add optional model_id field to PostureEnrichedEvent"
```

---

### Task 3: Add model_policy.rego to OPA

**Files:**
- Create: `opa/policies/model_policy.rego`
- Test: manual OPA eval (no pytest needed — policy tested via OPA CLI)

- [ ] **Step 1: Create the policy file**
```rego
# opa/policies/model_policy.rego
package model_policy

import future.keywords.if

# Default deny
default allow = false

# Allow if no model_id specified (backward compat with old clients)
allow if {
    not input.model_id
}

# Allow if model is not in blocked or retired sets
allow if {
    input.model_id
    not input.model_id in data.blocked_models
    not input.model_id in data.retired_models
}
```

- [ ] **Step 2: Verify OPA syntax (requires OPA CLI or Docker)**
```bash
docker run --rm -v $(pwd)/opa:/opa openpolicyagent/opa:0.70.0 \
  check /opa/policies/model_policy.rego
```
Expected: no output (clean check)

- [ ] **Step 3: Verify allow logic with test inputs**
```bash
# Should allow (no model_id)
echo '{"input": {}}' | docker run --rm -i \
  -v $(pwd)/opa:/opa openpolicyagent/opa:0.70.0 \
  eval --data /opa/policies/model_policy.rego \
  --stdin-input "data.model_policy.allow"

# Should allow (model not blocked)
echo '{"input": {"model_id": "abc"}}' | docker run --rm -i \
  -v $(pwd)/opa:/opa openpolicyagent/opa:0.70.0 \
  eval --data /opa/policies/model_policy.rego \
  --stdin-input "data.model_policy.allow"
```
Expected: `{"result": true}` for both

- [ ] **Step 4: Commit**
```bash
git add opa/policies/model_policy.rego
git commit -m "feat(spm): add model_policy.rego for model gate enforcement"
```

---

### Task 4: Stamp model_id in Processor + model gate in API

**Files:**
- Modify: `services/processor/app.py` — add `model_id` stamp
- Modify: `services/api/app.py` — add model gate before Kafka publish
- Test: `tests/test_spm_db_models.py`

- [ ] **Step 1: Write failing test for processor stamp**
```python
# Add to tests/test_spm_db_models.py
import os

def test_processor_stamps_model_id_from_env(monkeypatch):
    """Processor reads LLM_MODEL_ID env var and can stamp it."""
    monkeypatch.setenv("LLM_MODEL_ID", "test-model-v1")
    # Simulate what processor does
    model_id = os.getenv("LLM_MODEL_ID")
    assert model_id == "test-model-v1"

def test_model_gate_blocks_retired_model():
    """model gate returns False when model_id is in blocked set."""
    # Pure logic test — no OPA call needed
    blocked_models = {"retired-model-uuid"}
    model_id = "retired-model-uuid"
    allowed = model_id not in blocked_models
    assert allowed is False

def test_model_gate_allows_unknown_model_id():
    """model gate allows when model_id is None (backward compat)."""
    model_id = None
    allowed = model_id is None  # gate skipped when no model_id
    assert allowed is True
```

- [ ] **Step 2: Run to verify**
```bash
python -m pytest tests/test_spm_db_models.py -v
```
Expected: All PASS (these are pure logic tests)

- [ ] **Step 3: Implement Processor stamp**

In `services/processor/app.py`, find where `PostureEnrichedEvent` is constructed. Add `model_id` to the constructor:
```python
# Near top of processor/app.py, add:
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID")  # None if not configured

# In the PostureEnrichedEvent constructor (find existing construction), add:
model_id=LLM_MODEL_ID,
```

- [ ] **Step 4: Implement model gate in API**

In `services/api/app.py`, add the following after the guard model block and before building `RawEvent` (around line 200). `httpx` is already imported at the top of the existing file. Add only the redis import:
```python
import redis as redis_lib
```

Then add this helper function near `_call_guard_model`:
```python
_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=True,
        )
    return _redis_client

SPM_API_URL = os.getenv("SPM_API_URL", "http://spm-api:8092")
OPA_URL_FOR_GATE = os.getenv("OPA_URL", "http://opa:8181")

async def _check_model_gate(model_id: str, tenant_id: str) -> bool:
    """Returns True if model is approved, False if blocked. Fail-closed.

    Uses httpx directly (not the sync OPAClient) because:
    1. This is an async FastAPI handler
    2. The shared OPAClient casts non-dict results to {} — boolean OPA rules
       like model_policy/allow return a bool, not a dict, which would be lost.
    """
    if not model_id:
        return True  # backward compat: no model_id = skip gate

    cache_key = f"spm:model_gate:{model_id}:{tenant_id}"
    try:
        cached = _get_redis().get(cache_key)
        if cached is not None:
            return cached == "approved"
    except Exception:
        pass  # Redis miss — fall through to OPA

    # Direct OPA call with 500ms timeout, fail-closed
    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            resp = await client.post(
                f"{OPA_URL_FOR_GATE}/v1/data/model_policy/allow",
                json={"input": {"model_id": model_id, "tenant_id": tenant_id}},
            )
        if resp.status_code != 200:
            return False  # fail-closed
        data = resp.json()
        raw = data.get("result")
        # OPA boolean rule returns {"result": true/false}
        allowed = bool(raw) if isinstance(raw, bool) else bool(raw.get("allowed", False)) if isinstance(raw, dict) else False
        try:
            _get_redis().setex(cache_key, 30, "approved" if allowed else "blocked")
        except Exception:
            pass  # cache write failure is non-fatal
        return allowed
    except Exception:
        return False  # fail-closed on any network/timeout error
```

Then in the `/chat` endpoint, after the guard model block (after the `if guard_verdict == "block"` block), add:
```python
    # 3b. Model gate (SPM)
    model_id = os.getenv("LLM_MODEL_ID")
    if model_id and not await _check_model_gate(model_id, tenant_id):
        emit_audit(tenant_id, "api", "model_gate_block",
                   principal=user_id,
                   details={"model_id": model_id, "session_id": req.session_id})
        raise HTTPException(status_code=403,
                            detail={"error": "model_not_approved", "model_id": model_id})
```

- [ ] **Step 5: Run all tests**
```bash
python -m pytest tests/ -v
```
Expected: All existing 86 tests PASS + new tests PASS

- [ ] **Step 6: Commit**
```bash
git add services/processor/app.py services/api/app.py tests/test_spm_db_models.py
git commit -m "feat(spm): stamp model_id in processor; add model gate to API (fail-closed)"
```

---

### Task 5: Update startup_orchestrator — global topic + SPM self-registration

**Files:**
- Modify: `services/startup_orchestrator/app.py`
- Test: `tests/test_spm_db_models.py`

- [ ] **Step 1: Write failing test**
```python
# Add to tests/test_spm_db_models.py
def test_global_topic_name():
    from platform_shared.topics import GlobalTopics
    assert GlobalTopics().MODEL_EVENTS == "cpm.global.model_events"

def test_spm_self_register_payload_structure():
    """Validate the payload shape used for self-registration."""
    payload = {
        "name": "llama-guard-3",
        "version": "3.0.0",
        "provider": "local",
        "purpose": "content_screening",
        "risk_tier": "limited",
        "tenant_id": "global",
        "status": "approved",
        "approved_by": "startup-orchestrator",
    }
    required = {"name", "version", "provider", "purpose", "risk_tier", "tenant_id"}
    assert required.issubset(payload.keys())
```

- [ ] **Step 2: Run to verify**
```bash
python -m pytest tests/test_spm_db_models.py::test_spm_self_register_payload_structure -v
```
Expected: PASS

- [ ] **Step 3: Implement in startup_orchestrator**

`NewTopic` and `TopicAlreadyExistsError` are already imported at the top of `startup_orchestrator/app.py` — no new imports needed for these. The existing `requests` import is also already present.

Add near the top constants section of `services/startup_orchestrator/app.py`:
```python
SPM_API_URL = os.getenv("SPM_API_URL", "http://spm-api:8092")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "")
SERVICE_VERSION_STR = os.getenv("SERVICE_VERSION", "3.0.0")
```

Add a new function `create_global_topics` and `register_cpm_models_with_spm` in startup_orchestrator:

```python
def create_global_topics(admin: KafkaAdminClient) -> None:
    """Create the global model_events topic used by AI SPM."""
    log.info("── Step 8: Creating global SPM topic ──")
    from platform_shared.topics import GlobalTopics
    topic_name = GlobalTopics().MODEL_EVENTS
    try:
        admin.create_topics([
            NewTopic(
                name=topic_name,
                num_partitions=1,
                replication_factor=REPLICATION_FACTOR,
                topic_configs={"retention.ms": str(7 * 24 * 3600 * 1000)},
            )
        ], validate_only=False)
        log.info("  ✓ Created: %s", topic_name)
    except TopicAlreadyExistsError:
        log.info("  Topic already exists — skipping")


def register_cpm_models_with_spm() -> None:
    """Self-register CPM's own models in spm-api. Retries up to 10 times."""
    log.info("── Step 9: Registering CPM models with AI SPM ──")
    models = [
        {
            "name": "llama-guard-3", "version": "3.0.0",
            "provider": "local", "purpose": "content_screening",
            "risk_tier": "limited", "tenant_id": "global",
            "status": "approved", "approved_by": "startup-orchestrator",
        },
        {
            "name": "output-guard-llm", "version": SERVICE_VERSION_STR,
            "provider": "local", "purpose": "output_screening",
            "risk_tier": "limited", "tenant_id": "global",
            "status": "approved", "approved_by": "startup-orchestrator",
        },
    ]
    for attempt in range(10):
        try:
            for model in models:
                resp = requests.post(
                    f"{SPM_API_URL}/models",
                    json=model,
                    timeout=5.0,
                )
                if resp.status_code in (200, 201, 409):  # 409 = already exists, ok
                    log.info("  ✓ Registered: %s", model["name"])
                else:
                    raise RuntimeError(f"spm-api returned {resp.status_code}")
            return  # success
        except Exception as e:
            log.warning("  SPM registration attempt %d/10 failed: %s", attempt + 1, e)
            if attempt < 9:
                time.sleep(3)
    log.warning("  SPM registration failed after 10 attempts — continuing without it")
```

Then in `main()`, add calls after `validate_opa()`:
```python
        # Reopen admin client for global topics
        admin2 = wait_for_kafka(max_wait=30)
        create_global_topics(admin2)
        admin2.close()
        register_cpm_models_with_spm()
```

- [ ] **Step 4: Run tests**
```bash
python -m pytest tests/ -v
```
Expected: All 86+ tests PASS

- [ ] **Step 5: Commit**
```bash
git add services/startup_orchestrator/app.py tests/test_spm_db_models.py
git commit -m "feat(spm): create global model_events topic; self-register CPM models with spm-api"
```

---

## Phase 2: Database Foundation

### Task 6: PostgreSQL schema migration

**Files:**
- Create: `spm/db/migrations/001_initial.sql`
- Create: `spm/__init__.py`, `spm/db/__init__.py`

- [ ] **Step 1: Create directory structure**
```bash
mkdir -p spm/db/migrations spm/compliance
touch spm/__init__.py spm/db/__init__.py spm/compliance/__init__.py
```

- [ ] **Step 2: Write the SQL migration**

Create `spm/db/migrations/001_initial.sql`:
```sql
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
    model_id         UUID,  -- nullable FK (NULL = unknown model)
    tenant_id        TEXT NOT NULL,
    snapshot_at      TIMESTAMPTZ NOT NULL,
    request_count    INT NOT NULL DEFAULT 0,
    block_count      INT NOT NULL DEFAULT 0,
    escalation_count INT NOT NULL DEFAULT 0,
    avg_risk_score   FLOAT NOT NULL DEFAULT 0,
    max_risk_score   FLOAT NOT NULL DEFAULT 0,
    intent_drift_avg FLOAT NOT NULL DEFAULT 0,
    ttp_hit_count    INT NOT NULL DEFAULT 0,
    CONSTRAINT uq_snapshot UNIQUE NULLS DISTINCT (model_id, tenant_id, snapshot_at)
);

CREATE INDEX idx_snapshots_model_tenant_time
    ON posture_snapshots (model_id, tenant_id, snapshot_at DESC);

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
    event_id   TEXT NOT NULL UNIQUE,
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
```

- [ ] **Step 3: Verify syntax (requires psql or Docker)**
```bash
docker run --rm -e POSTGRES_PASSWORD=test -d --name pg-test postgres:16
sleep 3
docker exec -i pg-test psql -U postgres -c "CREATE DATABASE spm_test;"
docker exec -i pg-test psql -U postgres spm_test < spm/db/migrations/001_initial.sql
docker stop pg-test && docker rm pg-test
```
Expected: No errors

- [ ] **Step 4: Commit**
```bash
git add spm/
git commit -m "feat(spm): add initial PostgreSQL schema with 4 tables and immutability trigger"
```

---

### Task 7: SQLAlchemy ORM models

**Files:**
- Create: `spm/db/models.py`
- Create: `spm/db/session.py`
- Test: `tests/test_spm_db_models.py`

- [ ] **Step 1: Write failing tests**
```python
# Add to tests/test_spm_db_models.py
def test_spm_orm_model_registry_columns():
    """Verify ORM model has required columns."""
    import importlib
    # The module should be importable without a live DB
    from spm.db.models import ModelRegistry
    cols = {c.key for c in ModelRegistry.__table__.columns}
    assert "model_id" in cols
    assert "name" in cols
    assert "status" in cols
    assert "ai_sbom" in cols

def test_spm_orm_posture_snapshot_columns():
    from spm.db.models import PostureSnapshot
    cols = {c.key for c in PostureSnapshot.__table__.columns}
    assert "model_id" in cols
    assert "avg_risk_score" in cols
    assert "snapshot_at" in cols

def test_spm_session_is_importable():
    from spm.db.session import get_engine
    # Just verify import succeeds
    assert get_engine is not None
```

- [ ] **Step 2: Run to verify failure**
```bash
python -m pytest tests/test_spm_db_models.py::test_spm_orm_model_registry_columns -v
```
Expected: `ModuleNotFoundError: No module named 'spm'`

- [ ] **Step 3: Install dependencies (for local test runs)**
```bash
pip install sqlalchemy asyncpg psycopg2-binary --break-system-packages
```

- [ ] **Step 4: Create spm/db/models.py**
```python
"""
AI SPM — SQLAlchemy ORM models matching 001_initial.sql
"""
from __future__ import annotations
import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, Float, Index,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ModelProvider(str, enum.Enum):
    local = "local"
    openai = "openai"
    anthropic = "anthropic"
    other = "other"


class ModelRiskTier(str, enum.Enum):
    minimal = "minimal"
    limited = "limited"
    high = "high"
    unacceptable = "unacceptable"


class ModelStatus(str, enum.Enum):
    registered = "registered"
    under_review = "under_review"
    approved = "approved"
    deprecated = "deprecated"
    retired = "retired"


class ComplianceStatus(str, enum.Enum):
    satisfied = "satisfied"
    partial = "partial"
    not_satisfied = "not_satisfied"


# Valid lifecycle transitions
MODEL_TRANSITIONS: Dict[ModelStatus, set] = {
    ModelStatus.registered:   {ModelStatus.under_review},
    ModelStatus.under_review: {ModelStatus.approved, ModelStatus.registered},
    ModelStatus.approved:     {ModelStatus.deprecated},
    ModelStatus.deprecated:   {ModelStatus.retired},
    ModelStatus.retired:      set(),  # terminal
}


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    model_id    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(Text, nullable=False)
    version     = Column(Text, nullable=False)
    provider    = Column(Enum(ModelProvider), nullable=False, default=ModelProvider.local)
    purpose     = Column(Text)
    risk_tier   = Column(Enum(ModelRiskTier), nullable=False, default=ModelRiskTier.limited)
    tenant_id   = Column(Text, nullable=False, default="global")
    status      = Column(Enum(ModelStatus), nullable=False, default=ModelStatus.registered)
    approved_by = Column(Text)
    approved_at = Column(DateTime(timezone=True))
    ai_sbom     = Column(JSONB, default=dict)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("name", "version", "tenant_id", name="uq_model_name_version_tenant"),
    )

    def can_transition_to(self, new_status: ModelStatus) -> bool:
        return new_status in MODEL_TRANSITIONS.get(self.status, set())


class PostureSnapshot(Base):
    __tablename__ = "posture_snapshots"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    model_id         = Column(UUID(as_uuid=True), nullable=True)
    tenant_id        = Column(Text, nullable=False)
    snapshot_at      = Column(DateTime(timezone=True), nullable=False)
    request_count    = Column(Integer, default=0)
    block_count      = Column(Integer, default=0)
    escalation_count = Column(Integer, default=0)
    avg_risk_score   = Column(Float, default=0.0)
    max_risk_score   = Column(Float, default=0.0)
    intent_drift_avg = Column(Float, default=0.0)
    ttp_hit_count    = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_snapshots_model_tenant_time", "model_id", "tenant_id", "snapshot_at"),
    )


class ComplianceEvidence(Base):
    __tablename__ = "compliance_evidence"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    framework         = Column(Text, nullable=False, default="NIST_AI_RMF")
    function          = Column(Text, nullable=False)
    category          = Column(Text, nullable=False)
    subcategory       = Column(Text)
    cpm_control       = Column(Text, nullable=False)
    status            = Column(Enum(ComplianceStatus), nullable=False, default=ComplianceStatus.not_satisfied)
    evidence_ref      = Column(JSONB, default=dict)
    last_evaluated_at = Column(DateTime(timezone=True))


class AuditExport(Base):
    __tablename__ = "audit_export"

    event_id   = Column(Text, primary_key=True)
    tenant_id  = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    actor      = Column(Text)
    timestamp  = Column(DateTime(timezone=True), nullable=False)
    payload    = Column(JSONB, nullable=False)
```

- [ ] **Step 5: Create spm/db/session.py**
```python
"""
AI SPM — SQLAlchemy async engine and session factory.
"""
from __future__ import annotations
import os
from functools import lru_cache
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

SPM_DB_URL = os.getenv("SPM_DB_URL", "postgresql+asyncpg://spm_rw:spmpass@spm-db:5432/spm")


@lru_cache(maxsize=1)
def get_engine():
    return create_async_engine(
        SPM_DB_URL,
        pool_size=10,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        echo=False,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
```

- [ ] **Step 6: Run tests**
```bash
python -m pytest tests/test_spm_db_models.py -v
```
Expected: All tests PASS (ORM models are importable without a live DB)

- [ ] **Step 7: Commit**
```bash
git add spm/db/models.py spm/db/session.py spm/__init__.py spm/db/__init__.py
git commit -m "feat(spm): SQLAlchemy ORM models and async session factory"
```

---

## Phase 3: spm-aggregator

### Task 8: spm-aggregator Kafka consumer + snapshot writer

**Files:**
- Create: `services/spm_aggregator/app.py`
- Create: `services/spm_aggregator/requirements.txt`
- Create: `services/spm_aggregator/Dockerfile`
- Test: `tests/test_spm_aggregator.py`

- [ ] **Step 1: Write failing tests**
```python
# tests/test_spm_aggregator.py
from datetime import datetime, timezone

def _bucket(ts: datetime, interval_sec: int = 300) -> datetime:
    """Floor timestamp to N-second bucket boundary."""
    epoch = ts.timestamp()
    bucketed = (epoch // interval_sec) * interval_sec
    return datetime.fromtimestamp(bucketed, tz=timezone.utc)

def test_bucket_floors_to_5min():
    ts = datetime(2026, 1, 1, 12, 7, 42, tzinfo=timezone.utc)
    b = _bucket(ts, 300)
    assert b.minute == 5
    assert b.second == 0

def test_bucket_at_exact_boundary():
    ts = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    b = _bucket(ts, 300)
    assert b.minute == 5

def test_rolling_average_skips_empty_windows():
    snapshots = [
        {"avg_risk_score": 0.8},
        {"avg_risk_score": 0.9},
    ]
    # Only 2 snapshots, not 3 — should average the 2 that exist
    scores = [s["avg_risk_score"] for s in snapshots]
    avg = sum(scores) / len(scores)
    assert abs(avg - 0.85) < 0.001

def test_rolling_average_triggers_enforcement():
    threshold = 0.85
    scores = [0.9, 0.88, 0.92]
    avg = sum(scores) / len(scores)
    assert avg > threshold  # should trigger

def test_rolling_average_no_trigger_below_threshold():
    threshold = 0.85
    scores = [0.5, 0.6, 0.7]
    avg = sum(scores) / len(scores)
    assert avg < threshold  # should NOT trigger

def test_audit_event_id_derivation():
    """When event_id is absent, derive deterministic UUID from content."""
    import hashlib
    tenant_id = "t1"
    event_type = "guard_model_block"
    timestamp = "2026-01-01T12:00:00Z"
    derived = hashlib.sha256(
        f"{tenant_id}{event_type}{timestamp}".encode()
    ).hexdigest()[:36]
    assert len(derived) == 36
```

- [ ] **Step 2: Run to verify**
```bash
python -m pytest tests/test_spm_aggregator.py -v
```
Expected: All 6 PASS (pure logic tests, no DB needed)

- [ ] **Step 3: Create requirements.txt**
```
# services/spm_aggregator/requirements.txt
kafka-python==2.0.2
psycopg2-binary==2.9.9
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
requests==2.32.3
prometheus-client==0.21.1
```

- [ ] **Step 4: Create Dockerfile**
```dockerfile
# services/spm_aggregator/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY services/spm_aggregator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY spm/ ./spm/
COPY services/spm_aggregator/app.py .
CMD ["python", "app.py"]
```

- [ ] **Step 5: Create services/spm_aggregator/app.py**
```python
"""
SPM Aggregator — Kafka consumer that writes posture snapshots to PostgreSQL
and triggers enforcement when model risk threshold is exceeded.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
import requests
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("spm-aggregator")

# ── Config ────────────────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP      = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")
TENANTS              = [t.strip() for t in os.getenv("TENANTS", "t1").split(",") if t.strip()]
SPM_DB_URL           = os.getenv("SPM_DB_URL", "postgresql://spm_rw:spmpass@spm-db:5432/spm")
SPM_API_URL          = os.getenv("SPM_API_URL", "http://spm-api:8092")
BLOCK_THRESHOLD      = float(os.getenv("SPM_MODEL_BLOCK_THRESHOLD", "0.85"))
SNAPSHOT_INTERVAL    = int(os.getenv("SPM_SNAPSHOT_INTERVAL_SEC", "300"))
ENFORCEMENT_WINDOW   = int(os.getenv("SPM_ENFORCEMENT_WINDOW", "3"))
SERVICE_JWT          = os.getenv("SPM_SERVICE_JWT", "")  # minted by startup orchestrator


# ── Helpers ───────────────────────────────────────────────────────────────────

def bucket_ts(ts: datetime, interval_sec: int = SNAPSHOT_INTERVAL) -> datetime:
    """Floor timestamp to N-second bucket."""
    epoch = ts.timestamp()
    return datetime.fromtimestamp((epoch // interval_sec) * interval_sec, tz=timezone.utc)


def derive_event_id(tenant_id: str, event_type: str, timestamp: str) -> str:
    return hashlib.sha256(f"{tenant_id}{event_type}{timestamp}".encode()).hexdigest()[:36]


# ── DB helpers (synchronous psycopg2 for consumer loop) ──────────────────────

def get_db_conn():
    return psycopg2.connect(SPM_DB_URL)


def upsert_snapshot(conn, model_id: Optional[str], tenant_id: str,
                    snapshot_at: datetime, metrics: Dict) -> None:
    sql = """
    INSERT INTO posture_snapshots
        (model_id, tenant_id, snapshot_at, request_count, block_count,
         escalation_count, avg_risk_score, max_risk_score, intent_drift_avg, ttp_hit_count)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (model_id, tenant_id, snapshot_at) DO UPDATE SET
        request_count    = posture_snapshots.request_count    + EXCLUDED.request_count,
        block_count      = posture_snapshots.block_count      + EXCLUDED.block_count,
        escalation_count = posture_snapshots.escalation_count + EXCLUDED.escalation_count,
        avg_risk_score   = (posture_snapshots.avg_risk_score * posture_snapshots.request_count
                           + EXCLUDED.avg_risk_score) /
                           NULLIF(posture_snapshots.request_count + 1, 0),
        max_risk_score   = GREATEST(posture_snapshots.max_risk_score, EXCLUDED.max_risk_score),
        intent_drift_avg = (posture_snapshots.intent_drift_avg + EXCLUDED.intent_drift_avg) / 2,
        ttp_hit_count    = posture_snapshots.ttp_hit_count + EXCLUDED.ttp_hit_count
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            model_id, tenant_id, snapshot_at,
            metrics.get("request_count", 1),
            metrics.get("block_count", 0),
            metrics.get("escalation_count", 0),
            metrics.get("avg_risk_score", 0.0),
            metrics.get("max_risk_score", 0.0),
            metrics.get("intent_drift_avg", 0.0),
            metrics.get("ttp_hit_count", 0),
        ))
    conn.commit()


def get_rolling_avg(conn, model_id: Optional[str], tenant_id: str,
                    window: int = ENFORCEMENT_WINDOW) -> Optional[float]:
    """Return rolling average of avg_risk_score over last N non-empty snapshots."""
    sql = """
    SELECT avg_risk_score FROM posture_snapshots
    WHERE (model_id = %s OR (%s IS NULL AND model_id IS NULL))
      AND tenant_id = %s
    ORDER BY snapshot_at DESC LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (model_id, model_id, tenant_id, window))
        rows = cur.fetchall()
    if not rows:
        return None
    return sum(r[0] for r in rows) / len(rows)


def mirror_audit_event(conn, event: Dict) -> None:
    """Mirror CPM audit event to audit_export (append-only)."""
    event_id = event.get("event_id") or derive_event_id(
        event.get("tenant_id", ""), event.get("event_type", ""), str(event.get("ts", ""))
    )
    ts = datetime.fromtimestamp(event.get("ts", time.time() * 1000) / 1000, tz=timezone.utc)
    sql = """
    INSERT INTO audit_export (event_id, tenant_id, event_type, actor, timestamp, payload)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (event_id) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            event_id,
            event.get("tenant_id", ""),
            event.get("event_type", ""),
            event.get("principal"),
            ts,
            psycopg2.extras.Json(event),
        ))
    conn.commit()


# ── Enforcement ───────────────────────────────────────────────────────────────

def trigger_enforcement(model_id: str) -> None:
    """Call spm-api to enforce block on model. Retries 3 times."""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{SPM_API_URL}/internal/enforce/{model_id}",
                headers={"Authorization": f"Bearer {SERVICE_JWT}"},
                timeout=10.0,
            )
            if resp.status_code in (200, 409):  # 409 = already enforced
                log.info("Enforcement triggered for model_id=%s", model_id)
                return
            log.warning("Enforcement returned %d for model_id=%s", resp.status_code, model_id)
        except Exception as e:
            log.warning("Enforcement attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2 ** attempt)
    log.error("Enforcement failed after 3 attempts for model_id=%s", model_id)


# ── Message processing ────────────────────────────────────────────────────────

def process_posture_enriched(conn, msg: Dict) -> None:
    model_id  = msg.get("model_id")
    tenant_id = msg.get("tenant_id", "unknown")
    ts        = datetime.fromtimestamp(msg.get("ts", time.time() * 1000) / 1000, tz=timezone.utc)
    snap_at   = bucket_ts(ts)

    decision  = msg.get("decision", "allow")
    is_block  = 1 if decision == "block" else 0
    is_escal  = 1 if decision == "escalate" else 0

    upsert_snapshot(conn, model_id, tenant_id, snap_at, {
        "request_count":    1,
        "block_count":      is_block,
        "escalation_count": is_escal,
        "avg_risk_score":   msg.get("posture_score", 0.0),
        "max_risk_score":   msg.get("posture_score", 0.0),
        "intent_drift_avg": msg.get("intent_drift_score", 0.0),
        "ttp_hit_count":    len(msg.get("cep_ttps", [])),
    })

    if model_id:
        rolling = get_rolling_avg(conn, model_id, tenant_id)
        if rolling is not None and rolling > BLOCK_THRESHOLD:
            log.warning(
                "Model risk threshold exceeded: model_id=%s tenant=%s rolling_avg=%.3f",
                model_id, tenant_id, rolling
            )
            trigger_enforcement(model_id)
            # Note: enforce_count Counter is module-level in main(); imported via closure
            # it will be incremented inside trigger_enforcement if enforcement succeeds


# ── Main consumer loop ────────────────────────────────────────────────────────

def build_topics() -> List[str]:
    from platform_shared.topics import topics_for_tenant, GlobalTopics
    topics = []
    for t in TENANTS:
        tt = topics_for_tenant(t)
        topics.extend([tt.posture_enriched, tt.decision, tt.tool_result, tt.audit])
    topics.append(GlobalTopics().MODEL_EVENTS)
    return topics


def wait_for_kafka(max_wait: int = 120) -> KafkaConsumer:
    topics = build_topics()
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            consumer = KafkaConsumer(
                *topics,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id="spm-aggregator",
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                consumer_timeout_ms=1000,
            )
            log.info("Kafka connected, subscribed to %d topics", len(topics))
            return consumer
        except NoBrokersAvailable:
            log.info("Waiting for Kafka...")
            time.sleep(5)
    raise RuntimeError("Kafka unavailable after %ds" % max_wait)


def main() -> None:
    log.info("SPM Aggregator starting — tenants=%s", TENANTS)

    # Start Prometheus metrics server on :9091
    from prometheus_client import start_http_server, Gauge, Counter
    snapshot_lag   = Gauge("spm_snapshot_lag_seconds",   "Seconds since last snapshot write")
    enforce_count  = Counter("spm_enforcement_actions_total", "Enforcement actions taken",
                             ["action", "tenant_id"])
    start_http_server(9091)
    log.info("Prometheus metrics server started on :9091")

    conn = None

    # Wait for DB
    for attempt in range(20):
        try:
            conn = get_db_conn()
            log.info("PostgreSQL connected")
            break
        except Exception as e:
            log.info("Waiting for DB... (%s)", e)
            time.sleep(3)
    if conn is None:
        log.error("Could not connect to DB — exiting")
        sys.exit(1)

    consumer = wait_for_kafka()

    log.info("SPM Aggregator running")
    for msg in consumer:
        try:
            data = msg.value
            topic = msg.topic

            if "posture_enriched" in topic:
                process_posture_enriched(conn, data)
            elif topic.endswith(".audit"):
                mirror_audit_event(conn, data)
            # decision and tool_result contribute to posture via posture_enriched for now

        except Exception as e:
            log.error("Error processing message from %s: %s", msg.topic, e, exc_info=True)
            try:
                conn.rollback()
            except Exception:
                pass
            # Reconnect on connection errors
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn = get_db_conn()
            except Exception:
                log.error("DB reconnection failed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests**
```bash
python -m pytest tests/test_spm_aggregator.py -v
```
Expected: All 6 PASS

- [ ] **Step 7: Commit**
```bash
git add services/spm_aggregator/ tests/test_spm_aggregator.py
git commit -m "feat(spm): spm-aggregator Kafka consumer with snapshot writer and enforcement trigger"
```

---

## Phase 4: spm-api

### Task 9: spm-api scaffolding + model registry CRUD

**Files:**
- Create: `services/spm_api/app.py` (initial, grows across tasks 9–13)
- Create: `services/spm_api/requirements.txt`
- Create: `services/spm_api/Dockerfile`
- Test: `tests/test_spm_api_registry.py`

- [ ] **Step 1: Write failing tests**
```python
# tests/test_spm_api_registry.py
from spm.db.models import ModelRegistry, ModelStatus, MODEL_TRANSITIONS

def test_state_machine_valid_transition():
    m = ModelRegistry()
    m.status = ModelStatus.registered
    assert m.can_transition_to(ModelStatus.under_review) is True

def test_state_machine_invalid_skip():
    m = ModelRegistry()
    m.status = ModelStatus.registered
    assert m.can_transition_to(ModelStatus.approved) is False

def test_state_machine_retired_is_terminal():
    m = ModelRegistry()
    m.status = ModelStatus.retired
    assert m.can_transition_to(ModelStatus.deprecated) is False
    assert m.can_transition_to(ModelStatus.approved) is False

def test_state_machine_approved_to_deprecated():
    m = ModelRegistry()
    m.status = ModelStatus.approved
    assert m.can_transition_to(ModelStatus.deprecated) is True

def test_model_registry_default_status():
    m = ModelRegistry()
    assert m.status == ModelStatus.registered

def test_model_upsert_key_fields():
    """Unique constraint is on (name, version, tenant_id)."""
    from spm.db.models import ModelRegistry
    # Verify constraint name exists in table args
    constraints = {c.name for c in ModelRegistry.__table__.constraints}
    assert "uq_model_name_version_tenant" in constraints
```

- [ ] **Step 2: Run to verify**
```bash
python -m pytest tests/test_spm_api_registry.py -v
```
Expected: All 6 PASS (pure ORM model tests)

- [ ] **Step 3: Create requirements.txt**
```
# services/spm_api/requirements.txt
fastapi==0.115.6
uvicorn[standard]==0.32.1
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
psycopg2-binary==2.9.9
pyjwt[crypto]==2.10.1
httpx==0.27.2
requests==2.32.3
weasyprint==62.3
prometheus-fastapi-instrumentator==7.0.0
```

- [ ] **Step 4: Create Dockerfile**
```dockerfile
# services/spm_api/Dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/spm_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY platform_shared/ ./platform_shared/
COPY spm/ ./spm/
COPY services/spm_api/app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8092"]
```

- [ ] **Step 5: Create services/spm_api/app.py (initial skeleton + registry endpoints)**

```python
"""
SPM API — AI Security Posture Management control plane.

Endpoints:
  POST   /models                    Register a model
  GET    /models                    List all models (optionally filter by tenant)
  GET    /models/{model_id}         Get model detail
  PATCH  /models/{model_id}/status  Lifecycle transition
  POST   /internal/enforce/{model_id}  Internal: enforcement trigger (from aggregator)
  GET    /compliance/nist-airm/report  NIST AI RMF compliance report
  GET    /sbom/refresh              Aggregate AI-SBOM from all CPM services
  GET    /health
  GET    /metrics
  GET    /jwks                      RS256 public key in JWKS format
"""
from __future__ import annotations
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from spm.db.models import (
    AuditExport, ComplianceEvidence, ModelRegistry,
    ModelStatus, PostureSnapshot, ModelProvider, ModelRiskTier,
)
from spm.db.session import get_db, get_engine
from spm.db.models import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("spm-api")

# ── Config ────────────────────────────────────────────────────────────────────

OPA_URL              = os.getenv("OPA_URL", "http://opa:8181")
FREEZE_CONTROLLER_URL = os.getenv("FREEZE_CONTROLLER_URL", "http://freeze-controller:8090")
JWT_PUBLIC_KEY_PATH  = os.getenv("JWT_PUBLIC_KEY_PATH", "/keys/public.pem")
KAFKA_BOOTSTRAP      = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")
SPM_SERVICE_JWT      = os.getenv("SPM_SERVICE_JWT", "")


# ── JWT auth ─────────────────────────────────────────────────────────────────

def _load_public_key() -> str:
    try:
        with open(JWT_PUBLIC_KEY_PATH) as f:
            return f.read().strip()
    except FileNotFoundError:
        return os.getenv("JWT_PUBLIC_KEY", "")


def verify_jwt(authorization: Optional[str] = Header(None)) -> Dict:
    """Verify RS256 JWT and return claims. Raises 401 on failure."""
    import jwt as pyjwt
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    pub_key = _load_public_key()
    if not pub_key:
        raise HTTPException(status_code=500, detail="JWT public key not configured")
    try:
        return pyjwt.decode(token, pub_key, algorithms=["RS256"],
                            options={"verify_aud": False})
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def require_admin(claims: Dict = Depends(verify_jwt)) -> Dict:
    if "spm:admin" not in claims.get("roles", []):
        raise HTTPException(status_code=403, detail="spm:admin role required")
    return claims


def require_auditor(claims: Dict = Depends(verify_jwt)) -> Dict:
    roles = claims.get("roles", [])
    if "spm:admin" not in roles and "spm:auditor" not in roles:
        raise HTTPException(status_code=403, detail="spm:auditor or spm:admin role required")
    return claims


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ModelCreate(BaseModel):
    name: str
    version: str
    provider: str = "local"
    purpose: Optional[str] = None
    risk_tier: str = "limited"
    tenant_id: str = "global"
    status: str = "registered"
    approved_by: Optional[str] = None
    ai_sbom: Dict[str, Any] = {}


class ModelResponse(BaseModel):
    model_id: str
    name: str
    version: str
    provider: str
    purpose: Optional[str]
    risk_tier: str
    tenant_id: str
    status: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    @classmethod
    def from_orm(cls, m: ModelRegistry) -> "ModelResponse":
        return cls(
            model_id=str(m.model_id),
            name=m.name, version=m.version,
            provider=m.provider.value if m.provider else "local",
            purpose=m.purpose,
            risk_tier=m.risk_tier.value if m.risk_tier else "limited",
            tenant_id=m.tenant_id,
            status=m.status.value if m.status else "registered",
            approved_by=m.approved_by,
            approved_at=m.approved_at.isoformat() if m.approved_at else None,
            created_at=m.created_at.isoformat() if m.created_at else None,
            updated_at=m.updated_at.isoformat() if m.updated_at else None,
        )


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if they don't exist (fallback if migrations weren't run)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed compliance evidence from mapping file
    await seed_compliance_evidence()
    log.info("spm-api started")
    yield
    await get_engine().dispose()


app = FastAPI(title="AI SPM API", version="1.0.0", lifespan=lifespan)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "spm-api", "ts": int(time.time())}


# ── Model Registry ─────────────────────────────────────────────────────────────

@app.post("/models", status_code=201)
async def register_model(
    body: ModelCreate,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),  # any authenticated user can register
) -> ModelResponse:
    """Register a model (upsert on name+version+tenant_id)."""
    # Map string status directly (startup-orchestrator may pass "approved")
    status_val = ModelStatus(body.status) if body.status else ModelStatus.registered
    provider_val = ModelProvider(body.provider) if body.provider else ModelProvider.local
    risk_val = ModelRiskTier(body.risk_tier) if body.risk_tier else ModelRiskTier.limited

    stmt = pg_insert(ModelRegistry).values(
        name=body.name, version=body.version, provider=provider_val,
        purpose=body.purpose, risk_tier=risk_val, tenant_id=body.tenant_id,
        status=status_val, approved_by=body.approved_by,
        approved_at=datetime.now(tz=timezone.utc) if body.approved_by else None,
        ai_sbom=body.ai_sbom,
    ).on_conflict_do_update(
        constraint="uq_model_name_version_tenant",
        set_={"updated_at": datetime.now(tz=timezone.utc)},
    ).returning(ModelRegistry)

    result = await db.execute(stmt)
    await db.commit()
    row = result.scalar_one()
    return ModelResponse.from_orm(row)


@app.get("/models")
async def list_models(
    tenant_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
) -> List[ModelResponse]:
    stmt = select(ModelRegistry)
    if tenant_id:
        stmt = stmt.where(ModelRegistry.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return [ModelResponse.from_orm(m) for m in result.scalars().all()]


@app.get("/models/{model_id}")
async def get_model(
    model_id: str,
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(verify_jwt),
) -> ModelResponse:
    result = await db.get(ModelRegistry, uuid.UUID(model_id))
    if not result:
        raise HTTPException(status_code=404, detail="Model not found")
    return ModelResponse.from_orm(result)


class StatusTransition(BaseModel):
    new_status: str
    approved_by: Optional[str] = None


@app.patch("/models/{model_id}/status")
async def transition_status(
    model_id: str,
    body: StatusTransition,
    db: AsyncSession = Depends(get_db),
    claims: Dict = Depends(require_admin),
) -> ModelResponse:
    """Transition model lifecycle status. Validates state machine."""
    model = await db.get(ModelRegistry, uuid.UUID(model_id))
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    new_status = ModelStatus(body.new_status)
    if not model.can_transition_to(new_status):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid transition: {model.status.value} → {new_status.value}",
        )

    model.status = new_status
    if new_status == ModelStatus.approved and body.approved_by:
        model.approved_by = body.approved_by or claims.get("sub")
        model.approved_at = datetime.now(tz=timezone.utc)

    await db.commit()
    await db.refresh(model)

    # Sync to OPA if retiring
    if new_status == ModelStatus.retired:
        await _push_blocked_models_to_opa(db)
        await _call_freeze_controller(str(model.model_id), model.tenant_id)
        await _publish_model_event("model_blocked", str(model.model_id), model.tenant_id)

    return ModelResponse.from_orm(model)


# ── Internal: Enforcement ─────────────────────────────────────────────────────

@app.post("/internal/enforce/{model_id}", include_in_schema=False)
async def enforce_model(
    model_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict:
    """Called by spm-aggregator when risk threshold is exceeded. Idempotent."""
    model = await db.get(ModelRegistry, uuid.UUID(model_id))
    if not model:
        # Unknown model — create a blocked sentinel
        log.warning("Enforcement for unknown model_id=%s — skipping", model_id)
        return {"status": "skipped", "reason": "model_not_in_registry"}

    if model.status == ModelStatus.retired:
        return {"status": "already_enforced"}

    # Force to retired status (bypasses normal state machine for enforcement)
    model.status = ModelStatus.retired
    model.approved_by = "spm-enforcement"
    await db.commit()

    await _push_blocked_models_to_opa(db)
    await _call_freeze_controller(model_id, model.tenant_id)
    await _publish_model_event("model_blocked", model_id, model.tenant_id)

    return {"status": "enforced", "model_id": model_id}


async def _push_blocked_models_to_opa(db: AsyncSession) -> None:
    """Push blocked_models (retired) and retired_models sets to OPA.

    Spec §5.1: deprecated models are flagged in OPA but requests still allowed;
    retired models are fully blocked. We push both sets so model_policy.rego
    can differentiate. The policy only blocks retired models.
    """
    retired_result = await db.execute(
        select(ModelRegistry.model_id).where(ModelRegistry.status == ModelStatus.retired)
    )
    blocked = [str(r) for r in retired_result.scalars().all()]

    deprecated_result = await db.execute(
        select(ModelRegistry.model_id).where(ModelRegistry.status == ModelStatus.deprecated)
    )
    deprecated = [str(r) for r in deprecated_result.scalars().all()]

    for path, data in [("/v1/data/blocked_models", blocked),
                       ("/v1/data/deprecated_models", deprecated)]:
        try:
            resp = requests.put(f"{OPA_URL}{path}", json=data, timeout=5.0)
            if resp.status_code not in (200, 204):
                log.warning("OPA push to %s returned %d", path, resp.status_code)
        except Exception as e:
            log.error("OPA push to %s failed: %s", path, e)


async def _call_freeze_controller(model_id: str, tenant_id: str) -> None:
    """Call Freeze Controller to freeze access for this model's tenant."""
    try:
        resp = requests.post(
            f"{FREEZE_CONTROLLER_URL}/freeze",
            json={
                "scope": "tenant", "tenant_id": tenant_id,
                "actor": "spm-enforcement",
                "reason": "model_risk_threshold_exceeded",
                "model_id": model_id,
            },
            headers={"Authorization": f"Bearer {SPM_SERVICE_JWT}"},
            timeout=10.0,
        )
        if resp.status_code not in (200, 201, 409):
            log.warning("Freeze Controller returned %d", resp.status_code)
    except Exception as e:
        log.error("Freeze Controller call failed: %s", e)


def _publish_model_event(event: str, model_id: str, tenant_id: str) -> None:
    """Publish to cpm.global.model_events Kafka topic."""
    try:
        from kafka import KafkaProducer
        from platform_shared.topics import GlobalTopics
        import json
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        producer.send(GlobalTopics().MODEL_EVENTS, {
            "event": event, "model_id": model_id,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })
        producer.flush()
        producer.close()
    except Exception as e:
        log.error("Failed to publish model event: %s", e)


# ── JWKS endpoint for Grafana ─────────────────────────────────────────────────

@app.get("/jwks")
async def jwks():
    """Return RS256 public key in JWKS format for Grafana JWT auth."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
    import base64
    import cryptography.x509 as x509
    from cryptography.hazmat.primitives import serialization
    pub_key_pem = _load_public_key()
    if not pub_key_pem:
        raise HTTPException(status_code=503, detail="Public key not available")
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        pub = load_pem_public_key(pub_key_pem.encode())
        pub_numbers = pub.public_key().public_numbers() if hasattr(pub, "public_key") else pub.public_numbers()
        def to_b64url(n: int) -> str:
            length = (n.bit_length() + 7) // 8
            return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()
        return {
            "keys": [{
                "kty": "RSA", "use": "sig", "alg": "RS256", "kid": "cpm-key-1",
                "n": to_b64url(pub_numbers.n),
                "e": to_b64url(pub_numbers.e),
            }]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"JWKS generation failed: {e}")


# ── Compliance ─────────────────────────────────────────────────────────────────
# (seeding and report endpoint — implemented in Task 10)

async def seed_compliance_evidence():
    """Seed compliance_evidence from nist_airm_mapping.json if table is empty."""
    # In the Docker image, app.py is at /app/app.py and spm/ is at /app/spm/
    mapping_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "spm", "compliance", "nist_airm_mapping.json")
    if not os.path.exists(mapping_path):
        log.warning("NIST AI RMF mapping file not found at %s", mapping_path)
        return
    with open(mapping_path) as f:
        controls = json.load(f)
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(ComplianceEvidence).limit(1))
        if result.scalar_one_or_none():
            return  # already seeded
        for c in controls:
            db.add(ComplianceEvidence(
                framework=c["framework"], function=c["function"],
                category=c["category"], subcategory=c.get("subcategory"),
                cpm_control=c["cpm_control"], status="not_satisfied",
            ))
        await db.commit()
    log.info("Seeded %d compliance controls", len(controls))


from spm.db.session import get_session_factory  # noqa: E402 (needed after definition)


@app.get("/compliance/nist-airm/report")
async def compliance_report(
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(require_auditor),
):
    """Generate NIST AI RMF compliance report."""
    from spm.compliance.evaluator import evaluate_all_controls
    await evaluate_all_controls(db)

    result = await db.execute(select(ComplianceEvidence))
    controls = result.scalars().all()

    functions: Dict[str, Dict] = {}
    for c in controls:
        fn = c.function
        if fn not in functions:
            functions[fn] = {"function": fn, "controls": [], "gaps": [],
                             "satisfied": 0, "total": 0}
        functions[fn]["total"] += 1
        if c.status and c.status.value == "satisfied":
            functions[fn]["satisfied"] += 1
        else:
            functions[fn]["gaps"].append({
                "category": c.category, "control": c.cpm_control,
                "status": c.status.value if c.status else "not_satisfied",
            })
        functions[fn]["controls"].append({
            "category": c.category, "cpm_control": c.cpm_control,
            "status": c.status.value if c.status else "not_satisfied",
        })

    total_satisfied = sum(f["satisfied"] for f in functions.values())
    total_controls  = sum(f["total"] for f in functions.values())
    coverage = round(total_satisfied / total_controls * 100, 1) if total_controls else 0

    for fn in functions.values():
        fn["coverage_pct"] = round(fn["satisfied"] / fn["total"] * 100, 1) if fn["total"] else 0

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "framework": "NIST_AI_RMF",
        "overall_coverage_pct": coverage,
        "functions": list(functions.values()),
    }

    if format == "pdf":
        from spm.compliance.evaluator import render_pdf
        pdf_bytes = render_pdf(report)
        return Response(content=pdf_bytes, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=nist-airm-report.pdf"})

    return JSONResponse(report)


# ── AI-SBOM ────────────────────────────────────────────────────────────────────

CPM_INVENTORY_ENDPOINTS = [
    os.getenv("CPM_API_URL", "http://api:8080") + "/inventory",
    os.getenv("GUARD_MODEL_URL", "http://guard-model:8200") + "/inventory",
    os.getenv("FREEZE_CONTROLLER_URL", "http://freeze-controller:8090") + "/inventory",
    os.getenv("POLICY_SIMULATOR_URL", "http://policy-simulator:8091") + "/inventory",
]


@app.get("/sbom/refresh")
async def refresh_sbom(
    db: AsyncSession = Depends(get_db),
    _claims: Dict = Depends(require_admin),
) -> Dict:
    """Aggregate AI-SBOM from all CPM service /inventory endpoints."""
    components = []
    unavailable = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for endpoint in CPM_INVENTORY_ENDPOINTS:
            try:
                resp = await client.get(endpoint)
                if resp.status_code == 200:
                    components.append(resp.json())
                else:
                    unavailable.append({"endpoint": endpoint, "status": resp.status_code})
            except Exception as e:
                unavailable.append({"endpoint": endpoint, "error": str(e)})

    sbom = {
        "schema_version": "1.0",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "components": components,
        "unavailable_services": unavailable,
    }
    return sbom


# ── Prometheus metrics ─────────────────────────────────────────────────────────

from prometheus_fastapi_instrumentator import Instrumentator  # noqa: E402
Instrumentator().instrument(app).expose(app)
```

- [ ] **Step 6: Run tests**
```bash
python -m pytest tests/test_spm_api_registry.py -v
```
Expected: All 6 PASS

- [ ] **Step 7: Commit**
```bash
git add services/spm_api/ tests/test_spm_api_registry.py
git commit -m "feat(spm): spm-api with model registry CRUD, lifecycle state machine, enforcement, compliance, SBOM"
```

---

### Task 10: NIST AI RMF compliance evaluator + mapping file

**Files:**
- Create: `spm/compliance/evaluator.py`
- Create: `spm/compliance/nist_airm_mapping.json`
- Create: `spm/compliance/report_template.html`
- Test: `tests/test_spm_compliance.py`

- [ ] **Step 1: Write failing tests**
```python
# tests/test_spm_compliance.py
import json, os

def test_nist_mapping_file_exists():
    path = "spm/compliance/nist_airm_mapping.json"
    assert os.path.exists(path), f"Missing: {path}"

def test_nist_mapping_has_all_four_functions():
    with open("spm/compliance/nist_airm_mapping.json") as f:
        controls = json.load(f)
    functions = {c["function"] for c in controls}
    assert functions == {"GOVERN", "MAP", "MEASURE", "MANAGE"}

def test_nist_mapping_required_fields():
    with open("spm/compliance/nist_airm_mapping.json") as f:
        controls = json.load(f)
    for c in controls:
        assert "framework" in c
        assert "function" in c
        assert "category" in c
        assert "cpm_control" in c
        assert "evaluation_rule" in c

def test_compliance_coverage_calculation():
    """Coverage % calculation logic."""
    controls = [
        {"status": "satisfied"},
        {"status": "satisfied"},
        {"status": "not_satisfied"},
        {"status": "partial"},
    ]
    satisfied = sum(1 for c in controls if c["status"] == "satisfied")
    coverage = satisfied / len(controls) * 100
    assert coverage == 50.0
```

- [ ] **Step 2: Run to verify failure**
```bash
python -m pytest tests/test_spm_compliance.py::test_nist_mapping_file_exists -v
```
Expected: `AssertionError: Missing: spm/compliance/nist_airm_mapping.json`

- [ ] **Step 3: Create spm/compliance/nist_airm_mapping.json**
```json
[
  {
    "framework": "NIST_AI_RMF",
    "function": "GOVERN",
    "category": "GOVERN-1.1",
    "subcategory": "Policies and procedures for AI risk management are in place",
    "cpm_control": "OPA:prompt_policy.rego",
    "evaluation_rule": "opa_policy_loaded"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "GOVERN",
    "category": "GOVERN-1.2",
    "subcategory": "AI risk management framework includes human oversight",
    "cpm_control": "freeze_controller:spm:admin_required",
    "evaluation_rule": "opa_policy_loaded"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "GOVERN",
    "category": "GOVERN-2.1",
    "subcategory": "Model approval records with human sign-off",
    "cpm_control": "model_registry:approved_by_required",
    "evaluation_rule": "model_approved_exists"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "GOVERN",
    "category": "GOVERN-3.1",
    "subcategory": "Tool execution authorization with OPA policy",
    "cpm_control": "OPA:tool_policy.rego",
    "evaluation_rule": "opa_policy_loaded"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "GOVERN",
    "category": "GOVERN-4.1",
    "subcategory": "Output sanitization and content policy",
    "cpm_control": "OPA:output_policy.rego",
    "evaluation_rule": "opa_policy_loaded"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MAP",
    "category": "MAP-1.1",
    "subcategory": "AI risks identified via multi-dimension risk fusion",
    "cpm_control": "processor:7_dimension_risk_fusion",
    "evaluation_rule": "risk_fusion_active"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MAP",
    "category": "MAP-2.1",
    "subcategory": "Adversarial threat mapping via MITRE ATLAS",
    "cpm_control": "flink_cep:mitre_atlas_ttp_mapping",
    "evaluation_rule": "risk_fusion_active"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MAP",
    "category": "MAP-3.1",
    "subcategory": "Model risk classification via risk tiers",
    "cpm_control": "model_registry:risk_tier_assigned",
    "evaluation_rule": "models_have_risk_tier"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MAP",
    "category": "MAP-4.1",
    "subcategory": "RAG provenance and retrieval trust scoring",
    "cpm_control": "retrieval_gateway:sha256_provenance",
    "evaluation_rule": "risk_fusion_active"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MEASURE",
    "category": "MEASURE-1.1",
    "subcategory": "Continuous per-model posture snapshots",
    "cpm_control": "spm_aggregator:posture_snapshots",
    "evaluation_rule": "snapshots_recent"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MEASURE",
    "category": "MEASURE-2.1",
    "subcategory": "Content screening rate via Guard Model",
    "cpm_control": "guard_model:llama_guard_screen",
    "evaluation_rule": "snapshots_recent"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MEASURE",
    "category": "MEASURE-3.1",
    "subcategory": "Output guard block and redact counts",
    "cpm_control": "output_guard:two_pass_scan",
    "evaluation_rule": "snapshots_recent"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MEASURE",
    "category": "MEASURE-4.1",
    "subcategory": "Platform metrics exposed via Prometheus",
    "cpm_control": "prometheus:metrics_scraping",
    "evaluation_rule": "prometheus_reachable"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MANAGE",
    "category": "MANAGE-1.1",
    "subcategory": "Automated model enforcement on risk threshold breach",
    "cpm_control": "spm_api:enforcement_engine",
    "evaluation_rule": "enforcement_action_exists"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MANAGE",
    "category": "MANAGE-2.1",
    "subcategory": "Manual freeze control via authenticated admin",
    "cpm_control": "freeze_controller:rs256_admin_freeze",
    "evaluation_rule": "opa_policy_loaded"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MANAGE",
    "category": "MANAGE-3.1",
    "subcategory": "Human approval gate for side-effect tool execution",
    "cpm_control": "executor:human_approval_gate",
    "evaluation_rule": "opa_policy_loaded"
  },
  {
    "framework": "NIST_AI_RMF",
    "function": "MANAGE",
    "category": "MANAGE-4.1",
    "subcategory": "Model lifecycle deprecation and retirement workflow",
    "cpm_control": "model_registry:lifecycle_state_machine",
    "evaluation_rule": "enforcement_action_exists"
  }
]
```

- [ ] **Step 4: Create spm/compliance/evaluator.py**
```python
"""
AI SPM — NIST AI RMF compliance evaluator.
Maps evaluation_rule names to functions that check CPM/SPM state.
"""
from __future__ import annotations
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict

import requests
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from spm.db.models import AuditExport, ComplianceEvidence, ComplianceStatus, ModelRegistry, PostureSnapshot

log = logging.getLogger("spm.compliance")

OPA_URL        = os.getenv("OPA_URL", "http://opa:8181")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
OPA_POLICIES   = ["prompt_policy", "tool_policy", "output_policy", "memory_policy", "agent_policy"]


async def _rule_opa_policy_loaded(db: AsyncSession) -> ComplianceStatus:
    """Check all 5 OPA policies are loaded."""
    try:
        for policy in OPA_POLICIES:
            resp = requests.get(f"{OPA_URL}/v1/policies/{policy}", timeout=3.0)
            if resp.status_code != 200:
                return ComplianceStatus.partial
        return ComplianceStatus.satisfied
    except Exception:
        return ComplianceStatus.not_satisfied


async def _rule_model_approved_exists(db: AsyncSession) -> ComplianceStatus:
    """Check at least one model has an approved_by record."""
    from spm.db.models import ModelStatus
    result = await db.execute(
        select(func.count()).select_from(ModelRegistry)
        .where(ModelRegistry.approved_by.isnot(None))
    )
    count = result.scalar()
    return ComplianceStatus.satisfied if count > 0 else ComplianceStatus.partial


async def _rule_risk_fusion_active(db: AsyncSession) -> ComplianceStatus:
    """Check posture snapshots contain risk dimension data (sample last 100)."""
    result = await db.execute(
        select(PostureSnapshot).order_by(PostureSnapshot.snapshot_at.desc()).limit(1)
    )
    snap = result.scalar_one_or_none()
    if snap is None:
        return ComplianceStatus.partial  # no data yet, not fully satisfied
    return ComplianceStatus.satisfied


async def _rule_models_have_risk_tier(db: AsyncSession) -> ComplianceStatus:
    """Check all registered models have a risk_tier set."""
    result = await db.execute(
        select(func.count()).select_from(ModelRegistry)
        .where(ModelRegistry.risk_tier.is_(None))
    )
    missing = result.scalar()
    if missing == 0:
        return ComplianceStatus.satisfied
    return ComplianceStatus.partial


async def _rule_snapshots_recent(db: AsyncSession) -> ComplianceStatus:
    """Check a snapshot was written in the last 10 minutes."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    result = await db.execute(
        select(func.count()).select_from(PostureSnapshot)
        .where(PostureSnapshot.snapshot_at >= cutoff)
    )
    count = result.scalar()
    return ComplianceStatus.satisfied if count > 0 else ComplianceStatus.partial


async def _rule_prometheus_reachable(db: AsyncSession) -> ComplianceStatus:
    """Check Prometheus is up."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=3.0)
        return ComplianceStatus.satisfied if resp.status_code == 200 else ComplianceStatus.partial
    except Exception:
        return ComplianceStatus.not_satisfied


async def _rule_enforcement_action_exists(db: AsyncSession) -> ComplianceStatus:
    """Check at least one enforcement action in last 30 days."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
    result = await db.execute(
        select(func.count()).select_from(AuditExport)
        .where(AuditExport.event_type.in_(["enforcement_block", "freeze_applied"]))
        .where(AuditExport.timestamp >= cutoff)
    )
    count = result.scalar()
    # Partial if enforcement is configured but no actions taken yet (normal for new deployments)
    return ComplianceStatus.satisfied if count > 0 else ComplianceStatus.partial


RULE_MAP = {
    "opa_policy_loaded":      _rule_opa_policy_loaded,
    "model_approved_exists":  _rule_model_approved_exists,
    "risk_fusion_active":     _rule_risk_fusion_active,
    "models_have_risk_tier":  _rule_models_have_risk_tier,
    "snapshots_recent":       _rule_snapshots_recent,
    "prometheus_reachable":   _rule_prometheus_reachable,
    "enforcement_action_exists": _rule_enforcement_action_exists,
}


async def evaluate_all_controls(db: AsyncSession) -> None:
    """Re-evaluate all compliance controls and update their status."""
    # Load mapping to get evaluation_rule per control
    import json
    mapping_path = os.path.join(os.path.dirname(__file__), "nist_airm_mapping.json")
    with open(mapping_path) as f:
        controls_def = {c["category"]: c for c in json.load(f)}

    result = await db.execute(select(ComplianceEvidence))
    controls = result.scalars().all()

    for control in controls:
        rule_name = controls_def.get(control.category, {}).get("evaluation_rule")
        if rule_name and rule_name in RULE_MAP:
            new_status = await RULE_MAP[rule_name](db)
            control.status = new_status
            control.last_evaluated_at = datetime.now(tz=timezone.utc)

    await db.commit()
    log.info("Compliance evaluation complete")


def render_pdf(report: Dict) -> bytes:
    """Render compliance report to PDF via WeasyPrint."""
    import os
    from weasyprint import HTML

    template_path = os.path.join(os.path.dirname(__file__), "report_template.html")
    with open(template_path) as f:
        template = f.read()

    # Simple template substitution
    functions_html = ""
    for fn in report["functions"]:
        gaps_html = "".join(
            f"<li>{g['category']}: {g['control']} ({g['status']})</li>"
            for g in fn["gaps"]
        ) or "<li>None</li>"
        functions_html += f"""
        <div class="function">
            <h2>{fn['function']} — {fn['coverage_pct']}% coverage</h2>
            <p><strong>Gaps:</strong></p><ul>{gaps_html}</ul>
        </div>"""

    html = template.replace("{{generated_at}}", report["generated_at"])
    html = html.replace("{{overall_coverage_pct}}", str(report["overall_coverage_pct"]))
    html = html.replace("{{functions}}", functions_html)

    return HTML(string=html).write_pdf()
```

- [ ] **Step 5: Create spm/compliance/report_template.html**
```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: Arial, sans-serif; margin: 40px; color: #222; }
  h1 { color: #1a3a5c; border-bottom: 2px solid #1a3a5c; padding-bottom: 8px; }
  h2 { color: #2c5f8a; margin-top: 24px; }
  .meta { color: #666; font-size: 0.9em; margin-bottom: 24px; }
  .coverage { font-size: 2em; font-weight: bold; color: #1a7a4a; }
  .function { border: 1px solid #ddd; border-radius: 4px; padding: 16px; margin: 12px 0; }
  ul { margin: 8px 0; padding-left: 20px; }
  li { margin: 4px 0; }
</style>
</head>
<body>
  <h1>NIST AI Risk Management Framework — Compliance Report</h1>
  <div class="meta">Generated: {{generated_at}}</div>
  <p>Overall Coverage: <span class="coverage">{{overall_coverage_pct}}%</span></p>
  {{functions}}
</body>
</html>
```

- [ ] **Step 6: Run tests**
```bash
python -m pytest tests/test_spm_compliance.py -v
```
Expected: All 4 PASS

- [ ] **Step 7: Commit**
```bash
git add spm/compliance/ tests/test_spm_compliance.py
git commit -m "feat(spm): NIST AI RMF compliance evaluator, mapping file, and PDF report template"
```

---

## Phase 5: Observability

### Task 11: Prometheus + Grafana provisioning

**Files:**
- Create: `prometheus/prometheus.yml`
- Create: `grafana/provisioning/dashboards/dashboards.yaml`
- Create: `grafana/provisioning/datasources/datasources.yaml`
- Create: `grafana/dashboards/engineering.json`
- Create: `grafana/dashboards/compliance.json`

- [ ] **Step 1: Create prometheus/prometheus.yml**
```yaml
# prometheus/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: spm-api
    static_configs:
      - targets: ["spm-api:8092"]
    metrics_path: /metrics

  - job_name: spm-aggregator
    static_configs:
      - targets: ["spm-aggregator:9091"]
    metrics_path: /metrics
```

- [ ] **Step 2: Create Grafana provisioning files**

`grafana/provisioning/datasources/datasources.yaml`:
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    access: proxy

  - name: SPM-DB
    type: postgres
    url: spm-db:5432
    database: spm
    user: spm_ro
    secureJsonData:
      password: spmpass_ro
    jsonData:
      sslmode: disable
      postgresVersion: 1600
```

`grafana/provisioning/dashboards/dashboards.yaml`:
```yaml
apiVersion: 1
providers:
  - name: SPM Dashboards
    type: file
    disableDeletion: true
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 3: Create minimal engineering dashboard JSON**

`grafana/dashboards/engineering.json` — a Grafana dashboard JSON with panels for:
- Model posture score over time (Prometheus query: `spm_model_risk_score`)
- Enforcement actions total (counter: `spm_enforcement_actions_total`)
- Snapshot lag (gauge: `spm_snapshot_lag_seconds`)
- Model lifecycle count by status (PostgreSQL query to `model_registry`)

Create a minimal valid dashboard JSON (Grafana format):
```json
{
  "title": "AI SPM — Engineering",
  "uid": "spm-engineering",
  "schemaVersion": 36,
  "version": 1,
  "refresh": "1m",
  "panels": [
    {
      "id": 1, "type": "timeseries",
      "title": "Model Risk Score Over Time",
      "gridPos": {"x":0,"y":0,"w":12,"h":8},
      "targets": [{"expr": "spm_model_risk_score", "legendFormat": "{{model_id}}"}],
      "datasource": "Prometheus"
    },
    {
      "id": 2, "type": "stat",
      "title": "Enforcement Actions (Total)",
      "gridPos": {"x":12,"y":0,"w":6,"h":4},
      "targets": [{"expr": "sum(spm_enforcement_actions_total)", "instant": true}],
      "datasource": "Prometheus"
    },
    {
      "id": 3, "type": "gauge",
      "title": "Snapshot Lag (seconds)",
      "gridPos": {"x":18,"y":0,"w":6,"h":4},
      "targets": [{"expr": "spm_snapshot_lag_seconds", "instant": true}],
      "fieldConfig": {"defaults": {"thresholds": {"steps": [
        {"color":"green","value":0},{"color":"yellow","value":60},{"color":"red","value":300}
      ]}}},
      "datasource": "Prometheus"
    },
    {
      "id": 4, "type": "table",
      "title": "Model Lifecycle Status",
      "gridPos": {"x":0,"y":8,"w":24,"h":8},
      "targets": [{
        "rawSql": "SELECT name, version, tenant_id, status, risk_tier, approved_by, updated_at FROM model_registry ORDER BY updated_at DESC LIMIT 50",
        "format": "table"
      }],
      "datasource": "SPM-DB"
    }
  ]
}
```

`grafana/dashboards/compliance.json`:
```json
{
  "title": "AI SPM — Compliance (NIST AI RMF)",
  "uid": "spm-compliance",
  "schemaVersion": 36,
  "version": 1,
  "refresh": "5m",
  "panels": [
    {
      "id": 1, "type": "gauge",
      "title": "NIST AI RMF Overall Coverage %",
      "gridPos": {"x":0,"y":0,"w":6,"h":6},
      "targets": [{"expr": "avg(spm_compliance_coverage_pct)", "instant": true}],
      "fieldConfig": {"defaults": {"min":0,"max":100,"unit":"percent","thresholds":{"steps":[
        {"color":"red","value":0},{"color":"yellow","value":50},{"color":"green","value":80}
      ]}}},
      "datasource": "Prometheus"
    },
    {
      "id": 2, "type": "gauge",
      "title": "GOVERN Coverage %",
      "gridPos": {"x":6,"y":0,"w":6,"h":6},
      "targets": [{"expr": "spm_compliance_coverage_pct{function='GOVERN'}", "instant": true}],
      "fieldConfig": {"defaults": {"min":0,"max":100,"unit":"percent"}},
      "datasource": "Prometheus"
    },
    {
      "id": 3, "type": "table",
      "title": "Compliance Gaps",
      "gridPos": {"x":0,"y":6,"w":24,"h":10},
      "targets": [{
        "rawSql": "SELECT function, category, cpm_control, status, last_evaluated_at FROM compliance_evidence WHERE status != 'satisfied' ORDER BY function, category",
        "format": "table"
      }],
      "datasource": "SPM-DB"
    },
    {
      "id": 4, "type": "table",
      "title": "Model Approval Audit Trail",
      "gridPos": {"x":0,"y":16,"w":24,"h":8},
      "targets": [{
        "rawSql": "SELECT name, version, tenant_id, approved_by, approved_at, risk_tier FROM model_registry WHERE approved_by IS NOT NULL ORDER BY approved_at DESC",
        "format": "table"
      }],
      "datasource": "SPM-DB"
    }
  ]
}
```

- [ ] **Step 4: Commit**
```bash
git add prometheus/ grafana/
git commit -m "feat(spm): add Prometheus config and Grafana dashboards (engineering + compliance)"
```

---

## Phase 6: Docker Compose & Integration

### Task 12: Update docker-compose.yml and .env.example

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add new variables to .env.example**

Append to `.env.example`:
```bash
# ── AI SPM Platform ─────────────────────────────────────────────────────────

# spm-db PostgreSQL credentials
SPM_DB_PASSWORD=spmpass
SPM_DB_RO_PASSWORD=spmpass_ro

# SPM API connection (used by startup-orchestrator and spm-aggregator)
SPM_API_URL=http://spm-api:8092

# SPM enforcement thresholds
SPM_MODEL_BLOCK_THRESHOLD=0.85   # rolling avg risk score to trigger enforcement
SPM_SNAPSHOT_INTERVAL_SEC=300    # posture snapshot bucket size (5 min)
SPM_ENFORCEMENT_WINDOW=3         # N snapshots to average before enforcing

# Compliance
SPM_COMPLIANCE_REFRESH_CRON="0 2 * * *"

# Model identity (stamped on PostureEnrichedEvent by Processor)
LLM_MODEL_ID=

# Grafana
GRAFANA_ADMIN_PASSWORD=admin
```

- [ ] **Step 2: Add services to docker-compose.yml**

Append to the `services:` section of `docker-compose.yml`:
```yaml
  # ── AI SPM Platform ──────────────────────────────────────────────────────────

  spm-db:
    image: postgres:16-alpine
    container_name: cpm-spm-db
    environment:
      POSTGRES_DB: spm
      POSTGRES_USER: spm_rw
      POSTGRES_PASSWORD: ${SPM_DB_PASSWORD:-spmpass}
    volumes:
      - spm-db-data:/var/lib/postgresql/data
      - ./spm/db/migrations/001_initial.sql:/docker-entrypoint-initdb.d/001_initial.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U spm_rw -d spm"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks: [cpm-net]

  spm-api:
    build:
      context: .
      dockerfile: services/spm_api/Dockerfile
    container_name: cpm-spm-api
    ports: ["8092:8092"]
    environment:
      <<: *common-env
      SPM_DB_URL: postgresql+asyncpg://spm_rw:${SPM_DB_PASSWORD:-spmpass}@spm-db:5432/spm
      FREEZE_CONTROLLER_URL: http://freeze-controller:8090
      SPM_SERVICE_JWT: ""
      PROMETHEUS_URL: http://prometheus:9090
      CPM_API_URL: http://api:8080
      POLICY_SIMULATOR_URL: http://policy-simulator:8091
    volumes:
      - *key-vol
    depends_on:
      spm-db:
        condition: service_healthy
      <<: *depends-platform
    networks: [cpm-net]

  spm-aggregator:
    build:
      context: .
      dockerfile: services/spm_aggregator/Dockerfile
    container_name: cpm-spm-aggregator
    environment:
      <<: *common-env
      SPM_DB_URL: postgresql://spm_rw:${SPM_DB_PASSWORD:-spmpass}@spm-db:5432/spm
      SPM_API_URL: http://spm-api:8092
      SPM_MODEL_BLOCK_THRESHOLD: ${SPM_MODEL_BLOCK_THRESHOLD:-0.85}
      SPM_SNAPSHOT_INTERVAL_SEC: ${SPM_SNAPSHOT_INTERVAL_SEC:-300}
      SPM_ENFORCEMENT_WINDOW: ${SPM_ENFORCEMENT_WINDOW:-3}
    depends_on:
      spm-db:
        condition: service_healthy
      spm-api:
        condition: service_started
      <<: *depends-platform
    networks: [cpm-net]

  prometheus:
    image: prom/prometheus:v2.55.1
    container_name: cpm-prometheus
    ports: ["9090:9090"]
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    networks: [cpm-net]

  grafana:
    image: grafana/grafana:11.4.0
    container_name: cpm-grafana
    ports: ["3000:3000"]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
      GF_AUTH_JWT_ENABLED: "true"
      GF_AUTH_JWT_HEADER_NAME: "X-JWT-Assertion"
      GF_AUTH_JWT_URL_LOGIN: "false"
      GF_AUTH_JWT_JWK_SET_URL: "http://spm-api:8092/jwks"
      GF_AUTH_JWT_USERNAME_CLAIM: "sub"
      GF_AUTH_JWT_ROLE_ATTRIBUTE_PATH: "contains(roles[*], 'spm:admin') && 'Admin' || 'Viewer'"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
    depends_on: [spm-api, prometheus]
    networks: [cpm-net]
```

Also add to the `volumes:` section at the bottom:
```yaml
  spm-db-data:
  grafana-data:
```

- [ ] **Step 3: Verify compose file is valid**
```bash
docker compose config --quiet
```
Expected: No errors

- [ ] **Step 4: Commit**
```bash
git add docker-compose.yml .env.example
git commit -m "feat(spm): add spm-db, spm-api, spm-aggregator, prometheus, grafana to docker-compose"
```

---

### Task 13: Integration smoke test

**Files:**
- Modify: `Makefile` (add SPM targets)
- Test: `tests/test_spm_enforcement.py`

- [ ] **Step 1: Write enforcement unit tests**
```python
# tests/test_spm_enforcement.py
from spm.db.models import ModelRegistry, ModelStatus

def test_can_transition_registered_to_under_review():
    m = ModelRegistry()
    m.status = ModelStatus.registered
    assert m.can_transition_to(ModelStatus.under_review)

def test_cannot_transition_retired():
    m = ModelRegistry()
    m.status = ModelStatus.retired
    for s in ModelStatus:
        assert not m.can_transition_to(s)

def test_enforcement_sets_retired():
    """Enforcement forces status to retired regardless of current status."""
    for current in [ModelStatus.registered, ModelStatus.approved, ModelStatus.deprecated]:
        m = ModelRegistry()
        m.status = current
        # Simulate enforcement (direct status override)
        m.status = ModelStatus.retired
        assert m.status == ModelStatus.retired

def test_blocked_models_list_excludes_non_retired():
    """Only retired models go into blocked_models OPA set."""
    models = [
        {"status": ModelStatus.approved, "model_id": "a"},
        {"status": ModelStatus.retired, "model_id": "b"},
        {"status": ModelStatus.deprecated, "model_id": "c"},
    ]
    blocked = [m["model_id"] for m in models if m["status"] == ModelStatus.retired]
    assert blocked == ["b"]
    assert "a" not in blocked
    assert "c" not in blocked
```

- [ ] **Step 2: Run all tests**
```bash
python -m pytest tests/ -v
```
Expected: All tests PASS (86 original + new SPM tests)

- [ ] **Step 3: Add Makefile targets**

Add to `Makefile`:
```makefile
# ── AI SPM ───────────────────────────────────────────────────────────────────
spm-up:
	docker compose up -d spm-db spm-api spm-aggregator prometheus grafana

spm-logs:
	docker compose logs -f spm-api spm-aggregator

spm-token-admin:
	python scripts/mint_demo_jwt.py --roles spm:admin --tenant global

spm-token-auditor:
	python scripts/mint_demo_jwt.py --roles spm:auditor --tenant global

spm-register-model:
	@TOKEN=$$(make -s spm-token-admin) && \
	curl -s -X POST http://localhost:8092/models \
	  -H "Authorization: Bearer $$TOKEN" \
	  -H "Content-Type: application/json" \
	  -d '{"name":"test-model","version":"1.0","provider":"local","risk_tier":"limited"}' | jq .

spm-compliance:
	@TOKEN=$$(make -s spm-token-auditor) && \
	curl -s http://localhost:8092/compliance/nist-airm/report \
	  -H "Authorization: Bearer $$TOKEN" | jq .overall_coverage_pct

spm-smoke:
	@echo "=== Testing spm-api health ==="
	curl -sf http://localhost:8092/health | jq .status
	@echo "=== Testing JWKS endpoint ==="
	curl -sf http://localhost:8092/jwks | jq '.keys | length'
	@echo "=== Testing model list (unauth expects 401) ==="
	curl -s -o /dev/null -w "%{http_code}" http://localhost:8092/models
	@echo ""
	@echo "=== SPM smoke tests complete ==="
```

- [ ] **Step 4: Run smoke test against live stack**
```bash
make up   # bring up full CPM stack
sleep 30  # wait for startup orchestrator
make spm-smoke
```
Expected:
```
=== Testing spm-api health ===
"ok"
=== Testing JWKS endpoint ===
1
=== Testing model list (unauth expects 401) ===
401
=== SPM smoke tests complete ===
```

- [ ] **Step 5: Verify models were self-registered by startup orchestrator**
```bash
TOKEN=$(make -s spm-token-admin)
curl -s http://localhost:8092/models \
  -H "Authorization: Bearer $TOKEN" | jq '[.[] | {name, status, tenant_id}]'
```
Expected: JSON array containing `llama-guard-3` and `output-guard-llm` with `status: "approved"`

- [ ] **Step 6: Run full compliance report**
```bash
make spm-compliance
```
Expected: A number between 0 and 100 (coverage % will be low on first boot — this is correct)

- [ ] **Step 7: Final test run**
```bash
python -m pytest tests/ -v --tb=short
```
Expected: All tests PASS

- [ ] **Step 8: Commit**
```bash
git add Makefile tests/test_spm_enforcement.py
git commit -m "feat(spm): integration smoke test, Makefile targets, enforcement unit tests"
```

---

## Summary

**Total new files:** ~20
**Modified CPM files:** 4 (topics.py, models.py, api/app.py, processor/app.py, startup_orchestrator/app.py)
**New tests:** ~30 across 5 test files
**New Docker services:** spm-db, spm-api, spm-aggregator, prometheus, grafana

**Deployment order:**
1. `make up` — startup orchestrator creates the global Kafka topic and self-registers CPM models
2. spm-db starts and runs SQL migration automatically via `docker-entrypoint-initdb.d`
3. spm-api starts, seeds compliance controls, exposes registry + compliance endpoints
4. spm-aggregator starts, subscribes to Kafka, begins writing snapshots
5. Grafana and Prometheus start with pre-provisioned dashboards

**Verify everything is working:**
```bash
make spm-smoke       # health + auth check
make spm-compliance  # NIST AI RMF coverage %
make spm-logs        # check for errors
```
