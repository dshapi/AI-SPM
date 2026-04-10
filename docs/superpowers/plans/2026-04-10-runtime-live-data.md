# Runtime Live Data Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all mock data in `Runtime.jsx` with live backend sessions and WebSocket event streaming, keeping the UI structure pixel-identical.

**Architecture:** Fetch sessions by querying all known agent IDs in parallel (backend requires `agent_id` param — no global list endpoint exists). For the selected session: open a WebSocket if the session is active (`started`), fall back to REST event history for completed/blocked sessions. A `useSessionSocket` hook already exists in `hooks/useSessionSocket.js` — use it directly.

**Tech Stack:** React 18 (hooks), FastAPI WebSocket `/ws/sessions/{id}`, `GET /api/v1/sessions?agent_id=X`, `GET /api/v1/sessions/{id}/events`, existing `useSessionSocket` hook, existing `simulationApi.js` patterns.

---

## Codebase facts (read before coding)

| File | Role |
|---|---|
| `ui/src/admin/pages/Runtime.jsx` | Page being modified — 657 lines |
| `ui/src/api/simulationApi.js` | API helpers — add `fetchAllSessions` here |
| `ui/src/hooks/useSessionSocket.js` | WS hook — already complete, do not modify |
| `services/agent-orchestrator-service/routers/sessions.py:300-343` | `GET /api/v1/sessions?agent_id=X` — returns `{ agent_id, count, sessions: [{session_id, status, risk_score, risk_tier, policy_decision, created_at}] }` |
| `services/api/models/ws_event.py` | WsEvent shape: `{ session_id, correlation_id, event_type, source_service, timestamp, payload }` |

### Backend session status values → UI status tokens

| Backend `status` | UI `status` | UI dot color |
|---|---|---|
| `started` | `Active` | green pulse |
| `blocked` | `Blocked` | red |
| `completed` | `Completed` | gray |
| `failed` | `Completed` | gray |

### Backend `risk_tier` → UI `risk` token

| Backend `risk_tier` | UI `risk` |
|---|---|
| `minimal` | `Low` |
| `limited` | `Medium` |
| `high` | `High` |
| `unacceptable` | `Critical` |
| anything else | `Medium` |

### WsEvent `event_type` prefix → EventRow `type`

| Prefix / exact value | EventRow `type` |
|---|---|
| `prompt.*` | `prompt` |
| `risk.*` | `model` |
| `policy.*` (decision=block) | `blocked` |
| `policy.*` (other) | `policy` |
| `tool.*` | `tool` |
| `session.completed` | `success` |
| `session.blocked` | `blocked` |
| anything else | `prompt` |

### Known agent IDs (for parallel session fetch)
```js
const KNOWN_AGENTS = [
  'FinanceAssistant-v2', 'CustomerSupport-GPT', 'ThreatHunter-AI',
  'DataPipeline-Orchestrator', 'HR-Assistant-Pro',
]
```

---

## Task 1 — Add `fetchAllSessions` to simulationApi.js

**Files:**
- Modify: `ui/src/api/simulationApi.js` (append after `fetchSessionResults`)

- [ ] **Step 1: Add the function**

Append to the end of `simulationApi.js`:

```js
// ── fetchAllSessions ──────────────────────────────────────────────────────────

/**
 * Fetch recent sessions for all known agent IDs in parallel.
 * The backend requires agent_id — no global list endpoint exists.
 * Uses Promise.allSettled so a single agent failure doesn't block the rest.
 *
 * @param {string[]} agentIds   List of agent IDs to query
 * @param {number}   [limit=20] Max sessions per agent
 * @returns {Promise<Array<{
 *   session_id: string, agent_id: string, status: string,
 *   risk_score: number, risk_tier: string, policy_decision: string,
 *   created_at: string,
 * }>>} Flat list sorted by created_at desc
 */
export async function fetchAllSessions(agentIds, limit = 20) {
  const token   = await getToken()
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const results = await Promise.allSettled(
    agentIds.map(id =>
      fetch(`${ORCHESTRATOR_BASE}/sessions?agent_id=${encodeURIComponent(id)}&limit=${limit}`, { headers })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`${r.status}`)))
        .then(body => body.sessions ?? [])
    )
  )

  const all = results
    .filter(r => r.status === 'fulfilled')
    .flatMap(r => r.value)

  // Sort newest-first, deduplicate by session_id
  const seen = new Set()
  return all
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .filter(s => { if (seen.has(s.session_id)) return false; seen.add(s.session_id); return true })
}
```

- [ ] **Step 2: Smoke-test in browser console**

Open browser devtools on the Runtime page and run:
```js
import('/src/api/simulationApi.js').then(m => m.fetchAllSessions(['CustomerSupport-GPT']).then(console.log))
```
Expected: array (possibly empty) — no uncaught exception.

- [ ] **Step 3: Commit**
```bash
git add ui/src/api/simulationApi.js
git commit -m "feat(ui): add fetchAllSessions to simulationApi"
```

---

## Task 2 — Replace MOCK_SESSIONS with live data in Runtime.jsx

**Files:**
- Modify: `ui/src/admin/pages/Runtime.jsx`

### 2a — Add adapter functions and constants (before the `Runtime()` component)

> ⚠️ **Prerequisite:** Task 1 (`fetchAllSessions`) must be committed first — the import below fails at runtime otherwise.

- [ ] **Step 1: Add KNOWN_AGENTS constant and adapter helpers**

After the `DECISION_CFG` block (line ~51) and before `MOCK_SESSIONS`, add:

```js
import { fetchAllSessions, fetchSessionEvents } from '../../api/simulationApi.js'
import { useSessionSocket } from '../../hooks/useSessionSocket.js'
```

(Add these to the existing import block at the top.)

Then replace the `// ── Mock data ──` section (lines 53–164) with:

```js
// ── Agent IDs to poll ─────────────────────────────────────────────────────────

const KNOWN_AGENTS = [
  'FinanceAssistant-v2', 'CustomerSupport-GPT', 'ThreatHunter-AI',
  'DataPipeline-Orchestrator', 'HR-Assistant-Pro',
]

// ── Adapter: backend session → UI session shape ───────────────────────────────

const RISK_TIER_MAP = {
  minimal:      'Low',
  limited:      'Medium',
  high:         'High',
  unacceptable: 'Critical',
}

const STATUS_MAP = {
  started:   'Active',
  blocked:   'Blocked',
  completed: 'Completed',
  failed:    'Completed',
}

function _relativeTime(isoString) {
  if (!isoString) return '—'
  const diffMs = Date.now() - new Date(isoString).getTime()
  const s = Math.floor(diffMs / 1000)
  if (s < 60)  return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60)  return `${m}m ago`
  return `${Math.floor(m / 60)}h ago`
}

function _adaptSession(s) {
  const riskTier = RISK_TIER_MAP[s.risk_tier] ?? 'Medium'
  const riskScore = Math.round((s.risk_score ?? 0) * 100)
  return {
    id:           s.session_id,
    agent:        s.agent_id,
    agentType:    'Agent',
    risk:         riskTier,
    riskScore,
    status:       STATUS_MAP[s.status] ?? 'Active',
    lastActivity: _relativeTime(s.created_at),
    eventsCount:  0,      // enriched later from events
    environment:  'Production',
    duration:     '—',
    currentState: STATUS_MAP[s.status] ?? s.status,
    lastDecision: {
      action: s.policy_decision ?? 'allow',
      policy: '—',
      reason: '—',
    },
    lastPrompt:   null,
    lastToolCall: null,
  }
}

// ── Adapter: WsEvent / REST event → EventRow shape ───────────────────────────

function _eventType(eventType, payload) {
  if (!eventType) return 'prompt'
  if (eventType.startsWith('prompt.'))  return 'prompt'
  if (eventType.startsWith('risk.'))    return 'model'
  if (eventType.startsWith('tool.'))    return 'tool'
  if (eventType === 'session.completed') return 'success'
  if (eventType === 'session.blocked')   return 'blocked'
  if (eventType.startsWith('session.')) return 'success'
  if (eventType.startsWith('policy.')) {
    const dec = (payload?.decision ?? '').toLowerCase()
    return dec === 'block' ? 'blocked' : 'policy'
  }
  return 'prompt'
}

function _eventTitle(eventType) {
  const titles = {
    'prompt.received':    'Prompt received',
    'risk.calculated':    'Risk scored',
    'policy.decision':    'Policy evaluated',
    'policy.evaluated':   'Policy evaluated',
    'policy.enforced':    'Policy enforced',
    'tool.request':       'Tool call requested',
    'tool.observation':   'Tool call executed',
    'session.created':    'Session started',
    'session.completed':  'Session completed',
    'session.blocked':    'Session blocked',
    'final.response':     'Response generated',
    'memory.request':     'Memory read',
    'memory.result':      'Memory returned',
  }
  return titles[eventType] ?? eventType
}

function _eventDescription(event) {
  const p = event.payload ?? event  // REST events embed payload directly
  if (p.summary)       return p.summary
  if (p.reason)        return p.reason
  if (p.decision)      return `Decision: ${p.decision}`
  if (p.tool_name)     return `Tool: ${p.tool_name}`
  if (p.score != null) return `Risk score: ${Math.round(p.score * 100)}`
  return event.event_type ?? '—'
}

function _formatTs(isoOrTs) {
  if (!isoOrTs) return '—'
  // Already HH:MM:SS
  if (/^\d{2}:\d{2}:\d{2}$/.test(isoOrTs)) return isoOrTs
  const d = new Date(isoOrTs)
  if (isNaN(d)) return isoOrTs
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`
}

let _uid = 0
function _adaptEvent(raw, sessionId) {
  // Handles both WsEvent shape ({ event_type, source_service, timestamp, payload })
  // and REST events shape ({ event_type, summary, timestamp, payload }).
  // source_service is present in WsEvents; REST events may omit it → falls back to '—'.
  // Neither shape has agent_id — do not attempt raw.agent_id.
  const eventType = raw.event_type ?? raw.type
  const payload   = raw.payload ?? {}
  return {
    id:          ++_uid,
    type:        _eventType(eventType, payload),
    session:     raw.session_id ?? sessionId,
    agent:       raw.source_service ?? '—',
    title:       _eventTitle(eventType),
    description: _eventDescription(raw),
    tool:        payload.tool_name ?? null,
    ts:          _formatTs(raw.timestamp),
  }
}

// ── Enrich selected session with derived fields from events ───────────────────

function _enrichSession(session, events) {
  if (!session || events.length === 0) return session

  const lastPolicy = [...events].reverse().find(e =>
    (e.event_type ?? '').startsWith('policy.')
  )
  const lastPrompt  = [...events].reverse().find(e =>
    (e.event_type ?? '').startsWith('prompt.')
  )
  const lastTool    = [...events].reverse().find(e =>
    (e.event_type ?? '').startsWith('tool.')
  )
  const lastRisk    = [...events].reverse().find(e =>
    (e.event_type ?? '').startsWith('risk.')
  )

  const riskScore = lastRisk?.payload?.score != null
    ? Math.round(lastRisk.payload.score * 100)
    : session.riskScore

  const riskTier = lastRisk?.payload?.tier
    ? (RISK_TIER_MAP[lastRisk.payload.tier] ?? session.risk)
    : session.risk

  const policyPayload = lastPolicy?.payload ?? {}
  const policyDec     = (policyPayload.decision ?? session.lastDecision.action).toLowerCase()

  return {
    ...session,
    eventsCount:  events.length,
    riskScore,
    risk:         riskTier,
    lastDecision: {
      action: policyDec,
      policy: policyPayload.policy_version ?? policyPayload.policy ?? session.lastDecision.policy,
      reason: policyPayload.reason ?? session.lastDecision.reason,
    },
    lastPrompt:  lastPrompt?.payload?.text ?? lastPrompt?.payload?.prompt ?? null,
    lastToolCall: lastTool
      ? `${lastTool.payload?.tool_name ?? ''}${lastTool.payload?.tool_args ? ': ' + JSON.stringify(lastTool.payload.tool_args) : ''}`
      : null,
  }
}
```

- [ ] **Step 2: Verify the file still parses (no syntax errors)**
```bash
cd ui && node --input-type=module < /dev/null 2>&1 || npx eslint src/admin/pages/Runtime.jsx --max-warnings=99
```

- [ ] **Step 3: Commit**
```bash
git add ui/src/admin/pages/Runtime.jsx
git commit -m "feat(runtime): add session/event adapter helpers"
```

---

## Task 3 — Replace Runtime() state and effects

**Files:**
- Modify: `ui/src/admin/pages/Runtime.jsx` — `Runtime()` function only

- [ ] **Step 1: Replace the state and effects block**

Replace the `export default function Runtime()` body from line 459 through the end of the effects (up to line 503) with:

```js
export default function Runtime() {
  // ── UI state ───────────────────────────────────────────────────────────────
  const [paused,         setPaused]         = useState(false)
  const [newIds,         setNewIds]         = useState(new Set())
  const [suspiciousOnly, setSuspiciousOnly] = useState(false)
  const [sessionFilter,  setSessionFilter]  = useState({ search: '', risk: 'All', status: 'All' })
  const [streamType,     setStreamType]     = useState('All')

  // ── Sessions list state ────────────────────────────────────────────────────
  const [sessions,     setSessions]     = useState([])
  const [selectedId,   setSelectedId]   = useState(null)
  const [sessionsLoading, setSessionsLoading] = useState(true)

  // ── Per-session event state ────────────────────────────────────────────────
  const [events,       setEvents]       = useState([])
  const [wsStatus,     setWsStatus]     = useState('idle')  // idle|connecting|connected|closed|error

  // ── WebSocket hook ─────────────────────────────────────────────────────────
  const { connectionStatus, liveEvents, connectWs, disconnectWs } = useSessionSocket()

  const pausedRef = useRef(paused)
  pausedRef.current = paused

  // ── Load sessions list (poll every 10s) ────────────────────────────────────
  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const data = await fetchAllSessions(KNOWN_AGENTS)
        if (!cancelled) {
          setSessions(data.map(_adaptSession))
          setSessionsLoading(false)
        }
      } catch (err) {
        console.error('[Runtime] fetchAllSessions error:', err)
        if (!cancelled) setSessionsLoading(false)
      }
    }

    load()
    const iv = setInterval(load, 10_000)
    return () => { cancelled = true; clearInterval(iv) }
  }, [])

  // ── On session select: load history then open WS if active ────────────────
  useEffect(() => {
    if (!selectedId) return

    disconnectWs()
    setEvents([])
    setWsStatus('idle')

    const session = sessions.find(s => s.id === selectedId)

    async function hydrate() {
      // Always load REST history first so we have context immediately
      try {
        const data = await fetchSessionEvents(selectedId)
        if (!data?.events) return
        const adapted = data.events.map(e => _adaptEvent(e, selectedId))
        setEvents(adapted)
      } catch (err) {
        console.error('[Runtime] fetchSessionEvents error:', err)
      }

      // Open WS only for active sessions — completed ones won't emit new events
      if (!session || session.status === 'Active') {
        connectWs(selectedId)
      }
    }

    hydrate()

    return () => disconnectWs()
  }, [selectedId])   // intentionally exclude sessions/connectWs/disconnectWs from deps

  // ── Merge live WS events into events[] ────────────────────────────────────
  // useSessionSocket already deduplicates WS events by event_type.
  // We deduplicate against REST history using adapted-event fields (type+ts)
  // to avoid showing the same pipeline step twice when REST and WS overlap.
  useEffect(() => {
    if (paused || liveEvents.length === 0) return
    const adapted = liveEvents.map(e => _adaptEvent(e, selectedId))
    setEvents(prev => {
      // Build dedup set from existing REST-loaded events
      const seen = new Set(prev.map(e => `${e.type}:${e.ts}`))
      const fresh = adapted.filter(e => {
        const key = `${e.type}:${e.ts}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      if (fresh.length === 0) return prev
      const merged = [...prev, ...fresh].sort((a, b) => a.ts.localeCompare(b.ts))
      // Flash new IDs
      setNewIds(new Set(fresh.map(e => e.id)))
      setTimeout(() => setNewIds(new Set()), 1200)
      return merged.slice(-200)  // cap at 200 events
    })
  }, [liveEvents, paused, selectedId])

  // ── Sync WS connection status ──────────────────────────────────────────────
  useEffect(() => {
    setWsStatus(connectionStatus)
  }, [connectionStatus])
```

- [ ] **Step 2: Update derived values (replace lines 486–503)**

Replace the old derived-value block with:

```js
  // ── Derived values ─────────────────────────────────────────────────────────
  // NOTE: selectedSession enrichment is deliberately NOT done here.
  // It is wired in Task 4 once rawEventsRef is in place.
  // Until Task 4 is complete, selectedSession falls back to unenriched data.
  const selectedRaw     = sessions.find(s => s.id === selectedId) ?? null
  const selectedSession = selectedRaw ?? null  // enriched in Task 4

  const activeSessions   = sessions.filter(s => s.status === 'Active').length
  const highRiskSessions = sessions.filter(s => s.risk === 'Critical' || s.risk === 'High').length
  const blockedCount     = events.filter(e => e.type === 'blocked').length
  const eventsPerSec     = wsStatus === 'connected' ? '~live' : '—'

  const filteredEvents = events.filter(e => {
    if (suspiciousOnly && e.type !== 'blocked' && e.type !== 'policy') return false
    if (streamType !== 'All' && e.type !== streamType) return false
    return true
  })

  const sessionCount = sessions.filter(s => {
    const q = sessionFilter.search.toLowerCase()
    if (q && !s.agent.toLowerCase().includes(q) && !s.id.toLowerCase().includes(q)) return false
    if (sessionFilter.risk   !== 'All' && s.risk   !== sessionFilter.risk)   return false
    if (sessionFilter.status !== 'All' && s.status !== sessionFilter.status) return false
    return true
  }).length
```

- [ ] **Step 3: Update the JSX — KPI strip and session list**

In the JSX (line ~532), replace the KPI strip render:
```jsx
<KpiCard label="Active Sessions"    value={sessionsLoading ? '…' : activeSessions}   sub={`${sessions.length} total`}     accentClass="border-l-blue-500"    />
<KpiCard label="Events / sec"       value={eventsPerSec}                              sub={paused ? 'Paused' : wsStatus === 'connected' ? 'Live' : 'No session'} accentClass={wsStatus === 'connected' && !paused ? 'border-l-emerald-500' : 'border-l-amber-400'} dim={wsStatus !== 'connected'} />
<KpiCard label="Blocked Actions"    value={blockedCount}                              sub="In current view"                 accentClass="border-l-red-500"     />
<KpiCard label="High Risk Sessions" value={highRiskSessions}                          sub="Critical + High"                 accentClass="border-l-orange-500"  />
```

In the session list panel (line ~605), replace `sessions={MOCK_SESSIONS}` with `sessions={sessions}`:
```jsx
<SessionList
  sessions={sessions}
  selectedId={selectedId}
  onSelect={setSelectedId}
  filter={sessionFilter}
/>
```

Add empty state below the SessionList when sessions are loading:
```jsx
{sessionsLoading && sessions.length === 0 && (
  <p className="text-xs text-gray-400 text-center py-8">Loading sessions…</p>
)}
```

Also update the live indicator in the filter bar to reflect WS status:
```jsx
{wsStatus === 'connected' && !paused ? (
  <span className="flex items-center gap-1.5 text-[11px] text-emerald-600 font-medium">
    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live
  </span>
) : paused ? (
  <span className="flex items-center gap-1.5 text-[11px] text-amber-600 font-medium">
    <Pause size={11} strokeWidth={2} /> Stream paused
  </span>
) : (
  <span className="flex items-center gap-1.5 text-[11px] text-gray-400 font-medium">
    <span className="w-1.5 h-1.5 rounded-full bg-gray-300" /> {wsStatus === 'error' ? 'Disconnected' : 'Select session'}
  </span>
)}
```

- [ ] **Step 4: Delete dead code**

Remove these identifiers that are now unreferenced:
- `MOCK_SESSIONS` block (lines 55–128)
- `let _uid = 100` (the old one — _uid is re-declared in adapters)
- `INITIAL_EVENTS` block (lines 132–148)
- `LIVE_POOL` block (lines 150–159)
- `nowTs()` function (lines 161–164)
- The `setInterval` live-event simulation `useEffect` (lines 473–484)

- [ ] **Step 5: Verify no references to removed names remain**
```bash
grep -n "MOCK_SESSIONS\|INITIAL_EVENTS\|LIVE_POOL\|nowTs\|LIVE_POOL" ui/src/admin/pages/Runtime.jsx
```
Expected: no output.

- [ ] **Step 6: Commit**
```bash
git add ui/src/admin/pages/Runtime.jsx
git commit -m "feat(runtime): replace mock data with live sessions and WebSocket events"
```

---

## Task 4 — Fix `_enrichSession` event mapping (simplify)

The inline re-mapping in Task 3 Step 2 is convoluted. Replace `selectedSession` derivation with a cleaner approach that stores raw backend events alongside adapted display events.

**Files:**
- Modify: `ui/src/admin/pages/Runtime.jsx`

- [ ] **Step 1: Add a `rawEvents` ref to store original WsEvent/REST shapes**

In the `Runtime()` state block, add:
```js
const rawEventsRef = useRef([])
```

- [ ] **Step 2: Store raw events alongside adapted events**

In the `hydrate()` function (Task 3 effect), after setting events:
```js
rawEventsRef.current = data.events   // store raw for enrichment
```

In the liveEvents merge effect, also append to rawEventsRef:
```js
rawEventsRef.current = [...rawEventsRef.current, ...liveEvents]
```

- [ ] **Step 3: Replace the convoluted selectedSession derivation**

Replace:
```js
const selectedSession = selectedRaw ? _enrichSession(selectedRaw, events.map(e => ({...}))) : null
```

With:
```js
const selectedSession = selectedRaw
  ? _enrichSession(selectedRaw, rawEventsRef.current)
  : null
```

And update `_enrichSession` to read `raw.event_type` directly (it already does — this just passes the right shape).

- [ ] **Step 4: Verify the Control Panel renders correctly**

Select a completed session with events — confirm:
- Last Decision section shows actual policy name
- Last Prompt shows prompt text
- Event count > 0

- [ ] **Step 5: Commit**
```bash
git add ui/src/admin/pages/Runtime.jsx
git commit -m "fix(runtime): use raw events for session enrichment"
```

---

## Task 5 — Verification

- [ ] **Step 1: Start the full stack**
```bash
docker compose up -d
```

- [ ] **Step 2: Run a simulation to generate a real session**

Go to the Simulation page, run any scenario. Note the session ID from the response.

- [ ] **Step 3: Navigate to Runtime page**

Confirm:
- Sessions list shows real sessions (not placeholder names like `sess_01HZ9QR2XK`)
- KPI strip shows real counts
- Selecting a session loads its event history in the event stream panel
- Control panel shows real decision data

- [ ] **Step 4: Verify live events work**

While watching the Runtime page, trigger a new simulation. Confirm:
- The new session appears in the sessions list within ~10s (polling interval)
- Selecting the active session opens the WS and events stream in live

- [ ] **Step 5: Verify WS status indicator**

- Select an active session → live indicator should show green "Live"
- Select a completed session → indicator should show grey "Select session" or similar
- Pause button should suppress new event rendering

- [ ] **Step 6: Final commit**
```bash
git add ui/src/admin/pages/Runtime.jsx ui/src/api/simulationApi.js
git commit -m "feat(runtime): live operational dashboard complete"
```

---

## Key constraints recap

- **DO NOT** add new backend endpoints (`GET /api/v1/sessions` requires `agent_id` param — work around with parallel fetches)
- **DO NOT** modify `useSessionSocket.js` — it is already correct
- **DO NOT** modify `Simulation.jsx`
- **DO NOT** change UI structure, layout, component hierarchy, or styling
- **DO NOT** introduce Redux or new components
- `_uid` counter: remove the old `let _uid = 100` line; the new one in the adapters section starts at 0 — ensure only one declaration exists
