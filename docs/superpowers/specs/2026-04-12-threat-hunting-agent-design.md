# Threat Hunting Agent — Design Spec
**Date:** 2026-04-12
**Status:** Approved
**Author:** dany

---

## Overview

A new standalone microservice (`services/threat-hunting-agent/`) that runs a LangChain ReAct agent powered by Groq. The agent continuously consumes Kafka events, batches them into 30-second windows, and reasons over each batch to detect multi-stage AI-layer and infrastructure threats. When a threat is confirmed it opens a case in the agent-orchestrator-service and publishes a `threat_detected` event to Kafka. Humans investigate — no automated response actions.

---

## Goals

- Detect multi-stage attacks that span both AI-layer signals (jailbreaks, policy violations, guard blocks) and infrastructure signals (auth anomalies, posture spikes, unusual session patterns)
- Correlate signals that individually look benign but together indicate a campaign
- Surface confirmed threats as cases in the existing agent-orchestrator cases system
- Remain passive — no automated remediation in v1

## Non-Goals

- Automated freeze / model blocking (future v2)
- A dedicated threat hunting UI dashboard (future v2)
- Replacing the existing lexical scanner or guard model (complementary, not a replacement)

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
│   ├── postgres_tool.py            # Query audit_export, posture_snapshots, model_registry
│   ├── redis_tool.py               # Query live session data
│   ├── mitre_tool.py               # MITRE ATLAS external API queries
│   ├── opa_tool.py                 # Re-evaluate signals against OPA policy engine
│   ├── guard_tool.py               # Re-screen prompts via guard model /screen endpoint
│   └── case_tool.py                # POST to /api/v1/threat-findings on agent-orchestrator
├── consumer/
│   ├── __init__.py
│   └── kafka_consumer.py           # Batches Kafka events into 30s windows
├── db/
│   └── migrations/
│       └── 001_threat_findings.sql # New table (applied via agent-orchestrator alembic)
├── Dockerfile
└── requirements.txt
```

### Changes to existing services

**`services/agent-orchestrator-service/`** — two additions:
1. New `threat_findings` Postgres table (migration)
2. New `POST /api/v1/threat-findings` endpoint (internal only, no RBAC)

---

## Data Flow

```
Kafka topics                  Consumer (30s window)       LangChain ReAct Agent
────────────────────          ─────────────────────       ──────────────────────────────────
guard_model_block    ──┐
policy_block         ──┤      Batch accumulator           Batch arrives
lexical_block        ──┼───►  (asyncio Queue)    ──────►  │
audit_events         ──┤      max depth: 20               ├─ Observe: summarise signals
posture_updates      ──┘      drop oldest if full         │
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
```

**Batch window:** 30 seconds (configurable via `HUNT_BATCH_WINDOW_SEC`)
**Queue max depth:** 20 batches (configurable via `HUNT_QUEUE_MAX`). If exceeded, oldest batch is dropped — `audit_export` in Postgres is the source of truth for historical analysis.

---

## LangChain Tools

### 1. `QueryAuditLogs`
- **Input:** `tenant_id`, `time_range_minutes` (int), `event_types` (list, optional)
- **Action:** SELECT from `audit_export` in Postgres, ordered by timestamp DESC
- **Returns:** List of recent events with type, user_id, model, risk_score

### 2. `QueryPostureHistory`
- **Input:** `model_id` or `tenant_id`, `hours_back` (int)
- **Action:** SELECT from `posture_snapshots`, compute score delta over window
- **Returns:** Score trend, peak score, block/escalation counts

### 3. `QueryModelRegistry`
- **Input:** `model_id` or `name`
- **Action:** SELECT from `model_registry`
- **Returns:** Risk tier, approval status, provider, created_at

### 4. `QueryRedisSession`
- **Input:** `user_id`, `session_id` (optional)
- **Action:** SCAN Redis keys matching `session:{user_id}:*`, read recent prompts
- **Returns:** Session history — prompt count, time range, topics

### 5. `RescreenPrompt`
- **Input:** `prompt_text`
- **Action:** POST to `http://guard-model:8200/screen`
- **Returns:** verdict (allow/block), score, categories (S1–S15)

### 6. `EvaluateOPAPolicy`
- **Input:** signals dict (posture_score, guard_verdict, categories, etc.)
- **Action:** POST to `http://opa:8181/v1/data/spm/prompt/allow`
- **Returns:** decision (allow/block/escalate), reason, rule

### 7. `LookupMITRE`
- **Input:** `technique_id` (e.g. `AML.T0051`) or `keyword`
- **Action:** GET `https://atlas.mitre.org/api/techniques/{id}` or search endpoint
- **Returns:** Technique name, tactic, description, mitigations

### 8. `CreateFinding`
- **Input:** `title`, `severity` (low/medium/high/critical), `description`, `evidence` (dict), `ttps` (list), `tenant_id`
- **Action:** POST to `http://agent-orchestrator:8094/api/v1/threat-findings`
- **Returns:** finding ID, confirmation

---

## New Endpoint: `POST /api/v1/threat-findings`

Added to `agent-orchestrator-service`. Internal service-to-service only — not exposed outside the Docker network, no RBAC required.

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
  "tenant_id": "t1"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "title": "...",
  "severity": "high",
  "status": "open",
  "created_at": "2026-04-12T..."
}
```

---

## Data Model: `threat_findings` table

```sql
CREATE TABLE threat_findings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    description TEXT NOT NULL,
    evidence    JSONB DEFAULT '{}',
    ttps        TEXT[] DEFAULT '{}',
    tenant_id   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','investigating','closed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at   TIMESTAMPTZ
);

CREATE INDEX idx_threat_findings_tenant ON threat_findings (tenant_id, created_at DESC);
CREATE INDEX idx_threat_findings_severity ON threat_findings (severity, status);
```

---

## Error Handling & Resilience

| Failure scenario | Behaviour |
|-----------------|-----------|
| Individual tool throws | Returns structured error string; agent reasons about it and tries alternatives |
| Groq unavailable | Agent loop pauses, retries with exponential backoff (1s → 2s → 4s → max 30s) |
| Kafka consumer lag > 500 events | Oldest batch dropped; warning logged |
| Queue depth > `HUNT_QUEUE_MAX` | Oldest batch dropped; metric incremented |
| `agent-orchestrator` unreachable | `CreateFinding` tool returns error; agent logs and moves on (finding is not lost — evidence is in audit logs) |
| OPA / guard-model unreachable | Tool returns "unavailable" string; agent notes it in reasoning but continues |

---

## LLM Configuration

- **Provider:** Groq (`ChatGroq` from `langchain-groq`)
- **Model:** `llama-3.3-70b-versatile` (configurable via `GROQ_MODEL` env var)
- **Temperature:** 0 (deterministic reasoning)
- **Max iterations:** 10 per batch (prevents runaway tool loops)
- **Agent type:** ReAct (`create_react_agent` from `langchain`)

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
  volumes: *key-vol
  depends_on:
    <<: *depends-platform
    agent-orchestrator:
      condition: service_healthy
    guard-model:
      condition: service_healthy
```

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

## Out of Scope (v1)

- Automated freeze/block actions on threat confirmation
- Admin UI dashboard for threat findings
- Scheduled / historical hunt runs (only real-time Kafka batches)
- Multi-agent architecture (single ReAct agent is sufficient for v1)
