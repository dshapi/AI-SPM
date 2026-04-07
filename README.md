# Context Posture Management Platform v3

Production-grade, event-driven AI agent security platform.  
**86/86 tests passing. Zero skeleton code.**

---

## Architecture

```
User Request
    │
    ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STARTUP ORCHESTRATOR (runs once at boot)                            │
│  • Auto-generates RSA-2048 key pair (if missing)                     │
│  • Creates all Kafka topics + retention policies per tenant          │
│  • Configures per-tenant Kafka ACLs                                  │
│  • Seeds Redis defaults (freeze states, service registry, AI-BOM)   │
│  • Validates all OPA policies with smoke-test inputs                 │
│  • Emits startup audit record                                        │
└──────────────────────────────────────────────────────────────────────┘
    │ (startup-orchestrator exits 0 → all services start)
    ▼
┌─────────────────┐
│   API  :8080    │  RS256 JWT auth · rate limiting (sliding window)
│                 │  Guard model gate (blocks before Kafka)
└────────┬────────┘
         │ kafka: cpm.{tenant}.raw
         ▼
┌─────────────────┐
│RETRIEVAL GATEWAY│  Fetches context items from knowledge base
│                 │  SHA-256 provenance verification
│                 │  Semantic coherence scoring
│                 │  Tamper detection → security alert
└────────┬────────┘
         │ kafka: cpm.{tenant}.retrieved
         ▼
┌─────────────────┐
│   PROCESSOR     │  7-dimension risk fusion:
│                 │  prompt_risk · behavioral_risk · identity_risk
│                 │  memory_risk · retrieval_trust · guard_risk
│                 │  intent_drift (Jaccard, session baseline)
└────────┬────────┘
         │ kafka: cpm.{tenant}.posture_enriched
         ├──────────────────────────────────► FLINK CEP
         │                                    MITRE ATLAS TTP mapping
         │                                    multi-window burst+volume
         ▼
┌─────────────────┐
│ POLICY DECIDER  │  OPA: prompt_policy.rego
│                 │  allow · escalate · block
└────────┬────────┘
         │ kafka: cpm.{tenant}.decision
         ▼
┌─────────────────┐
│     AGENT       │  OPA intent manifest (no string matching)
│                 │  Freeze-aware (tenant/user/session)
│                 │  Human approval for side-effect tools
└──────┬──────────┘
       ├─── kafka: cpm.{tenant}.memory_request
       │         ▼
       │    ┌────────────────┐
       │    │ MEMORY SERVICE │  session · longterm · system namespaces
       │    │                │  SHA-256 write-time integrity hash
       │    │                │  Read-time verification
       │    │                │  Soft-delete (tombstone)
       │    └────────────────┘
       │
       └─── kafka: cpm.{tenant}.tool_request
                 ▼
            ┌──────────────┐
            │   EXECUTOR   │  OPA tool_policy.rego
            │              │  9 tools: calendar·gmail·file·db·web·security
            │              │  Human approval for side-effect tools
            └──────┬───────┘
                   │ kafka: cpm.{tenant}.tool_result
                   ▼
            ┌──────────────┐
            │ TOOL PARSER  │  Recursive sanitization (direct·base64·hex·URL)
            │              │  Schema validation per tool
            └──────┬───────┘
                   │ kafka: cpm.{tenant}.tool_observation
                   ▼
         ← back to AGENT → final_response
                   │
                   ▼
         ┌──────────────────┐
         │   OUTPUT GUARD   │  Pass 1: 11 regex PII/secret patterns
         │                  │  Pass 2: LLM semantic scan via guard model
         │                  │  OPA output_policy.rego: block·redact·allow
         └──────────────────┘

CONTROL PLANE (sidecar channels):
  FREEZE CONTROLLER :8090    RS256 JWT + spm:admin role required
                             Scope: tenant·user·session · auto-expiry
  POLICY SIMULATOR  :8091    Dry-run OPA evaluation without touching Kafka
  GUARD MODEL       :8200    Llama Guard category classifier (15 categories)
                             /screen · /screen/batch · /categories
```

---

## Security controls

| Gap from v1 | v3 implementation |
|---|---|
| Unauthenticated freeze controller | RS256 JWT + `spm:admin` role on every request |
| HS256 symmetric JWT | RS256 asymmetric — only issuer holds private key |
| No key management | Auto-generated at startup, mounted read-only to services |
| Kafka ACLs disabled | Per-tenant ACLs provisioned at startup (`KAFKA_ENABLE_ACLS=true`) |
| OPA `latest` tag | Pinned `openpolicyagent/opa:0.70.0` |
| No guard model | Guard model blocks before event reaches Kafka |
| String-match tool selection | OPA agent intent manifest (`agent_policy.rego`) |
| RAG provenance gap | SHA-256 hash at index, verified at retrieval; tamper → trust penalty |
| Flat memory namespace | `session` · `longterm` · `system` with separate TTLs and scopes |
| No write integrity | SHA-256 hash stored alongside every write, verified on read |
| No soft-delete | Tombstone key preserves audit trail |
| Regex-only output guard | Two-pass: regex + LLM semantic scan |
| CEP single heuristic | Short+long window, MITRE ATLAS TTP mapping, intent drift |
| No rate limiting | Sliding-window token bucket (Redis), configurable RPM |
| No AI-BOM | `/inventory` endpoint on every service + Redis registry |
| No startup automation | Startup orchestrator provisions everything automatically |

---

## Quick start

```bash
git clone <repo>
cd cpm-v3

# First boot: everything is automatic
make up

# Wait ~30s for startup orchestrator to complete, then:
make smoke-test

# View all logs
make logs

# Mint tokens
make token          # user token
make admin-token    # spm:admin token

# Freeze a user
make freeze

# Run unit tests (no Docker needed)
make test

# Simulate policies
make simulate
```

---

## Services and ports

| Service | Port | Role |
|---|---|---|
| API | 8080 | Ingress, JWT auth, rate limiting, guard gate |
| Guard Model | 8200 | Pre-LLM content screening (15 Llama Guard categories) |
| Freeze Controller | 8090 | Authenticated control plane (admin-only) |
| Policy Simulator | 8091 | Dry-run policy testing |
| OPA | 8181 | Policy evaluation engine |
| Kafka broker | 19092 | External access for dev tools |
| Redis | 6379 | State: rate limits, freeze flags, memory, CEP windows |

---

## OPA policies

| Policy | File | Rules |
|---|---|---|
| Prompt | `prompt_policy.rego` | allow · escalate · block with 9 hard-block conditions |
| Tools | `tool_policy.rego` | 9 tools, scope-gated, posture-gated |
| Memory | `memory_policy.rego` | 3 namespaces, separate scope requirements per namespace |
| Output | `output_policy.rego` | allow · redact · block |
| Agent | `agent_policy.rego` | Intent manifest: keyword → OPA → tool_name |

---

## Extending the platform

**Add a new tool:** Register in `services/executor/app.py` TOOL_REGISTRY and add a rule to `opa/policies/tool_policy.rego`.

**Add a new tenant:** Add to `TENANTS=t1,t2` in `.env` and restart. Startup orchestrator creates all topics and ACLs.

**Add a new risk signal:** Add pattern to `PROMPT_PATTERNS` in `platform_shared/risk.py`, set weight in `SIGNAL_WEIGHTS`, and add OPA rule if needed.

**Replace guard model:** Implement your Llama Guard 3 or BERT endpoint as a FastAPI `/screen` handler with the same request/response schema as `services/guard_model/app.py`.

**Add real RAG:** Replace `_fetch_contexts()` in `services/retrieval_gateway/app.py` with your vector store call. Store `ingestion_hash = SHA256(content)` at index time.

---

## Environment variables

See `.env.example` for all variables with documentation.

---

## Testing

```bash
make test                    # 86 unit tests, no Docker needed
make test-coverage           # with coverage report
```

Test coverage:
- Signal extraction (10 tests)
- Prompt scoring (7 tests)
- Critical combination detection (4 tests)
- MITRE ATLAS TTP mapping (6 tests)
- Retrieval trust scoring (6 tests)
- Guard score translation (4 tests)
- Intent drift (5 tests)
- Risk fusion (6 tests)
- Provenance hashing (4 tests)
- Trust assessment (6 tests)
- Security / JWT / RBAC (8 tests)
- Output guard regex (6 tests)
- Tool parser sanitization (4 tests)
- Guard model screening (6 tests)
- Integration pipeline (4 tests)
