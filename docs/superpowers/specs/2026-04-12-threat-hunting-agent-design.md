# Threat Hunting Agent — Design Spec
**Date:** 2026-04-12
**Status:** Approved
**Author:** dany

---

## Overview

A new standalone microservice (`services/threat-hunting-agent/`) that runs a LangChain ReAct agent powered by Groq. The agent continuously consumes Kafka events, batches them into 30-second windows, and reasons over each batch to detect multi-stage AI-layer and infrastructure threats. When a threat is confirmed it opens a finding in the agent-orchestrator-service and publishes a `threat_detected` event to Kafka. Humans investigate — no automated response actions.

---

## Goals

- Detect multi-stage attacks that span both AI-layer signals (jailbreaks, policy violations, guard blocks) and infrastructure signals (auth anomalies, posture spikes, unusual session patterns)
- Correlate signals that individually look benign but together indicate a campaign
- Surface confirmed threats as findings in the agent-orchestrator-service
- Remain passive — no automated remediation in v1

## Non-Goals

- Automated freeze / model blocking (future v2)
- Admin UI dashboard for threat findings (future v2)
- Scheduled / historical hunt runs (only real-time Kafka batches)
- Multi-agent architecture (single ReAct agent is sufficient for v1)

---

## Architecture

### New service: `services/threat-hunting-agent/`

```
services/threat-hunting-agent/
├── app.py                          # FastAPI + health endpoint + lifespan
├── agent/
│   ├── __init__.py
│   ├── agent.py                    # LangChain ReAct agent + Groq LLM wiring
│   └── prompts.py                  # System prompt and hunting instructions
├── tools/
│   ├── __init__.py
│   ├── postgres_tool.py            # Query audit_export, posture_snapshots, model_registry (SPM DB)
│   ├── redis_tool.py               # Query live session data
│   ├── mitre_tool.py               # MITRE ATLAS external API queries
│   ├── opa_tool.py                 # Re-evaluate signals against OPA policy engine
│   ├── guard_tool.py               # Re-screen prompts via guard model /screen endpoint
│   └── case_tool.py                # POST to /api/v1/threat-findings on agent-orchestrator
├── consumer/
│   ├── __init__.py
│   └── kafka_consumer.py           # Batches Kafka events into 30s windows
├── Dockerfile
└── requirements.txt
```

### Changes to existing services

**`services/agent-orchestrator-service/`** — two additions:
1. New `threat_findings` table in agent-orchestrator's SQLite database (new alembic migration)
2. New `POST /api/v1/threat-findings` endpoint served by a new `ThreatFindingsService` (internal only, no JWT auth)

---

## Kafka Topics

The platform uses tenant-scoped topic names from `platform_shared/topics.py`:

```python
def topics_for_tenant(tenant_id: str) -> TenantTopics:
    p = f"cpm.{tenant_id}"
    # e.g. cpm.t1.audit, cpm.t1.decision, cpm.t1.posture_enriched ...
```

**Topics the threat-hunting-agent subscribes to** (per tenant, from `TENANTS` env var):

| Platform topic field | Example name | What it carries |
|---------------------|--------------|-----------------|
| `audit`             | `cpm.t1.audit` | All audit events incl. blocks, violations |
| `decision`          | `cpm.t1.decision` | OPA/guard decisions (block/allow/escalate) |
| `posture_enriched`  | `cpm.t1.posture_enriched` | Posture-scored events |

The service reads `TENANTS` env var (e.g. `"t1,t2"`) and subscribes to the relevant topics for each tenant at startup.

**Outbound topic (global):**

| Topic | What it carries |
|-------|-----------------|
| `cpm.global.threat_detected` | Confirmed threat findings published by the agent |

**Consumer group:** `cpm-threat-hunter-group`
**Offset reset:** `latest` — start from current position on first run; do not replay historical events
**Commit strategy:** Manual commit after a batch is fully processed (either finding created or batch discarded). If the agent crashes mid-batch, events are replayed on restart (idempotency key prevents duplicate findings).

---

## Data Flow

```
Kafka topics (per tenant)      Consumer (30s window)       LangChain ReAct Agent
─────────────────────          ─────────────────────       ──────────────────────────────────
cpm.t1.audit         ──┐
cpm.t1.decision      ──┼───►  Batch accumulator           Batch arrives (per tenant)
cpm.t1.posture_      ──┘      asyncio Queue               │
         enriched             max depth: 20               ├─ Observe: summarise signals
                              drop oldest if full         │   (scoped to single tenant_id)
                                                          ├─ Act: QueryAuditLogs
                                                          ├─ Act: QueryPostureHistory
                                                          ├─ Act: QueryRedisSession
                                                          ├─ Act: RescreenPrompt (if needed)
                                                          ├─ Act: EvaluateOPAPolicy
                                                          ├─ Act: LookupMITRE
                                                          │
                                                          ├─ Reason: is this a threat?
                                                          │
                                                          ├─ YES → CreateFinding
                                                          │         (POST /api/v1/threat-findings)
                                                          │         publish threat_detected → Kafka
                                                          │
                                                          └─ NO  → log + discard batch
                                                                    commit Kafka offset
```

**Tenant isolation:** Events from multiple tenants arrive on separate topics. The consumer builds separate per-tenant batches. Each batch is tagged with its `tenant_id` and all tool calls are scoped to that tenant. The agent never mixes signals across tenants.

### Batching algorithm

Every 30 seconds (`HUNT_BATCH_WINDOW_SEC`):
1. Drain all accumulated events from the asyncio queue into a list
2. Group events by `tenant_id` — one batch per tenant
3. Submit each tenant batch to the agent for analysis
4. If queue depth exceeds `HUNT_QUEUE_MAX` (20) before the 30s window closes, drop the oldest batch and log a warning
5. If the queue is empty at the 30s boundary, skip — do not submit an empty batch
6. Commit Kafka offsets only after the batch is fully processed

---

## LangChain Tools

All tools catch their own exceptions and return a structured error dict (`{"error": "..."}`) rather than raising. The agent reasons about failures and tries alternatives.

### 1. `QueryAuditLogs`
- **Input:** `tenant_id: str`, `time_range_minutes: int`, `event_types: list[str] | None`
- **Action:** SELECT from `audit_export` in SPM PostgreSQL (`SPM_DB_URL`), ordered by timestamp DESC, max 100 rows
- **Returns:**
  ```json
  [{"event_id": "...", "event_type": "guard_model_block", "user_id": "u1",
    "model": "gpt-4", "risk_score": 0.87, "timestamp": "2026-04-12T10:00:00Z"}]
  ```

### 2. `QueryPostureHistory`
- **Input:** `tenant_id: str`, `model_id: str | None`, `hours_back: int`
- **Action:** SELECT from `posture_snapshots` in SPM PostgreSQL, compute delta (latest score − earliest score) over the window
- **Returns:**
  ```json
  {"model_id": "...", "tenant_id": "t1", "avg_score": 0.54, "max_score": 0.91,
   "score_delta": 0.37, "block_count": 12, "escalation_count": 3}
  ```

### 3. `QueryModelRegistry`
- **Input:** `model_id: str | None`, `name: str | None`
- **Action:** SELECT from `model_registry` in SPM PostgreSQL
- **Returns:**
  ```json
  {"model_id": "...", "name": "gpt-4-turbo", "risk_tier": "high",
   "status": "approved", "provider": "openai"}
  ```

### 4. `QueryRedisSession`
- **Input:** `user_id: str`, `session_id: str | None`
- **Action:** SCAN Redis keys matching `session:{user_id}:*`, read up to 20 most recent entries
- **Returns:**
  ```json
  {"user_id": "u1", "session_count": 3, "prompt_count": 14,
   "time_range_minutes": 28, "topics_summary": "repeated requests about ..."}
  ```

### 5. `RescreenPrompt`
- **Input:** `prompt_text: str`
- **Action:** POST to `http://guard-model:8200/screen` with `{"text": prompt_text, "context": "threat_hunt"}`
- **Returns:**
  ```json
  {"verdict": "block", "score": 0.92, "categories": ["S9"], "backend": "groq/llama-guard-3-8b"}
  ```
- **On failure:** `{"error": "guard model unavailable"}`

### 6. `EvaluateOPAPolicy`
- **Input:** signals dict: `{"posture_score": 0.8, "guard_verdict": "block", "guard_categories": ["S9"], ...}`
- **Action:** POST to `http://opa:8181/v1/data/spm/prompt/allow` with `{"input": signals}`
- **Returns:**
  ```json
  {"decision": "block", "reason": "posture score exceeds block threshold", "action": "deny_execution"}
  ```
- **On failure:** `{"error": "OPA unavailable"}`

### 7. `LookupMITRE`
- **Input:** `technique_id: str | None` (e.g. `"AML.T0051"`), `keyword: str | None`
- **Action:** GET `https://atlas.mitre.org/api/techniques/{technique_id}` OR search endpoint if keyword provided
- **Returns:**
  ```json
  {"id": "AML.T0051", "name": "LLM Prompt Injection", "tactic": "Initial Access",
   "description": "...", "mitigations": ["..."] }
  ```
- **On failure:** `{"error": "MITRE ATLAS API unreachable"}`

### 8. `CreateFinding`
- **Input:** `title: str`, `severity: str` (low/medium/high/critical), `description: str`, `evidence: dict`, `ttps: list[str]`, `tenant_id: str`
- **Action:** POST to `http://agent-orchestrator:8094/api/v1/threat-findings`
- **Idempotency:** Computes `batch_hash = sha256(sorted(evidence.event_ids))` and includes it in the request body. The endpoint deduplicates by `batch_hash`.
- **Returns:**
  ```json
  {"id": "uuid", "title": "...", "severity": "high", "status": "open", "created_at": "..."}
  ```
- **On failure:** `{"error": "agent-orchestrator unreachable — finding not saved"}`

---

## New Endpoint: `POST /api/v1/threat-findings`

Added to `agent-orchestrator-service`. Docker-internal only — not published on an external port. No JWT auth required (service-to-service on the Docker bridge network).

**Service layer:** A new `ThreatFindingsService` class in `services/threat_findings.py` handles the insert, following the same pattern as `CasesService`.

**Request body:**
```json
{
  "title": "Multi-stage jailbreak campaign detected",
  "severity": "high",
  "description": "Three users from tenant t1 attempted coordinated jailbreak across 14 sessions...",
  "evidence": {
    "event_ids": ["abc123", "def456"],
    "sessions": ["sess-1", "sess-2"],
    "prompts": ["..."],
    "posture_delta": 0.42
  },
  "ttps": ["AML.T0051.000", "AML.T0054"],
  "tenant_id": "t1",
  "batch_hash": "sha256hex..."
}
```

**Responses:**

| Status | Body | When |
|--------|------|------|
| 201 | `{"id": "uuid", "title": "...", "severity": "high", "status": "open", "created_at": "..."}` | Finding created |
| 200 | `{"id": "existing_uuid", "deduplicated": true}` | batch_hash already exists |
| 400 | `{"code": "VALIDATION_ERROR", "message": "..."}` | Invalid severity / missing fields |
| 500 | `{"code": "INTERNAL_ERROR", "message": "..."}` | DB write failed |

Uses the same `ErrorDetail` / `ErrorResponse` Pydantic schemas as the existing cases endpoint.

---

## Data Model: `threat_findings` table

Added to agent-orchestrator's **SQLite** database via a new alembic migration in `services/agent-orchestrator-service/alembic/versions/`.

```sql
CREATE TABLE threat_findings (
    id          TEXT PRIMARY KEY,              -- UUID as string (SQLite compatible)
    batch_hash  TEXT UNIQUE NOT NULL,          -- Idempotency key (sha256 of event_ids)
    title       TEXT NOT NULL,
    severity    TEXT NOT NULL,                 -- low | medium | high | critical
    description TEXT NOT NULL,
    evidence    TEXT NOT NULL,                 -- JSON serialised
    ttps        TEXT NOT NULL DEFAULT '[]',   -- JSON serialised list
    tenant_id   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open', -- open | investigating | closed
    created_at  TEXT NOT NULL,                -- ISO-8601
    closed_at   TEXT
);

CREATE INDEX idx_threat_findings_tenant ON threat_findings (tenant_id, created_at DESC);
CREATE INDEX idx_threat_findings_severity ON threat_findings (severity, status);
```

---

## Error Handling & Resilience

### Groq retry behaviour

Retry is **batch-level** — the entire agent loop is reset and the batch is re-submitted fresh (no cached intermediate tool results). Backoff: 1 s → 2 s → 4 s → 8 s (max 30 s cumulative). Kafka offset is **not committed** during retries so the batch replays on restart. Once the cumulative wait exceeds 30 s, the batch is dropped and the offset is committed to prevent infinite replay.

### Idempotency & offset commit

`batch_hash = sha256("|".join(sorted(event_ids)))`. If `event_ids` is empty, `batch_hash = sha256("empty:" + tenant_id + ":" + batch_start_iso)`. The endpoint returns HTTP 200 with `{"deduplicated": true}` if the hash already exists — the agent treats this as success and commits the offset normally. This means a crash between `CreateFinding` succeeding and offset commit will produce a deduplicated no-op on replay, not a duplicate finding.

### Offset commit strategy by failure mode

| Failure scenario | Commit offset? | Rationale |
|-----------------|---------------|-----------|
| Individual tool throws (OPA, guard, MITRE) | ✅ Yes (after batch) | Tools are best-effort; finding may still be created |
| Groq unavailable — within backoff window | ❌ No | Allow replay; Groq may recover |
| Groq still down after 30 s backoff | ✅ Yes | Prevent infinite loop; audit_export has the events |
| `CreateFinding` succeeds (201 or deduplicated 200) | ✅ Yes | Normal path |
| `CreateFinding` fails (5xx / unreachable) | ✅ Yes | Log locally; do not block pipeline for one bad write |
| Queue depth > `HUNT_QUEUE_MAX` | ✅ Yes (drop oldest) | Consumer must keep up; audit_export is the safety net |
| Kafka consumer lag > 500 events | ✅ Yes (drop oldest) | Same rationale |

---

## LLM Configuration

- **Provider:** Groq (`ChatGroq` from `langchain-groq`)
- **Model:** `llama-3.3-70b-versatile` (configurable via `GROQ_MODEL` env var)
- **Temperature:** 0 (deterministic reasoning)
- **Max iterations:** 10 per batch (prevents runaway tool loops)
- **Agent type:** ReAct (`create_react_agent` from `langchain`)
- **Required:** `GROQ_API_KEY` must be set. Service will fail to start if absent — add to `.env`.

---

## Docker Compose Addition

```yaml
threat-hunting-agent:
  build: {context: ., dockerfile: services/threat-hunting-agent/Dockerfile}
  container_name: cpm-threat-hunter
  environment:
    <<: *common-env
    GROQ_API_KEY: ${GROQ_API_KEY:-}
    GROQ_MODEL: ${GROQ_MODEL:-llama-3.3-70b-versatile}
    HUNT_BATCH_WINDOW_SEC: ${HUNT_BATCH_WINDOW_SEC:-30}
    HUNT_QUEUE_MAX: ${HUNT_QUEUE_MAX:-20}
    ORCHESTRATOR_URL: http://agent-orchestrator:8094
    GUARD_MODEL_URL: http://guard-model:8200
    OPA_URL: http://opa:8181
    SPM_DB_URL: postgresql://spm_rw:${SPM_DB_PASSWORD:-spmpass}@spm-db:5432/spm
  volumes: *key-vol
  depends_on:
    <<: *depends-platform
    agent-orchestrator:
      condition: service_healthy
    guard-model:
      condition: service_healthy
    spm-db:
      condition: service_healthy
```

> **Kafka ACLs:** If `KAFKA_ENABLE_ACLS=true`, the `cpm-threat-hunter-group` consumer group needs read permission on all subscribed topics (`cpm.*.audit`, `cpm.*.decision`, `cpm.*.posture_enriched`) and write permission on `cpm.global.threat_detected`.

---

## Requirements (`requirements.txt`)

```
langchain>=0.3
langchain-groq>=0.2
langchain-community>=0.3
fastapi>=0.111
uvicorn>=0.30
httpx>=0.27
kafka-python>=2.0
redis>=5.0
psycopg2-binary>=2.9
pydantic>=2.7
```

---

## Admin UI Registration

The agent must appear in the **Inventory page** (`/admin/inventory`, Agents tab) as `ThreatHunter-AI`.

Replace the stale `ag-005` mock entry in `ui/src/admin/pages/Inventory.jsx` `ASSETS.agents` with:

```js
{
  id:            'ag-005',
  name:          'ThreatHunter-AI',
  type:          'LangChain Agent',
  risk:          'High',
  owner:         'security-ops',
  provider:      'Internal',
  policyStatus:  'partial',
  lastSeen:      'live',
  description:   'Real-time threat hunting agent. Consumes Kafka events across all tenants, '
               + 'correlates AI-layer and infrastructure signals, and opens findings for human '
               + 'investigation. Powered by Groq llama-3.3-70b-versatile.',
  linkedPolicies: ['Audit-Log v1', 'OPA-Policy v1'],
  linkedAlerts:  0,
}
```

No new UI component or route is required.

---

## Out of Scope (v1)

- Automated freeze/block actions on threat confirmation
- Dedicated threat findings dashboard in the admin UI
- Scheduled / historical hunt runs (only real-time Kafka batches)
- Multi-agent architecture (single ReAct agent is sufficient for v1)
