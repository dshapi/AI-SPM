# Orbyx AI SPM  - AI Security Posture Management 

 > AI security posture management (AI-SPM) is a comprehensive approach to maintaining the security and integrity of artificial intelligence (AI) and machine learning (ML) systems. It involves continuous monitoring, assessment, and improvement of the security posture of AI models, data, and infrastructure. AI-SPM includes identifying and addressing vulnerabilities, misconfigurations, and potential risks associated with AI adoption, as well as ensuring compliance with relevant privacy and security regulations.

This opensource project dedicated to implementing Enterprise level AI-SPM. By doing so organizations can proactively protect their AI systems from threats, minimize data exposure, and maintain the trustworthiness of their AI applications (agents, mpc servers, models and more).
Your organization is putting everything it’s got into AI applications—are you prepared to secure them? <br>
Before you answer, think about these specific questions:<br>
Can you identify all the shadow AI (including AI models, agents and associated resources) that's in your environment?<br>
Are you effectively securing AI data to prevent data poisoning, bias and compliance breaches?<br>
Do you know how to prioritize critical AI risks with context?<br>
Are you confident that you can detect and respond quickly to suspicious activity in AI pipelines?<br>
If you answered “not sure,” or “no” to even one of those questions, then you should take a closer look in to this project. It’s the way to see the current state of your AI ecosystem security. 

Discover your AI models , agents, and associated resources security.
Identify risks across AI application supply chains/piplines and agents - that can lead to data exfiltration and misuse of resources.
Implement proper governance controls around AI usage.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) ![Version](https://img.shields.io/badge/version-1.0.0-blue) ![Language](https://img.shields.io/badge/language-python-yellow) [![GitHub](https://img.shields.io/badge/GitHub-%23121011.svg?logo=github&logoColor=white)](https://github.com/dshapi/AI-SPM/) ![OBS package build status](https://img.shields.io/obs/openSUSE%3ATools/osc/Debian_11/x86_64)

<p align="center"><img src="/ui/public/logo.png" width="50%"></p>
<div align="center">
<h1>OrbiX AI SPM </h1>
</div>
 

## 📋 Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Tech Stack](#tech-stack)
- [Contributing](#contributing)

## ℹ️ Project Information

- **👤 Author:** Dany Shapiro
  - [![linkedin](https://www.readmecodegen.com/api/social-icon?name=linkedin&size=16&link=https%3A%2F%2Flinkedin.com%2Fin%2Fdanyshapiro)](https://linkedin.com/in/danyshapiro) https://www.linkedin.com/in/danyshapiro/
- **📦 Version:** 1.0.0
- **📄 License:** Apache-2.0
- **📂 Repository:** [https://github.com/dshapi/AI-SPM](https://github.com/dshapi/AI-SPM)

## Features

## Platform at a Glance

|                          |                                                                  |
|--------------------------|------------------------------------------------------------------|
| **Microservices**        | 16                                                               |
| **OPA Policies**         | 6                                                                |
| **Kafka Topics**         | 12+                                                              |
| **Admin User Interface** | 1 ( Admin portal )                                               |
| **Supported Models**     | Anthropic / OpenAI-compatible endpoint / 3rd party model imprort 
| **Compliance Framework** | NIST AI RMF (GOVERN / MAP / MEASURE / MANAGE)                    |

---

## Table of Contents

- [Security & Access Control](#security--access-control)
- [LLM Integration & Gateway](#llm-integration--gateway)
- [Conversation Memory](#conversation-memory)
- [Observability & Compliance](#observability--compliance)
- [Infrastructure & Event Pipeline](#infrastructure--event-pipeline)
- [UI & Developer Experience](#ui--developer-experience)
- [Roadmap](#roadmap)

---

<div align="center">
<h2>Admin Portal - main dashboard </h2>
<h3>An AI Security Posture Management control plane providing real-time visibility, risk detection, and policy enforcement across agents, models, and context flows.</h3>
</div>

<p align="center"><img src="/docs/OrbiX.jpg" width="100%"></p>

<div align="center">
<h2>Admin Portal - Inventory </h2>
</div>

<p align="center"><img src="/docs/OrbiX2.jpg" width="100%"></p>

---

## Security & Access Control

### Authentication & Authorization

| Feature | Description | Component |
|---|---|---|
| **RS256 JWT Auth** | Every API request validated against platform-generated RSA key pair. Tokens are short-lived and audience-scoped. | CPM API |
| **Role-Based Access** | Roles (`spm:admin`, `spm:auditor`, `user`) enforced on all SPM endpoints via OPA policy evaluation per request. | OPA / CPM API |
| **Dev Token Endpoint** | `/dev-token` generates 24-hour demo JWTs signed by the platform's own private key — no external IdP needed for development. | CPM API |
| **Per-User Rate Limiting** | Sliding window in Redis: 60 req/min with burst allowance of 10. Returns `429` with retry headers. | CPM API / Redis |
| **Tenant Isolation** | All events, topics, and audit records are scoped by `tenant_id`. Multi-tenant from day one. | All services |

### Prompt Security

| Feature | Description | Component |
|---|---|---|
| **Guard Model Screening** | Every prompt passes through Llama Guard 3 (8B) before reaching the LLM. Blocks harmful content with category labels. | Guard Model |
| **Prompt Injection Detection** | Memory service scans writes for injection patterns: `ignore previous instructions`, `act as if`, `override instructions` etc. | Memory Service |
| **OPA Prompt Policy** | Rego policy evaluates posture score, intent drift, guard verdict, and auth context. Decisions: `allow` / `escalate` / `block`. | OPA |
| **Posture-Based Blocking** | Requests with risk score ≥ 0.70 are auto-blocked. 0.30–0.70 escalated. Below 0.30 allowed. | Policy Decider |
| **Intent Drift Detection** | Jaccard similarity tracks deviation from session baseline. High drift triggers escalation. | Flink CEP |

### Output Security

| Feature | Description | Component |
|---|---|---|
| **Secret Scanning** | Regex detects API keys (`sk-`, `ghp_`, `AKIA*`), Bearer tokens, passwords in LLM responses. | CPM API |
| **PII Detection** | Detects email addresses, US SSNs, and phone numbers in responses. Triggers redaction or block via OPA output policy. | CPM API |
| **Output Redaction** | Matched secrets and PII replaced with `[REDACTED-SECRET]` / `[REDACTED-PII]` before reaching the user. | CPM API |
| **OPA Output Policy** | Second-pass policy evaluation on LLM output. Considers `contains_secret`, `contains_pii`, and LLM verdict. | OPA |
| **Output Guard LLM** | Optional second-pass LLM semantic scan for subtle policy violations not caught by regex. | Output Guard |

---

## LLM Integration & Gateway

### Model Management

| Feature | Description | Component |
|---|---|---|
| **Model Registry** | Full lifecycle: register → approve → freeze → retire. Tracked with provider, version, risk tier, and approver. | SPM API / DB |
| **Model Gate** | CPM API checks SPM approval status before every LLM call. Unapproved models return `403`. Fail-closed by design. | CPM API / OPA |
| **Risk Tier Classification** | Models classified as `low` / `medium` / `high` risk. Influences OPA policy thresholds and compliance evidence requirements. | SPM API |
| **Multi-Model Support** | Swap between Claude Haiku, Sonnet, Opus via `ANTHROPIC_MODEL` env var. Architecture supports any OpenAI-compatible endpoint. | CPM API |
| **Model Freeze** | Freeze controller suspends a model from serving traffic in real time via Kafka `freeze_control` topic. | Freeze Controller |

### Agentic Tools

| Feature | Description | Component |
|---|---|---|
| **Web Search** | Claude autonomously searches the web via Tavily API when prompted about current events or real-time data. | CPM API / Tavily |
| **Web Fetch** | Claude fetches and reads any URL provided by the user. HTML cleaned with BeautifulSoup before injection into context. | CPM API |
| **Tool Authorization** | OPA `tool_policy.rego` evaluates every tool call against posture score, intent, and auth context before execution. | OPA / Executor |
| **Tool Execution Pipeline** | Tool requests flow: `tool_request` → OPA auth → Executor → `tool_result`. Side-effect tools require approval. | Executor / Agent |
| **Approval Workflow** | Write/send/delete tools emit to `approval_request` topic and await `approval_result` before executing. | Executor |

---

## Conversation Memory

| Feature | Description | Component |
|---|---|---|
| **Cross-Session Memory** | Conversation history stored in Redis with 30-day TTL. Claude receives last 20 turns as context on every request. | CPM API / Redis |
| **Integrity Verification** | Every memory write generates a SHA-256 hash. Reads verify the hash — `integrity_ok=False` triggers a security alert. | Memory Service |
| **Namespace Scoping** | Three namespaces: `session` (1h TTL), `longterm` (30d TTL), `system` (24h TTL). OPA policy controls access per namespace. | Memory Service |
| **Injection Protection** | Memory writes scanned for prompt injection patterns before storage. Malicious writes are rejected and audited. | Memory Service |
| **Soft Delete** | Memory deletes create tombstones rather than hard deleting. Audit trail preserved for forensics. | Memory Service |

---

## Observability & Compliance

### Prometheus Metrics

| Metric | Description |
|---|---|
| `spm_model_risk_score` | Per-model gauge updated on every posture event. Labels: `model_id`, `tenant_id`. |
| `spm_enforcement_actions_total` | Counter tracking `block` / `escalate` / `allow` decisions. Labels: `action`, `tenant_id`. |
| `spm_snapshot_lag_seconds` | Seconds since last posture snapshot write. Updated every 15s by background thread. |
| `spm_compliance_coverage_pct` | NIST AI RMF coverage % per function. Labels: `function` (GOVERN, MAP, MEASURE, MANAGE, OVERALL). |

### Grafana Dashboards

**Engineering Dashboard**
- Model Risk Score over time (time-series)
- Enforcement Actions total (stat)
- Snapshot Lag (gauge with thresholds)
- Model Lifecycle Status (table — name, version, status, risk tier, approver)
- Web Tool Calls — every search/fetch with user, session, exact query (table)
- Tool Type Breakdown — Search vs Fetch split (donut chart)
- Blocked Requests — guard blocks, output blocks, model gate blocks with reason (table)

**Compliance Dashboard**
- NIST AI RMF Coverage per function (gauge panels)
- Overall Coverage % (stat)
- Compliance Gap Table (table — control, status, evidence)

### Audit & Compliance

| Feature | Description | Component |
|---|---|---|
| **Tamper-Evident Audit Log** | All events written to Kafka audit topic and mirrored to `audit_export` table in PostgreSQL. `ON CONFLICT DO NOTHING` ensures idempotency. | SPM Aggregator / DB |
| **NIST AI RMF Alignment** | Compliance evidence mapped to GOVERN, MAP, MEASURE, MANAGE functions. Coverage % computed per function. | SPM API / DB |
| **MITRE ATLAS TTP Mapping** | CEP maps behavioural patterns to ATLAS TTPs (e.g. `AML.T0048`, `AML.T0051.000`). Attached to security alerts. | Flink CEP |
| **Compliance Evidence** | Attach evaluation results, test reports, and approval notes to each model as structured evidence records. | SPM API |
| **Startup Audit Record** | Platform startup writes an audit record per tenant. Baseline timestamp for forensic investigation. | Startup Orchestrator |

### Behavioural Analytics

| Feature | Description | Component |
|---|---|---|
| **Burst Detection** | Tracks request volume in a 2-minute window. >5 events triggers burst alert with ATLAS TTP code. | Flink CEP |
| **Sustained Volume Detection** | 1-hour rolling window detects sustained high-volume usage (>15 events). | Flink CEP |
| **Critical Combo Detection** | Specific signal combinations (e.g. exfiltration + high posture + PII) trigger immediate critical escalation. | Flink CEP |
| **Session Signal Accumulation** | Signals accumulate across a session. Repeated suspicious signals compound the risk score. | Flink CEP |
| **Posture Snapshot History** | Risk scores snapshotted every 5 minutes per model per tenant. Rolling average over configurable N snapshots. | SPM Aggregator |

---

## Infrastructure & Event Pipeline

### Kafka Event Bus

| Topic | Publisher | Consumer |
|---|---|---|
| `{tenant}.raw` | CPM API | Processor |
| `{tenant}.posture_enriched` | Processor | Policy Decider, Flink CEP, SPM Aggregator |
| `{tenant}.decision` | Policy Decider | Agent |
| `{tenant}.tool_request` | Agent / Tool Parser | Executor |
| `{tenant}.tool_result` | Executor | Agent |
| `{tenant}.audit` | All services | SPM Aggregator → `audit_export` |
| `{tenant}.memory_request` | Agent | Memory Service |
| `{tenant}.memory_result` | Memory Service | Agent |
| `{tenant}.approval_request` | Executor | (human reviewer) |
| `{tenant}.freeze_control` | Freeze Controller | All consumers |

### Platform Services

| Service | Role |
|---|---|
| **Startup Orchestrator** | Validates OPA policies, waits for Kafka, creates topics, registers models, smoke-tests all policies on boot. |
| **Processor** | Enriches raw events with posture scoring, intent analysis, CEP signals. Publishes `PostureEnrichedEvent`. |
| **Policy Decider** | Evaluates OPA prompt policy on enriched events. Publishes `DecisionEvent`. |
| **Agent Orchestrator** | Plans tool execution and memory access based on OPA intent manifest. |
| **Executor** | Runs authorised tools. Implements tool registry with approval flow for side-effect operations. |
| **Tool Parser** | Extracts and validates structured tool calls from LLM output before forwarding to executor. |
| **Memory Service** | Scoped key-value store in Redis with integrity hashing, injection protection, and soft delete. |
| **Output Guard** | Optional second-pass LLM semantic scan of responses for subtle policy violations. |
| **Retrieval Gateway** | RAG-ready retrieval service. Scores document chunks for trust before injecting into LLM context. |
| **Freeze Controller** | Real-time model suspension via Kafka. Freeze propagates to all consumers within milliseconds. |
| **Policy Simulator** | Dry-run any policy change before deployment. Returns allow/block/escalate without touching live traffic. |
| **SPM Aggregator** | Consumes posture and audit events, writes to PostgreSQL, updates Prometheus metrics. |
| **SPM API** | REST API for model registry, compliance evidence, approval workflow, and audit export. |
| **Guard Model** | Llama Guard 3 (8B) inference service. Screens every prompt for harmful content categories. |

---

## UI & Developer Experience

| Feature                     | Description |
|-----------------------------|---|
| **Orbyx Admin Portal**      | An AI Security Posture Management control plane providing real-time visibility, risk detection, and policy enforcement across agents, models, and context flows.. |
| **Orbyx Chat UI**           | React + Vite chat interface with landing state, simulated streaming, model selector, and New Chat button. |
| **Tool Use Badges**         | Web search and fetch tool calls rendered as blue pill badges above the response text. |
| **Security Footer**         | Persistent footer: *"All messages are screened by the Orbyx security layer"* — visible on every message. |
| **Mock Fallback**           | UI falls back to mock responses when API is unreachable. Graceful degradation for demos. |
| **Cross-Session Memory UI** | Claude remembers previous conversations across sessions — no user action required. |
| **Model Selector**          | Switch between Claude Haiku / Sonnet / Opus from the chat header or landing page. |

#TODO: add more screenshorts from the admin portal
---

## Roadmap

Features not yet implemented — candidates for the next sprint:

- [ ] **Real token streaming** — true SSE streaming from Claude instead of simulated word-by-word reveal
- [ ] **Human-in-the-loop escalation** — middle-risk requests (0.30–0.70) route to a human reviewer queue
- [ ] **Automated compliance reports** — one-click PDF/DOCX export of NIST AI RMF posture for auditors
- [ ] **Model drift detection** — alert when a model's risk score distribution shifts after a provider update
- [ ] **Shadow mode** — run a candidate model in parallel without serving its responses, compare metrics
- [ ] **Cost tracking** — token spend per tenant/user/model tracked in Prometheus and Grafana
- [ ] **Alerting** — Slack/email when blocked requests spike above configurable threshold
- [ ] **Hallucination scoring** — post-response confidence estimation using a lightweight verifier model
- [ ] **Local model support** — Ollama/vLLM integration for HuggingFace models on Apple Silicon or GPU
- [ ] **A/B model routing** — split traffic between two approved models and compare quality/risk metrics
- [ ] **Fine-grained tool RBAC** — different user roles get access to different tools
- [ ] **Session replay** — replay any conversation in the audit UI for incident investigation

---

*Orbyx AI SPM v3.0 · April 2026*


## Installation


## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Clone & Configure](#clone--configure)
3. [API Keys](#api-keys)
4. [First Boot](#first-boot)
5. [Verify the Platform](#verify-the-platform)
6. [Access the UI & Dashboards](#access-the-ui--dashboards)
7. [Run the Smoke Test](#run-the-smoke-test)
8. [Stopping & Cleaning Up](#stopping--cleaning-up)
9. [Troubleshooting](#troubleshooting)
10. [Environment Reference](#environment-reference)

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| **Docker Desktop** | 4.25+ | Enable "Use containerd for pulling and storing images" for best performance |
| **Docker Compose** | v2.20+ | Bundled with Docker Desktop |
| **Git** | any | To clone the repo |
| **Make** | any | `brew install make` (macOS) / `apt install make` (Linux) |
| **4 GB free RAM** | — | Kafka + all services |
| **2 GB free disk** | — | Images + volumes |

> All images are published for `linux/arm64`. The compose file already sets the correct platform tags.

---

## Clone & Configure

```bash
git clone https://github.com/your-org/orbyx-aispm.git
cd orbyx-aispm
```

Copy the example environment file:

```bash
cp .env.example .env
```

> **Do not** commit your `.env` file — it is already in `.gitignore`.

---

## API Keys

Open `.env` in any editor and fill in the two required secrets:

### Anthropic (required for Claude responses)

```dotenv
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
ANTHROPIC_MODEL=claude-sonnet-4-6      # or claude-haiku-4-5-20251001 / claude-opus-4-6
```

Get a key at [console.anthropic.com](https://console.anthropic.com).

### Tavily (required for web search tool)

```dotenv
TAVILY_API_KEY=tvly-xxxxxxxxxxxx
```

Get a free key at [app.tavily.com](https://app.tavily.com). Without this key, the web search tool will silently skip search calls and Claude will answer from its training data only.

### Groq (optional — accelerates Llama Guard 3)

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxx
GROQ_MODEL=llama-guard-3-8b
```

Get a free key at [console.groq.com](https://console.groq.com). Without this, the platform falls back to a built-in regex classifier for content moderation (still functional, just less accurate).

---

## First Boot

```bash
make up
```

This single command will:

1. Build all Docker images from source
2. Start the full infrastructure stack (Kafka, Redis, PostgreSQL, OPA, Prometheus, Grafana)
3. Run the **startup orchestrator**, which automatically:
   - Generates RSA key-pair into `./keys/` (used for JWT signing)
   - Creates Kafka topics and ACLs per tenant
   - Seeds OPA with the default policy bundle
   - Registers the default AI model in the SPM registry
4. Start all platform services (API, Guard Model, CEP, SPM, UI, etc.)

The orchestrator exits when provisioning is complete. Expect the first build to take **3–5 minutes** depending on your internet speed. Subsequent starts are near-instant.

You'll see this when it's ready:

```
✓ Platform started.
  API:               http://localhost:8080
  Guard Model:       http://localhost:8200
  Freeze Controller: http://localhost:8090
  Policy Simulator:  http://localhost:8091
  OPA:               http://localhost:8181
```

---

## Verify the Platform

Check that all services are healthy:

```bash
make status
```

Expected output shows all containers as `Up` or `healthy`. The API and Guard Model health endpoints will return JSON `{"status": "ok"}`.

Alternatively:

```bash
docker compose ps
```

---

## Access the UI & Dashboards

| Service | URL | Credentials |
|---|---|---|
| **Orbyx Chat UI** | http://localhost:3000 | Auto-login via JWT (click "Sign In") |
| **Grafana** | http://localhost:3001 | `admin` / `admin` (change on first login) |
| **Prometheus** | http://localhost:9090 | No auth |
| **OPA** | http://localhost:8181 | No auth |
| **SPM API** | http://localhost:8092 | JWT Bearer token required |
| **Policy Simulator** | http://localhost:8091 | JWT Bearer token required |

### Grafana Dashboards

Three dashboards are pre-provisioned and load automatically:

- **AI SPM Overview** — posture scores, enforcement actions, risk trends
- **Engineering** — tool calls, blocked requests, model performance, CEP events
- **Compliance** — NIST AI RMF control coverage, audit trail

---

## Run the Smoke Test

Send a real request through the full pipeline and verify end-to-end:

```bash
make smoke-test
```

This will:
1. Mint a demo JWT
2. Send `"What meetings do I have today?"` → expects a Claude response
3. Send a prompt injection attempt → expects `HTTP 400` (blocked)

A passing run ends with:

```
✓ Smoke test PASSED
```

---

## Stopping & Cleaning Up

**Stop all services (keeps data):**

```bash
make down
# or
docker compose down
```

**Stop and wipe all data (volumes, generated keys):**

```bash
make clean
```

> ⚠️ `make clean` deletes the RSA keys in `./keys/`. New keys will be auto-generated on next `make up`, which invalidates any previously minted JWTs.

---

## Troubleshooting

### Services fail to start / `make up` exits early

Check the orchestrator logs:

```bash
docker compose logs startup-orchestrator
```

Common causes: Kafka not ready in time. Re-run `make up` — it is idempotent.

### `cpm-startup-orchestrator` not found

Use the **service name** (not the container name) with `docker compose`:

```bash
docker compose restart startup-orchestrator   # ✓ correct
docker compose restart cpm-startup-orchestrator  # ✗ wrong
```

### Chat UI shows `[object Object]` error

This indicates a model gate rejection. Check that `LLM_MODEL_ID` in `.env` is blank:

```dotenv
LLM_MODEL_ID=
```

Then restart the API:

```bash
docker compose up -d --build api
```

### `404 model not found` from Anthropic

The model name in your `.env` is outdated. Update to a current model:

```dotenv
ANTHROPIC_MODEL=claude-sonnet-4-6
```

Current valid model IDs:

| Label | Model ID |
|---|---|
| Claude Haiku | `claude-haiku-4-5-20251001` |
| Claude Sonnet | `claude-sonnet-4-6` |
| Claude Opus | `claude-opus-4-6` |

### Grafana panels show "No data"

Panels populate after the first real request is processed. Run `make smoke-test` to generate events, then refresh the dashboard.

### Port conflict

If any port (3000, 3001, 8080, etc.) is already in use, edit `docker-compose.yml` and change the host-side port mapping:

```yaml
ports:
  - "3100:3000"  # change 3000 → 3100 (host:container)
```

### Rebuilding a single service after code changes

```bash
docker compose up -d --build api          # rebuild API only
docker compose up -d --build ui           # rebuild UI only
docker compose up -d --build spm-aggregator  # rebuild SPM aggregator
```

---

## Environment Reference

The following variables can be tuned in `.env`. All have sane defaults and only the API keys need to be set for a working installation.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model to use |
| `TAVILY_API_KEY` | *(optional)* | Tavily key for web search tool |
| `GROQ_API_KEY` | *(optional)* | Groq key for Llama Guard 3 |
| `TENANTS` | `t1` | Comma-separated tenant IDs |
| `RATE_LIMIT_RPM` | `60` | Max requests per minute per user |
| `GUARD_MODEL_ENABLED` | `true` | Enable/disable content guard |
| `POSTURE_BLOCK_THRESHOLD` | `0.70` | Risk score at which requests are blocked |
| `CEP_SHORT_WINDOW_SEC` | `120` | Burst detection window (seconds) |
| `CEP_LONG_WINDOW_SEC` | `3600` | Sustained volume window (seconds) |
| `MEMORY_LONGTERM_TTL_SEC` | `2592000` | Cross-session memory TTL (30 days) |
| `SPM_SNAPSHOT_INTERVAL_SEC` | `300` | Posture snapshot interval (5 min) |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `REDIS_PASSWORD` | *(blank)* | Redis password (blank = no auth) |
| `SPM_DB_PASSWORD` | `spmpass` | PostgreSQL password for SPM DB |
| `LLM_MODEL_ID` | *(blank)* | SPM model registry ID (leave blank to bypass gate) |

---

## Quick-Reference Commands

```bash
make up              # Start everything
make down            # Stop everything
make status          # Health check
make logs            # Tail all logs
make logs-api        # Tail API logs only
make smoke-test      # End-to-end test
make token           # Mint a demo user JWT
make admin-token     # Mint an admin JWT
make freeze          # Freeze demo user (requires admin token)
make unfreeze        # Unfreeze demo user
make clean           # Wipe all data and keys
```

---

## Usage

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Clone & Configure](#clone--configure)
3. [API Keys](#api-keys)
4. [First Boot](#first-boot)
5. [Verify the Platform](#verify-the-platform)
6. [Access the UI & Dashboards](#access-the-ui--dashboards)
7. [Run the Smoke Test](#run-the-smoke-test)
8. [Stopping & Cleaning Up](#stopping--cleaning-up)
9. [Troubleshooting](#troubleshooting)
10. [Environment Reference](#environment-reference)

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| **Docker Desktop** | 4.25+ | Enable "Use containerd for pulling and storing images" for best performance |
| **Docker Compose** | v2.20+ | Bundled with Docker Desktop |
| **Git** | any | To clone the repo |
| **Make** | any | `brew install make` (macOS) / `apt install make` (Linux) |
| **4 GB free RAM** | — | Kafka + all services |
| **2 GB free disk** | — | Images + volumes |

> **Apple Silicon (M1/M2/M3):** All images are published for `linux/arm64`. The compose file already sets the correct platform tags.

---

## Clone & Configure

```bash
git clone https://github.com/your-org/orbyx-aispm.git
cd orbyx-aispm
```

Copy the example environment file:

```bash
cp .env.example .env
```

> **Do not** commit your `.env` file — it is already in `.gitignore`.

---

## API Keys

Open `.env` in any editor and fill in the two required secrets:

### Anthropic (required for Claude responses)

```dotenv
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
ANTHROPIC_MODEL=claude-sonnet-4-6      # or claude-haiku-4-5-20251001 / claude-opus-4-6
```

Get a key at [console.anthropic.com](https://console.anthropic.com).

### Tavily (required for web search tool)

```dotenv
TAVILY_API_KEY=tvly-xxxxxxxxxxxx
```

Get a free key at [app.tavily.com](https://app.tavily.com). Without this key, the web search tool will silently skip search calls and Claude will answer from its training data only.

### Groq (optional — accelerates Llama Guard 3)

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxx
GROQ_MODEL=llama-guard-3-8b
```

Get a free key at [console.groq.com](https://console.groq.com). Without this, the platform falls back to a built-in regex classifier for content moderation (still functional, just less accurate).

---

## First Boot

```bash
make up
```

This single command will:

1. Build all Docker images from source
2. Start the full infrastructure stack (Kafka, Redis, PostgreSQL, OPA, Prometheus, Grafana)
3. Run the **startup orchestrator**, which automatically:
   - Generates RSA key-pair into `./keys/` (used for JWT signing)
   - Creates Kafka topics and ACLs per tenant
   - Seeds OPA with the default policy bundle
   - Registers the default AI model in the SPM registry
4. Start all platform services (API, Guard Model, CEP, SPM, UI, etc.)

The orchestrator exits when provisioning is complete. Expect the first build to take **3–5 minutes** depending on your internet speed. Subsequent starts are near-instant.

You'll see this when it's ready:

```
✓ Platform started.
  API:               http://localhost:8080
  Guard Model:       http://localhost:8200
  Freeze Controller: http://localhost:8090
  Policy Simulator:  http://localhost:8091
  OPA:               http://localhost:8181
```

---

## Verify the Platform

Check that all services are healthy:

```bash
make status
```

Expected output shows all containers as `Up` or `healthy`. The API and Guard Model health endpoints will return JSON `{"status": "ok"}`.

Alternatively:

```bash
docker compose ps
```

---

## Access the UI & Dashboards

| Service | URL | Credentials |
|---|---|---|
| **Orbyx Chat UI** | http://localhost:3000 | Auto-login via JWT (click "Sign In") |
| **Grafana** | http://localhost:3001 | `admin` / `admin` (change on first login) |
| **Prometheus** | http://localhost:9090 | No auth |
| **OPA** | http://localhost:8181 | No auth |
| **SPM API** | http://localhost:8092 | JWT Bearer token required |
| **Policy Simulator** | http://localhost:8091 | JWT Bearer token required |

### Grafana Dashboards

Three dashboards are pre-provisioned and load automatically:

- **AI SPM Overview** — posture scores, enforcement actions, risk trends
- **Engineering** — tool calls, blocked requests, model performance, CEP events
- **Compliance** — NIST AI RMF control coverage, audit trail

---

## Run the Smoke Test

Send a real request through the full pipeline and verify end-to-end:

```bash
make smoke-test
```

This will:
1. Mint a demo JWT
2. Send `"What meetings do I have today?"` → expects a Claude response
3. Send a prompt injection attempt → expects `HTTP 400` (blocked)

A passing run ends with:

```
✓ Smoke test PASSED
```

---

## Stopping & Cleaning Up

**Stop all services (keeps data):**

```bash
make down
# or
docker compose down
```

**Stop and wipe all data (volumes, generated keys):**

```bash
make clean
```

> ⚠️ `make clean` deletes the RSA keys in `./keys/`. New keys will be auto-generated on next `make up`, which invalidates any previously minted JWTs.

---

## Troubleshooting

### Services fail to start / `make up` exits early

Check the orchestrator logs:

```bash
docker compose logs startup-orchestrator
```

Common causes: Kafka not ready in time. Re-run `make up` — it is idempotent.

### `cpm-startup-orchestrator` not found

Use the **service name** (not the container name) with `docker compose`:

```bash
docker compose restart startup-orchestrator   # ✓ correct
docker compose restart cpm-startup-orchestrator  # ✗ wrong
```

### Chat UI shows `[object Object]` error

This indicates a model gate rejection. Check that `LLM_MODEL_ID` in `.env` is blank:

```dotenv
LLM_MODEL_ID=
```

Then restart the API:

```bash
docker compose up -d --build api
```

### `404 model not found` from Anthropic

The model name in your `.env` is outdated. Update to a current model:

```dotenv
ANTHROPIC_MODEL=claude-sonnet-4-6
```

Current valid model IDs:

| Label | Model ID |
|---|---|
| Claude Haiku | `claude-haiku-4-5-20251001` |
| Claude Sonnet | `claude-sonnet-4-6` |
| Claude Opus | `claude-opus-4-6` |

### Grafana panels show "No data"

Panels populate after the first real request is processed. Run `make smoke-test` to generate events, then refresh the dashboard.

### Port conflict

If any port (3000, 3001, 8080, etc.) is already in use, edit `docker-compose.yml` and change the host-side port mapping:

```yaml
ports:
  - "3100:3000"  # change 3000 → 3100 (host:container)
```

### Rebuilding a single service after code changes

```bash
docker compose up -d --build api          # rebuild API only
docker compose up -d --build ui           # rebuild UI only
docker compose up -d --build spm-aggregator  # rebuild SPM aggregator
```

---

## Environment Reference

The following variables can be tuned in `.env`. All have sane defaults and only the API keys need to be set for a working installation.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model to use |
| `TAVILY_API_KEY` | *(optional)* | Tavily key for web search tool |
| `GROQ_API_KEY` | *(optional)* | Groq key for Llama Guard 3 |
| `TENANTS` | `t1` | Comma-separated tenant IDs |
| `RATE_LIMIT_RPM` | `60` | Max requests per minute per user |
| `GUARD_MODEL_ENABLED` | `true` | Enable/disable content guard |
| `POSTURE_BLOCK_THRESHOLD` | `0.70` | Risk score at which requests are blocked |
| `CEP_SHORT_WINDOW_SEC` | `120` | Burst detection window (seconds) |
| `CEP_LONG_WINDOW_SEC` | `3600` | Sustained volume window (seconds) |
| `MEMORY_LONGTERM_TTL_SEC` | `2592000` | Cross-session memory TTL (30 days) |
| `SPM_SNAPSHOT_INTERVAL_SEC` | `300` | Posture snapshot interval (5 min) |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `REDIS_PASSWORD` | *(blank)* | Redis password (blank = no auth) |
| `SPM_DB_PASSWORD` | `spmpass` | PostgreSQL password for SPM DB |
| `LLM_MODEL_ID` | *(blank)* | SPM model registry ID (leave blank to bypass gate) |

---

## Quick-Reference Commands

```bash
make up              # Start everything
make down            # Stop everything
make status          # Health check
make logs            # Tail all logs
make logs-api        # Tail API logs only
make smoke-test      # End-to-end test
make token           # Mint a demo user JWT
make admin-token     # Mint an admin JWT
make freeze          # Freeze demo user (requires admin token)
make unfreeze        # Unfreeze demo user
make clean           # Wipe all data and keys
```

---
---

## Chat Interface

Open **http://localhost:3000** in your browser.

1. Click **Sign In** — a demo JWT is minted automatically.
2. Type a message in the input box and press **Enter** or click **Send**.
3. Claude will respond. If a web search or web fetch was used, you'll see a badge above the reply:

   > `🔍 Searched: "latest AI news"` &nbsp; `🌐 Fetched: https://example.com`

4. Use the **model selector** (top-right) to switch between Haiku, Sonnet, and Opus.

### Conversation Memory

Claude remembers your previous messages across sessions for **30 days**. You can refer back to earlier conversations naturally — no need to repeat context.

---

## Blocked Requests

Some prompts are automatically blocked by the platform:

| Block type | Example trigger | HTTP code |
|---|---|---|
| Prompt injection | "Ignore previous instructions…" | `400` |
| High posture score | Repeated suspicious patterns | `400` |
| Model gate | Unapproved model ID in request | `403` |
| Output guard | Sensitive data in LLM response | `400` |

When a request is blocked the UI shows a red error message explaining why.

---

## Admin Actions

Mint tokens and manage users from the terminal:

```bash
# Mint a regular user token
make token

# Mint an admin token
make admin-token

# Freeze a user (blocks all their requests)
make freeze

# Unfreeze a user
make unfreeze
```

---

## Grafana Dashboards

Open **http://localhost:3001** → login with `admin` / `admin`.

| Dashboard | What to look at |
|---|---|
| **AI SPM Overview** | Real-time posture scores, enforcement actions, risk trends per tenant |
| **Engineering** | Tool call counts, blocked requests with reasons, CEP events, model latency |
| **Compliance** | NIST AI RMF control coverage, 30-day audit trail |

Dashboards auto-refresh every 30 seconds. Use the time-range picker (top-right) to zoom into a specific window.

---

## SPM API (REST)

Base URL: **http://localhost:8092**

All endpoints require a Bearer token. Use `make admin-token` or `make spm-token-auditor` to get one.

```bash
# List registered AI models
TOKEN=$(make admin-token -s)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8092/models

# Register a new model
curl -X POST http://localhost:8092/models \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-model","version":"1.0","provider":"openai","risk_tier":"limited"}'

# NIST AI RMF compliance report
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8092/compliance/nist-airm/report
```

---

## Policy Simulator

Test policy changes against sample events before rolling them out:

```bash
make simulate
```

Or call the API directly at **http://localhost:8091/simulate** with a JSON payload of candidate policy + sample events. The response shows which events would be allowed, escalated, or blocked under the new policy.

---

## Logs

```bash
make logs              # all services
make logs-api          # API only
make logs-spm-api      # SPM API only
docker compose logs -f guard-model   # any service by name
```

---

## Common Workflows

### Investigate a blocked request

1. Open Grafana → **Engineering** dashboard → **Blocked Requests** table
2. Note the `reason` and `session_id`
3. Search logs: `make logs-api | grep <session_id>`

### Check a user's posture score

```bash
TOKEN=$(make admin-token -s)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8092/posture?tenant_id=t1&user_id=user-demo-1"
```

### Simulate a compliance report

```bash
make spm-compliance
```

Returns a JSON report mapping NIST AI RMF controls to pass/fail/partial status based on current platform configuration.

---


## Tech Stack

# Orbyx AI SPM — Tech Stack

A full reference of every technology, library, and external service used in the platform.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Browser (React)                      │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────┐
│              API Gateway  (FastAPI / Python)             │
│  Auth · Rate limit · Guard · CEP · Memory · LLM tools   │
└──────┬────────────┬────────────┬───────────┬────────────┘
       │ Kafka      │ Redis      │ OPA        │ Anthropic
┌──────▼──────┐ ┌───▼───┐ ┌────▼────┐ ┌─────▼──────────┐
│   Kafka     │ │ Redis │ │   OPA   │ │  Claude (LLM)  │
│  (events)   │ │(cache)│ │(policy) │ │  + Tavily      │
└──────┬──────┘ └───────┘ └─────────┘ └────────────────┘
       │
┌──────▼──────────────────────────────────────────────────┐
│             SPM Aggregator  (Python)                     │
│         Consumes events → writes to Postgres            │
└──────────────────────────┬──────────────────────────────┘
                           │ SQL
┌──────────────────────────▼──────────────────────────────┐
│              SPM API  (FastAPI / Python)                 │
│   Model registry · Posture · Compliance · Enforcement   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│          Observability  (Prometheus + Grafana)           │
└─────────────────────────────────────────────────────────┘
```

---

## Infrastructure

| Component | Technology | Version | Role |
|---|---|---|---|
| **Container runtime** | Docker + Docker Compose | Compose v2 | Runs all services locally |
| **Message broker** | Apache Kafka (Confluent) | 7.6.1 | Event streaming backbone — audit, posture, CEP events |
| **Cache / memory** | Redis | 7 (Alpine) | Session memory, long-term conversation history, rate limiting |
| **Database** | PostgreSQL | 16 (Alpine) | SPM audit log, posture snapshots, model registry |
| **Policy engine** | Open Policy Agent (OPA) | 0.70.0 | Rego-based request policy evaluation |
| **Metrics** | Prometheus | v2.55.1 | Scrapes all service `/metrics` endpoints |
| **Dashboards** | Grafana | 11.4.0 | Pre-provisioned AI SPM, Engineering, and Compliance dashboards |

---

## Backend Services

All backend services are written in **Python 3.11** and served with **FastAPI + Uvicorn**.

| Service | Port | Description |
|---|---|---|
| `api` | 8080 | Main gateway — auth, guard, LLM proxy, rate limiting |
| `guard-model` | 8200 | Content moderation (Llama Guard 3 via Groq or regex fallback) |
| `freeze-controller` | 8090 | Admin freeze/unfreeze of users and tenants |
| `policy-simulator` | 8091 | Dry-run policy evaluation against sample events |
| `spm-api` | 8092 | Model registry, posture API, compliance reports |
| `spm-aggregator` | — | Kafka consumer → Postgres writer, Prometheus metrics |
| `processor` | — | Kafka consumer — enriches raw events with posture scores |
| `memory-service` | — | Manages session, long-term, and system memory in Redis |
| `output-guard` | — | Second-pass LLM scan on Claude's responses |
| `policy-decider` | — | Evaluates OPA decisions and emits enforcement events |
| `retrieval-gateway` | — | Context retrieval for RAG (tool results, calendar, etc.) |
| `tool-parser` | — | Parses and validates tool call requests |
| `executor` | — | Executes approved tool calls |
| `agent` | — | Orchestrates multi-step agentic workflows |
| `startup-orchestrator` | — | One-shot init container: keys, Kafka topics, OPA seed |

### Core Python Libraries

| Library | Version | Used for |
|---|---|---|
| **FastAPI** | 0.115.x | REST API framework |
| **Uvicorn** | 0.30–0.32 | ASGI server |
| **Pydantic** | 2.9 | Request/response validation |
| **anthropic** | 0.40.0 | Claude API client (tool use, streaming) |
| **kafka-python-ng** | 2.2.3 | Kafka producer/consumer |
| **redis** | 5.1–5.2 | Redis client |
| **PyJWT + cryptography** | 2.9–2.10 / 43.0 | RS256 JWT signing and verification |
| **httpx** | 0.27.2 | Async HTTP client (tool fetch, inter-service calls) |
| **requests** | 2.32 | Sync HTTP client |
| **SQLAlchemy (asyncio)** | 2.0.36 | Async ORM for SPM database |
| **asyncpg** | 0.30.0 | Async PostgreSQL driver |
| **psycopg2-binary** | 2.9.9 | Sync PostgreSQL driver |
| **groq** | 0.11.0 | Groq client for Llama Guard 3 inference |
| **tavily-python** | 0.5.0 | Web search tool (Tavily API) |
| **beautifulsoup4 + lxml** | 4.12.3 / 5.3.0 | HTML parsing for web fetch tool |
| **prometheus-client** | 0.21.1 | Exposes `/metrics` endpoint |
| **prometheus-fastapi-instrumentator** | 7.0.0 | Auto-instruments FastAPI with Prometheus |
| **weasyprint** | 62.3 | PDF report generation (compliance exports) |

---

## Frontend

| Technology | Version | Role |
|---|---|---|
| **React** | 18.3 | UI framework |
| **Vite** | 5.4 | Build tool and dev server |
| **react-markdown** | 9.0 | Renders Claude's markdown responses |
| **remark-gfm** | 4.0 | GitHub-flavored markdown (tables, strikethrough, etc.) |

The UI is a single-page app served by an Nginx container (`ui`) on port 3000. No external CSS framework — fully custom design with CSS variables for theming.

---

## External APIs

| Service | Purpose | Required |
|---|---|---|
| **Anthropic Claude** | LLM backend (Haiku / Sonnet / Opus) | ✅ Yes |
| **Tavily** | Real-time web search tool for Claude | ⚠️ Optional |
| **Groq** | Fast Llama Guard 3 inference for content moderation | ⚠️ Optional |

---

## Security & Auth

| Component | Technology | Notes |
|---|---|---|
| **Authentication** | RS256 JWT | Key-pair auto-generated at startup into `./keys/` |
| **Authorization** | OPA + Rego | Policy-as-code, evaluated per request |
| **Content moderation** | Llama Guard 3 (Groq) | Falls back to regex classifier if no Groq key |
| **Output scanning** | Second-pass LLM guard | Checks Claude responses for sensitive data leakage |
| **Rate limiting** | In-process Redis counter | Configurable RPM per user |
| **Prompt injection detection** | Guard model + CEP patterns | Pattern-matched and ML-scored |

---

## Observability

| Layer | Technology | Details |
|---|---|---|
| **Metrics** | Prometheus | Scraped from all services every 15 s |
| **Dashboards** | Grafana | 3 pre-provisioned dashboards, auto-loaded via provisioning config |
| **Audit log** | PostgreSQL (`audit_export` table) | Every request written as JSONB with full event payload |
| **Structured logs** | Python `logging` → stdout | Collected by Docker, viewable via `make logs` |
| **Posture snapshots** | PostgreSQL + Prometheus | 5-min bucketed risk scores per tenant |

---

## Data Flow

```
User prompt
    │
    ▼
JWT Auth → Rate Limit → Guard Model (content check)
    │
    ▼
OPA Policy Evaluation
    │
    ▼
Memory Load (Redis — last 20 turns, 30-day TTL)
    │
    ▼
Claude API (tool loop — up to 3 rounds)
    │  ├── web_search  →  Tavily
    │  └── web_fetch   →  httpx + BeautifulSoup
    ▼
Output Guard (second-pass LLM scan)
    │
    ▼
Audit Event → Kafka → SPM Aggregator → PostgreSQL + Prometheus
    │
    ▼
Response → User
```

---

## Kafka Topics

| Topic | Producers | Consumers |
|---|---|---|
| `{tenant}.raw_events` | API gateway | Processor, CEP |
| `{tenant}.posture_events` | Processor | SPM Aggregator, Policy Decider |
| `{tenant}.enforcement_actions` | Policy Decider, Freeze Controller | SPM Aggregator |
| `{tenant}.audit_export` | API gateway, SPM services | SPM Aggregator → Postgres |

---

## Language & Runtime Summary

| Layer | Language | Runtime |
|---|---|---|
| All backend services | Python 3.11 | CPython |
| Frontend | JavaScript (ESM) | Node 20 (build only), Nginx (serve) |
| Policy | Rego | OPA 0.70 |
| Infrastructure config | YAML / Dockerfile | Docker Compose v2 |
| Database migrations | SQL | PostgreSQL 16 |
| Build automation | Make | GNU Make |

---


## Contributing

# Contributing to Orbyx AI SPM

Thanks for your interest in contributing! Here's everything you need to get started.

---

## Getting Started

1. Fork the repository and clone your fork
2. Follow [INSTALL.md](./INSTALL.md) to get the platform running locally
3. Create a feature branch: `git checkout -b feat/your-feature-name`

---

## Development Workflow

### Making changes

Most services are hot-reloaded in development. After editing Python files, rebuild only the affected service:

```bash
docker compose up -d --build api          # API changes
docker compose up -d --build spm-api      # SPM API changes
docker compose up -d --build ui           # Frontend changes
```

### Running tests

```bash
make test              # unit tests (no Docker needed)
make smoke-test        # end-to-end test against running platform
```

Tests live in `tests/`. Please add or update tests for any new behaviour.

### Checking logs

```bash
make logs              # all services
make logs-api          # single service
```

---

## Pull Request Guidelines

- **One concern per PR** — keep changes focused and reviewable
- **Write a clear description** — what changed and why
- **Include tests** — new features and bug fixes should have test coverage
- **Pass CI** — all tests must be green before review
- **Update docs** — if you change behaviour, update the relevant `.md` file

Branch naming:

| Type | Pattern |
|---|---|
| Feature | `feat/short-description` |
| Bug fix | `fix/short-description` |
| Docs | `docs/short-description` |
| Refactor | `refactor/short-description` |

---

## Project Structure

```
services/          # Backend microservices (Python / FastAPI)
ui/                # Frontend (React + Vite)
platform_shared/   # Shared Python modules (JWT, Kafka, models)
spm/               # SPM policy and compliance definitions
opa/               # OPA Rego policies
grafana/           # Dashboard JSON and provisioning config
prometheus/        # Scrape config
tests/             # Unit and integration tests
scripts/           # Dev utilities (JWT minting, etc.)
```

---

## Reporting Issues

Please open a GitHub Issue and include:

- A clear description of the problem
- Steps to reproduce
- Relevant logs (`make logs-api` output)
- Your environment (OS, Docker version, chip architecture)

---

## Code Style

- **Python** — follow PEP 8; use type hints where practical
- **JavaScript** — standard ESM; no external linting config required
- **Commits** — use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, etc.)

---


