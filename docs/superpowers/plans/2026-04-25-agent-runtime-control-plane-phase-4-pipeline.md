# Agent Runtime Control Plane — Phase 4: Chat Pipeline + Policy Attachment

> Use superpowers:subagent-driven-development to execute task-by-task.

**Goal:** Make `/api/spm/agents/{id}/chat` a real, secure, observable round-trip — same security pipeline the existing `/chat/stream` uses (prompt-guard → policy-decider → … → output-guard) — and let operators **attach policies to agents** so the policy-decider has something to evaluate. Wire the agent-side hops (`web_fetch` MCP tool, LLM proxy) so they emit `AgentToolCallEvent` / `AgentLLMCallEvent` lineage events. Update the audit consumer + Activity tab so operators can see the full conversation as it happens.

**Architecture:** New `services/spm_api/agent_chat.py` SSE endpoint mirrors `services/api/app.py::chat_stream` but with per-agent Kafka topics and the new `Agent*Event` types. New `agent_policies` join table + REST surface for attaching/detaching policies. UI extends `PreviewPanel` "Linked Policies" with an actual editable selector, and `ActivityTab` ditches its placeholder for a real live tail.

**Reference spec:** `docs/superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md`
**Reference Phase 1:** `2026-04-25-agent-runtime-control-plane-phase-1-backend.md`
**Reference Phase 2:** `2026-04-25-agent-runtime-control-plane-phase-2-sdk.md`
**Reference Phase 3:** `2026-04-25-agent-runtime-control-plane-phase-3-ui.md`

**Survey reference (existing chat pipeline):** `services/api/app.py::chat_stream` lines 1016–1399 — the canonical security flow we mirror.

---

## File Structure

### New files

```
spm/alembic/versions/006_agent_policies.py             # join table

services/spm_api/agent_chat.py                          # SSE endpoint with full pipeline
services/spm_api/agent_policies_routes.py               # GET/POST/DELETE policy attachment
services/spm_api/tests/                                 # mirror existing pattern

services/spm_mcp/lineage.py                             # publish_lineage_event helper for tool calls
services/spm_llm_proxy/lineage.py                       # same for LLM calls

ui/src/admin/agents/PolicySelector.jsx                  # multi-select dropdown
ui/src/admin/agents/__tests__/PolicySelector.test.jsx
ui/src/admin/agents/hooks/useAgentActivity.js           # SSE tail of Agent* lineage events
```

### Modified files

```
spm/db/models.py                                        # add Agent.linked_policies relationship
services/spm_api/agent_routes.py                        # mount agent_chat + policies routers
services/spm_api/agent_chat.py                          # ↑ new — listed for clarity
services/spm_mcp/tools/web_fetch.py                     # emit AgentToolCallEvent on every call
services/spm_llm_proxy/main.py                          # emit AgentLLMCallEvent on every chat completion
services/agent-orchestrator-service/services/lineage_ingest.py
                                                        # persist Agent* events into session_events
ui/src/admin/pages/Inventory.jsx                        # PreviewPanel "Linked Policies" → editable
ui/src/admin/agents/tabs/ActivityTab.jsx                # real live tail (replace placeholder)
```

---

## Task 1 — DB: agent_policies join table (Alembic 006)

**Files:**
- Create: `spm/alembic/versions/006_agent_policies.py`
- Modify: `spm/db/models.py` — add `Agent.linked_policies = relationship(...)`

**Schema:**

```sql
CREATE TABLE agent_policies (
    agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    policy_id  TEXT NOT NULL,                       -- references CPM policy registry by ID
    attached_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attached_by TEXT,                                -- user sub from JWT
    PRIMARY KEY (agent_id, policy_id)
);
CREATE INDEX ix_agent_policies_policy ON agent_policies (policy_id);
```

`policy_id` is text not FK because the source-of-truth policy table lives in CPM (orchestrator), not spm-db. Phase 4 stores the ID; the UI fetches metadata (name, coverage) from `GET /api/v1/policies` (already exists).

- [ ] Step 1: write Alembic migration with upgrade/downgrade
- [ ] Step 2: ORM `AgentPolicy` model in `spm/db/models.py` + `Agent.policies` relationship
- [ ] Step 3: tests in `tests/test_agent_models.py` covering the relationship + cascade
- [ ] Step 4: run `alembic upgrade head` against dev DB; commit

---

## Task 2 — REST: policy attachment endpoints

**Files:**
- Create: `services/spm_api/agent_policies_routes.py`
- Modify: `services/spm_api/app.py` — mount the router
- Test: `tests/test_agent_policies_routes.py`

```
GET    /api/spm/agents/{id}/policies              → [{policy_id, attached_at, attached_by}, ...]
PUT    /api/spm/agents/{id}/policies              → replace the full set; body: {policy_ids: [...]}
POST   /api/spm/agents/{id}/policies/{policy_id}  → attach one
DELETE /api/spm/agents/{id}/policies/{policy_id}  → detach
```

PUT is the operator-friendly atomic-replace surface (matches the multi-select UI). POST/DELETE are for fine-grained scripting.

`require_admin` on writes; `verify_jwt` on reads.

- [ ] Step 1: failing tests for each verb
- [ ] Step 2: implement
- [ ] Step 3: include in `_to_dict(agent)` so list/get returns `linked_policies: [...]` (replaces the `"No policies applied"` UI text path)
- [ ] Step 4: run, commit

---

## Task 3 — UI: PolicySelector component + Inventory wiring

**Files:**
- Create: `ui/src/admin/agents/PolicySelector.jsx`
- Test: `ui/src/admin/agents/__tests__/PolicySelector.test.jsx`
- Modify: `ui/src/admin/pages/Inventory.jsx` — replace the static "Linked Policies" block

PolicySelector pattern: shows currently-linked policies as removable chips, plus a `+ Add policy` dropdown sourced from `GET /api/v1/policies`. Calls `PUT /agents/{id}/policies` on each change.

- [ ] Step 1: tests for chip render, add, remove, save
- [ ] Step 2: implement
- [ ] Step 3: PreviewPanel "Linked Policies" section — when asset is a live agent, render `<PolicySelector>` instead of the read-only badge list
- [ ] Step 4: run, commit

---

## Task 4 — Chat endpoint shell: SSE + auth + persistence

**Files:**
- Create: `services/spm_api/agent_chat.py`
- Modify: `services/spm_api/app.py` — mount the router
- Test: `tests/test_agent_chat.py`

Initial endpoint, no security yet (security tasks 5/6 wrap it):

```
POST /api/spm/agents/{id}/chat
body:    {"message": str, "session_id": str?}
auth:    verify_jwt
accept:  text/event-stream
```

Behaviour:
1. Look up agent; reject if not running.
2. Insert/upsert `agent_chat_sessions` row.
3. Persist user turn into `agent_chat_messages` (role=user).
4. Produce envelope to `cpm.{tenant}.agents.{id}.chat.in` (Kafka).
5. Subscribe to `chat.out`, await reply matching session_id (timeout 120s).
6. Persist agent turn (role=agent).
7. Stream `data: {"type":"done","text":<reply>}\n\n`.

- [ ] Step 1: failing tests covering happy path + 404 + 409 (agent not running) + timeout
- [ ] Step 2: implement
- [ ] Step 3: smoke against real stack (existing `agent.py.example` should round-trip)
- [ ] Step 4: commit

---

## Task 5 — Inbound security: prompt-guard + policy-decider

**Files:**
- Modify: `services/spm_api/agent_chat.py` — add the two screening calls
- Test: `tests/test_agent_chat.py`

Mirror `services/api/app.py::chat_stream` lines 1110–1230. Concrete:

```python
guard_verdict, guard_score, guard_categories = await call_guard(text)
if guard_verdict == "block":
    yield sse({"type":"error","text":"Prompt blocked by safety guard."})
    return

policy_decision = await call_policy(
    posture_score=guard_score,
    signals=guard_categories,
    auth_context={"sub": user_id, "tenant_id": tenant_id, ...},
    linked_policies=[p.policy_id for p in agent.policies],   # NEW: agent-attached policies
)
if policy_decision.is_blocked:
    yield sse({"type":"error","text": policy_decision.reason})
    return
```

The `linked_policies` field is new — the OPA policy package needs to know what policies are attached so it can evaluate them. Phase 4 passes them as input; the actual OPA rule update lands in a follow-up if existing rules don't already accept the list.

- [ ] Step 1: failing tests — prompt-guard block, policy block, allow happy path
- [ ] Step 2: import from `services/api/prompt_security/adapters/{guard,policy}_adapter.py` (re-use; don't duplicate)
- [ ] Step 3: persist `AgentChatMessageEvent` to lineage on every accepted user turn
- [ ] Step 4: commit

---

## Task 6 — Outbound security: output-guard

**Files:**
- Modify: `services/spm_api/agent_chat.py`
- Test: `tests/test_agent_chat.py`

Mirror `services/api/app.py` lines 777–804. After consuming the agent reply:

```python
contains_secret, contains_pii = _scan_output(reply)
output_decision = await call_output_policy(
    contains_secret=contains_secret,
    contains_pii=contains_pii,
    llm_verdict="allow",
)
if output_decision == "block":
    yield sse({"type":"error","text":"Reply blocked by output guard."})
    return
if output_decision == "redact":
    reply = _redact(reply)
yield sse({"type":"done","text": reply})
```

- [ ] Step 1: tests — secret leak → block; PII → redact; clean → allow
- [ ] Step 2: emit `AgentChatMessageEvent` (role=agent) AFTER the output-guard verdict
- [ ] Step 3: commit

---

## Task 7 — spm-mcp: emit AgentToolCallEvent

**Files:**
- Create: `services/spm_mcp/lineage.py`
- Modify: `services/spm_mcp/tools/web_fetch.py`
- Test: `services/spm_mcp/tests/test_lineage.py`

```python
# Inside web_fetch_mcp() — wrap the body
started = time.monotonic()
ok, args = True, {"query": query, "max_results": max_results}
try:
    result = await _web_fetch(...)
    return result
except Exception:
    ok = False; raise
finally:
    publish_lineage_event(
        producer,
        agent_id=agent["id"], tenant_id=agent["tenant_id"],
        event=AgentToolCallEvent(
            agent_id=agent["id"], tenant_id=agent["tenant_id"],
            tool="web_fetch", args=args, ok=ok,
            duration_ms=int((time.monotonic()-started)*1000),
            trace_id=ctx.trace_id,
        ),
    )
```

The agent's identity comes from the existing Bearer auth (verify_mcp_token returns the agent dict). `trace_id` is the chat envelope's trace_id, threaded through MCP via a custom header.

- [ ] Step 1: tests with mocked Kafka producer
- [ ] Step 2: implement
- [ ] Step 3: commit

---

## Task 8 — spm-llm-proxy: emit AgentLLMCallEvent

**Files:**
- Create: `services/spm_llm_proxy/lineage.py`
- Modify: `services/spm_llm_proxy/main.py::chat_completions`
- Test: `tests/test_spm_llm_proxy_lineage.py`

Same pattern as Task 7. After the upstream LLM responds, emit:

```python
AgentLLMCallEvent(
    agent_id=agent["id"], tenant_id=agent["tenant_id"],
    model=upstream_model,
    prompt_tokens=usage.get("prompt_tokens", 0),
    completion_tokens=usage.get("completion_tokens", 0),
    trace_id=request_trace_id,
)
```

- [ ] Step 1: tests
- [ ] Step 2: implement
- [ ] Step 3: commit

---

## Task 9 — Audit consumer: persist Agent* events

**Files:**
- Modify: `services/agent-orchestrator-service/services/lineage_ingest.py`

The orchestrator's lineage consumer already drains `cpm.global.lineage_events`. Today it knows about session events. Phase 4 extends `persist_lineage_event` to recognise the six `Agent*` event types and write them to `session_events` (or a new `agent_events` table — decide based on the existing schema).

For the Activity tab specifically, we need:
- `AgentChatMessageEvent` → row keyed by agent_id + session_id
- `AgentToolCallEvent` → row keyed by agent_id + trace_id
- `AgentLLMCallEvent` → same

- [ ] Step 1: read existing `lineage_ingest.persist_lineage_event` to understand the dispatch
- [ ] Step 2: add Agent* handlers — write to existing `session_events` if shape matches, else add a small `agent_events` table via Alembic 007
- [ ] Step 3: tests
- [ ] Step 4: commit

---

## Task 10 — UI ActivityTab: real live tail

**Files:**
- Modify: `ui/src/admin/agents/tabs/ActivityTab.jsx`
- Create: `ui/src/admin/agents/hooks/useAgentActivity.js`
- Tests

Replace the placeholder. Pull from a new `GET /api/spm/agents/{id}/activity?since=<ts>` endpoint (returns the last N Agent* events for that agent) and poll every 3s — same pattern `useAgentList` uses. SSE upgrade is V2.

- [ ] Step 1: failing tests
- [ ] Step 2: implement endpoint + hook + tab
- [ ] Step 3: commit

---

## Task 11 — End-to-end smoke

**Files:**
- Modify: `tests/e2e/test_aispm_sdk_smoke.py`

Extend the existing smoke to:
1. Attach a policy to the agent before chatting.
2. Send a chat message via `/api/spm/agents/{id}/chat`.
3. Assert the SSE stream produces `done` with non-empty text.
4. Assert the agent_chat_messages table has both user + agent rows.
5. Assert `cpm.global.lineage_events` received `AgentChatMessageEvent` for both turns.

- [ ] Step 1: extend the existing test
- [ ] Step 2: run, commit

---

## Task 12 — Docs

**Files:**
- Modify: `docs/agents/operator-quickstart.md`

Append:
- "Attach a policy to an agent" walkthrough (UI + curl)
- "Chat with an agent" — full round-trip
- "Read the activity tail" — what events surface and when
- Phase 4 limitations: streaming is still V1.5 (one done event), no per-tenant chat rate limits yet

- [ ] Commit `docs: phase-4 chat pipeline walkthrough`

---

## Phase 4 Done Criteria

- [ ] Operator can attach/detach policies via the UI; backend persists in `agent_policies`.
- [ ] `POST /api/spm/agents/{id}/chat` returns SSE; rejects bad prompts; redacts/blocks bad output.
- [ ] User + agent turns both persisted in `agent_chat_messages`.
- [ ] `web_fetch` MCP calls emit `AgentToolCallEvent`.
- [ ] LLM proxy calls emit `AgentLLMCallEvent`.
- [ ] Activity tab shows the events live.
- [ ] All tests green; no regressions.

---

## Out of scope (deferred to V1.5 / V2)

- Token-by-token streaming (one `done` event for now).
- Tool-call approval UI ("agent wants to run X — approve?").
- Per-tenant chat rate limits.
- Attachment of policies via API token rather than admin JWT.
- Replay UI for prior turns.
