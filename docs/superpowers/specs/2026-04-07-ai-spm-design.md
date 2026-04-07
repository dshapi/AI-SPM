# AI SPM Platform — Design Spec
**Date:** 2026-04-07
**Status:** Approved
**Project:** CPM v3 + AI SPM Layer

---

## 1. Problem Statement

CPM v3 is a production-grade AI agent security platform that enforces runtime controls on every request — risk fusion, guard model screening, OPA policy evaluation, MITRE ATLAS TTP detection, and output sanitization. It secures individual AI interactions in real time.

What CPM v3 does not have is a governance plane: there is no model registry, no lifecycle management for AI models, no continuous posture monitoring over time, no compliance evidence collection, and no cross-tenant visibility dashboard. An attacker could compromise a model between deployments; a deprecated model could remain in service; compliance evidence is scattered across Kafka logs with no structured mapping to any regulatory framework.

The AI SPM (AI Security Posture Management) layer closes this gap. It is a fully independent platform that runs alongside CPM v3, consumes its event stream, and provides model governance, aggregate posture monitoring, active enforcement, and NIST AI RMF compliance reporting.

---

## 2. Goals

- Provide a model registry with full lifecycle state management (registered → under_review → approved → deprecated → retired)
- Aggregate per-request CPM posture data into per-model, per-tenant time-series snapshots
- Automatically block models whose aggregate risk score exceeds threshold by pushing policy to OPA and calling the Freeze Controller
- Expose a centralized AI Bill of Materials (AI-SBOM) by aggregating each CPM service's `/inventory` endpoint
- Generate NIST AI RMF compliance reports (JSON + PDF); EU AI Act mapping deferred to v2
- Surface two role-gated Grafana dashboards: engineering view (posture, alerts) and compliance view (framework coverage, audit trail)
- Require zero breaking changes to existing CPM v3 services

**Out of scope (v1):** EU AI Act mapping, ISO 42001, external threat feeds, multi-cluster federation, UI beyond Grafana.

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  CPM v3  (4 additive changes only — marked ▲)                                │
│                                                                              │
│  API :8080 ──▲model gate──► OPA (model_policy.rego NEW)                     │
│      │                                                                       │
│      ▼ Kafka: cpm.{tenant}.raw → posture_enriched → decision → tool_result  │
│  [all existing services unchanged]                                           │
│      │                                                                       │
│  Processor ──▲ stamps model_id on PostureEnrichedEvent                      │
│  Startup Orchestrator ──▲ self-registers CPM models on first boot           │
└──────────────────────────────────────────────────────────────────────────────┘
                    │ Kafka (read)           ▲ OPA policy sync
                    │                       │ Freeze Controller calls
                    ▼                       │
┌──────────────────────────────────────────────────────────────────────────────┐
│  AI SPM PLATFORM                                                             │
│                                                                              │
│  spm-aggregator  — Kafka consumer, posture rollup, enforcement trigger      │
│  spm-db          — PostgreSQL 16, four schemas (see §5)                     │
│  spm-api :8092   — FastAPI, model registry, compliance, enforcement API     │
│  prometheus :9090 — metrics scraping                                        │
│  grafana :3000    — engineering + compliance dashboards                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

All AI SPM services are added to the existing `cpm-v3/docker-compose.yml`. No separate compose file or orchestrator is required.

---

## 4. New Services

### 4.1 spm-db (PostgreSQL 16)
Persistent store for the entire AI SPM layer. Internal only — not exposed on the host. Four schemas: `model_registry`, `posture_snapshots`, `compliance_evidence`, `audit_export`.

**Connection pool:** 10 min connections, 20 max connections, 30s idle timeout. Configured via SQLAlchemy `create_engine` parameters in `spm/db/session.py`.

**Audit immutability:** A PostgreSQL row-level trigger on `audit_export` raises an exception on any UPDATE or DELETE, enforced at the DB layer independent of application code. A dedicated read-write user (`spm_rw`) is used by spm-aggregator and spm-api for all writes. A separate read-only user (`spm_ro`) is used by the Grafana PostgreSQL data source — preventing any dashboard-originating mutation.

**Retention:** No automated archival in v1. Retention policy is out of scope; operators manage via pg_dump.

### 4.2 spm-aggregator
A Kafka consumer service using consumer group `spm-aggregator`. Reads three existing CPM topics per tenant: `cpm.{tenant}.posture_enriched`, `cpm.{tenant}.decision`, `cpm.{tenant}.tool_result`. Also reads `cpm.{tenant}.audit` per tenant for the `audit_export` mirror. Subscribes to `cpm.global.model_events` to reset its in-memory model status cache.

**Multi-tenant subscription:** On startup, the aggregator reads the `TENANTS` environment variable (already present in CPM) and subscribes to all matching topic patterns. When a tenant is added and CPM is restarted, the aggregator also restarts (it is in the same compose stack) and picks up the new topics.

**Snapshot cadence:** Writes time-bucketed posture snapshots (5-minute default, configurable via `SPM_SNAPSHOT_INTERVAL_SEC`) to `posture_snapshots`. After each upsert, evaluates the enforcement rule (see §8.3).

**Risk score calculation:** The aggregator extracts `posture_score` from `PostureEnrichedEvent` (the fused scalar already computed by the CPM Processor from all 7 dimensions). It stores `avg_risk_score` as the mean of all `posture_score` values in the bucket, and `max_risk_score` as the max. The rolling enforcement check averages `avg_risk_score` across the last N snapshots (default: 3) for the same `(model_id, tenant_id)`. If no requests arrive in a window, the bucket is skipped (not counted as 0) — a window with zero events does not artificially lower the rolling average.

**Enforcement trigger:** If rolling average exceeds `SPM_MODEL_BLOCK_THRESHOLD` (default: `0.85`), calls `spm-api POST /internal/enforce/{model_id}` with a service token (a pre-shared `spm:admin` JWT minted at startup by the startup orchestrator and stored in Redis under key `spm:service_token`).

**Audit mirror:** For every consumed event from `cpm.{tenant}.audit`, the aggregator writes one row to `audit_export`. The `event_id` is taken from `AuditEvent.event_id`. If the field is absent (legacy events), a deterministic UUID is derived from `sha256(tenant_id + event_type + timestamp)`. Unique constraint on `event_id` makes replay idempotent.

### 4.3 spm-api (FastAPI, :8092)
The AI SPM control plane. Responsibilities:

- **Model registry CRUD and lifecycle state machine** — see §5.1 for state transitions
- **AI-SBOM aggregation** — polls CPM service `/inventory` endpoints on demand (`GET /sbom/refresh`) and nightly via `SPM_COMPLIANCE_REFRESH_CRON`; see §9 for SBOM schema
- **NIST AI RMF compliance report generation** — JSON + PDF via WeasyPrint; PDF template at `spm/compliance/report_template.html`; see §8
- **Enforcement engine** — pushes updated `model_policy.rego` to OPA and calls Freeze Controller; see §6.3
- **`/metrics` endpoint** — Prometheus scraping
- **Auth** — CPM's existing RS256 JWT with two new roles: `spm:admin` (full write + enforcement) and `spm:auditor` (read-only + compliance reports). Roles are issued by minting JWTs with the `roles` claim set to include `spm:admin` or `spm:auditor` using the existing `mint_demo_jwt.py` pattern. No changes to CPM's JWT issuer logic.

**Model approval authorization:** Any holder of `spm:admin` role may approve a model. No multi-person review in v1 — a single `approved_by` (the JWT `sub`) is recorded. v2 may add a quorum approval table.

**WeasyPrint dependency:** Added to `spm/requirements.txt`. Requires system packages `libpango-1.0-0 libcairo2` in the spm-api Docker image (added to Dockerfile).

**Dependencies environment variables:**
```
OPA_URL              http://opa:8181      (reuse CPM's OPA)
FREEZE_CONTROLLER_URL http://freeze-controller:8090
SPM_DB_URL           postgresql+asyncpg://spm_rw:<pw>@spm-db:5432/spm
JWT_PUBLIC_KEY_PATH  /keys/public.pem    (shared read-only mount from CPM)
```

### 4.4 prometheus (:9090)
Scrapes `spm-api` and `spm-aggregator` every 15s. Metric definitions:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `spm_model_risk_score` | Gauge | `model_id`, `tenant_id` | Latest avg_risk_score from most recent snapshot |
| `spm_enforcement_actions_total` | Counter | `action` (block/unblock), `tenant_id` | Count of enforcement actions taken |
| `spm_compliance_coverage_pct` | Gauge | `framework`, `function` | % of controls with status=satisfied |
| `spm_snapshot_lag_seconds` | Gauge | — | Seconds since last snapshot was written |
| `spm_model_lifecycle_count` | Gauge | `status` | Count of models per lifecycle status |

### 4.5 grafana (:3000)
Two pre-provisioned dashboards loaded from `grafana/dashboards/` at startup via `grafana/provisioning/dashboards/`. Role-gating implemented via Grafana's built-in JWT auth: `grafana.ini` sets `[auth.jwt]` with `jwks_url = http://spm-api:8092/jwks` (spm-api exposes a `/jwks` endpoint that proxies CPM's RS256 public key in JWKS format). The JWT `roles` claim is mapped to Grafana `Viewer` (any authenticated user) or `Editor` (spm:admin). The compliance dashboard panels use Grafana's panel-level permissions to restrict to users with `spm:auditor` or `spm:admin` role, checked via a data source query that returns 403 for unauthorized roles.

The Grafana PostgreSQL data source connects using `spm_ro` credentials (read-only user) to prevent mutations from dashboards.

---

## 5. Data Model

### 5.1 model_registry
| Column | Type | Notes |
|---|---|---|
| model_id | UUID PK | `gen_random_uuid()` default |
| name | TEXT NOT NULL | e.g., "llama-guard-3" |
| version | TEXT NOT NULL | e.g., "3.0.0" |
| provider | ENUM NOT NULL | local / openai / anthropic / other |
| purpose | TEXT | e.g., "content_screening" |
| risk_tier | ENUM NOT NULL | minimal / limited / high / unacceptable |
| tenant_id | TEXT NOT NULL | tenant ID or "global" for CPM-owned models |
| status | ENUM NOT NULL | registered / under_review / approved / deprecated / retired |
| approved_by | TEXT | sub from JWT of approving admin |
| approved_at | TIMESTAMPTZ | |
| ai_sbom | JSONB | see §9 for schema |
| created_at | TIMESTAMPTZ | `now()` default |
| updated_at | TIMESTAMPTZ | updated by trigger |

**Unique constraint:** `(name, version, tenant_id)`

**State machine (enforced in spm-api, returns 409 on invalid transition):**
```
registered → under_review → approved → deprecated → retired
                                                       (terminal)
```
- `deprecated` models: requests are still allowed through (model remains in service) but the model is flagged in the OPA model_policy and a dashboard warning is shown.
- `retired` models: added to OPA `blocked_models` set; all requests return 403. Cannot be reactivated.
- In-flight requests at the moment of retirement complete normally (request is already past the model gate).

### 5.2 posture_snapshots
| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| model_id | UUID NOT NULL | nullable FK to model_registry; NULL for sentinel "unknown" events |
| tenant_id | TEXT NOT NULL | |
| snapshot_at | TIMESTAMPTZ NOT NULL | 5-minute bucket boundary (floor to interval) |
| request_count | INT NOT NULL DEFAULT 0 | |
| block_count | INT NOT NULL DEFAULT 0 | |
| escalation_count | INT NOT NULL DEFAULT 0 | |
| avg_risk_score | FLOAT NOT NULL | mean of posture_score in bucket |
| max_risk_score | FLOAT NOT NULL | max of posture_score in bucket |
| intent_drift_avg | FLOAT NOT NULL DEFAULT 0 | |
| ttp_hit_count | INT NOT NULL DEFAULT 0 | |

**model_id is nullable** (not a strict FK) to accommodate unknown model events. The unique constraint is on `(model_id, tenant_id, snapshot_at)` with NULLS DISTINCT so NULL model_id events aggregate into a single unknown bucket per tenant per window.

### 5.3 compliance_evidence
| Column | Type | Notes |
|---|---|---|
| id | SERIAL PK | |
| framework | TEXT NOT NULL | e.g., "NIST_AI_RMF" |
| function | TEXT NOT NULL | GOVERN / MAP / MEASURE / MANAGE |
| category | TEXT NOT NULL | e.g., "GOVERN-1.1" |
| subcategory | TEXT | |
| cpm_control | TEXT NOT NULL | e.g., "OPA:prompt_policy.rego" |
| status | ENUM NOT NULL | satisfied / partial / not_satisfied |
| evidence_ref | JSONB | pointer to audit record or snapshot |
| last_evaluated_at | TIMESTAMPTZ | |

Seeded at startup from `spm/compliance/nist_airm_mapping.json`. Re-evaluated nightly via `SPM_COMPLIANCE_REFRESH_CRON`.

**Satisfaction rules (evaluated by `spm/compliance/evaluator.py`):**

| Function | Satisfied When | Partial When |
|---|---|---|
| GOVERN | All 5 OPA policy files loadable via `GET /v1/policies` from OPA + ≥1 model with `approved_by IS NOT NULL` | OPA policies OK but no approved models yet |
| MAP | `posture_enriched` events contain all 7 risk dimensions (checked by sampling last 100 events from DB) + all registered models have `risk_tier IS NOT NULL` | Some models missing risk_tier |
| MEASURE | A snapshot was written in last 10 minutes + Prometheus `/metrics` returns 200 | Snapshots present but Prometheus unreachable |
| MANAGE | ≥1 row in `audit_export` with `event_type IN ('enforcement_block', 'freeze_applied')` in last 30 days | Enforcement configured but no actions taken yet |

**Coverage gauge calculation:** `satisfied_count / total_count` per NIST function across all rows in `compliance_evidence` where `framework = 'NIST_AI_RMF'`.

### 5.4 audit_export
| Column | Type | Notes |
|---|---|---|
| event_id | TEXT NOT NULL UNIQUE | from AuditEvent.event_id or derived SHA-256 |
| tenant_id | TEXT NOT NULL | |
| event_type | TEXT NOT NULL | maps AuditEvent.event_type to string |
| actor | TEXT | AuditEvent.actor |
| timestamp | TIMESTAMPTZ NOT NULL | |
| payload | JSONB NOT NULL | full serialized event |

**Immutability enforcement:** A PostgreSQL trigger (`audit_export_immutable_trg`) raises `RAISE EXCEPTION 'audit_export is append-only'` on any UPDATE or DELETE. This trigger is created in the DB migration and is independent of application code.

---

## 6. Kafka Integration

### 6.1 Read side (spm-aggregator)
Consumer group: `spm-aggregator`. Topics consumed per tenant (from `TENANTS` env var, same as CPM):
- `cpm.{tenant}.posture_enriched` — primary signal (posture_score, model_id)
- `cpm.{tenant}.decision` — allow/escalate/block outcome
- `cpm.{tenant}.tool_result` — behavioral signal
- `cpm.{tenant}.audit` — full audit mirror to audit_export

Global topic (consumed once, not per-tenant):
- `cpm.global.model_events` — invalidates aggregator's in-memory model status cache

### 6.2 Global topic definition
`cpm.global.model_events` is defined in a new `GlobalTopics` dataclass in `platform_shared/topics.py`:
```python
@dataclass
class GlobalTopics:
    MODEL_EVENTS: str = "cpm.global.model_events"
```
The startup orchestrator creates this topic at boot alongside tenant topics (1 partition, retention 7 days).

### 6.3 Enforcement pipeline
1. `spm-aggregator` detects threshold breach → calls `spm-api POST /internal/enforce/{model_id}` with service JWT
2. `spm-api` sets model status to `retired` in DB (using the state machine — triggers the block)
3. Generates `model_policy.rego` with model_id added to `blocked_models` set (see §7.4 for policy schema)
4. Pushes policy via `PUT /v1/policies/model_policy` to OPA at `OPA_URL` (existing env var)
5. Calls Freeze Controller: `POST /freeze` with body `{"scope": "tenant", "tenant_id": "<id>", "actor": "spm-enforcement", "reason": "model_risk_threshold_exceeded", "model_id": "<id>"}` using the `spm:admin` service JWT; expects `200 OK`
6. Publishes `{"event": "model_blocked", "model_id": "...", "tenant_id": "...", "timestamp": "..."}` to `cpm.global.model_events`
7. Writes enforcement record to `audit_export` with `event_type = "enforcement_block"`

**Idempotency:** Steps 3–7 are wrapped in an idempotency check: if the model is already in `retired` status in DB, spm-api returns `200` immediately without re-pushing to OPA or Freeze Controller.

**Error handling:** If OPA push fails (non-200), spm-api logs the error, writes a partial audit record with `status=failed`, and returns `500` to spm-aggregator. spm-aggregator retries with exponential backoff (max 3 attempts, 2s/4s/8s). If Freeze Controller call fails, same retry pattern. OPA and Freeze are called sequentially; a Freeze failure does not roll back the OPA push.

---

## 7. CPM v3 Changes (Additive Only)

### 7.1 platform_shared/topics.py — GlobalTopics dataclass
Add a new frozen dataclass alongside the existing `TenantTopics`:
```python
@dataclass(frozen=True)
class GlobalTopics:
    MODEL_EVENTS: str = "cpm.global.model_events"
```
The startup orchestrator imports and uses `GlobalTopics().MODEL_EVENTS` when creating the global topic. The spm-aggregator uses the same constant when subscribing. This ensures the topic name is defined in one place.

### 7.2 platform_shared/models.py — PostureEnrichedEvent
Add one optional field:
```python
model_id: Optional[str] = None  # stamped by Processor from its LLM client config
```

### 7.3 services/processor/app.py — stamp model_id
The Processor service has a configured LLM client (referenced via `LLM_MODEL_ID` env var or equivalent). Add `model_id = settings.llm_model_id` when constructing the `PostureEnrichedEvent`. If not configured, defaults to `None`. This is a one-line change in the event construction block.

Add `LLM_MODEL_ID` to `.env.example` with documentation comment.

### 7.4 services/api/app.py — model gate
Before publishing to `cpm.{tenant}.raw`, perform an OPA check:

```python
# Redis cache key: spm:model_gate:{model_id}:{tenant_id}
# TTL: 30s. Value: "approved" | "blocked"
# Fail-closed: if OPA is unreachable OR cache miss AND OPA times out → return 403
opa_input = {"model_id": model_id, "tenant_id": tenant_id}
result = await opa_client.evaluate("model_policy/allow", opa_input)
if not result:
    raise HTTPException(status_code=403, detail={"error": "model_not_approved", "model_id": model_id})
```

**Fail-closed behavior:** On cache miss, OPA is called with a 500ms timeout. If OPA times out or is unreachable, the request is **blocked** (403), not passed through. This eliminates the stale-cache security gap. Cache is populated on successful OPA response and invalidated when a `model_blocked` or `model_unblocked` event is consumed from `cpm.global.model_events` by a lightweight consumer in the API service.

**Cold start:** On first request (empty cache), OPA is called directly. The 30s TTL is a performance optimization only — correctness always falls back to OPA.

**Model ID source:** The API service reads the model ID from the request JWT claim `model_id` if present, or from the `X-Model-ID` request header. If absent, the gate is skipped (backward compatible with clients that don't specify a model).

### 7.5 OPA model_policy.rego (new file)
Location: `opa/policies/model_policy.rego`

```rego
package model_policy

import future.keywords.if

default allow = false

# Allow if model is not in blocked set
allow if {
    not input.model_id in data.blocked_models
    not input.model_id in data.deprecated_models
}

# Allow if no model_id provided (backward compat)
allow if {
    not input.model_id
}
```

`data.blocked_models` and `data.deprecated_models` are OPA data documents pushed by spm-api whenever enforcement state changes. Initial state: empty sets.

Push format: `PUT /v1/data/blocked_models` with body `["model-uuid-1", "model-uuid-2"]`.

### 7.6 services/startup_orchestrator/app.py — self-registration
After all CPM topics and ACLs are provisioned, the orchestrator calls spm-api to register CPM's own models. Uses retry logic: up to 10 attempts with 3s backoff, since spm-api may not be ready immediately.

```python
models_to_register = [
    {"name": "llama-guard-3", "version": "3.0.0", "provider": "local",
     "purpose": "content_screening", "risk_tier": "limited",
     "tenant_id": "global", "status": "approved", "approved_by": "startup-orchestrator"},
    {"name": "output-guard-llm", "version": settings.service_version, "provider": "local",
     "purpose": "output_screening", "risk_tier": "limited",
     "tenant_id": "global", "status": "approved", "approved_by": "startup-orchestrator"},
]
# POST /models with upsert semantics (unique on name+version+tenant_id)
```

If spm-api is unreachable after all retries, the orchestrator logs a warning and continues — CPM operates normally but without SPM model gate enforcement until spm-api comes up.

---

## 8. NIST AI RMF Compliance

### 8.1 Mapping file
Location: `spm/compliance/nist_airm_mapping.json`. Format:
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
  ...
]
```
The `evaluation_rule` field maps to a named function in `spm/compliance/evaluator.py`. Implementers add one Python function per rule name.

### 8.2 Report endpoint
`GET /compliance/nist-airm/report?format=json|pdf`

Requires `spm:auditor` or `spm:admin` role. JSON response structure:
```json
{
  "generated_at": "...",
  "framework": "NIST_AI_RMF",
  "overall_coverage_pct": 75.0,
  "functions": [
    {"function": "GOVERN", "coverage_pct": 100.0, "controls": [...], "gaps": []},
    ...
  ]
}
```
PDF is rendered from `spm/compliance/report_template.html` via WeasyPrint. Requires `libpango-1.0-0 libcairo2` in the spm-api Dockerfile.

---

## 9. AI-SBOM

### 9.1 CPM service inventory endpoints
The following CPM services already expose `/inventory` (from the existing AI-BOM implementation):
- `api:8080/inventory`
- `guard-model:8200/inventory`
- `freeze-controller:8090/inventory`
- `policy-simulator:8091/inventory`

spm-api polls all four on demand and nightly. If a service is unreachable, its inventory is omitted from the merged SBOM with a `"status": "unavailable"` entry — partial SBOMs are returned rather than failing the entire operation.

### 9.2 SBOM JSONB schema (stored in model_registry.ai_sbom)
```json
{
  "schema_version": "1.0",
  "model_card": {
    "description": "...",
    "training_data": "...",
    "intended_use": "...",
    "limitations": "..."
  },
  "provenance": {
    "source_url": "...",
    "sha256": "...",
    "download_date": "..."
  },
  "dependencies": [
    {"name": "transformers", "version": "4.38.0", "type": "python_package"}
  ],
  "inventory_sources": ["api:8080/inventory", "guard-model:8200/inventory"]
}
```
No strict JSON schema validation in v1 — JSONB accepts any valid JSON. v2 may add JSON Schema validation via `jsonschema` library.

---

## 10. New Environment Variables

| Variable | Default | Service | Description |
|---|---|---|---|
| `SPM_DB_URL` | — | spm-api, spm-aggregator | PostgreSQL connection string |
| `SPM_MODEL_BLOCK_THRESHOLD` | `0.85` | spm-aggregator | Rolling avg risk score that triggers enforcement |
| `SPM_SNAPSHOT_INTERVAL_SEC` | `300` | spm-aggregator | Posture snapshot bucket size |
| `SPM_ENFORCEMENT_WINDOW` | `3` | spm-aggregator | Number of snapshots to average before enforcing |
| `SPM_API_URL` | `http://spm-api:8092` | startup-orchestrator | Used for self-registration |
| `SPM_COMPLIANCE_REFRESH_CRON` | `0 2 * * *` | spm-api | Nightly compliance re-evaluation |
| `LLM_MODEL_ID` | — | processor | Model ID stamped on PostureEnrichedEvent |
| `FREEZE_CONTROLLER_URL` | `http://freeze-controller:8090` | spm-api | Freeze Controller endpoint |

---

## 11. Port Summary

| Service | Port | Role |
|---|---|---|
| spm-api | 8092 | AI SPM control plane & compliance API |
| spm-db | 5432 | PostgreSQL (internal only) |
| prometheus | 9090 | Metrics scraping |
| grafana | 3000 | Engineering + compliance dashboards |

---

## 12. Value Delivered

| Gap in CPM v3 | AI SPM Solution |
|---|---|
| No model registry or lifecycle management | `model_registry` table + state machine API |
| Runtime risk only — no aggregate posture over time | `posture_snapshots` time-series + Grafana posture charts |
| No automated model-level enforcement | Enforcement pipeline: threshold → OPA push → Freeze |
| AI-BOM per-service only, no central view | AI-SBOM aggregator polls all `/inventory` endpoints |
| No compliance evidence or reports | NIST AI RMF mapping + PDF/JSON report endpoint |
| No cross-tenant visibility | Grafana engineering dashboard with per-tenant heatmap |
| No audit trail beyond raw Kafka logs | `audit_export` append-only PostgreSQL table with DB-level trigger |

---

## 13. Future Work (v2)

- EU AI Act article-level control mapping and conformity documentation
- ISO 42001 management system evidence
- External threat feed integration (CVE matching against AI-SBOM components)
- Model red-team / adversarial test result ingestion
- Multi-cluster / multi-region federation
- Custom UI to replace Grafana for the compliance dashboard
- JSON Schema validation for AI-SBOM JSONB field
- Multi-person approval quorum for model lifecycle transitions
- Long-term audit_export archival to object storage
