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

- [Project Information](#ℹ️-project-information)
- [Platform at a Glance](#platform-at-a-glance)
- [Features](#features)
  - [Security & Access Control](#security--access-control)
  - [LLM Integration & Gateway](#llm-integration--gateway)
  - [Conversation Memory](#conversation-memory)
  - [Observability & Compliance](#observability--compliance)
  - [Infrastructure & Event Pipeline](#infrastructure--event-pipeline)
  - [UI & Developer Experience](#ui--developer-experience)
- [Roadmap](#roadmap)
- [Installation](#installation)
  - [Prerequisites](#prerequisites)
  - [Clone & Configure](#clone--configure)
  - [API Keys](#api-keys)
  - [First Boot](#first-boot)
  - [Verify the Platform](#verify-the-platform)
  - [Access the UI & Dashboards](#access-the-ui--dashboards)
  - [Run the Smoke Test](#run-the-smoke-test)
  - [Stopping & Cleaning Up](#stopping--cleaning-up)
- [Local SSO with Keycloak + Traefik](#local-sso-with-keycloak--traefik)
- [Troubleshooting](#troubleshooting)
- [Environment Reference](#environment-reference)
- [Usage](#usage)
- [Tech Stack](#tech-stack)
- [Architecture Overview](#architecture-overview)
- [Contributing](#contributing)

## ℹ️ Project Information

- **👤 Author:** Dany Shapiro
  - [![linkedin](https://www.readmecodegen.com/api/social-icon?name=linkedin&size=16&link=https%3A%2F%2Flinkedin.com%2Fin%2Fdanyshapiro)](https://linkedin.com/in/danyshapiro) https://www.linkedin.com/in/danyshapiro/
- **📦 Version:** 1.0.0
- **📄 License:** Apache-2.0
- **📂 Repository:** [https://github.com/dshapi/AI-SPM](https://github.com/dshapi/AI-SPM)

## Features

### Agent runtime control plane

AI-SPM hosts customer-uploaded AI agents in sandboxed containers and
routes their I/O through the existing security pipeline. The full chat
loop is live (Phase 4): **prompt-guard → policy-decider (with attached
agent policies) → Kafka chat.in → agent runtime → web_fetch / LLM proxy
→ Kafka chat.out → output-guard → SSE → UI**, with a per-agent
**Activity** tab showing chat turns, `web_fetch` tool calls, and LLM
calls (model + token counts) tailing live every 5 s.

See the [operator quickstart](docs/agents/operator-quickstart.md) for
the end-to-end pipeline diagram, provider dispatch table, common
gotchas, and env-tunable knobs. The
[design spec](docs/superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md)
covers architecture and V2 roadmap.

#### Deploying an agent

The fastest path is the UI:

1. Open **Inventory → Agents → Register Asset**.
2. Drop in a `.py` file from [`Example agents/`](Example%20agents/) —
   pick the matching **Type** in the form. Each example targets a
   different `agent_type` enum value:

   | File                                                  | Pick this Type      | Demonstrates |
   |-------------------------------------------------------|---------------------|--------------|
   | [`custom_agent.py`](Example%20agents/custom_agent.py) | `custom`            | Bare-SDK happy path with `aispm.chat.history()` conversation memory and a strong web-search prompt. **Easiest first deploy.** |
   | [`langchain_agent.py`](Example%20agents/langchain_agent.py)         | `langchain`         | LangChain `AgentExecutor` + `@tool` calling our MCP / LLM proxies (requires LangChain in the runtime image). |
   | [`llamaindex_agent.py`](Example%20agents/llamaindex_agent.py)       | `llamaindex`        | LlamaIndex chat-engine routed through `aispm.llm`, with a hand-rolled retrieval fallback when the package isn't installed. |
   | [`autogpt_agent.py`](Example%20agents/autogpt_agent.py)             | `autogpt`           | Self-prompting plan → execute → reflect loop, capped at 3 hops. |
   | [`openai_assistant_agent.py`](Example%20agents/openai_assistant_agent.py) | `openai_assistant`  | OpenAI Assistants-style request shape (system + tools), no framework. |

3. Click **Register & Deploy**.
4. Wait for runtime state to flip from **starting** to **running**
   (~5–15 s on first deploy).
5. Click **Open Chat** in the right-side panel and send a message. For
   the live event timeline (chat turns + tool/LLM calls), click
   **View Detail** in the same panel → **Activity** tab.

The minimum platform setup needed for chat to actually round-trip:

- An LLM provider integration configured under
  **Integrations → AI Providers** (Anthropic, Ollama, etc.) with a
  working API key on it.
- The **AI-SPM Agent Runtime Control Plane (MCP)** integration
  configured (also under AI Providers): pick that provider as
  **Default LLM** and your Tavily integration as **Tavily Integration**.
  Both fields are dropdowns of existing integrations.

Once the **Test** button on the agent-runtime row turns green, any
agent you upload can chat.

The same flow is also scriptable via `POST /api/spm/agents` with
`deploy_after=true`; see
[`docs/agents/operator-quickstart.md`](docs/agents/operator-quickstart.md)
for the curl recipes.

#### Adding a new integration (LLM provider, Tavily, etc.)

All upstream resources — Anthropic, OpenAI, Bedrock, Vertex, Ollama,
Groq, Tavily, Postgres, Kafka, Slack, etc. — are added the same way:

1. Open **Integrations** in the admin UI (left nav under **Discover**).
2. Click **+ Add Integration** at the top right of the page header.
3. The vendor picker groups all 22 connector types by category
   (AI Providers, Data / Storage, Messaging, Auth, …). Search by name
   or scroll to the section. Click the vendor's tile.
4. The form switches to the vendor-specific schema. Required fields
   are marked with a red asterisk; defaults are pre-filled where the
   connector declares one (e.g. Anthropic's base URL is
   `https://api.anthropic.com`, Ollama defaults the port to `11434`).
   Fill in the credentials field (API Key / IAM role / service
   account) and any vendor knobs (default model, region, etc.).
5. Click **Create**. The row appears in the integration list. Click
   **Test** on the new row to probe the upstream — green means the
   credentials work and the platform can reach the service.

#### Adding an LLM specifically — minimum setup

Most operators want to bring their own LLM provider for the agent
runtime. The minimum path is:

1. **Add the LLM provider** as in the section above
   (Integrations → + Add → e.g. Anthropic). Fill in the API key.
   Click **Test** — turns green.
2. **Point the agent-runtime control plane at it.** Open the
   **AI-SPM Agent Runtime Control Plane (MCP)** integration → click
   **Configure** → **Default LLM** dropdown → pick the integration
   you just created → **Save**. No restart needed; the proxy
   resolves the upstream on every request.
3. **Switch providers anytime** by changing that same **Default LLM**
   dropdown — Anthropic ↔ Ollama ↔ etc. The proxy translates request
   and response shape per provider, so your agent code stays
   unchanged regardless of which one you pick. See the provider
   dispatch table in
   [`docs/agents/operator-quickstart.md`](docs/agents/operator-quickstart.md)
   for what's translated where.

Adding a new **model** to an existing provider doesn't need a new
integration — set it on the provider integration's *Default Model*
field (e.g. `claude-sonnet-4-6` on Anthropic, `llama3.2` on Ollama).
The platform records it on the row's `config.model` and the LLM proxy
sends it as the upstream `model` parameter.

#### Adding a new asset type (model registry entry, dataset, prompt, …)

The **Inventory** page (left nav under **Discover**) is where
non-integration assets live: model registry rows, datasets, prompts,
evals. Each has its own tab at the top of the page.

- **Models** tab: click **+ Register Asset** to add a model registry
  entry (provider, version, owner, risk metadata). Models are also
  populated automatically by the SPM API's `/spm/v1/models/register`
  endpoint when a service self-registers, so manual rows are usually
  only for legacy or third-party models.
- **Agents** tab: same flow as the deploy section above — file upload,
  not just metadata. Agent rows are runtime-spawnable, the others
  aren't.

For programmatic registration of any asset, see
[`docs/superpowers/specs/`](docs/superpowers/specs/) for the per-asset
schemas and
[`docs/agents/operator-quickstart.md`](docs/agents/operator-quickstart.md)
for the agent-specific REST surface.

## Platform at a Glance

|                          |                                                                  |
|--------------------------|------------------------------------------------------------------|
| **Microservices**        | 16                                                               |
| **OPA Policies**         | 6                                                                |
| **Kafka Topics**         | 12+                                                              |
| **Admin User Interface** | 1 ( Admin portal )                                               |
| **Supported Models**     | Anthropic / OpenAI-compatible endpoint / 3rd party model imprort 
| **Compliance Framework** | NIST AI RMF (GOVERN / MAP / MEASURE / MANAGE)                    |



<div align="center">
<h2>Admin Portal - Overview </h2>
<h3>A Real-time AI security posture across every agent, model, and data source — inventory, runtime, policies, and threat response unified.</h3>
</div>
<p align="center"><img src="/docs/Admiin_Portal_overview.jpg" width="100%"></p>



<div align="center">
<h2>Admin Portal - Dashboard </h2>
<h3>An AI Security Posture Management control plane providing real-time visibility, risk detection, and policy enforcement across agents, models, and context flows.</h3>
</div>
<p align="center"><img src="/docs/OrbiX.jpg" width="100%"></p>


<div align="center">
<h2>Admin Portal - Inventory </h2>
</div>
<p align="center"><img src="/docs/OrbiX2.jpg" width="100%"></p>

---
<div align="center">
<h2>Check out the Demo </h2>

[![Watch the video](https://img.youtube.com/vi/OucfJ6_wcTM/0.jpg)](https://www.youtube.com/watch?v=OucfJ6_wcTM)

</div>




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

### Groq (required for Threat Hunting Agent + optional guard acceleration)

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxx
HUNT_MODEL=llama-3.3-70b-versatile   # model used by the threat-hunting agent
```

Get a free key at [console.groq.com](https://console.groq.com).

Groq is used in two places:
- **Threat Hunting Agent** — `GROQ_API_KEY` is **required**. Without it the `threat-hunting-agent` service will refuse to start.
- **Guard Model (Llama Guard)** — optional. Without a key the guard falls back to a built-in regex classifier (still functional, just less accurate).

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
  Admin chat:        http://localhost:3001/
  Admin:             http://localhost:3001/admin
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

**Stop all services including auth (keeps data):**

```bash
./stop.sh
# or
docker-compose -f docker-compose.yml -f docker-compose.auth.yml down
```

**Start everything back up:**

```bash
./start.sh
```

**Stop without the auth overlay:**

```bash
docker compose down
```

**Stop and wipe all data (volumes, generated keys):**

```bash
make clean
```

> ⚠️ `make clean` deletes the RSA keys in `./keys/` and the Keycloak realm volume (`keycloak-data`). New keys are auto-generated on next `make up` (invalidates existing JWTs). You will also need to redo the [first-time Keycloak setup](#first-time-keycloak-setup).

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

### Threat hunting collectors report `column "session_id" does not exist`

The `audit_export` table is missing the `session_id` column added in migration `002`. Run the migration once while the stack is up:

```bash
# Option A — via Alembic
docker compose exec spm-api alembic upgrade head

# Option B — direct SQL
docker compose exec spm-db psql -U spm_rw -d spm -c "
  ALTER TABLE audit_export ADD COLUMN IF NOT EXISTS session_id VARCHAR(64);
  CREATE INDEX IF NOT EXISTS idx_audit_export_session_id ON audit_export (session_id);
"
```

### `threat-hunting-agent` fails to start — `GROQ_API_KEY` missing

The threat-hunting-agent requires a Groq API key. Set it in `.env`:

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxx
```

Get a free key at [console.groq.com](https://console.groq.com), then rebuild the service:

```bash
docker compose up -d --build threat-hunting-agent
```

### Rebuilding a single service after code changes

```bash
docker compose up -d --build api                  # rebuild API only
docker compose up -d --build ui                   # rebuild UI only
docker compose up -d --build spm-aggregator       # rebuild SPM aggregator
docker compose up -d --build threat-hunting-agent # rebuild threat hunting agent
```

---

## Environment Reference

The following variables can be tuned in `.env`. All have sane defaults and only the API keys need to be set for a working installation.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model to use |
| `TAVILY_API_KEY` | *(optional)* | Tavily key for web search tool |
| `GROQ_API_KEY` | *(required for threat hunting)* | Groq key — powers the Threat Hunting Agent LLM and optionally accelerates Llama Guard 3 |
| `HUNT_MODEL` | `llama-3.3-70b-versatile` | Groq model used by the threat-hunting agent |
| `HUNT_BATCH_WINDOW_SEC` | `30` | Kafka batch window for the threat-hunting agent (seconds) |
| `THREATHUNTING_AI_INTERVAL_SEC` | `300` | Proactive threat scan interval (seconds) |
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

### Groq (required for Threat Hunting Agent + optional guard acceleration)

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxx
HUNT_MODEL=llama-3.3-70b-versatile   # model used by the threat-hunting agent
```

Get a free key at [console.groq.com](https://console.groq.com).

Groq is used in two places:
- **Threat Hunting Agent** — `GROQ_API_KEY` is **required**. Without it the `threat-hunting-agent` service will refuse to start.
- **Guard Model (Llama Guard)** — optional. Without a key the guard falls back to a built-in regex classifier (still functional, just less accurate).

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
  Chat:              http://localhost:3001 
  Admin portal:      http://localhost:3001/admin
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

**Stop all services including auth (keeps data):**

```bash
./stop.sh
# or
docker-compose -f docker-compose.yml -f docker-compose.auth.yml down
```

**Start everything back up:**

```bash
./start.sh
```

**Stop without the auth overlay:**

```bash
docker compose down
```

**Stop and wipe all data (volumes, generated keys):**

```bash
make clean
```

> ⚠️ `make clean` deletes the RSA keys in `./keys/` and the Keycloak realm volume (`keycloak-data`). New keys are auto-generated on next `make up` (invalidates existing JWTs). You will also need to redo the [first-time Keycloak setup](#first-time-keycloak-setup).

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

### Threat hunting collectors report `column "session_id" does not exist`

The `audit_export` table is missing the `session_id` column added in migration `002`. Run the migration once while the stack is up:

```bash
# Option A — via Alembic
docker compose exec spm-api alembic upgrade head

# Option B — direct SQL
docker compose exec spm-db psql -U spm_rw -d spm -c "
  ALTER TABLE audit_export ADD COLUMN IF NOT EXISTS session_id VARCHAR(64);
  CREATE INDEX IF NOT EXISTS idx_audit_export_session_id ON audit_export (session_id);
"
```

### `threat-hunting-agent` fails to start — `GROQ_API_KEY` missing

The threat-hunting-agent requires a Groq API key. Set it in `.env`:

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxx
```

Get a free key at [console.groq.com](https://console.groq.com), then rebuild the service:

```bash
docker compose up -d --build threat-hunting-agent
```

### Rebuilding a single service after code changes

```bash
docker compose up -d --build api                  # rebuild API only
docker compose up -d --build ui                   # rebuild UI only
docker compose up -d --build spm-aggregator       # rebuild SPM aggregator
docker compose up -d --build threat-hunting-agent # rebuild threat hunting agent
```

---

## Environment Reference

The following variables can be tuned in `.env`. All have sane defaults and only the API keys need to be set for a working installation.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model to use |
| `TAVILY_API_KEY` | *(optional)* | Tavily key for web search tool |
| `GROQ_API_KEY` | *(required for threat hunting)* | Groq key — powers the Threat Hunting Agent LLM and optionally accelerates Llama Guard 3 |
| `HUNT_MODEL` | `llama-3.3-70b-versatile` | Groq model used by the threat-hunting agent |
| `HUNT_BATCH_WINDOW_SEC` | `30` | Kafka batch window for the threat-hunting agent (seconds) |
| `THREATHUNTING_AI_INTERVAL_SEC` | `300` | Proactive threat scan interval (seconds) |
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

![Orbyx AI-SPM Architecture](docs/updated-architecture.png)

### Control Plane & Data Path

![Control Plane & Data Path](docs/architecture-flows.png)




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
| `agent-orchestrator` | 8094 | Session lifecycle, risk scoring, threat finding storage, case management |
| `threat-hunting-agent` | — | Autonomous AI threat hunter — 9 proactive scans + LangChain/Groq LLM |
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
| **Groq** | Threat Hunting Agent LLM (Llama 3.3 70B) + Llama Guard 3 content moderation | ✅ Required (threat hunting) / ⚠️ Optional (guard) |

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

## Threat Hunting Agent

The **threat-hunting-agent** is an autonomous AI security service that continuously scans the platform for threats — independent of user-triggered requests. It runs a LangChain agent backed by **Groq + Llama 3.3 70B Versatile** and fires on two triggers:

- **Kafka consumer** — reacts to session events in near real-time
- **Scheduler** — runs a full proactive scan cycle every 5 minutes (configurable via `THREATHUNTING_AI_INTERVAL_SEC`)

### Proactive Scans

Every scan cycle runs all 9 detectors in parallel. Each detector queries live data (Postgres, Redis, `/proc`) and produces structured findings that the agent analyses with the LLM before posting to the orchestrator.

| Scan | What it detects |
|---|---|
| `exposed_credentials` | API keys, tokens, and passwords stored in Redis under unexpected namespaces |
| `sensitive_data_exposure` | PII patterns, DB connection strings in Redis (broader sweep) |
| `unused_open_ports` | Internal service ports reachable that should not be (misconfigured or rogue services) |
| `unexpected_listen_ports` | Ports in LISTEN state in `/proc/net/tcp` not on the allowed service list |
| `overprivileged_tools` | AI models in the registry with unacceptable risk tier still set to `active` |
| `runtime_anomaly_detection` | High-frequency actors, enforcement block clusters (3+/session/hour), session storms (5+/actor/10 min) |
| `prompt_secret_exfiltration` | API keys and bearer tokens inside prompt/response text in the audit log |
| `data_leakage_detection` | SSNs, credit card numbers, email addresses in agent response text |
| `tool_misuse_detection` | High tool-call frequency (>20/actor/hour), rapid chaining (>5 calls/session/min), high block ratios |

### Findings & Cases

When a scan finds an anomaly the LLM produces a structured **threat finding** (severity, hypothesis, evidence, recommended actions) which is:

1. Posted to the agent-orchestrator via `POST /api/v1/threat-findings`
2. Deduplicated by batch hash — the same pattern won't flood the findings tab
3. Automatically prioritised (risk score, recency, occurrence count)
4. Escalated to a **Case** when `should_open_case=true` and priority score ≥ 0.40

### Configuration

```dotenv
GROQ_API_KEY=gsk_xxxxxxxxxxxx           # required — service won't start without it
HUNT_MODEL=llama-3.3-70b-versatile      # LLM model (any Groq-hosted model)
HUNT_BATCH_WINDOW_SEC=30                # Kafka batch window
THREATHUNTING_AI_INTERVAL_SEC=300       # Proactive scan interval (seconds)
```

### Database Migration

The threat hunting collectors query the `session_id` column on the `audit_export` table. If you are upgrading an existing installation run the migration before starting the agent:

```bash
# Option A — via Alembic (recommended)
docker compose exec spm-api alembic upgrade head

# Option B — direct SQL (if Alembic is unavailable)
docker compose exec spm-db psql -U spm_rw -d spm -c "
  ALTER TABLE audit_export ADD COLUMN IF NOT EXISTS session_id VARCHAR(64);
  CREATE INDEX IF NOT EXISTS idx_audit_export_session_id ON audit_export (session_id);
"
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

## Local SSO with Keycloak + Traefik

The auth overlay adds a full OIDC login flow in front of the admin portal, running entirely on localhost. No real domain or TLS certificate required.

### What it adds

| Component | Role |
|---|---|
| **Traefik v3** | Reverse proxy. Routes `aispm.local` → admin UI via the ForwardAuth middleware. Uses a static file provider — no Docker socket required. |
| **Keycloak 24** | OIDC identity provider running in dev mode. Realm config is persisted to `./DataVolumes/keycloak/` (host bind mount) so it survives restarts and `docker compose down -v`. |
| **traefik-forward-auth** | Sits in front of every protected route. Inspects every request via `X-Forwarded-Uri` — including `/_oauth` callbacks — and sets a signed session cookie on `aispm.local`. |

### One-time host setup

Add these entries to `/etc/hosts` on your Mac:

```bash
sudo sh -c 'echo "127.0.0.1  keycloak.local auth.local aispm.local" >> /etc/hosts'
```

### Start / Stop

```bash
./start.sh   # full stack including auth
./stop.sh    # tear everything down (data preserved in ./DataVolumes/)
```

### First-time Keycloak setup

Only required once — Keycloak persists the realm to `./DataVolumes/keycloak/h2/`.

1. `./start.sh` then open **http://keycloak.local:8180/admin/** (`admin` / `admin`)
2. Top-left dropdown → **Create realm** → name: `aispm` → **Create**
3. **Realm Settings** → **General** tab → **Require SSL** → set to **none** → **Save**
   - Required for local-dev HTTP. If left at the default (`external`), Keycloak rejects every non-localhost request with the page "We are sorry... HTTPS required" and traefik-forward-auth's token exchange silently fails.
   - Repeat the same toggle on the **master** realm if you want to log into the admin UI via `keycloak.local` (master defaults to `external` too).
4. **Clients** → **Create client**
   - Client ID: `traefik-forward-auth`
   - Turn ON **Client authentication** → **Next**
   - Valid redirect URIs: `http://aispm.local/_oauth`
   - Web origins: `http://aispm.local` → **Save**
5. **Credentials** tab → copy **Client secret** → paste into `.env.auth`:
   ```
   PROVIDERS_OIDC_CLIENT_SECRET=<paste here>
   ```
6. **Realm roles** → **Create role** → name: `spm:admin` → **Save**. Repeat for `spm:auditor`.
   - The spm-api enforces these via `require_admin` / `require_auditor`. Without `spm:admin` in the JWT roles claim, every integration write endpoint returns 403.
7. **Users** → **Create user** → set username and email → **Create**
8. **Credentials** tab → set password → turn OFF **Temporary** → **Save password**
9. **Role mapping** tab → **Assign role** → tick `spm:admin` → **Assign**
10. Restart forward-auth: `docker compose -f docker-compose.auth.yml up -d --force-recreate traefik-forward-auth`

#### Scriptable equivalent (kcadm)

If you'd rather skip the UI, the same setup via kcadm — useful when the master realm's "HTTPS required" gate is locking you out of the admin console:

```bash
KC=/opt/keycloak/bin/kcadm.sh

docker compose exec keycloak $KC config credentials \
  --server http://localhost:8080 --realm master --user admin --password admin

# Disable SSL gate on both realms (master = admin console, aispm = the app)
docker compose exec keycloak $KC update realms/master -s sslRequired=NONE
docker compose exec keycloak $KC update realms/aispm  -s sslRequired=NONE

# Create the two realm roles spm-api expects
docker compose exec keycloak $KC create roles -r aispm -s name=spm:admin
docker compose exec keycloak $KC create roles -r aispm -s name=spm:auditor

# Create user, set password, assign admin role
docker compose exec keycloak $KC create users -r aispm \
  -s username=dany -s enabled=true -s email=dany@example.com
docker compose exec keycloak $KC set-password -r aispm \
  --username dany --new-password dany
docker compose exec keycloak $KC add-roles -r aispm \
  --uusername dany --rolename spm:admin
```

### Access

| URL | What |
|---|---|
| **http://aispm.local/admin** | Admin portal (SSO protected — redirects to Keycloak login) |
| **http://keycloak.local:8180/admin/** | Keycloak admin console (master realm, `admin`/`admin`) |
| **http://localhost:9091/dashboard/** | Traefik routing dashboard |

### Configuration files

| File | Purpose |
|---|---|
| `docker-compose.auth.yml` | Compose overlay — adds Traefik, Keycloak, and traefik-forward-auth. Keycloak data is bind-mounted from `./DataVolumes/keycloak/`. |
| `auth/traefik.yml` | Traefik static config (file provider, entrypoints, dashboard on `:9091`) |
| `auth/traefik-dynamic.yml` | Route + middleware definitions. **Important:** there is a single `aispm` router covering every path — including `/_oauth`. The SSO middleware itself recognizes the OIDC callback via `X-Forwarded-Uri` and short-circuits it. Do **not** add a separate router that routes `/_oauth` directly to the forward-auth backend service (e.g. `aispm-oauth: service: auth-svc`) — that strips the `X-Forwarded-*` headers and forward-auth then can't tell it's a callback, falling into an infinite redirect loop. |
| `.env.auth` | OIDC client ID, client secret, and cookie signing secret |

### Troubleshooting auth

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser endlessly bounces between `aispm.local/_oauth?code=...` and Keycloak | `auth/traefik-dynamic.yml` has a router that sends `/_oauth` directly to forward-auth as a backend, skipping the middleware (drops `X-Forwarded-Uri`). | Remove the `/_oauth` router; let the catch-all `aispm` router with the `sso` middleware handle every path. |
| Keycloak page: "We are sorry… HTTPS required" | Realm `sslRequired` is `external` (default). | `kcadm update realms/<realm> -s sslRequired=NONE` for both `master` and `aispm`, OR access the admin console via `http://localhost:8180/` (localhost bypasses the gate). |
| Login succeeds but `/_oauth` returns "Cookie not found" | Stale `_forward_auth_csrf` cookies from a previous failed run. | Close all incognito windows (don't just open a new tab) and start a fresh session. |
| spm-api returns 403 "spm:admin role required" after login | The JWT user has no `spm:admin` realm role. | In Keycloak: realm `aispm` → Users → user → **Role mapping** → assign `spm:admin`. |
| `LOG_LEVEL=debug` doesn't take effect | Compose only reloads env on recreate. | `docker compose -f docker-compose.auth.yml up -d --force-recreate traefik-forward-auth` |

### Persistent data — bind-mounted volumes

Postgres, Keycloak, Redis, Grafana, and the agent-orchestrator all bind-mount their state under `./DataVolumes/` instead of using Docker named volumes. Layout:

```
DataVolumes/
├── spm-db/                ← Postgres data dir (UID 999 inside container)
├── keycloak/h2/           ← Keycloak embedded H2 DB (realms, users, secrets)
├── redis/                 ← Redis AOF / dump
├── grafana/               ← Grafana SQLite + dashboards
└── agent-orchestrator/    ← Orchestrator SQLite session log
```

The directories are tracked via `.gitkeep`; their contents are gitignored (see `.gitignore`). To reset any one of them, stop the relevant service, `rm -rf` the directory contents, and restart.

### Database migrations (alembic)

Migrations live in `spm/alembic/versions/`. The CI workflow runs `alembic upgrade head` automatically, but local containers do **not** — if you pull new migrations, run them by hand:

```bash
cd spm
SPM_DB_URL="postgresql://spm_rw:spmpass@localhost:5432/spm" alembic upgrade head
```

If the DB's `alembic_version` row points at a revision that no longer exists in `spm/alembic/versions/` (can happen after switching branches or restoring a snapshot), `alembic upgrade head` errors with `Can't locate revision identified by 'NNN'`. Reset the bookmark to the latest revision actually present, then re-run:

```bash
cd spm
# Replace 003 with whatever is the highest revision file present
SPM_DB_URL="..." alembic stamp --purge 003
SPM_DB_URL="..." alembic upgrade head
```

The repo's migrations are written to be idempotent (`ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`), so re-running a stamped revision is safe.

---


