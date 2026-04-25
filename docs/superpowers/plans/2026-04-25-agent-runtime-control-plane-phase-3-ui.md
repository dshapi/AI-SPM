# Agent Runtime Control Plane — Phase 3: UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing AISPM admin UI to the Phase 1 + 2 backend so operators can register agents, configure them, chat with them, and monitor their runtime activity — all from the Inventory → Agents tab. Replace the 5 hard-coded mock rows in `Inventory.jsx` with live data from `GET /api/spm/agents`. Build the detail drawer (5 tabs per spec § 6), the SSE-driven chat panel, the right-click context menu, the run/stop toggle, and the agent-upload extension to `RegisterAssetPanel`.

**Architecture:** New components colocated under `ui/src/admin/agents/` so the Phase 3 surface area is self-contained and reviewable as one unit. New API client `ui/src/admin/api/agents.js` mirrors the existing `spm.js` token-caching pattern. Live agent rows merge into the existing Inventory table the same way live model rows do today (`live-{id}` prefix). Chat uses the existing SSE wire format from `ui/src/api.js::sendMessageStream` with a new endpoint path.

**Tech Stack (already in `ui/package.json`):** React 18.3.1, Vite 8.0.8, react-router-dom 6.26.2, Tailwind 3.4.13, lucide-react. Tests via Vitest + @testing-library/react.

**Reference spec:** `docs/superpowers/specs/2026-04-25-agent-runtime-control-plane-mcp-design.md` § 6 (Agent detail panel) + § 9 (Customer journey).
**Reference Phase 1 plan:** `docs/superpowers/plans/2026-04-25-agent-runtime-control-plane-phase-1-backend.md`
**Reference Phase 2 plan:** `docs/superpowers/plans/2026-04-25-agent-runtime-control-plane-phase-2-sdk.md`

---

## File Structure

### New files

```
ui/src/admin/api/agents.js                                     # API client (list/get/create/patch/delete/start/stop)
ui/src/admin/agents/
  AgentDetailDrawer.jsx                                        # 5-tab detail drawer
  AgentDetailDrawer.test.jsx
  AgentChatPanel.jsx                                           # SSE-driven chat
  AgentChatPanel.test.jsx
  AgentRunStopToggle.jsx                                       # Reusable run/stop button
  ContextMenu.jsx                                              # Right-click menu primitive
  ContextMenu.test.jsx
  tabs/
    OverviewTab.jsx
    ConfigureTab.jsx
    ActivityTab.jsx
    SessionsTab.jsx
    LineageTab.jsx
  hooks/
    useAgentList.js                                            # Live polling + merge with mocks
    useAgentChat.js                                            # SSE subscription
    useAgentLifecycle.js                                       # Start/stop/restart actions
ui/src/admin/api/__tests__/agents.test.js
```

### Modified files

```
ui/src/admin/pages/Inventory.jsx                               # extend ASSETS, RegisterAssetPanel, agents tab → live data, right-click handler
ui/src/admin/pages/Inventory.test.jsx                          # update mock-vs-live agent assertions
ui/src/index.jsx                                               # no route changes — drawer is in-page
```

---

## Task 1: API client — `ui/src/admin/api/agents.js`

**Files:**
- Create: `ui/src/admin/api/agents.js`
- Create: `ui/src/admin/api/__tests__/agents.test.js`

Mirrors `ui/src/admin/api/spm.js`'s pattern: token caching, `_authHeaders()`, fetch wrapper, file-upload via XHR for the multipart agent.py upload.

- [ ] **Step 1: Failing tests**

```js
// ui/src/admin/api/__tests__/agents.test.js
import { describe, it, expect, vi, beforeEach } from "vitest"
import * as agents from "../agents"

beforeEach(() => {
  global.fetch = vi.fn()
})

describe("listAgents", () => {
  it("GETs /api/spm/agents with bearer token", async () => {
    global.fetch.mockResolvedValueOnce(new Response(
      JSON.stringify([{ id: "ag-001", name: "x" }]),
      { status: 200 }
    ))
    const out = await agents.listAgents()
    expect(out).toEqual([{ id: "ag-001", name: "x" }])
    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toContain("/api/spm/agents")
    expect(opts.headers.Authorization).toMatch(/^Bearer /)
  })
})

describe("startAgent / stopAgent", () => {
  it("POSTs /agents/{id}/start", async () => {
    global.fetch.mockResolvedValueOnce(new Response("", { status: 202 }))
    await agents.startAgent("ag-001")
    const [url] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/agents\/ag-001\/start$/)
  })

  it("POSTs /agents/{id}/stop", async () => {
    global.fetch.mockResolvedValueOnce(new Response("", { status: 202 }))
    await agents.stopAgent("ag-001")
    const [url] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/agents\/ag-001\/stop$/)
  })
})

// + tests for getAgent, patchAgent, deleteAgent, createAgentWithFile (XHR multipart)
```

- [ ] **Step 2: Implement**

Surface (concrete signatures):

```js
// agents.js
export async function listAgents()                 // GET /api/spm/agents → Agent[]
export async function getAgent(id)                 // GET /api/spm/agents/{id}
export async function patchAgent(id, body)         // PATCH (description/owner/risk/policy_status)
export async function deleteAgent(id)              // DELETE
export async function startAgent(id)               // POST /start
export async function stopAgent(id)                // POST /stop
export async function createAgentWithFile({       // POST multipart, XHR with progress
  name, version, agentType, owner, description,
  deployAfter, file, onProgress, signal,
})
```

Token caching is identical to `spm.js`: 60s freshness window, fetch from `/api/dev-token` on miss.

- [ ] **Step 3: Run, pass; commit**

```
pnpm test agents.test
git add ui/src/admin/api/agents.js ui/src/admin/api/__tests__/agents.test.js
git commit -m "feat(ui): agents API client"
```

---

## Task 2: useAgentList hook — live polling + merge with mocks

**Files:**
- Create: `ui/src/admin/agents/hooks/useAgentList.js`
- Test: `ui/src/admin/agents/hooks/__tests__/useAgentList.test.jsx`

Polls `listAgents()` every 5s. Merges live rows with the inline ASSETS mocks the same way `Inventory.jsx` already merges live models (lines 1085–1136 in current file). Live rows take precedence; rows present in both (matched by name) hide the mock.

- [ ] **Step 1: Failing test** — covers (a) returns mocks immediately on mount, (b) replaces mocks with live data on first poll, (c) preserves mocks for names absent from live data, (d) cleans up interval on unmount.

- [ ] **Step 2: Implement.** Key logic:

```js
export function useAgentList({ pollMs = 5000 } = {}) {
  const [live, setLive]   = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const rows = await listAgents()
        if (!cancelled) setLive(rows)
      } catch (e) { if (!cancelled) setError(e) }
    }
    tick()
    const id = setInterval(tick, pollMs)
    return () => { cancelled = true; clearInterval(id) }
  }, [pollMs])

  return { live, error }
}

// merge helper
export function mergeAgents(mocks, live) {
  const liveNames = new Set(live.map(a => a.name))
  return [
    ...live.map(a => ({ ...a, _source: "live" })),
    ...mocks.filter(m => !liveNames.has(m.name))
            .map(m => ({ ...m, _source: "mock" })),
  ]
}
```

- [ ] **Step 3: Tests + commit.**

---

## Task 3: Wire Inventory's Agents tab to live data

**Files:**
- Modify: `ui/src/admin/pages/Inventory.jsx`
- Modify: `ui/src/admin/pages/__tests__/Inventory.test.jsx`

- [ ] **Step 1: Replace inline ASSETS lookup for agents** with `mergeAgents(MOCK_AGENTS, live)` from `useAgentList`. Mock array stays as a fallback for offline dev (no spm-api running).

- [ ] **Step 2: Add a small "live" badge** next to live agent names so operators can see at a glance which rows are real vs. seed data. Pattern: `{a._source === "live" && <Dot className="text-emerald-500" />}`

- [ ] **Step 3: Update `Inventory.test.jsx`** so the agents-tab tests mock `listAgents` instead of asserting on the hard-coded 5 rows.

- [ ] **Step 4: Run, commit.**

---

## Task 4: Extend RegisterAssetPanel — Asset type = Agent

**Files:**
- Modify: `ui/src/admin/pages/Inventory.jsx` (RegisterAssetPanel section, lines 676–1081)
- Modify: `ui/src/admin/pages/__tests__/Inventory.test.jsx`

The current panel handles models. Adding agents needs:

1. New `ASSET_TYPE` outer toggle (Model | Agent) at the top of the form.
2. When Agent is selected, swap the model-specific fields (model_type) for the agent-specific ones (agent_type: langchain/llamaindex/autogpt/openai_assistant/custom).
3. The file picker stays — same chip UI — but the accept attribute changes (`.py` only) and the upload route changes from `registerModelWithFile` to `createAgentWithFile`.
4. New checkbox `Deploy after registration` (defaults to `true`) — wired through to the `deploy_after` form field.
5. After success: close the panel, fire a toast, optimistically prepend the row to the agents list with `runtime_state="starting"` so the table updates before the next poll.

- [ ] **Step 1: Failing tests** for the toggle + agent-form rendering + file-type validation.

- [ ] **Step 2: Implement** — mostly composition of existing primitives. Reuse `FIELD_CLS` / `SELECT_CLS` for visual consistency.

- [ ] **Step 3: Commit** — `feat(ui): RegisterAssetPanel can register agents with agent.py upload`

---

## Task 5: AgentRunStopToggle component

**Files:**
- Create: `ui/src/admin/agents/AgentRunStopToggle.jsx`
- Test: `ui/src/admin/agents/AgentRunStopToggle.test.jsx`

Reusable button for the "Run / Stop" action. Used in 3 places: PreviewPanel header, AgentDetailDrawer Overview tab, right-click context menu.

Props: `agent`, `onChange?: (newState) => void`. Reads `agent.runtime_state`, renders the right icon (`Play` / `Square` / `RefreshCw` for crashed), shows a brief loading spinner while the start/stop API call is in flight, surfaces errors via an inline tooltip.

- [ ] **Steps 1-3:** failing test → implement → pass → commit.

---

## Task 6: Right-click ContextMenu primitive

**Files:**
- Create: `ui/src/admin/agents/ContextMenu.jsx`
- Test: `ui/src/admin/agents/ContextMenu.test.jsx`

Reusable across the codebase. There's no existing pattern (the survey confirmed none of the current UI uses `onContextMenu`), so this becomes the canonical primitive.

API:

```jsx
<ContextMenu items={[
  { label: "Open Chat",    icon: <MessageSquare/>, onClick: () => ... },
  { label: "Configure",    icon: <Settings/>,      onClick: () => ... },
  { kind: "separator" },
  { label: "Stop",         icon: <Square/>,        onClick: () => ..., danger: true },
]}>
  <tr>...</tr>
</ContextMenu>
```

Positioning: capture `clientX/clientY` on right-click, render an absolutely-positioned panel with z-50, close on Escape / click-outside / scroll. Keyboard navigable (arrows + Enter).

- [ ] **Steps 1-3:** failing test (click event opens menu, Escape closes, item click fires callback) → implement → pass → commit.

---

## Task 7: AgentDetailDrawer — Tab 1 (Overview)

**Files:**
- Create: `ui/src/admin/agents/AgentDetailDrawer.jsx`
- Create: `ui/src/admin/agents/tabs/OverviewTab.jsx`
- Tests: `AgentDetailDrawer.test.jsx`, `OverviewTab.test.jsx`

Drawer = right-side panel (matches `PreviewPanel` width but ~60vw, since it has tabs and more content). Risk-tinted header (mirror `PreviewPanel`'s pattern). Tab strip below header, content below that.

Overview tab content per spec § 6:
- Display name + agent_type + risk badge + policy_status badge
- Owner / Provider / Last Seen / Description rows
- Linked Policies card (with quick-add)
- Active Alerts count + link
- Runtime status row with `<AgentRunStopToggle>` button
- "Open Chat" CTA button

- [ ] **Step 1: Failing tests** — drawer opens/closes via prop, all required fields render, run/stop toggle wired.

- [ ] **Step 2: Implement** — compose from existing primitives. The drawer itself manages tab state via `useState`; tabs are passive.

- [ ] **Step 3: commit.**

---

## Task 8: AgentDetailDrawer — Tab 2 (Configure)

**Files:**
- Create: `ui/src/admin/agents/tabs/ConfigureTab.jsx`
- Test: `tabs/__tests__/ConfigureTab.test.jsx`

Per spec § 6: 5 field groups (Identity / LLM / Resources / Custom env vars / Tools / Code).

- Identity: name, version, agent_type, owner, description (PATCH on save)
- LLM: override LLM dropdown (sourced from `GET /api/spm/integrations?category=AI%20Providers` — the new `enum_integration` field type backend support already lands in Phase 1), override model name, max_tokens, temperature
- Resources: memory_limit, cpu_quota, idle_timeout
- Custom env vars: KEY+value rows. Posts to `PATCH /agents/{id}` with a `config.env_vars` map (Phase 4 will encrypt; Phase 3 sends plaintext over HTTPS)
- Tools: web_fetch on/off (just one switch in Phase 3)
- Code: read-only filename + sha256, "Replace code" button that opens the same multipart upload UI as RegisterAssetPanel

Restart-required changes show a banner: "Saving will restart the agent (~5s)". Save fires `PATCH` then `POST /restart` (which is `stop` then `start`).

- [ ] **Steps 1–3:** failing tests for each field group → implement → commit.

---

## Task 9: AgentDetailDrawer — Tabs 3+4+5 (Activity / Sessions / Lineage)

**Files:**
- Create: `ui/src/admin/agents/tabs/ActivityTab.jsx`
- Create: `ui/src/admin/agents/tabs/SessionsTab.jsx`
- Create: `ui/src/admin/agents/tabs/LineageTab.jsx`

All three reuse existing components from `Runtime.jsx` (`RecentActivityTable`, the lineage view, etc.) scoped by `?agent_id=` query param. No new visual primitives.

- **Activity:** Live tail of `AgentChatMessage` / `AgentToolCall` / `AgentLLMCall` events. Phase 4 wires those event types into the existing audit consumers; for Phase 3 we render whatever the audit feed emits, even if some types don't appear yet.
- **Sessions:** List of `agent_chat_sessions` rows from `GET /agents/{id}/sessions`. Click → opens that user's chat history in the chat panel.
- **Lineage:** Reuses the existing Lineage view, scoped to this agent.

- [ ] **Steps 1–3 each:** lightweight tests (renders without crashing, calls the right endpoint) → implement → commit.

---

## Task 10: AgentChatPanel — SSE-driven chat UI

**Files:**
- Create: `ui/src/admin/agents/AgentChatPanel.jsx`
- Create: `ui/src/admin/agents/hooks/useAgentChat.js`
- Tests: both files

The chat panel is a separate drawer (not nested inside the detail drawer) so users can keep the detail drawer open while chatting. Triggered by:
- "Open Chat" button on the Overview tab
- "Open Chat" item in the right-click context menu
- A separate `<MessageSquare/>` button in the row's hover toolbar

Wire format: identical to `ui/src/api.js::sendMessageStream` — POST `/api/spm/agents/{id}/chat` with `{message, session_id}`, stream back `data: {type: "token"|"badge"|"done", text}` SSE chunks.

`useAgentChat` returns:
```js
{
  messages,             // [{ role, text, ts }]
  send(text),           // POSTs + appends
  reset(),              // new session_id
  isStreaming,          // bool — for spinner
  error,
}
```

Reuse the `requestAnimationFrame` token-coalescing pattern from `App.jsx` (lines 78–105) so token-by-token SSE doesn't cause render jank.

- [ ] **Step 1: Failing tests** — covers a full round trip (send → token chunks arrive → done → error path).

- [ ] **Step 2: Implement** — directly mirrors the existing chat path. Phase 3 backend doesn't yet stream (V1 does full-message replies); the panel handles both: when the SSE stream emits one big `done` event, it renders that message all at once. Phase 1.5 streaming will start working without UI changes.

- [ ] **Step 3: commit.**

---

## Task 11: Wire context menu into the Agents tab

**Files:**
- Modify: `ui/src/admin/pages/Inventory.jsx`

For each row in the agents table:

```jsx
<ContextMenu items={[
  { label: "Open Chat",   icon: <MessageSquare/>, onClick: () => setChatAgent(agent) },
  { label: "Configure",   icon: <Settings/>,      onClick: () => setDetailAgent(agent) },
  { kind: "separator" },
  agent.runtime_state === "running"
    ? { label: "Stop",  icon: <Square/>, onClick: () => stopAgent(agent.id), danger: true }
    : { label: "Start", icon: <Play/>,   onClick: () => startAgent(agent.id) },
  { kind: "separator" },
  { label: "Retire", icon: <Trash2/>, onClick: () => deleteAgent(agent.id), danger: true,
    confirm: { title: "Retire agent?",
                body: "Stops container, deletes topics, drops the row. This cannot be undone.",
                cta: "Retire" } },
]}>
  {/* existing <tr/> contents */}
</ContextMenu>
```

`confirm` is a built-in option of `ContextMenu` — when present, the menu fires `onClick` only after the user confirms in a small modal. Keeps the destructive action behind one click.

- [ ] Tests + commit.

---

## Task 12: Switch single-click to open detail drawer

**Files:**
- Modify: `ui/src/admin/pages/Inventory.jsx`

Per spec § 6 the Configure menu item AND single-click on a row both open the detail drawer. The current single-click opens `PreviewPanel`; we keep PreviewPanel for non-agent assets and route to `AgentDetailDrawer` when the asset is an agent.

```jsx
const handleRowClick = (asset) => {
  if (asset.kind === "agent") {
    setDetailAgent(asset)
  } else {
    navigate(`/admin/inventory/${asset.id}`, { replace: true })
  }
}
```

- [ ] Tests + commit.

---

## Task 13: End-to-end smoke (Vitest jsdom)

**Files:**
- Create: `ui/src/admin/agents/__tests__/agents_e2e.test.jsx`

Component-level e2e (no real backend): mock `agents.js`, render `<Inventory>` with a routing wrapper, simulate the full operator journey:

1. Click "Register Asset" → toggle to Agent → fill form → upload a fake `agent.py` File → submit.
2. Mocked `createAgentWithFile` returns `{id, runtime_state: "starting"}`. Optimistic row appears.
3. Mocked `listAgents` returns the same row with `runtime_state: "running"` after a tick. Row updates.
4. Right-click the row → "Open Chat". Chat panel opens.
5. Type a message → mocked SSE stream returns three token chunks then `done`. Rendered text matches.
6. Right-click → "Stop". Mocked `stopAgent` called. Row's runtime_state flips to `"stopped"` on next poll.

This is the regression net for the whole UI surface — fast (~200ms) but covers the critical paths.

- [ ] **Steps 1–3:** failing test → implement supporting fixtures → pass → commit.

---

## Task 14: Operator-quickstart + README updates

**Files:**
- Modify: `docs/agents/operator-quickstart.md` (Phase 1's doc)
- Modify: `README.md`

Append Phase 3 sections to the operator quickstart:

- "Register an agent (UI)" — screenshot-friendly walkthrough mirroring the curl examples
- "Chat with an agent" — using AgentChatPanel
- "Configure / Stop / Retire from the UI"

Update the README's "Agent runtime control plane" section to mention "and a full UI under Inventory → Agents."

- [ ] Commit `docs: phase-3 UI walkthrough`.

---

## Phase 3 Done Criteria

- [ ] Agents tab in Inventory shows live `/api/spm/agents` data, falling back to mocks when backend is offline.
- [ ] RegisterAssetPanel can upload an `agent.py` and successfully creates the agent (verified against running spm-api).
- [ ] Right-click on any agent row opens a context menu with Open Chat / Configure / Start|Stop / Retire.
- [ ] Single-click opens AgentDetailDrawer (5 tabs).
- [ ] AgentChatPanel does a full-message round trip with the spm-api chat endpoint (Phase 4 wires the actual streaming pipeline).
- [ ] Run/Stop toggle works from PreviewPanel, Detail drawer, and context menu.
- [ ] All new tests pass: `pnpm test` runs ≥ existing count + the Phase 3 additions, no regressions.
- [ ] Storybook screenshots (if Storybook lands later) are pixel-clean against the existing PreviewPanel/Runtime designs.

What Phase 3 does NOT do (deferred):

- The `/api/spm/agents/{id}/chat` SSE endpoint streaming actual tokens — Phase 4 wires prompt-guard → Kafka → output-guard. Phase 3's chat panel works but the responses arrive as one block until then.
- Tool-call approval UI ("agent wants to run web_fetch — approve?") — V2.
- Sessions tab "fork from this turn" — V2 replay UI.
- Multi-tenant agent visibility — Phase 3 trusts the JWT's tenant claim and lists everything in scope.

---

## Out of scope (deferred to V1.5 / V2)

- Token-by-token streaming (`aispm.chat.stream()` SDK surface exists; backend wiring is V1.5).
- Custom MCP tool registration UI.
- Per-agent secret rotation flow (Phase 3 reads the secret list and lets the operator set values; UI for "rotate now" is V2).
- Replay UI (scrub / fork prior turns).
