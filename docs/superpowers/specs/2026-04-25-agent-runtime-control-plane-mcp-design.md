# Agent Runtime Control Plane + MCP Server — Design Spec

**Status:** draft for review
**Date:** 2026-04-25
**Author:** dany.shapiro@gmail.com

## 1. Goal

Let end users deploy AI agents on AI-SPM. Customer uploads `agent.py` from the
Inventory → Agents tab; AI-SPM runs it in a sandboxed container, hands it
batteries-included tools through an MCP server, and routes its chat I/O through
the existing security pipeline (prompt-guard, policy-decider, output-guard,
lineage). The platform's value proposition is **"a secure execution
environment for agents"** — every input, every LLM call, and every tool call
passes through guardrails the customer doesn't have to build themselves.

V1 ships one MCP tool (`web_fetch`, Tavily-powered) and the platform-provided
LLM proxy (defaults to Ollama). The agent's only path to the outside world is
through MCP and the LLM proxy; the container has no direct internet egress.

## 2. Non-goals (V1)

These are deliberately out of scope and tracked for V2:

- Multi-tenant routing (table has `tenant_id` but enforcement is V2)
- Scale-to-zero (idle timeout column wired but not enforced)
- Custom MCP tools registered by customers
- `sql` MCP tool + per-agent DSN management
- gVisor / Firecracker microVM sandboxing (V1 uses Docker resource limits + network policies)
- Per-user-per-agent containers (V1 has one shared container per agent)
- Token-by-token streaming replies (V1.5)
- LLM cost metering / quotas
- OAuth on the MCP server (V1 uses static per-agent bearer tokens)
- User can interrupt a streaming response, approve/deny tool calls, or edit prior messages

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ AI-SPM Admin UI                                                 │
│   Inventory → Agents tab → right-click row → Open Chat / Stop   │
│   Detail drawer → 5 tabs (Overview / Configure / Activity /     │
│                            Sessions / Lineage)                  │
│   AgentChatPanel (new component, SSE-driven)                    │
└─────────┬───────────────────────────────────────────────────────┘
          │  POST /api/spm/agents/{id}/chat   (SSE)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│ EXISTING SECURITY PIPELINE                                       │
│   prompt-guard  ──►  policy-decider                              │
└─────────┬───────────────────────────────────────────────────────┘
          │  produce → cpm.{tenant_id}.agents.{agent_id}.chat.in   (Kafka)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│ NEW: agent container  (one per uploaded agent.py, always-on)    │
│                                                                 │
│   customer's agent.py   import aispm                            │
│       ↑ Kafka in/out                                            │
│       ↓ HTTP MCP                       ↓ HTTP OpenAI-compat     │
└──────────┬─────────────────────────────────────┬────────────────┘
           ▼                                     ▼
┌─────────────────────────┐  ┌─────────────────────────────────────┐
│ NEW: spm-mcp            │  │ NEW: spm-llm-proxy                  │
│ FastMCP server          │  │ Translates OpenAI calls to the      │
│ tools: web_fetch        │  │ configured AI Provider integration  │
│ Bearer auth per agent   │  │ (Ollama default; any active LLM)    │
└────────┬────────────────┘  └────────────────┬────────────────────┘
         │                                    │
         ▼                                    ▼
   tool-parser ── policy-decider ── output-guard ── lineage-events
   (existing pipeline intercepts every tool call and every LLM call)

   ▲
   │  consume ◄ cpm.{tenant_id}.agents.{agent_id}.chat.out
   │
   spm-api → output-guard → SSE chunks to UI
```

**Egress policy** — agent container's network namespace allows only:
- `spm-mcp:8500` (tools)
- `spm-llm-proxy:8500` (LLM)
- `kafka-broker:9092` (chat in/out)

No direct internet, no DB, no other services.

**Three new services in docker-compose:**

| Service | Image | Replicas | Purpose |
|---|---|---|---|
| `spm-mcp` | new build (FastMCP) | 1 | MCP server exposing `web_fetch` |
| `spm-llm-proxy` | new build (LiteLLM-style) | 1 | OpenAI-compat → configured LLM integration |
| `agent-runtime-base` | new build (Python 3.12 + aispm SDK) | image only | Base for customer agent containers |

**One new module in spm-api:** `agent_controller.py` — orchestrates docker spawn/stop, Kafka topic CRUD, mcp_token rotation. Not a separate service to keep ops simple.

## 4. Data model

### New table `agents` (Alembic 005)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | displayed as `ag-001`, `ag-002`, ... |
| `name` | text | display name; unique per tenant |
| `version` | text | semver; bumped per upload |
| `agent_type` | enum | `langchain` / `llamaindex` / `autogpt` / `openai_assistant` / `custom` |
| `provider` | enum | reuses existing: uploaded agents always = `internal` |
| `owner` | text | team/user |
| `description` | text | free-form |
| `risk` | enum | `low` / `medium` / `high` / `critical` (derived later) |
| `policy_status` | enum | reuses existing: `covered` / `partial` / `none` |
| `runtime_state` | enum | `stopped` / `starting` / `running` / `crashed` |
| `code_path` | text | `./DataVolumes/agents/{id}/agent.py` (note: `DataVolumes` is the actual repo directory name — kept as-is to match existing layout, not a typo introduced by this spec) |
| `code_sha256` | text | tamper detection |
| `mcp_token` | text | bearer for spm-mcp; encrypted at rest |
| `llm_api_key` | text | bearer for spm-llm-proxy; encrypted at rest |
| `last_seen_at` | timestamptz | updated on each chat message processed |
| `tenant_id` | text | single value today |
| `created_at` / `updated_at` | timestamptz | |

### New table `agent_chat_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | session_id |
| `agent_id` | UUID FK → agents.id | |
| `user_id` | text | who opened the chat |
| `started_at` / `last_message_at` | timestamptz | |
| `message_count` | int | for metrics |

### New table `agent_chat_messages`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | message_id |
| `session_id` | UUID FK → agent_chat_sessions.id | |
| `role` | enum | `user` / `agent` |
| `text` | text | rendered content |
| `ts` | timestamptz | |
| `trace_id` | text | links to lineage events |

Backs the chat history helper (`aispm.chat.history()`) and the Sessions tab.

### Existing tables touched

- **`integrations`** — Alembic seeds one `agent-runtime` integration row pointing at `spm-mcp`. Configure tab fields (Section 5) are stored in `integrations.config` (non-secret) and `integration_credentials` (secret, but V1 has no secrets).
- **`audit_events` / Kafka audit topic** — new event types: `AgentDeployed`, `AgentStarted`, `AgentStopped`, `AgentChatMessage`, `AgentToolCall`, `AgentLLMCall`. Published via existing `platform_shared/lineage_events.py`.

### No changes to `model_registry`

Agents have a distinct lifecycle (running container, code file, runtime state) and distinct metadata (agent_type vs model_type). They live in their own table.

## 5. spm-mcp — Configure form

The spm-mcp server appears in Integrations under category **"AI Providers"** with the standard Configure / Test Connection / Recent Activity tabs (`SchemaForm` component handles the form rendering).

ConnectorType key: `agent-runtime`. Schema (in `connector_registry.py`):

**Connection group**

| Field | Type | Default | Notes |
|---|---|---|---|
| Internal endpoint | url, read-only | `http://spm-mcp:8500/mcp` | Computed; shown for ops visibility |
| Health status | derived | — | Existing health badge |

**Defaults group**

| Field | Type | Required | Default |
|---|---|---|---|
| Default LLM | enum (dropdown of AI Provider integrations) | yes | `ollama` |
| Tavily integration | enum (dropdown of Tavily integrations) | yes | first Tavily integration |
| Default fallback model | text | no | `llama3.1:8b` |

**Resources group**

| Field | Type | Default |
|---|---|---|
| Default memory per agent (MB) | integer | 512 |
| Default CPU quota | float | 0.5 |
| Tool call timeout (s) | integer | 30 |
| Max concurrent agents | integer | 50 |
| Max chat sessions per agent | integer | 100 |

**Tool behaviour group**

| Field | Type | Default |
|---|---|---|
| Tavily max results | integer | 5 |
| Tavily max chars per result | integer | 4000 |

**Audit group**

| Field | Type | Default |
|---|---|---|
| Log LLM prompts | boolean | true |
| Audit topic suffix | text | `audit_events` |

**No credentials group** — spm-mcp itself stores no secrets. All credentials (Tavily key, LLM key) live on referenced AI Provider integrations and are fetched at runtime via `get_credential()`.

**Test Connection probe** — verifies (1) spm-mcp HTTP health, (2) referenced LLM integration's Test Connection passes, (3) referenced Tavily integration's Test Connection passes.

### `connector_registry.py` entry (concrete)

The "Internal endpoint" and "Health status" rows are display-only metadata, not user-editable fields, so they don't appear in the registry — the detail page composes them from container state. The actual `CONNECTOR_TYPES["agent-runtime"]` entry is:

```python
"agent-runtime": ConnectorType(
    key="agent-runtime",
    label="AI-SPM Agent Runtime Control Plane (MCP)",
    category="AI Providers",
    vendor="AI-SPM",
    icon_hint="bot",
    description=(
        "Hosts customer-uploaded AI agents in sandboxed containers. "
        "Provides MCP tools (web_fetch) and an OpenAI-compatible LLM proxy. "
        "Configure the default LLM and Tavily integration here."
    ),
    fields=[
        # Defaults
        FieldSpec(key="default_llm_integration_id", label="Default LLM",
                  type="enum_integration", required=True,
                  group="Defaults",
                  hint="Active AI Provider integration that backs spm-llm-proxy.",
                  options_provider="ai_provider_integrations"),
        FieldSpec(key="tavily_integration_id", label="Tavily Integration",
                  type="enum_integration", required=True,
                  group="Defaults",
                  options_provider="tavily_integrations"),
        FieldSpec(key="default_model_name", label="Default model name",
                  type="string", default="llama3.1:8b", group="Defaults"),
        # Resource limits
        FieldSpec(key="default_memory_mb", label="Memory per agent (MB)",
                  type="integer", default=512, group="Resources"),
        FieldSpec(key="default_cpu_quota", label="CPU quota",
                  type="float", default=0.5, group="Resources"),
        FieldSpec(key="tool_call_timeout_s", label="Tool call timeout (s)",
                  type="integer", default=30, group="Resources"),
        FieldSpec(key="max_concurrent_agents", label="Max concurrent agents",
                  type="integer", default=50, group="Resources"),
        FieldSpec(key="max_sessions_per_agent", label="Max chat sessions per agent",
                  type="integer", default=100, group="Resources"),
        # Tool behaviour
        FieldSpec(key="tavily_max_results", label="Tavily max results",
                  type="integer", default=5, group="Tool behaviour"),
        FieldSpec(key="tavily_max_chars", label="Tavily max chars per result",
                  type="integer", default=4000, group="Tool behaviour"),
        # Audit
        FieldSpec(key="log_llm_prompts", label="Log LLM prompts",
                  type="boolean", default=True, group="Audit"),
        FieldSpec(key="audit_topic_suffix", label="Audit topic suffix",
                  type="string", default="audit_events", group="Audit"),
    ],
    probe=connector_probes.probe_agent_runtime,
),
```

Two notes:
- `enum_integration` is a new `FieldSpec.type` — renders as a dropdown of currently-active integrations matching the `options_provider` filter (`ai_provider_integrations` returns Anthropic, OpenAI, Bedrock, Vertex, Ollama; `tavily_integrations` returns just Tavily). Implemented in `SchemaForm.jsx` by hitting a new `GET /api/spm/integrations?category=...` endpoint. This is reusable beyond agent-runtime — any integration that references another integration.
- `probe_agent_runtime` is a new function in `connector_probes.py` that runs the three checks above.

## 6. Agent detail panel

Opens from a single-click on a row in the Agents tab, or from the Configure menu item in the right-click context menu.

Right-click context menu items:
- ▶ **Open Chat** — opens the AgentChatPanel in a drawer
- ⚙ **Configure** — opens the detail drawer (same as single-click)
- ❚❚ **Stop** / ▶ **Start** — toggles runtime_state

### Tab 1: Overview

Mirrors the existing model detail panel layout you screenshotted:

- Display name, agent type, risk badge, policy status
- Owner, Provider, Last Seen, Description
- Linked Policies (with quick-add)
- Active Alerts count + link
- **Runtime status row** — `Running / Stopped / Crashed` with the run/stop toggle button
- **Open Chat button** (next to Apply Policy)

### Tab 2: Configure

Everything per-agent goes here. **No environment variables, no secrets in code.**

| Group | Field | Type | Notes |
|---|---|---|---|
| **Identity** | Name | text | |
| | Version | text | semver |
| | Agent type | enum | langchain / llamaindex / autogpt / openai_assistant / custom |
| | Owner | text | |
| | Description | textarea | |
| **LLM** | Override LLM | enum (optional) | empty = use spm-mcp default |
| | Override model name | text (optional) | overrides default fallback model |
| | Max tokens per response | integer | default 2048 |
| | Temperature | float | default 0.7 |
| **Resources** | Memory limit (MB) | integer (optional) | overrides spm-mcp default |
| | CPU quota | float (optional) | overrides spm-mcp default |
| | Idle timeout (min) | integer | 0 = always-on; >0 = scale-to-zero (V2) |
| **Custom env vars** | KEY + value pairs | row-add | encrypted via `integration_credentials`; agent reads via `aispm.get_secret(name)` |
| **Tools** | web_fetch | enabled checkbox | default on |
| **Code** | Uploaded file | filename + sha256 | read-only |
| | Replace code | file picker | uploads new agent.py and bumps version |

Changes that require restart (Override LLM, env vars, resource limits) trigger an automatic restart with an "Applying changes..." toast.

### Tab 3: Recent Activity

Live tail of `AgentChatMessage`, `AgentToolCall`, `AgentLLMCall` events filtered by agent_id. Reuses the existing `RecentActivityTable` renderer.

### Tab 4: Sessions

List of `agent_chat_sessions` rows for this agent. Click → opens that user's chat history.

### Tab 5: Lineage

Reuses the existing Lineage view, scoped to this agent. Tool-call → LLM-call → response chains.

### Run / Stop semantics

- **Stop** — SIGTERM container, wait 10s, SIGKILL. State stays in DB. `runtime_state = stopped`. Active chat sessions show a "Agent paused" banner; new messages return a friendly error.
- **Start** — spawn container with current code + config. Wait for SDK's `aispm.ready()` signal (~5s). `runtime_state = running`.
- **Restart** — stop + start.
- **Crashed** — container exited non-zero. UI shows last error log line. Auto-retry once with exponential backoff; then `runtime_state = crashed` until manual restart.

## 7. Wire protocol — Kafka chat I/O

Two topics per agent, named via the existing `platform_shared/topics.py` pattern:

| Topic | Producer | Consumer | Key |
|---|---|---|---|
| `cpm.{tenant_id}.agents.{agent_id}.chat.in` | spm-api (after prompt-guard / policy-decider) | the agent's container | `session_id` |
| `cpm.{tenant_id}.agents.{agent_id}.chat.out` | the agent's container | spm-api (then output-guard, then SSE to UI) | `session_id` |

Names follow the existing `cpm.{tenant_id}.*` per-tenant pattern from `platform_shared/topics.py` (`topics_for_tenant`). For V1's single tenant the values resolve to e.g. `cpm.t1.agents.ag-001.chat.in`; multi-tenant V2 needs no naming change. Add a new helper `agent_topics_for(tenant_id, agent_id)` in `topics.py` so consumers don't hand-build the strings.

Partition-by-session_id preserves per-conversation ordering. Topics created on agent deploy, deleted on agent retire. With `max_concurrent_agents=50`, the topic count stays ≤100 per tenant.

**End-to-end flow for one user message:**

1. UI POSTs to `/api/spm/agents/{id}/chat`, opens SSE.
2. spm-api → prompt-guard → policy-decider.
3. spm-api produces to `cpm.{tenant_id}.agents.{agent_id}.chat.in` (key=session_id).
4. Agent consumes, processes (may call `web_fetch` via HTTP MCP, may call LLM via `spm-llm-proxy`). Tool calls and LLM calls go through tool-parser / policy-decider on the way out.
5. Agent produces reply to `cpm.{tenant_id}.agents.{agent_id}.chat.out`.
6. spm-api consumes, runs output-guard, streams SSE chunks to UI.

**Tool calls remain HTTP** — the agent calls spm-mcp directly. spm-mcp publishes a `ToolCallEvent` to the existing audit topic so tool calls are still in the lineage pipeline. Putting tool calls through Kafka adds latency for no benefit.

## 8. Agent SDK contract — the `aispm` module

Pre-installed in `agent-runtime-base`. Customer imports and codes against it.

### Package layout

```
agent_runtime/
├── Dockerfile                  # Python 3.12-slim + the aispm package
└── aispm/
    ├── __init__.py             # public re-exports + connection-info constants
    ├── chat.py                 # Kafka in/out wrappers
    ├── mcp.py                  # HTTP MCP client
    ├── llm.py                  # OpenAI-compat HTTP client (convenience)
    ├── secrets.py              # `get_secret()` — read from /api/spm/agents/{id}/secrets
    ├── lifecycle.py            # `ready()`, signal handling, graceful shutdown
    ├── log.py                  # `log()` — structured to lineage
    └── types.py                # ChatMessage, Completion, ToolResult dataclasses
```

`aispm/__init__.py` re-exports the public API so customers write `aispm.chat.subscribe()` not `aispm.chat.chat.subscribe()`. Connection info (`AGENT_ID`, `LLM_BASE_URL`, etc.) is module-level — populated at import time from env vars the controller injects at container start (these env vars are infrastructure-injected, NOT customer secrets — the no-env-vars rule from §6 applies to customer config, not to platform-injected wiring).

### Public API — concrete signatures

```python
# aispm/types.py
@dataclass
class ChatMessage:
    id: str            # message UUID
    session_id: str    # session UUID, partition key
    user_id: str
    text: str
    ts: datetime

@dataclass
class HistoryEntry:
    role: Literal["user", "agent"]
    text: str
    ts: datetime

@dataclass
class Completion:
    text: str
    model: str
    usage: dict        # {"prompt_tokens": int, "completion_tokens": int}

# aispm/chat.py
async def subscribe() -> AsyncIterator[ChatMessage]: ...
async def reply(session_id: str, text: str) -> None: ...
async def stream(session_id: str) -> AsyncContextManager[StreamWriter]: ...    # V1.5
async def history(session_id: str, limit: int = 10) -> list[HistoryEntry]: ...

# aispm/mcp.py
async def call(tool: str, **kwargs) -> dict: ...
# V1: only tool="web_fetch" with {query: str, max_results: int = 5}

# aispm/llm.py
async def complete(messages: list[dict], *, model: str | None = None,
                   max_tokens: int = 2048, temperature: float = 0.7) -> Completion: ...

# aispm/secrets.py
async def get_secret(name: str) -> str: ...

# aispm/lifecycle.py
async def ready() -> None: ...     # signals controller; sets runtime_state=running

# aispm/log.py
def log(message: str, *, trace: str | None = None, **fields) -> None: ...
```

The full type signatures matter because the V1 quickstart docs will reference them and customer IDEs need them for autocomplete.



```python
# Connection info — injected at container start; no secrets in code
aispm.AGENT_ID            # str
aispm.LLM_BASE_URL        # http://spm-llm-proxy:8500/v1   (OpenAI-compat)
aispm.LLM_API_KEY         # per-agent token
aispm.MCP_URL             # http://spm-mcp:8500/mcp
aispm.MCP_TOKEN           # per-agent bearer token

# Chat — user-facing channel
async for msg in aispm.chat.subscribe(): ...
    msg.session_id, msg.user_id, msg.text, msg.ts

await aispm.chat.reply(session_id, text)              # full message (V1)
async with aispm.chat.stream(session_id) as out:      # token-by-token (V1.5)
    await out.write(chunk)

history = await aispm.chat.history(session_id, limit=10)
# [{"role": "user|agent", "text": "...", "ts": ...}, ...]

# Tools — MCP server
result = await aispm.mcp.call("web_fetch", query=..., max_results=5)

# Convenience LLM wrapper (most LangChain users hit the proxy directly)
resp = await aispm.llm.complete(messages=[...])

# Per-agent secrets — configured in detail panel Tab 2 → Custom env vars
val = await aispm.get_secret("MY_API_KEY")

# Lifecycle
await aispm.ready()                                   # signal "I'm initialized"
aispm.log("starting reasoning step", trace=msg.id)    # to lineage
```

### Bare-minimum agent (~10 lines)

```python
import aispm, asyncio

async def main():
    await aispm.ready()
    async for msg in aispm.chat.subscribe():
        ctx = await aispm.mcp.call("web_fetch", query=msg.text)
        resp = await aispm.llm.complete(messages=[
            {"role": "system", "content": "Answer using the context."},
            {"role": "user", "content": f"{msg.text}\n\nContext: {ctx}"},
        ])
        await aispm.chat.reply(msg.session_id, resp.text)

asyncio.run(main())
```

### LangChain agent (~20 lines)

```python
import aispm, asyncio
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate

llm = ChatOpenAI(base_url=aispm.LLM_BASE_URL, api_key=aispm.LLM_API_KEY)

@tool
async def web_fetch(query: str) -> str:
    """Search the web via Tavily."""
    return await aispm.mcp.call("web_fetch", query=query)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You're a research assistant."),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])
executor = AgentExecutor(
    agent=create_tool_calling_agent(llm, [web_fetch], prompt),
    tools=[web_fetch],
)

async def main():
    await aispm.ready()
    async for msg in aispm.chat.subscribe():
        result = await executor.ainvoke({"input": msg.text})
        await aispm.chat.reply(msg.session_id, result["output"])

asyncio.run(main())
```

### Concurrent sessions

To handle multiple users in parallel (so one slow request doesn't block others), the customer wraps the body in a task:

```python
async for msg in aispm.chat.subscribe():
    asyncio.create_task(handle(msg))
```

Will be in the docs.

### Failure semantics

- Uncaught exception in customer code → SDK catches at the loop level, replies `"Agent error (logged)"` to user, full traceback to lineage.
- Agent doesn't reply within `chat_response_timeout` (default 60s) → SDK times out, sends `"Agent timeout"`, marks the trace as failed.
- Container OOM/crash → controller restarts once with backoff; if still failing, sets `runtime_state = crashed` and surfaces in detail panel.

## 9. Customer journey

```
1. UPLOAD
   Inventory → Agents → "+ Register Asset"
   Form fields: Name, Version, Owner, Description, Asset type=Agent,
                Agent type, Upload agent.py, Deploy after registration ☑
   Submit → POST /api/spm/agents
     - Validates agent.py — three checks, all blocking:
       (a) `ast.parse()` — must be syntactically valid Python 3.12
       (b) Top-level `async def main()` must exist (parsed from AST)
       (c) Dry-import inside an ephemeral agent-runtime-base container
           (`python -c "import importlib.util; spec=...; spec.loader.exec_module(...)"`):
           catches missing imports / NameError at module top-level.
       Failures return 422 with the offending line + reason; warnings (e.g.
       `import langchain_extensions` not in base image) are returned as
       warnings but do NOT block — customer can add via Tab 2 → Custom env
       vars or by waiting for V2's "extra packages" feature.
     - Inserts row in `agents` (runtime_state=stopped)
     - Mints mcp_token + llm_api_key
     - Optionally triggers deploy

2. DEPLOY
   spm-api orchestrator:
     a. Creates Kafka topics cpm.{tenant_id}.agents.{agent_id}.chat.in/.out
     b. Spawns container from agent-runtime-base with the agent's code
        bind-mounted, env populated from DB
     c. Container runs main(); SDK connects to Kafka + MCP
     d. SDK calls aispm.ready() → controller marks runtime_state=running
   Whole sequence ~5-10s. UI polls /api/spm/agents/{id} for state change.

3. CONFIGURE  (any time)
   Detail drawer → Tab 2. Restart-required changes trigger automatic restart.

4. CHAT
   Right-click → Open Chat (or Open Chat button in detail panel).
   Pipeline: prompt-guard → Kafka in → agent → tools/LLM → Kafka out → output-guard → SSE → UI.

5. STOP / RETIRE
   Stop: container down, state stays. Topics preserved.
   Retire: stop + delete code + delete topics + soft-delete the agents row.
```

## 10. Implementation phasing

**Phase 1 — backend foundation (1 week)**
- Alembic 005: `agents` + `agent_chat_sessions` + `agent_chat_messages` tables; seed existing 5 mock agents
- `services/spm_mcp/` — FastMCP server, web_fetch tool, Bearer auth
- `services/spm_llm_proxy/` — minimal OpenAI-compat HTTP shim
- `services/spm_api/agent_routes.py` — `POST /agents`, `GET /agents/{id}`, `POST /agents/{id}/start|stop`, `POST /agents/{id}/chat`
- `services/spm_api/agent_controller.py` — docker spawn/stop, Kafka topic CRUD
- `connector_registry.py` — `agent-runtime` connector type schema
- Pytest: target ≥80% coverage on new modules

**Phase 2 — agent runtime SDK (3-4 days)**
- `agent_runtime/aispm/` — `chat.py` (Kafka), `mcp.py` (HTTP MCP client), `llm.py` (HTTP), `secrets.py`
- `agent_runtime/Dockerfile` — Python 3.12-slim + SDK pre-installed
- Smoke tests: bare-minimum agent + LangChain agent end-to-end

**Phase 3 — UI (3-4 days)**
- Extend `RegisterAssetPanel` with Asset type=Agent + agent.py file picker
- New `AgentDetailDrawer` (5 tabs)
- New `AgentChatPanel` (SSE-driven)
- Right-click context menu on Agents tab
- Run/stop toggle wiring
- Replace mock data on Agents tab with `/api/spm/agents`

**Phase 4 — pipeline integration (2-3 days)**
- Wire prompt-guard / policy-decider / output-guard around `/agents/{id}/chat`
- Add `AgentChatMessage`, `AgentToolCall`, `AgentLLMCall` event types to `platform_shared/lineage_events.py`
- Update audit consumers (Recent Activity tab) for new event types

**Phase 5 — docs + polish (2 days)**
- "How to deploy your first agent" guide
- LangChain quickstart with the example from §8
- Operator runbook for the agent-runtime integration
- README updates

**Total ~3 weeks, parallelizable across two devs after Phase 1 lands.**

## 11. Open questions / V2 candidates

- Multi-tenancy enforcement on every endpoint
- `sql` MCP tool + per-agent named DSN management
- Custom MCP tool registration (customer ships a tool definition + endpoint)
- Token-by-token streaming (`aispm.chat.stream()` already in SDK; backend wiring deferred)
- Tool-call approval UI (user clicks "approve" before destructive tools run)
- LLM cost metering and quotas
- gVisor / Firecracker microVM sandboxing for stronger isolation
- Per-user-per-agent containers when blast-radius isolation matters
- OAuth on the MCP server in place of static bearer tokens
- Replay UI: scrub a chat session backwards / fork from a prior turn
