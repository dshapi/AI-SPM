# Agent Runtime Control Plane — Operator Quickstart (Phase 1)

This guide walks through the Phase 1 backend for the agent runtime
control plane: standing up the new services, uploading a hello-world
`agent.py`, listing agents, and retiring them. Phase 2 ships the
`aispm` SDK and Phase 3 adds the UI; until then the only way to
interact with the system is the HTTP API documented here.

For the design rationale, see
[`docs/superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md`](../superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md).

## What's new

Phase 1 adds three pieces of infrastructure:

- **`spm-mcp`** — a FastMCP server exposing the platform-provided
  `web_fetch` tool (Tavily-backed). One container per stack, listening
  on port 8500.
- **`spm-llm-proxy`** — an OpenAI-compatible HTTP shim in front of the
  configured AI Provider integration (default: host Ollama). One
  container per stack, listening on port 8501.
- **`aispm-agent-runtime:latest`** — the base image used to spawn one
  container per customer-uploaded agent. Phase 1 ships a stub that
  echoes its env and stays alive; Phase 2 replaces it with the real
  `aispm` SDK.

Plus one new module in spm-api (`agent_controller.py`) that orchestrates
Docker spawn/stop and Kafka topic CRUD, and a new `agent-runtime`
ConnectorType under Integrations → AI Providers.

## Configure the control plane

The Phase 1 backend needs the agent-runtime ConnectorType configured
before any agent can talk to the LLM proxy or call `web_fetch`:

1. Open the AI-SPM admin UI → Integrations → AI Providers.
2. Look for **AI-SPM Agent Runtime Control Plane (MCP)**. Click
   **Configure**.
3. Set the **Default LLM** dropdown to the active AI Provider
   integration that should back `spm-llm-proxy` (Ollama works for dev).
4. Set the **Tavily Integration** dropdown to your Tavily integration
   row (`web_fetch` reads its `api_key` at every call).
5. Save. Click **Test Connection** — it probes spm-mcp's `/health`,
   then runs the chosen LLM and Tavily integrations' probes.

Phase 1 stores all values in `integrations.config` (non-secret); no
credentials live on this row directly.

## Upload an agent

Get a dev token (only available in dev — production goes through the
real auth path):

```bash
TOKEN=$(curl -s http://localhost:8092/api/dev-token | jq -r .token)
```

A minimal valid `agent.py`:

```python
import asyncio

async def main():
    print("hello from agent")
    await asyncio.sleep(1)

asyncio.run(main())
```

Upload it:

```bash
curl -X POST http://localhost:8092/api/spm/agents \
  -H "Authorization: Bearer $TOKEN" \
  -F name=hello \
  -F version=1.0 \
  -F agent_type=custom \
  -F owner=$USER \
  -F deploy_after=false \
  -F code=@agent.py
```

The validator runs three checks before accepting:

1. `ast.parse()` — must be syntactically valid Python 3.12.
2. Top-level `async def main()` must exist.
3. Dry-import inside an ephemeral Python — surfaces missing-stdlib
   errors. ImportErrors on third-party modules become **warnings**
   (returned in the response), not blockers, because the runtime
   container ships those packages.

Validation failures return **422** with a `detail` list of the offending
errors; warnings appear in the response body's `warnings` field.

## List, inspect, delete

```bash
# All agents in the caller's tenant
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8092/api/spm/agents | jq

# One agent by id
AGENT_ID=...
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8092/api/spm/agents/$AGENT_ID | jq

# Patch (description, owner, risk, policy_status, version, agent_type, name)
curl -s -X PATCH http://localhost:8092/api/spm/agents/$AGENT_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description":"updated"}' | jq

# Delete (stops container, deletes topics, drops the row)
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8092/api/spm/agents/$AGENT_ID
```

The response shape NEVER includes `mcp_token` or `llm_api_key` — those
are admin-only and are minted, stored encrypted (V2), and consumed
internally by the runtime container's env. `code_path` and
`code_sha256` are returned for tamper detection.

## Start / stop / restart

```bash
# Idempotent kick — async, returns 202 immediately
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8092/api/spm/agents/$AGENT_ID/start

curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8092/api/spm/agents/$AGENT_ID/stop
```

Poll `GET /api/spm/agents/$AGENT_ID` and watch `runtime_state`
transition `stopped → starting → running` (or `crashed` on failure).
Phase 2's SDK signal replaces the V1 hardcoded 5-second readiness
delay.

## Logs and debugging

```bash
docker logs -f cpm-spm-mcp           # MCP server (Tavily, web_fetch)
docker logs -f cpm-spm-llm-proxy     # LLM proxy (Ollama forward)
docker logs -f agent-$AGENT_ID       # the per-agent runtime container
docker logs -f cpm-spm-api           # the controller — spawn/stop/Kafka
```

Useful one-liners:

```bash
# Health
curl -fs http://localhost:8500/health   # spm-mcp
curl -fs http://localhost:8501/health   # spm-llm-proxy

# Kafka topics for a deployed agent
docker compose exec kafka-broker kafka-topics \
  --list --bootstrap-server kafka-broker:9092 \
  | grep "cpm.*agents.$AGENT_ID"
```

## Phase 1 limitations (intentional)

The following are deferred to subsequent phases — see the spec for the
full V2 list:

- **No agent-runtime SDK yet**: the runtime image is a Phase 1 stub
  that echoes env vars and sleeps. Uploaded agents that `import aispm`
  will fail at runtime until Phase 2.
- **No UI**: the Inventory → Agents tab still renders mocks. Phase 3
  switches it to the live `/api/spm/agents` endpoint.
- **No chat pipeline**: `POST /api/spm/agents/{id}/chat` is unwired
  until Phase 4 (prompt-guard → Kafka → output-guard → SSE).
- **No streaming**: `aispm.chat.stream()` exists in the SDK contract
  but the backend wiring is V1.5.
- **No multi-tenant enforcement**: tenant_id is in the schema and
  honoured by the list endpoint, but the rest of the system is single-
  tenant. V2 enforces strict isolation.
- **Plaintext tokens at rest**: V1 stores `mcp_token` / `llm_api_key`
  unencrypted. The row is admin-only and never returned in responses,
  but V2 will encrypt with the existing Fernet key.

## Phase 4 — chat actually works

End-to-end chat is live as of 2026-04-25. The full path:

```
UI → POST /agents/{id}/chat (SSE)
      ↓
   prompt-guard /screen   ── allow/block (Llama Guard 3)
      ↓
   policy-decider /v1/data/spm/prompt/allow  ── OPA, takes attached agent_policies into account
      ↓
   Persist user turn (agent_chat_messages) + emit AgentChatMessageEvent
      ↓
   Kafka cpm.{tenant}.agents.{id}.chat.in
      ↓
   ────── agent runtime ─────────────────────────────
      aispm.chat.subscribe()  (consumer with auto_offset_reset=earliest
                                so first message is never lost)
      aispm.chat.history()    ← prior turns (real conversation memory)
      aispm.mcp.call('web_fetch', ...) → spm-mcp /mcp (Tavily)
      aispm.llm.complete(...)  → spm-llm-proxy /v1/chat/completions
      aispm.chat.reply(...)    → Kafka cpm.{tenant}.agents.{id}.chat.out
   ─────────────────────────────────────────────────
      ↓
   output-guard regex (secrets/PII) + policy-decider /v1/data/spm/output/allow
      ↓
   Persist agent turn + AgentChatMessageEvent
      ↓
   SSE: data: {"type":"done","text":"..."}
```

### Bring-up checklist

1. `docker compose up -d` (everything).
2. **Configure the agent-runtime row** under Integrations → AI Providers → *AI-SPM Agent Runtime Control Plane (MCP)*. **Default LLM** and **Tavily Integration** are real dropdowns now — pick from the list.
3. Verify **Default LLM**'s upstream is itself configured (Anthropic API key set, or Ollama serving the model named on its row).
4. Click *Test* on the agent-runtime row. Should turn green.
5. Inventory → Agents → Register Asset → drop in `Example agents/custom_agent.py` → type `custom` → Register.
6. Wait for runtime state to flip to **running** (~5–15 s on first deploy).
7. Click *Open Chat* → send a message.

### Provider dispatch

`spm-llm-proxy` branches on the upstream integration's `connector_type`:

| `connector_type` | URL                                            | Auth header                   | Model source           |
|------------------|------------------------------------------------|-------------------------------|------------------------|
| `anthropic`      | `{base_url}/v1/messages` (default `api.anthropic.com`) | `x-api-key` + `anthropic-version: 2023-06-01` | integration `model` field — payload model is honoured only if it starts with `claude` |
| `ollama` (base ends in `/v1`) | `{base_url}/chat/completions` (OpenAI-compat) | none                          | integration `model` (e.g. `llama3.2`) |
| `ollama` (base does NOT end in `/v1`) | `{base_url}/api/chat` (native)                  | none                          | integration `model` field   |

The operator's configured model wins over whatever the agent's SDK sent. The SDK leaves `model` unset by default; only an explicit `aispm.llm.complete(model="...")` call overrides.

### Switching providers

Just change the **Default LLM** dropdown on the agent-runtime row. The proxy resolves on every request — no restart, no agent re-deploy. Works for Anthropic ↔ Ollama (and any other provider once dispatch is added).

### Common gotchas (and what they look like)

| Symptom | Cause | Fix |
|---|---|---|
| Agent stuck `paused` / shows Restart immediately after deploy | `spm-api` reading stale identity-mapped Agent row in `_wait_for_ready` | Already fixed (`db.expire_all()` per poll). Just rebuild `spm-api`. |
| First chat after deploy silently lost | Kafka consumer hadn't joined the group yet | Already fixed (`auto_offset_reset="earliest"`). Rebuild agent-runtime image. |
| Chat returns `(error: Load failed)` | `spm-api` crashed. Common causes: missing `aiokafka`, `204 must not have a response body` import-time assertion, missing `spm_api` package import. | All inlined / fixed. Check `docker compose logs spm-api`. |
| Chat returns `502 Bad Gateway` from `/v1/chat/completions` | Upstream integration not configured, wrong model name, or `connector_type` mismatch (e.g. `/v1/api/chat`). | Check `docker compose logs spm-llm-proxy` — the new `dispatching connector_type=...` line names the cause. |
| `web_fetch` 404 on `http://spm-mcp:8500/mcp` | `spm-mcp` had FastMCP tools but the HTTP route wasn't mounted | Already fixed (explicit `POST /mcp` JSON-RPC handler). |
| `Prompt blocked by safety guard. (S2)` on the literal word "yes" | Guard model returns benign category on short input; old code force-blocked on any S1–S15 cat | Already fixed (8-char short-input bypass + score ≥ `GUARD_BLOCK_SCORE` only). |
| Agent has no memory between turns | The example agent didn't fetch `aispm.chat.history()` | Already fixed in `Example agents/custom_agent.py`. Re-upload it. |

### Configuration knobs (env, mostly safe defaults)

| Env var | Service | Default | Purpose |
|---|---|---|---|
| `GUARD_BLOCK_SCORE` | `api`, `spm-api` | `0.6` | Min guard score to escalate `allow + category` → `block`. |
| `GUARD_MIN_TEXT_LEN` | `api`, `spm-api` | `8` | Inputs shorter than this skip the guard entirely. |
| `AGENT_READY_TIMEOUT_S` | `spm-api` | `30` | Deploy poll budget for the SDK's `ready()` handshake. |
| `AGENT_CHAT_REPLY_TIMEOUT_S` | `spm-api` | `120` | How long the chat round-trip waits for an agent reply on `chat.out`. |
| `AGENT_CONTROLLER_URL` | `spm-api` | `http://spm-api:8092` | What gets injected as `CONTROLLER_URL` into spawned agent containers. |

## Reference

- Design spec: [`docs/superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md`](../superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md)
- Implementation plan: [`docs/superpowers/plans/2026-04-25-agent-runtime-control-plane-phase-1-backend.md`](../superpowers/plans/2026-04-25-agent-runtime-control-plane-phase-1-backend.md)
- Phase 4 plan: [`docs/superpowers/plans/2026-04-25-agent-runtime-control-plane-phase-4-pipeline.md`](../superpowers/plans/2026-04-25-agent-runtime-control-plane-phase-4-pipeline.md)
- Example agents: [`Example agents/`](../../Example%20agents/)
- V1 non-goals: spec §2
- V2 candidates: spec §11
