# Simulation State Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate scattered simulation lifecycle state into a single `useSimulationState` hook that provides progressive rendering, a 30-second fail-safe timeout, and clean state transitions — without rewriting the existing WS infrastructure.

**Architecture:** A new `useSimulationState` hook wraps the existing `useSimulationStream` (which wraps `useSessionSocket`) and exposes a single `SimulationState` object with `status`, `steps`, `partialResults`, `finalResults`, `error`, and timing fields. `Simulation.jsx` delegates all lifecycle management to this hook. `ResultsPanel.jsx` consumes the unified state via props.

**Tech Stack:** React 18, custom hooks, existing WebSocket layer (`useSessionSocket` / `useSimulationStream`), Tailwind CSS, existing `_buildResultFromSimEvents` / `simulationApi.js` utilities.

---

## Why the previous version had problems

The previous architecture spread state across three locations:
- `Simulation.jsx`: `running` (bool), `result` (object|null), `apiError`, `sessionId`
- `useSimulationStream`: raw `simEvents[]`, `connectionStatus`
- `deriveSimState(connectionStatus, running)`: ad-hoc mapper with known edge cases

This caused:
1. **Stuck "running" forever** — no timeout; if the WS raced ahead of the backend, no terminal event arrived and `running` stayed `true`.
2. **Wrong ALLOWED verdict** — when `simulation.blocked` was dropped by the race condition, `_buildResultFromSimEvents` defaulted to `allowed` because it saw no blocked event.
3. **0ms exec time** — hardcoded fallback, backend never emitted timing.
4. **Tabs hidden during Garak** — an early-return render path removed the tab bar entirely.
5. **No progressive partial results** — nothing accumulated partials as probes ran.

Commits 32f066b, cfbe3bc, 841d330, f62c3e5 fixed bugs 2–4. This plan adds the missing state consolidation (1, 5) and the fail-safe timeout.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **CREATE** | `ui/src/hooks/useSimulationState.js` | Single source of truth for all simulation lifecycle state; exposes `SimulationState`, `startSimulation()`, `resetSimulation()`, timeout watchdog |
| **MODIFY** | `ui/src/admin/pages/Simulation.jsx` | Replace manual `running`/`result`/`sessionId` state with `useSimulationState`; pass unified `simState` to `ResultsPanel` |
| **MODIFY** | `ui/src/components/simulation/ResultsPanel.jsx` | Accept `simState` prop (in addition to existing `result` prop for backwards compat); display `steps` / `partialResults` in Timeline and Summary; show error state on `status === 'failed'` |
| **MODIFY** | `ui/src/hooks/useSimulationStream.js` | Export `toSimulationEvent` so `useSimulationState` can use it (already defined, just not exported) |

---

## Task 1 — Export `toSimulationEvent` from `useSimulationStream`

**Files:**
- Modify: `ui/src/hooks/useSimulationStream.js`

`useSimulationState` needs to call `toSimulationEvent` directly. It is currently a module-private function.

- [ ] **Step 1.1: Add `export` to `toSimulationEvent`**

In `ui/src/hooks/useSimulationStream.js`, change line 47:
```js
// BEFORE
function toSimulationEvent(wsEvent) {

// AFTER
export function toSimulationEvent(wsEvent) {
```

- [ ] **Step 1.2: Verify no import errors**
```bash
cd ui && npx vite build --mode development 2>&1 | grep -i error | head -20
```
Expected: no new errors.

- [ ] **Step 1.3: Commit**
```bash
git add ui/src/hooks/useSimulationStream.js
git commit -m "refactor(simulation): export toSimulationEvent for reuse"
```

---

## Task 2 — Create `useSimulationState` hook

**Files:**
- Create: `ui/src/hooks/useSimulationState.js`

This is the central piece. It:
- Wraps `useSimulationStream` internally
- Maintains `SimulationState` (status, steps, partialResults, finalResults, error, timing)
- Fires `startSimulation(config)` which calls the existing API helpers
- Runs a 30-second watchdog `setTimeout` that transitions `status → 'failed'` if no terminal event arrives
- Exposes `resetSimulation()` for the Reset button

- [ ] **Step 2.1: Create the file**

Create `ui/src/hooks/useSimulationState.js` with the full implementation:

```js
/**
 * hooks/useSimulationState.js
 * ────────────────────────────
 * Unified simulation lifecycle state.
 *
 * Wraps useSimulationStream and exposes a single SimulationState object
 * plus start/reset helpers.  Replaces the scattered running/result/sessionId
 * state that previously lived in Simulation.jsx.
 *
 * SimulationState shape
 * ─────────────────────
 * {
 *   status:         'idle' | 'running' | 'completed' | 'failed'
 *   steps:          SimulationStep[]     — ordered WS events as step objects
 *   partialResults: any[]                — intermediate probe results (Garak)
 *   finalResults:   object | null        — built from _buildResultFromSimEvents
 *   error:          string | undefined
 *   startedAt:      number | undefined   — Date.now() when started
 *   completedAt:    number | undefined   — Date.now() when terminal event arrived
 *   sessionId:      string | null
 *   // pass-throughs from useSimulationStream
 *   simEvents:      SimulationEvent[]
 *   connectionStatus: string
 * }
 *
 * SimulationStep shape
 * ────────────────────
 * {
 *   id:        string   — same dedup key as SimulationEvent.id
 *   label:     string   — human-readable event label
 *   status:    'pending' | 'running' | 'done' | 'failed'
 *   timestamp: number   — ms epoch
 * }
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useSimulationStream } from './useSimulationStream'
import { _buildResultFromSimEvents } from '../admin/pages/Simulation'
import { runSinglePromptSimulation, runGarakSimulation } from '../api/simulationApi'

// ── Constants ─────────────────────────────────────────────────────────────────
const TIMEOUT_MS   = 30_000   // 30 s watchdog
const TERMINAL_STAGES = new Set(['completed', 'error', 'blocked', 'allowed'])

// ── Label helper ──────────────────────────────────────────────────────────────
function stepLabel(event) {
  if (!event) return 'Event'
  const et = event.event_type || ''
  if (et === 'simulation.started')   return 'Simulation started'
  if (et === 'simulation.blocked')   return 'Request blocked'
  if (et === 'simulation.allowed')   return 'Request allowed'
  if (et === 'simulation.completed') return 'Simulation complete'
  if (et === 'simulation.error')     return 'Simulation error'
  if (et === 'simulation.progress') {
    const msg = event.details?.message
    return msg ? `Probe: ${msg}` : 'Probe running'
  }
  // Generic: capitalise dot-namespaced type
  return et.split('.').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

// ── Initial state factory ─────────────────────────────────────────────────────
function makeIdle() {
  return {
    status:         'idle',
    steps:          [],
    partialResults: [],
    finalResults:   null,
    error:          undefined,
    startedAt:      undefined,
    completedAt:    undefined,
    sessionId:      null,
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export function useSimulationState() {
  const { connectionStatus, simEvents, startStream, stopStream } =
    useSimulationStream()

  const [simState, setSimState] = useState(makeIdle)

  // Watchdog timer ref — cleared on terminal event or reset
  const watchdogRef   = useRef(null)
  // Prevent double-processing the same terminal event
  const terminatedRef = useRef(false)

  // ── Clear watchdog helper ────────────────────────────────────────────────
  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current)
      watchdogRef.current = null
    }
  }, [])

  // ── React to incoming simEvents ──────────────────────────────────────────
  useEffect(() => {
    if (simEvents.length === 0) return
    const latest = simEvents[simEvents.length - 1]

    // ── Build / update steps array ──────────────────────────────────────
    const newStep = {
      id:        latest.id,
      label:     stepLabel(latest),
      status:    TERMINAL_STAGES.has(latest.stage) ? 'done' : 'running',
      timestamp: latest.timestamp ? new Date(latest.timestamp).getTime() : Date.now(),
    }

    // ── Detect terminal event ────────────────────────────────────────────
    const isTerminal = TERMINAL_STAGES.has(latest.stage)

    if (isTerminal && !terminatedRef.current) {
      terminatedRef.current = true
      clearWatchdog()

      const built = _buildResultFromSimEvents(simEvents)
      const isFailed = latest.stage === 'error'
      const errMsg   = latest.details?.error_message || (isFailed ? 'Simulation failed' : undefined)

      console.log('[SimState] terminal event', latest.stage, '— building result', built)

      setSimState(prev => ({
        ...prev,
        status:       isFailed ? 'failed' : 'completed',
        steps:        [...prev.steps.filter(s => s.id !== newStep.id), { ...newStep, status: isFailed ? 'failed' : 'done' }],
        finalResults: built,
        error:        errMsg,
        completedAt:  Date.now(),
      }))
      return
    }

    // ── Accumulate partial results for Garak probes ──────────────────────
    // simulation.allowed events during a Garak run are per-probe results
    const isProbeResult = latest.stage === 'allowed' || latest.stage === 'blocked'

    setSimState(prev => {
      if (prev.status !== 'running') return prev   // stale event after completion
      return {
        ...prev,
        steps: (() => {
          const existing = prev.steps.find(s => s.id === newStep.id)
          if (existing) return prev.steps
          return [...prev.steps, newStep]
        })(),
        partialResults: isProbeResult
          ? [...prev.partialResults, latest]
          : prev.partialResults,
      }
    })

    console.log('[SimState] step added', newStep.label)
  }, [simEvents, clearWatchdog])

  // ── Start simulation ─────────────────────────────────────────────────────
  const startSimulation = useCallback(async (config) => {
    console.log('[SimState] simulation started', config.attackType)

    const sid = crypto.randomUUID()
    terminatedRef.current = false

    // Reset to running state
    setSimState({
      ...makeIdle(),
      status:    'running',
      sessionId: sid,
      startedAt: Date.now(),
    })

    // Connect WS before POST so no events are missed
    startStream(sid)

    // Watchdog: fail after TIMEOUT_MS if no terminal event
    clearWatchdog()
    watchdogRef.current = setTimeout(() => {
      if (terminatedRef.current) return
      terminatedRef.current = true
      console.warn('[SimState] watchdog fired — simulation timed out after', TIMEOUT_MS, 'ms')
      setSimState(prev => ({
        ...prev,
        status: 'failed',
        error:  'Simulation timeout — no response received within 30 seconds.',
        completedAt: Date.now(),
      }))
    }, TIMEOUT_MS)

    try {
      if (config.attackType === 'custom' && config.customMode === 'garak') {
        await runGarakSimulation({
          garakConfig:   config.garakConfig,
          sessionId:     sid,
          executionMode: config.execMode,
        })
      } else {
        await runSinglePromptSimulation({
          prompt:        config.prompt,
          sessionId:     sid,
          executionMode: config.execMode,
          attackType:    config.attackType,
        })
      }
      console.log('[SimState] API call returned (background task started)')
    } catch (err) {
      console.error('[SimState] API call failed', err.message)
      clearWatchdog()
      terminatedRef.current = true
      setSimState(prev => ({
        ...prev,
        status: 'failed',
        error:  err.message || 'Failed to start simulation',
        completedAt: Date.now(),
      }))
    }

    return sid
  }, [startStream, clearWatchdog])

  // ── Reset simulation ─────────────────────────────────────────────────────
  const resetSimulation = useCallback(() => {
    console.log('[SimState] reset')
    clearWatchdog()
    terminatedRef.current = false
    stopStream()
    setSimState(makeIdle())
  }, [clearWatchdog, stopStream])

  // ── Cleanup on unmount ────────────────────────────────────────────────────
  useEffect(() => () => clearWatchdog(), [clearWatchdog])

  return {
    simState: {
      ...simState,
      simEvents,
      connectionStatus,
    },
    startSimulation,
    resetSimulation,
  }
}
```

> **Note on `_buildResultFromSimEvents` import:** This function currently lives inside `Simulation.jsx` (unexported). Task 3 extracts it.

- [ ] **Step 2.2: Verify the file was created**
```bash
ls -la ui/src/hooks/useSimulationState.js
```

- [ ] **Step 2.3: Commit (file only — wiring comes in Task 3–4)**
```bash
git add ui/src/hooks/useSimulationState.js
git commit -m "feat(simulation): add useSimulationState hook with 30s watchdog"
```

---

## Task 3 — Extract `_buildResultFromSimEvents` from `Simulation.jsx`

**Files:**
- Create: `ui/src/lib/buildResultFromSimEvents.js`
- Modify: `ui/src/admin/pages/Simulation.jsx` (change import)
- Modify: `ui/src/hooks/useSimulationState.js` (update import)

`_buildResultFromSimEvents` is a pure function that shouldn't live inside a component file. Extracting it makes it importable by both `Simulation.jsx` and `useSimulationState.js`.

- [ ] **Step 3.1: Create `ui/src/lib/buildResultFromSimEvents.js`**

Copy the function body from `Simulation.jsx` (lines ~509–598) into the new file, adding a named export:

```js
/**
 * lib/buildResultFromSimEvents.js
 * ─────────────────────────────────
 * Pure function — builds the MOCK_RESULTS-compatible result object
 * from an array of SimulationEvents received over the WS stream.
 *
 * Exported so both Simulation.jsx and useSimulationState can use it.
 */

export function buildResultFromSimEvents(simEvents) {
  // ... (copy exact body of _buildResultFromSimEvents from Simulation.jsx)
}
```

- [ ] **Step 3.2: Update `Simulation.jsx` to import from the new location**

Near the top of `Simulation.jsx`, add:
```js
import { buildResultFromSimEvents } from '../lib/buildResultFromSimEvents'
```

And change all internal uses of `_buildResultFromSimEvents(...)` to `buildResultFromSimEvents(...)`.

- [ ] **Step 3.3: Update `useSimulationState.js` import**

Change:
```js
import { _buildResultFromSimEvents } from '../admin/pages/Simulation'
```
To:
```js
import { buildResultFromSimEvents } from '../lib/buildResultFromSimEvents'
```

And update the call inside the hook accordingly.

- [ ] **Step 3.4: Verify build**
```bash
cd ui && npx vite build --mode development 2>&1 | grep -i error | head -20
```

- [ ] **Step 3.5: Commit**
```bash
git add ui/src/lib/buildResultFromSimEvents.js ui/src/admin/pages/Simulation.jsx ui/src/hooks/useSimulationState.js
git commit -m "refactor(simulation): extract buildResultFromSimEvents to lib/"
```

---

## Task 4 — Wire `useSimulationState` into `Simulation.jsx`

**Files:**
- Modify: `ui/src/admin/pages/Simulation.jsx`

Replace the manual `running`, `result`, `sessionId` state + `useSimulationStream` call + result-building effects with `useSimulationState`.

- [ ] **Step 4.1: Replace hook usage**

At the top of the `Simulation` component, replace:
```js
// BEFORE
const [running,     setRunning]    = useState(false)
const [result,      setResult]     = useState(null)
const [sessionId,   setSessionId]  = useState(null)
const { connectionStatus, simEvents, startStream, stopStream } = useSimulationStream()
```

With:
```js
// AFTER
const { simState, startSimulation, resetSimulation } = useSimulationState()
const {
  status:          simStatus,
  steps:           simSteps,
  partialResults,
  finalResults:    result,
  error:           simError,
  startedAt,
  completedAt,
  sessionId,
  simEvents,
  connectionStatus,
} = simState
const running = simStatus === 'running'
```

- [ ] **Step 4.2: Remove the two result-building `useEffect` blocks**

Delete (they are now inside `useSimulationState`):
```js
// DELETE THIS:
useEffect(() => {
  if (simEvents.length === 0) return
  const last = simEvents[simEvents.length - 1]
  if (!['completed', 'error', 'blocked', 'allowed'].includes(last.stage)) return
  const built = _buildResultFromSimEvents(simEvents)
  if (built) setResult(built)
}, [simEvents])

// DELETE THIS:
useEffect(() => {
  const last = simEvents[simEvents.length - 1]
  if (!last) return
  if (['completed', 'error', 'blocked', 'allowed'].includes(last.stage)) {
    setRunning(false)
  }
}, [simEvents])
```

- [ ] **Step 4.3: Update `handleRun`**

Replace:
```js
// BEFORE
const handleRun = useCallback(async () => {
  ...
  const sid = crypto.randomUUID()
  setSessionId(sid)
  setRunning(true)
  setResult(null)
  setApiError(null)
  startStream(sid)
  try {
    if (config.attackType === 'custom' && config.customMode === 'garak') {
      await runGarakSimulation({...})
    } else {
      await runSinglePromptSimulation({...})
    }
  } catch (err) {
    ...
    setRunning(false)
  }
}, [config, startStream, compareMode, result, resultA, resultB])
```

With:
```js
// AFTER
const handleRun = useCallback(async () => {
  // Compare mode: save outgoing result before clearing
  if (compareMode && result) {
    if (!resultA) setResultA(result)
    else if (!resultB) setResultB(result)
  }
  setApiError(null)
  await startSimulation(config)
}, [config, startSimulation, compareMode, result, resultA, resultB])
```

- [ ] **Step 4.4: Update `handleReset`**

Replace:
```js
// BEFORE
const handleReset = () => {
  stopStream()
  setRunning(false)
  setResult(null)
  ...
}
```

With:
```js
// AFTER
const handleReset = () => {
  resetSimulation()
  setResultA(null)
  setResultB(null)
  setApiError(null)
}
```

- [ ] **Step 4.5: Update the `simulation` prop passed to `ResultsPanel`**

Extend the existing `simulation` prop to carry `steps` and `partialResults`:
```js
const simulation = {
  state:          deriveSimState(connectionStatus, running),
  events:         simEvents,
  mode:           config.attackType === 'custom' && config.customMode === 'garak' ? 'garak' : 'single',
  steps:          simSteps,          // NEW
  partialResults, // NEW
  startedAt,      // NEW
  completedAt,    // NEW
  simError,       // NEW — for 'failed' status display
}
```

- [ ] **Step 4.6: Verify the page renders and a simulation can run end-to-end**

Open `localhost:3001/admin/simulation`, run a prompt injection simulation, confirm:
- Tabs appear immediately
- Summary shows after completion
- No console errors

- [ ] **Step 4.7: Commit**
```bash
git add ui/src/admin/pages/Simulation.jsx
git commit -m "refactor(simulation): wire useSimulationState into Simulation.jsx"
```

---

## Task 5 — Update `ResultsPanel` to consume new state fields

**Files:**
- Modify: `ui/src/components/simulation/ResultsPanel.jsx`

Three changes:
1. Accept and use `steps` for a richer Timeline
2. Accept and display `simError` for the `status === 'failed'` path
3. Show step count badge on Timeline tab

- [ ] **Step 5.1: Add `steps` and `simError` to destructured props**

In `ResultsPanel`, destructure `steps` and `simError` from the `simulation` prop:
```js
const { state, events: simEvents = [], mode, steps = [], simError } = simulation
```

- [ ] **Step 5.2: Add failed/error state display**

After the `isIdle` early-return, add an error panel for the `'error'` / `'failed'` state. Directly below the `isIdle` guard:
```jsx
const isFailed = state === 'error' || (simError && !result)
if (isFailed) {
  return (
    <div className="flex flex-col h-full">
      <div className="h-10 px-4 flex items-center gap-2 border-b border-gray-100 shrink-0">
        <Target size={13} className="text-gray-400" strokeWidth={1.75} />
        <span className="text-[12px] font-semibold text-gray-700">Results</span>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 border border-red-200 text-[10px] font-bold text-red-700">
          Failed
        </span>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-8">
        <div className="w-10 h-10 rounded-xl bg-red-50 flex items-center justify-center">
          <AlertCircle size={18} className="text-red-400" />
        </div>
        <div>
          <p className="text-[13px] font-medium text-gray-700">Simulation failed</p>
          <p className="text-[11px] text-gray-400 mt-1">{simError || 'An unexpected error occurred.'}</p>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 5.3: Pass `steps` into `TimelineTab`**

Find the `<TimelineTab>` render (around line 607) and add the `steps` prop:
```jsx
{activeTab === 'Timeline' && (
  <TimelineTab
    simulation={simulation}
    selectedId={selectedEvent?.id}
    onSelect={handleSelectEvent}
    steps={steps}   // NEW
  />
)}
```

- [ ] **Step 5.4: Show live step count on the Timeline tab button**

In the tab-bar render loop, add a badge for the Timeline tab when `steps.length > 0`:
```jsx
{RESULT_TABS.map(tab => (
  <button key={tab} ...>
    {tab}
    {tab === 'Timeline' && steps.length > 0 && (
      <span className="ml-1 px-1 py-0.5 rounded text-[9px] bg-blue-100 text-blue-600 font-bold tabular-nums">
        {steps.length}
      </span>
    )}
  </button>
))}
```

- [ ] **Step 5.5: Verify no regressions**

Confirm:
- Idle state still shows empty panel
- Running state shows spinner on Summary (no result yet)
- Timeline shows events live
- Failed state shows error panel with message
- Completed state shows Summary results

- [ ] **Step 5.6: Commit**
```bash
git add ui/src/components/simulation/ResultsPanel.jsx
git commit -m "feat(simulation): ResultsPanel shows step count, failed state, uses steps prop"
```

---

## Task 6 — Add logging (temporary, per spec)

**Files:**
- Modify: `ui/src/hooks/useSimulationState.js` (already has `console.log` calls)
- Modify: `ui/src/hooks/useSimulationStream.js` (add event logs)

The `useSimulationState` implementation already logs:
```
[SimState] simulation started {attackType}
[SimState] step added {label}
[SimState] terminal event {stage} — building result ...
[SimState] watchdog fired — simulation timed out after 30000 ms
[SimState] API call failed {message}
[SimState] reset
```

Add one more log line to `useSimulationStream.js` when a WS event is processed:
```js
// After the simEvent is built and before setSimEvents:
console.log('[SimStream] event', simEvent.event_type, 'stage:', simEvent.stage)
```

- [ ] **Step 6.1: Add the stream log**
- [ ] **Step 6.2: Commit**
```bash
git add ui/src/hooks/useSimulationStream.js
git commit -m "feat(simulation): add temporary event logging"
```

---

## Task 7 — Rebuild and validate

- [ ] **Step 7.1: Rebuild containers**
```bash
docker compose up -d --build api ui
```

- [ ] **Step 7.2: Validation checklist**

Open `localhost:3001/admin/simulation` and verify:

| Scenario | Expected |
|---|---|
| Page load, no run yet | Empty panel, no tabs |
| Click "Run Simulation" (single prompt) | Tabs appear immediately, Summary selected |
| During run | Spinner on Summary, Timeline tab gets live step count badge |
| After completion (BLOCKED) | Summary shows "BLOCKED", correct risk score, real exec time |
| After completion (ALLOWED) | Summary shows "ALLOWED" |
| Garak run during probes | Timeline tab selected, steps accumulate |
| Garak run complete | Decision Trace selected, final results shown |
| Network error / API down | Failed panel with error message (not stuck spinner) |
| 30s timeout (kill API mid-run) | "Simulation timeout" error message appears |
| Reset button | Panel returns to empty idle state |
| Two back-to-back runs | Second run clears first result, new tabs appear |

- [ ] **Step 7.3: Final commit if any hot-fixes needed**
```bash
git add -p
git commit -m "fix(simulation): post-validation fixes"
```

---

## State Transition Diagram

```
        handleRun()
            │
            ▼
         [idle]
            │  startSimulation()
            │  sessionId = new UUID
            │  WS connects
            ▼
        [running] ◄──── WS events accumulate in steps[]
            │
            ├── terminal WS event (blocked/allowed/completed)
            │        │
            │        ▼
            │   [completed]  finalResults built, completedAt set
            │
            ├── error WS event
            │        │
            │        ▼
            │    [failed]  error message set
            │
            └── 30s watchdog fires (no terminal event)
                     │
                     ▼
                 [failed]  "Simulation timeout"

    resetSimulation() from any state → [idle]
```

---

## Scope Boundaries (what this plan does NOT touch)

- `useSessionSocket.js` — WS transport layer unchanged
- `useSimulationStream.js` — only exports `toSimulationEvent` (1-line change)
- Backend `simulation.py` — no changes (timing fix already committed)
- Policy validation, prompt sanitization — untouched
- Compare mode, Save/Load scenario — untouched
- Garak probe runner — untouched (still stub)
