# Unified Event Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish `eventSchema.js` as the single source of truth for all simulation events, then wire Lineage and Alerts to consume live events — eliminating all mock data.

**Architecture:** All WS events are normalised through `canonicalise()` (already in `sessionResults.js`) into canonical `SimulationEvent` objects. `useSimulationState` switches from imperative `setState` chains to a `useReducer` pattern so all state transitions are traceable. Pure transform functions (`lineageFromEvents`, `alertsFromEvents`) derive view-model data from the canonical event stream; pages become thin wrappers that subscribe to the existing `simState.simEvents` array.

**Tech Stack:** React 18, `useReducer`, existing `useSimulationState` / `useSimulationStream` hooks, `sessionResults.js` (`CANONICAL_EVENT_TYPES`, `canonicalise`), Vitest + React Testing Library.

> **Bash path note:** All bash commands use the session-local mount path `/sessions/sweet-zen-johnson/mnt/AISPM/`. This is the correct shell path that maps to `/Users/danyshapiro/PycharmProjects/AISPM/`. Do not change these paths — the mapping is correct for this workspace.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| **Create** | `ui/src/lib/eventSchema.js` | `EVENT_TYPES` re-export + `@typedef SimulationEvent` + `normalizeEvent()` |
| **Modify** | `ui/src/hooks/useSimulationState.js` | Replace `useState` chains with `useReducer`; dispatch action for each event |
| **Modify** | `ui/src/hooks/useSimulationStream.js` | Import `normalizeEvent` from `eventSchema.js` instead of inline `toSimulationEvent` |
| **Create** | `ui/src/lib/lineageFromEvents.js` | Pure fn: `SimulationEvent[] → LineageGraph { nodes, edges }` |
| **Modify** | `ui/src/admin/pages/Lineage.jsx` | Remove all mock data; accept `simEvents` prop or read from context; render from `lineageFromEvents` |
| **Create** | `ui/src/lib/alertsFromEvents.js` | Pure fn: `SimulationEvent[] → Alert[]` (blocked/escalated → alert) |
| **Modify** | `ui/src/admin/pages/Alerts.jsx` | Merge live sim alerts with existing `useFindings` alerts |
| **Create** | `ui/src/lib/__tests__/eventSchema.test.js` | Unit tests for `normalizeEvent` |
| **Create** | `ui/src/lib/__tests__/lineageFromEvents.test.js` | Unit tests for `lineageFromEvents` |
| **Create** | `ui/src/lib/__tests__/alertsFromEvents.test.js` | Unit tests for `alertsFromEvents` |
| **Create** | `ui/src/hooks/__tests__/useSimulationState.test.js` | Tests for reducer state transitions |

---

## Task 1: Create `eventSchema.js` — Single Source of Truth

**Files:**
- Create: `ui/src/lib/eventSchema.js`
- Create: `ui/src/lib/__tests__/eventSchema.test.js`

This module re-exports `CANONICAL_EVENT_TYPES` under the friendlier name `EVENT_TYPES`, defines the `SimulationEvent` JSDoc typedef, and exports `normalizeEvent()` — the single place where raw WS frames become typed events. It delegates to the existing `canonicalise()` in `sessionResults.js` to avoid duplicating normalization logic.

- [ ] **Step 1.1: Write the failing tests**

  ```js
  // ui/src/lib/__tests__/eventSchema.test.js
  import { describe, it, expect } from 'vitest'
  import { EVENT_TYPES, normalizeEvent } from '../eventSchema.js'

  describe('EVENT_TYPES', () => {
    it('exports SESSION_STARTED', () => {
      expect(EVENT_TYPES.SESSION_STARTED).toBe('session.started')
    })
    it('exports POLICY_BLOCKED', () => {
      expect(EVENT_TYPES.POLICY_BLOCKED).toBe('policy.blocked')
    })
    it('exports 24 canonical types', () => {
      expect(Object.keys(EVENT_TYPES).length).toBeGreaterThanOrEqual(24)
    })
  })

  describe('normalizeEvent', () => {
    it('preserves canonical event_type unchanged', () => {
      const raw = { event_type: 'session.started', timestamp: '2026-01-01T00:00:00Z' }
      const ev  = normalizeEvent(raw)
      expect(ev.event_type).toBe('session.started')
    })

    it('maps legacy raw_event → session.started', () => {
      const raw = { event_type: 'raw_event', timestamp: '2026-01-01T00:00:00Z' }
      const ev  = normalizeEvent(raw)
      expect(ev.event_type).toBe('session.started')
    })

    it('maps policy.decision + block → policy.blocked', () => {
      const raw = { event_type: 'policy.decision', payload: { decision: 'block' }, timestamp: '2026-01-01T00:00:00Z' }
      const ev  = normalizeEvent(raw)
      expect(ev.event_type).toBe('policy.blocked')
    })

    it('maps policy.decision + allow → policy.allowed', () => {
      const raw = { event_type: 'policy.decision', payload: { decision: 'allow' }, timestamp: '2026-01-01T00:00:00Z' }
      const ev  = normalizeEvent(raw)
      expect(ev.event_type).toBe('policy.allowed')
    })

    it('sets dedup id as event_type:correlation_id:timestamp', () => {
      const raw = { event_type: 'risk.calculated', correlation_id: 'abc', timestamp: '2026-01-01T00:00:00Z' }
      const ev  = normalizeEvent(raw)
      expect(ev.id).toBe('risk.calculated:abc:2026-01-01T00:00:00Z')
    })

    it('sets stage for policy.blocked → blocked', () => {
      const raw = { event_type: 'policy.decision', payload: { decision: 'block' }, timestamp: '2026-01-01T00:00:00Z' }
      expect(normalizeEvent(raw).stage).toBe('blocked')
    })

    it('sets stage for session.started → started', () => {
      const raw = { event_type: 'session.started', timestamp: 'ts' }
      expect(normalizeEvent(raw).stage).toBe('started')
    })

    it('copies source_service and details.payload', () => {
      const raw = { event_type: 'audit.logged', source_service: 'svc-a', payload: { foo: 1 }, timestamp: 'ts' }
      const ev  = normalizeEvent(raw)
      expect(ev.source_service).toBe('svc-a')
      expect(ev.details.foo).toBe(1)
    })

    it('returns valid event for completely unknown event_type', () => {
      const raw = { event_type: 'some.unknown.type', timestamp: 'ts' }
      const ev  = normalizeEvent(raw)
      expect(ev.id).toBeTruthy()
      expect(ev.stage).toBe('progress')
    })
  })
  ```

- [ ] **Step 1.2: Run tests — verify all fail**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/lib/__tests__/eventSchema.test.js 2>&1 | tail -20
  ```
  Expected: FAIL — `Cannot find module '../eventSchema.js'`

- [ ] **Step 1.3: Implement `eventSchema.js`**

  ```js
  /**
   * lib/eventSchema.js
   * ───────────────────
   * Single source of truth for simulation event types and normalization.
   *
   * Re-exports CANONICAL_EVENT_TYPES as EVENT_TYPES and provides
   * normalizeEvent() — the single place raw WS frames become typed
   * SimulationEvent objects.  Delegates canonicalization to sessionResults.js
   * to avoid duplicate normalization logic.
   *
   * @module eventSchema
   */
  import { CANONICAL_EVENT_TYPES, canonicalise } from './sessionResults.js'

  // ── Public registry ──────────────────────────────────────────────────────────
  export { CANONICAL_EVENT_TYPES }

  /** Alias for ergonomic imports: `import { EVENT_TYPES } from './eventSchema.js'` */
  export const EVENT_TYPES = CANONICAL_EVENT_TYPES

  // ── Stage derivation ─────────────────────────────────────────────────────────
  // Maps canonical event_type → timeline stage used by phaseGrouping.js.
  // "stage" is a UI concept that maps events into visual phases.

  const _TYPE_TO_STAGE = {
    [CANONICAL_EVENT_TYPES.SESSION_STARTED]:        'started',
    [CANONICAL_EVENT_TYPES.SESSION_CREATED]:        'started',
    [CANONICAL_EVENT_TYPES.SESSION_COMPLETED]:      'completed',
    [CANONICAL_EVENT_TYPES.SESSION_BLOCKED]:        'blocked',
    [CANONICAL_EVENT_TYPES.SESSION_FAILED]:         'error',
    [CANONICAL_EVENT_TYPES.POLICY_ALLOWED]:         'allowed',
    [CANONICAL_EVENT_TYPES.POLICY_BLOCKED]:         'blocked',
    [CANONICAL_EVENT_TYPES.POLICY_ESCALATED]:       'escalated',
    [CANONICAL_EVENT_TYPES.CONTEXT_RETRIEVED]:      'progress',
    [CANONICAL_EVENT_TYPES.RISK_ENRICHED]:          'progress',
    [CANONICAL_EVENT_TYPES.RISK_CALCULATED]:        'progress',
    [CANONICAL_EVENT_TYPES.AGENT_MEMORY_REQUESTED]: 'progress',
    [CANONICAL_EVENT_TYPES.AGENT_MEMORY_RESOLVED]:  'progress',
    [CANONICAL_EVENT_TYPES.AGENT_TOOL_PLANNED]:     'progress',
    [CANONICAL_EVENT_TYPES.AGENT_RESPONSE_READY]:   'progress',
    [CANONICAL_EVENT_TYPES.TOOL_INVOKED]:           'progress',
    [CANONICAL_EVENT_TYPES.TOOL_APPROVAL_REQUIRED]: 'progress',
    [CANONICAL_EVENT_TYPES.TOOL_COMPLETED]:         'progress',
    [CANONICAL_EVENT_TYPES.TOOL_OBSERVED]:          'progress',
    [CANONICAL_EVENT_TYPES.OUTPUT_GENERATED]:       'progress',
    [CANONICAL_EVENT_TYPES.OUTPUT_SCANNED]:         'progress',
    [CANONICAL_EVENT_TYPES.AUDIT_LOGGED]:           'progress',
  }

  function deriveStage(canonicalType) {
    return _TYPE_TO_STAGE[canonicalType] ?? 'progress'
  }

  // ── SimulationEvent typedef ──────────────────────────────────────────────────

  /**
   * @typedef {Object} SimulationEvent
   * @property {string}  id             — dedup key: `event_type:correlation_id:timestamp`
   * @property {string}  event_type     — canonical event type from EVENT_TYPES
   * @property {string}  stage          — UI timeline stage: started|progress|blocked|allowed|escalated|completed|error
   * @property {string}  status         — alias for stage (legacy compat)
   * @property {string}  timestamp      — ISO-8601 from WS frame
   * @property {string}  [source_service] — originating backend service
   * @property {object}  details        — raw payload from WS frame
   */

  /**
   * Normalize a raw WebSocket frame into a typed SimulationEvent.
   *
   * This is the ONLY place in the codebase that should convert raw WS events
   * into SimulationEvents.  All consumers import this function.
   *
   * @param {object} wsEvent — raw frame from useSessionSocket
   * @returns {SimulationEvent}
   */
  export function normalizeEvent(wsEvent) {
    const canonicalType = canonicalise(wsEvent)
    const stage         = deriveStage(canonicalType)

    return {
      id:             `${canonicalType}:${wsEvent.correlation_id || ''}:${wsEvent.timestamp}`,
      event_type:     canonicalType,
      stage,
      status:         stage,
      timestamp:      wsEvent.timestamp,
      source_service: wsEvent.source_service,
      details:        wsEvent.payload || {},
    }
  }
  ```

- [ ] **Step 1.4: Run tests — verify all pass**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/lib/__tests__/eventSchema.test.js 2>&1 | tail -20
  ```
  Expected: 9/9 PASS

- [ ] **Step 1.5: Commit**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM && git add ui/src/lib/eventSchema.js ui/src/lib/__tests__/eventSchema.test.js && git commit -m "feat(events): add eventSchema.js — single source of truth for SimulationEvent types and normalization"
  ```

---

## Task 2: Wire `useSimulationStream` to `normalizeEvent`

**Files:**
- Modify: `ui/src/hooks/useSimulationStream.js` (lines 47–79, the `toSimulationEvent` function)

`useSimulationStream` currently has its own inline `toSimulationEvent` that duplicates stage-derivation logic. Replace it with a call to `normalizeEvent` from `eventSchema.js`. The exported `toSimulationEvent` name is kept as an alias so nothing breaks downstream.

- [ ] **Step 2.0: Verify `canonicalise` handles all required mappings before writing tests**

  Confirm `prompt_received → session.started` is in `_RAW_TO_CANONICAL` in `sessionResults.js`:

  ```bash
  grep "prompt_received\|posture.enriched\|policy.decision" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src/lib/sessionResults.js
  ```

  Expected output shows these three keys in `_RAW_TO_CANONICAL`. The tests below rely on these mappings being present. If any are missing, add them to `sessionResults.js` first (not to `eventSchema.js`).

- [ ] **Step 2.1: Write the failing test**

  ```js
  // ui/src/hooks/__tests__/useSimulationStream.normalization.test.js
  import { describe, it, expect } from 'vitest'
  import { toSimulationEvent } from '../useSimulationStream.js'

  describe('toSimulationEvent (uses normalizeEvent internally)', () => {
    it('maps posture.enriched → risk.enriched canonical type', () => {
      const raw = { event_type: 'posture.enriched', timestamp: 'ts', payload: {} }
      const ev  = toSimulationEvent(raw)
      expect(ev.event_type).toBe('risk.enriched')
    })

    it('maps policy.decision+block → policy.blocked + stage blocked', () => {
      const raw = { event_type: 'policy.decision', payload: { decision: 'block' }, timestamp: 'ts' }
      const ev  = toSimulationEvent(raw)
      expect(ev.event_type).toBe('policy.blocked')
      expect(ev.stage).toBe('blocked')
    })

    it('maps prompt_received → session.started + stage started', () => {
      const raw = { event_type: 'prompt_received', timestamp: 'ts', payload: {} }
      const ev  = toSimulationEvent(raw)
      expect(ev.event_type).toBe('session.started')
      expect(ev.stage).toBe('started')
    })
  })
  ```

- [ ] **Step 2.2: Run test — verify it fails (wrong canonical type)**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/hooks/__tests__/useSimulationStream.normalization.test.js 2>&1 | tail -20
  ```
  Expected: FAIL — canonical type is `posture.enriched` not `risk.enriched` (old inline logic)

- [ ] **Step 2.3: Update `useSimulationStream.js`**

  Replace the `toSimulationEvent` function body with a delegation to `normalizeEvent`:

  ```js
  // At top of file, add import:
  import { normalizeEvent } from '../lib/eventSchema.js'

  // Replace the entire toSimulationEvent function (lines 47-79) with:
  /**
   * Parse a WsEvent into a SimulationEvent.
   * Delegates to normalizeEvent() from eventSchema.js — single source of truth.
   * Exported for use in tests and useSimulationState.
   */
  export function toSimulationEvent(wsEvent) {
    return normalizeEvent(wsEvent)
  }
  ```

  Also remove the now-unused `EVENT_TYPE_STAGE` constant (lines 30-35) and the old inline stage-derivation logic.

- [ ] **Step 2.4: Run both test suites — verify all pass**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/hooks/__tests__/useSimulationStream.normalization.test.js src/lib/__tests__/eventSchema.test.js 2>&1 | tail -20
  ```
  Expected: 12/12 PASS

- [ ] **Step 2.5: Run full test suite — verify no regressions**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run 2>&1 | tail -30
  ```
  Expected: same pass count as before (163+), 0 new failures

- [ ] **Step 2.6: Commit**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM && git add ui/src/hooks/useSimulationStream.js ui/src/hooks/__tests__/useSimulationStream.normalization.test.js && git commit -m "refactor(stream): delegate toSimulationEvent to normalizeEvent — one normalization path"
  ```

---

## Task 3: Refactor `useSimulationState` to `useReducer`

**Files:**
- Modify: `ui/src/hooks/useSimulationState.js`
- Create: `ui/src/hooks/__tests__/useSimulationState.test.js`

The current hook uses multiple `setState` calls, making state transitions hard to trace. Replacing with `useReducer` means every transition is an explicit action (`EVENT_RECEIVED`, `SIMULATION_STARTED`, `SIMULATION_RESET`, `WATCHDOG_FIRED`, `API_ERROR`). The public API — `{ simState, startSimulation, resetSimulation }` — stays identical. **Do not change the hook's return shape.**

- [ ] **Step 3.1: Write the failing reducer unit tests**

  ```js
  // ui/src/hooks/__tests__/useSimulationState.test.js
  import { describe, it, expect } from 'vitest'
  import { simReducer, makeIdle, Actions } from '../useSimulationState.js'
  import { EVENT_TYPES } from '../../lib/eventSchema.js'

  function makeEvent(event_type, stage, overrides = {}) {
    return { id: `${event_type}:x:ts`, event_type, stage, status: stage, timestamp: 'ts', details: {}, ...overrides }
  }

  describe('simReducer', () => {
    it('SIMULATION_STARTED transitions idle → running', () => {
      const state  = makeIdle()
      const next   = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 'sid-1', startedAt: 1000 })
      expect(next.status).toBe('running')
      expect(next.sessionId).toBe('sid-1')
      expect(next.startedAt).toBe(1000)
      expect(next.steps).toEqual([])
    })

    it('EVENT_RECEIVED appends a step while running', () => {
      const state = { ...makeIdle(), status: 'running' }
      const ev    = makeEvent(EVENT_TYPES.RISK_CALCULATED, 'progress')
      const next  = simReducer(state, { type: Actions.EVENT_RECEIVED, event: ev })
      expect(next.steps).toHaveLength(1)
      expect(next.steps[0].id).toBe(ev.id)
    })

    it('EVENT_RECEIVED does not mutate state when not running', () => {
      const state = makeIdle()
      const ev    = makeEvent(EVENT_TYPES.RISK_CALCULATED, 'progress')
      const next  = simReducer(state, { type: Actions.EVENT_RECEIVED, event: ev })
      expect(next).toBe(state) // referential equality — no change
    })

    it('terminal EVENT_RECEIVED (blocked) → completed status', () => {
      const state = { ...makeIdle(), status: 'running' }
      const ev    = makeEvent(EVENT_TYPES.POLICY_BLOCKED, 'blocked')
      const next  = simReducer(state, { type: Actions.EVENT_RECEIVED, event: ev, finalResults: { verdict: 'blocked' } })
      expect(next.status).toBe('completed')
      expect(next.finalResults.verdict).toBe('blocked')
    })

    it('terminal EVENT_RECEIVED (error) → failed status', () => {
      const state = { ...makeIdle(), status: 'running' }
      const ev    = makeEvent(EVENT_TYPES.SESSION_FAILED, 'error')
      const next  = simReducer(state, { type: Actions.EVENT_RECEIVED, event: ev })
      expect(next.status).toBe('failed')
    })

    it('WATCHDOG_FIRED → failed with timeout message', () => {
      const state = { ...makeIdle(), status: 'running' }
      const next  = simReducer(state, { type: Actions.WATCHDOG_FIRED })
      expect(next.status).toBe('failed')
      expect(next.error).toMatch(/timeout/i)
    })

    it('API_ERROR → failed with error message', () => {
      const state = { ...makeIdle(), status: 'running' }
      const next  = simReducer(state, { type: Actions.API_ERROR, error: 'network failure' })
      expect(next.status).toBe('failed')
      expect(next.error).toBe('network failure')
    })

    it('SIMULATION_RESET → idle regardless of current status', () => {
      const state = { ...makeIdle(), status: 'completed', finalResults: { verdict: 'blocked' } }
      const next  = simReducer(state, { type: Actions.SIMULATION_RESET })
      expect(next.status).toBe('idle')
      expect(next.finalResults).toBeNull()
    })

    it('reducer is pure — does not mutate input', () => {
      const state = { ...makeIdle(), status: 'running' }
      const frozen = Object.freeze({ ...state, steps: Object.freeze([]) })
      const ev    = makeEvent(EVENT_TYPES.RISK_CALCULATED, 'progress')
      expect(() => simReducer(frozen, { type: Actions.EVENT_RECEIVED, event: ev })).not.toThrow()
    })
  })
  ```

- [ ] **Step 3.2: Run tests — verify they fail**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/hooks/__tests__/useSimulationState.test.js 2>&1 | tail -20
  ```
  Expected: FAIL — `simReducer`, `makeIdle`, `Actions` are not exported

- [ ] **Step 3.3: Refactor `useSimulationState.js`**

  Key changes:
  1. Export `Actions` constant (action type strings)
  2. Export `makeIdle()` (already exists — just add `export`)
  3. Export `simReducer(state, action)` — pure function
  4. Replace `useState(makeIdle)` with `useReducer(simReducer, makeIdle())`
  5. Replace `setSimState(prev => ...)` calls with `dispatch({ type: Actions.X, ... })`
  6. The `useEffect` that listens to `simEvents` now dispatches `EVENT_RECEIVED` per event

  **Important:** `terminatedRef.current` guard stays in the `useEffect`, not in the reducer. The reducer is pure and stateless — it cannot and should not track "have I seen this terminal event before." The `useEffect` already checks `terminatedRef.current` before dispatching the terminal action, so the reducer only ever sees each terminal event once. Document this boundary clearly in comments.

  ```js
  // ── Terminal stage set ────────────────────────────────────────────────────────
  // Keep in sync with useSimulationStream.js TERMINAL_STAGES if it exists there.
  const TERMINAL_STAGES = new Set(['completed', 'blocked', 'allowed', 'escalated', 'error'])

  // ── Action types ──────────────────────────────────────────────────────────────
  export const Actions = Object.freeze({
    SIMULATION_STARTED: 'SIMULATION_STARTED',
    EVENT_RECEIVED:     'EVENT_RECEIVED',
    WATCHDOG_FIRED:     'WATCHDOG_FIRED',
    API_ERROR:          'API_ERROR',
    SIMULATION_RESET:   'SIMULATION_RESET',
  })

  // ── Reducer ────────────────────────────────────────────────────────────────────
  export function simReducer(state, action) {
    switch (action.type) {

      case Actions.SIMULATION_STARTED:
        return {
          ...makeIdle(),
          status:    'running',
          sessionId: action.sessionId,
          startedAt: action.startedAt,
        }

      case Actions.EVENT_RECEIVED: {
        if (state.status !== 'running') return state   // stale event after completion

        const { event, finalResults } = action
        const isTerminal = TERMINAL_STAGES.has(event.stage)
        const isFailed   = event.stage === 'error'
        const isProbe    = event.stage === 'allowed' || event.stage === 'blocked'

        const newStep = {
          id:        event.id,
          label:     stepLabel(event),
          status:    isTerminal ? (isFailed ? 'failed' : 'done') : 'running',
          timestamp: event.timestamp ? new Date(event.timestamp).getTime() : Date.now(),
        }

        if (isTerminal) {
          return {
            ...state,
            status:       isFailed ? 'failed' : 'completed',
            steps:        addOrReplaceStep(state.steps, newStep),
            finalResults: isFailed ? null : (finalResults ?? null),
            error:        isFailed ? (event.details?.error_message || 'Simulation failed') : undefined,
            completedAt:  Date.now(),
          }
        }

        return {
          ...state,
          steps:          addOrReplaceStep(state.steps, newStep),
          partialResults: isProbe
            ? [...state.partialResults, event]
            : state.partialResults,
        }
      }

      case Actions.WATCHDOG_FIRED:
        return {
          ...state,
          status:      'failed',
          error:       'Simulation timeout — no response received within 30 seconds.',
          completedAt: Date.now(),
        }

      case Actions.API_ERROR:
        return {
          ...state,
          status:      'failed',
          error:       action.error || 'Failed to start simulation',
          completedAt: Date.now(),
        }

      case Actions.SIMULATION_RESET:
        return makeIdle()

      default:
        return state
    }
  }
  ```

  In the hook body, replace `useState` with `useReducer` and wire dispatch to each site:

  ```js
  // Replace:  const [simState, setSimState] = useState(makeIdle)
  // With:
  const [simState, dispatch] = useReducer(simReducer, makeIdle())

  // In the useEffect that watches simEvents:
  useEffect(() => {
    if (simEvents.length === 0) return
    const latest = simEvents[simEvents.length - 1]
    if (!TERMINAL_STAGES.has(latest.stage)) {
      dispatch({ type: Actions.EVENT_RECEIVED, event: latest })
      return
    }
    if (terminatedRef.current) return
    terminatedRef.current = true
    clearWatchdog()
    const built = buildResultFromSimEvents(simEvents)
    dispatch({ type: Actions.EVENT_RECEIVED, event: latest, finalResults: built })
  }, [simEvents, clearWatchdog])

  // In startSimulation — replace the setSimState({ ...makeIdle(), status:'running', ... }):
  dispatch({ type: Actions.SIMULATION_STARTED, sessionId: sid, startedAt: Date.now() })

  // In watchdog timeout callback:
  dispatch({ type: Actions.WATCHDOG_FIRED })

  // In catch block:
  dispatch({ type: Actions.API_ERROR, error: err.message })

  // In resetSimulation:
  dispatch({ type: Actions.SIMULATION_RESET })
  ```

- [ ] **Step 3.4: Run reducer tests — verify all pass**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/hooks/__tests__/useSimulationState.test.js 2>&1 | tail -20
  ```
  Expected: 9/9 PASS

- [ ] **Step 3.5: Run full test suite — verify no regressions**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run 2>&1 | tail -30
  ```
  Expected: 0 new failures

- [ ] **Step 3.6: Commit**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM && git add ui/src/hooks/useSimulationState.js ui/src/hooks/__tests__/useSimulationState.test.js && git commit -m "refactor(state): switch useSimulationState to useReducer — all transitions explicit and testable"
  ```

---

## Task 4: Create `lineageFromEvents.js` — Pure Transform

**Files:**
- Create: `ui/src/lib/lineageFromEvents.js`
- Create: `ui/src/lib/__tests__/lineageFromEvents.test.js`

Produces a `LineageGraph` (`{ nodes, edges }`) from a `SimulationEvent[]`. The graph mirrors the node/edge shapes already used by `Lineage.jsx` (`NODE_CFG` keys: `prompt`, `context`, `rag`, `model`, `tool`, `policy`, `output`). Each relevant event type creates or updates a node; canonical ordering is preserved.

- [ ] **Step 4.1: Write the failing tests**

  ```js
  // ui/src/lib/__tests__/lineageFromEvents.test.js
  import { describe, it, expect } from 'vitest'
  import { lineageFromEvents } from '../lineageFromEvents.js'
  import { EVENT_TYPES } from '../eventSchema.js'

  function ev(event_type, details = {}) {
    return { id: `${event_type}:x:ts`, event_type, stage: 'progress', status: 'progress', timestamp: 'ts', details }
  }

  describe('lineageFromEvents', () => {
    it('returns empty graph for no events', () => {
      const g = lineageFromEvents([])
      expect(g.nodes).toEqual([])
      expect(g.edges).toEqual([])
    })

    it('session.started creates a prompt node', () => {
      const g = lineageFromEvents([ev(EVENT_TYPES.SESSION_STARTED, { prompt: 'hello' })])
      expect(g.nodes.find(n => n.type === 'prompt')).toBeTruthy()
    })

    it('context.retrieved creates a context node', () => {
      const g = lineageFromEvents([
        ev(EVENT_TYPES.SESSION_STARTED),
        ev(EVENT_TYPES.CONTEXT_RETRIEVED, { retrieved_contexts: ['ctx1', 'ctx2'] }),
      ])
      expect(g.nodes.find(n => n.type === 'context')).toBeTruthy()
    })

    it('risk.enriched creates a model node', () => {
      const g = lineageFromEvents([
        ev(EVENT_TYPES.SESSION_STARTED),
        ev(EVENT_TYPES.RISK_ENRICHED),
      ])
      expect(g.nodes.find(n => n.type === 'model')).toBeTruthy()
    })

    it('tool.invoked creates a tool node', () => {
      const g = lineageFromEvents([
        ev(EVENT_TYPES.SESSION_STARTED),
        ev(EVENT_TYPES.TOOL_INVOKED, { tool_name: 'sql_query' }),
      ])
      expect(g.nodes.find(n => n.type === 'tool')).toBeTruthy()
      expect(g.nodes.find(n => n.type === 'tool').label).toMatch(/sql_query/i)
    })

    it('policy.blocked creates a policy node with flagged=true', () => {
      const g = lineageFromEvents([
        ev(EVENT_TYPES.SESSION_STARTED),
        ev(EVENT_TYPES.POLICY_BLOCKED, { reason: 'pii detected' }),
      ])
      const policyNode = g.nodes.find(n => n.type === 'policy')
      expect(policyNode).toBeTruthy()
      expect(policyNode.flagged).toBe(true)
    })

    it('output.generated creates an output node', () => {
      const g = lineageFromEvents([
        ev(EVENT_TYPES.SESSION_STARTED),
        ev(EVENT_TYPES.OUTPUT_GENERATED, { response: 'hello' }),
      ])
      expect(g.nodes.find(n => n.type === 'output')).toBeTruthy()
    })

    it('creates prompt→context edge when both present', () => {
      const g = lineageFromEvents([
        ev(EVENT_TYPES.SESSION_STARTED),
        ev(EVENT_TYPES.CONTEXT_RETRIEVED),
      ])
      expect(g.edges.some(e => e.from === 'prompt' && e.to === 'context')).toBe(true)
    })

    it('creates policy→output edge when both present', () => {
      const g = lineageFromEvents([
        ev(EVENT_TYPES.SESSION_STARTED),
        ev(EVENT_TYPES.POLICY_ALLOWED),
        ev(EVENT_TYPES.OUTPUT_GENERATED),
      ])
      expect(g.edges.some(e => e.from === 'policy' && e.to === 'output')).toBe(true)
    })

    it('is pure — same input same output', () => {
      const events = [ev(EVENT_TYPES.SESSION_STARTED), ev(EVENT_TYPES.POLICY_BLOCKED)]
      expect(lineageFromEvents(events)).toEqual(lineageFromEvents(events))
    })
  })
  ```

- [ ] **Step 4.2: Run tests — verify they fail**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/lib/__tests__/lineageFromEvents.test.js 2>&1 | tail -20
  ```
  Expected: FAIL — module not found

- [ ] **Step 4.3: Implement `lineageFromEvents.js`**

  ```js
  /**
   * lib/lineageFromEvents.js
   * ─────────────────────────
   * Pure function: SimulationEvent[] → LineageGraph
   *
   * LineageGraph shape
   * ──────────────────
   * {
   *   nodes: LineageNode[]
   *   edges: LineageEdge[]
   * }
   *
   * LineageNode shape  (mirrors Lineage.jsx NODE_CFG key system)
   * ──────────────────
   * {
   *   id:      string     — node id ('prompt' | 'context' | 'rag' | 'model' | 'tool-{n}' | 'policy' | 'output')
   *   type:    string     — NODE_CFG key
   *   label:   string     — display label
   *   sub:     string     — subtitle / detail line
   *   risk:    string     — 'Low' | 'Medium' | 'High' | 'Critical'
   *   flagged: boolean
   * }
   *
   * LineageEdge shape
   * ──────────────────
   * {
   *   id:   string   — 'from-to'
   *   from: string   — source node id
   *   to:   string   — target node id
   *   type: string   — EDGE_CFG key: 'data' | 'sensitive' | 'tool' | 'policy' | 'output'
   *   label: string
   * }
   */
  import { EVENT_TYPES } from './eventSchema.js'

  /**
   * @param {import('./eventSchema.js').SimulationEvent[]} events
   * @returns {{ nodes: object[], edges: object[] }}
   */
  export function lineageFromEvents(events) {
    if (!events || events.length === 0) return { nodes: [], edges: [] }

    const nodeMap = new Map()   // id → node
    const edges   = []
    let   toolIdx = 0

    function addNode(id, type, label, sub, risk = 'Low', flagged = false) {
      if (!nodeMap.has(id)) nodeMap.set(id, { id, type, label, sub, risk, flagged })
      else {
        // Merge — escalate risk, set flagged
        const n = nodeMap.get(id)
        if (flagged) n.flagged = true
        if (riskLevel(risk) > riskLevel(n.risk)) n.risk = risk
        if (sub) n.sub = sub
      }
    }

    function addEdge(from, to, type, label) {
      const id = `${from}-${to}`
      if (!edges.find(e => e.id === id)) edges.push({ id, from, to, type, label })
    }

    for (const ev of events) {
      const d = ev.details || {}

      switch (ev.event_type) {
        case EVENT_TYPES.SESSION_STARTED:
        case EVENT_TYPES.SESSION_CREATED:
          addNode('prompt', 'prompt', 'User Prompt',
            d.prompt ? `"${d.prompt.slice(0, 40)}…"` : 'Prompt received')
          break

        case EVENT_TYPES.CONTEXT_RETRIEVED: {
          const count = d.retrieved_contexts?.length ?? d.context_count ?? 0
          addNode('context', 'context', 'Session Context', `${count} context item${count !== 1 ? 's' : ''}`)
          addEdge('prompt', 'context', 'data', 'context')
          break
        }

        case EVENT_TYPES.RISK_ENRICHED:
        case EVENT_TYPES.RISK_CALCULATED: {
          const score = d.posture_score ?? d.risk_score ?? 0
          const risk  = score >= 0.8 ? 'Critical' : score >= 0.5 ? 'High' : score >= 0.3 ? 'Medium' : 'Low'
          addNode('model', 'model', 'LLM Processing', `Risk: ${Math.round(score * 100)}`, risk, score >= 0.8)
          if (nodeMap.has('context')) addEdge('context', 'model', 'data', 'context')
          else addEdge('prompt', 'model', 'data', 'prompt')
          break
        }

        case EVENT_TYPES.AGENT_TOOL_PLANNED:
        case EVENT_TYPES.TOOL_INVOKED:
        case EVENT_TYPES.TOOL_COMPLETED: {
          const toolName = d.tool_name || `Tool ${toolIdx + 1}`
          const toolId   = `tool-${toolName.replace(/\s+/g, '-').toLowerCase()}`
          if (!nodeMap.has(toolId)) toolIdx++
          addNode(toolId, 'tool', `Tool: ${toolName}`, d.status || 'invoked')
          addEdge('model', toolId, 'tool', 'tool call')
          break
        }

        case EVENT_TYPES.TOOL_APPROVAL_REQUIRED: {
          const toolName = d.tool_name || 'Tool'
          const toolId   = `tool-${toolName.replace(/\s+/g, '-').toLowerCase()}`
          addNode(toolId, 'tool', `Tool: ${toolName}`, 'approval required', 'Medium', true)
          if (!edges.find(e => e.to === toolId)) addEdge('model', toolId, 'tool', 'tool call')
          break
        }

        case EVENT_TYPES.POLICY_ALLOWED:
        case EVENT_TYPES.POLICY_ESCALATED:
        case EVENT_TYPES.POLICY_BLOCKED: {
          const isBlock    = ev.event_type === EVENT_TYPES.POLICY_BLOCKED
          const isEscalate = ev.event_type === EVENT_TYPES.POLICY_ESCALATED
          const risk       = isBlock ? 'Critical' : isEscalate ? 'High' : 'Low'
          const sub        = d.reason || d.policy_version || (isBlock ? 'BLOCKED' : isEscalate ? 'ESCALATED' : 'ALLOWED')
          addNode('policy', 'policy', 'Policy Gate', sub, risk, isBlock || isEscalate)
          const fromId = nodeMap.has('model') ? 'model' : 'prompt'
          addEdge(fromId, 'policy', 'policy', 'policy eval')
          break
        }

        case EVENT_TYPES.OUTPUT_GENERATED:
        case EVENT_TYPES.OUTPUT_SCANNED: {
          const sub = d.pii_redacted ? 'Redacted · ' : ''
          addNode('output', 'output', 'Output',
            `${sub}${d.response_latency_ms ? `${d.response_latency_ms}ms` : 'generated'}`)
          const fromId = nodeMap.has('policy') ? 'policy' : nodeMap.has('model') ? 'model' : 'prompt'
          addEdge(fromId, 'output', 'output', 'gated')
          break
        }

        case EVENT_TYPES.SESSION_BLOCKED: {
          // Blocked before output — ensure policy node exists and is flagged
          addNode('policy', 'policy', 'Policy Gate', d.reason || 'Blocked', 'Critical', true)
          if (!edges.find(e => e.to === 'policy')) {
            const fromId = nodeMap.has('model') ? 'model' : 'prompt'
            addEdge(fromId, 'policy', 'policy', 'policy eval')
          }
          break
        }

        default:
          break
      }
    }

    return { nodes: Array.from(nodeMap.values()), edges }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────
  function riskLevel(r) {
    return { Low: 0, Medium: 1, High: 2, Critical: 3 }[r] ?? 0
  }
  ```

- [ ] **Step 4.4: Run tests — verify all pass**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/lib/__tests__/lineageFromEvents.test.js 2>&1 | tail -20
  ```
  Expected: 10/10 PASS

- [ ] **Step 4.5: Commit**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM && git add ui/src/lib/lineageFromEvents.js ui/src/lib/__tests__/lineageFromEvents.test.js && git commit -m "feat(lineage): add lineageFromEvents — pure SimulationEvent[] → LineageGraph transform"
  ```

---

## Task 5: Wire `Lineage.jsx` to Live Events

**Files:**
- Modify: `ui/src/admin/pages/Lineage.jsx`

Replace the hardcoded `NODES` and `EDGES` arrays with a call to `lineageFromEvents(simEvents)`. The `simEvents` array comes from a new optional prop `simEvents` (default `[]`). All `NODE_CFG`, `EDGE_CFG`, and rendering code stays untouched — only the data source changes. The static demo data is removed or moved behind a `DEV_DEMO` flag for future reference.

**Important:** The render logic in `Lineage.jsx` uses `cx`/`cy` coordinates for SVG layout. `lineageFromEvents` returns abstract nodes without coordinates. A layout function `assignCoords(nodes)` must map node types to static x/y positions (the same positions as the current hardcoded nodes) so the existing SVG render code works unchanged.

- [ ] **Step 5.1: Add `assignCoords` to `lineageFromEvents.js`**

  ```js
  // Add to lineageFromEvents.js (exported helper):

  // Static layout positions by node type.
  // Matches the NW=55, NH=28, CW=790, CH=300 canvas used in Lineage.jsx.
  const _LAYOUT = {
    prompt:  { cx: 65,  cy: 150 },
    context: { cx: 210, cy: 78  },
    rag:     { cx: 210, cy: 222 },
    model:   { cx: 380, cy: 150 },
    tool:    { cx: 520, cy: 72  },   // first tool; subsequent stagger by 60px
    policy:  { cx: 570, cy: 228 },
    output:  { cx: 710, cy: 150 },
  }

  const _NW = 55, _NH = 28

  /**
   * Assign SVG cx/cy coordinates to LineageGraph nodes.
   * Adds right/left/top/bottom port helpers used by edge path generation.
   *
   * @param {object[]} nodes — from lineageFromEvents
   * @returns {object[]} nodes with cx, cy added
   */
  export function assignCoords(nodes) {
    const toolNodes = nodes.filter(n => n.type === 'tool')
    let toolCount   = 0
    return nodes.map(n => {
      let pos = _LAYOUT[n.type] ?? { cx: 400, cy: 150 }
      if (n.type === 'tool') {
        pos = { cx: _LAYOUT.tool.cx, cy: _LAYOUT.tool.cy + toolCount * 60 }
        toolCount++
      }
      return { ...n, ...pos }
    })
  }

  /**
   * Generate SVG path strings for edges given a positioned node map.
   *
   * @param {object[]} edges  — from lineageFromEvents
   * @param {Map}      nodeById — id → positioned node
   * @returns {object[]} edges with path added
   */
  export function assignEdgePaths(edges, nodeById) {
    return edges.map(edge => {
      const from = nodeById.get(edge.from)
      const to   = nodeById.get(edge.to)
      if (!from || !to) return { ...edge, path: '' }
      // Simple straight cubic bezier from right port to left port
      const x1 = from.cx + _NW, y1 = from.cy
      const x2 = to.cx   - _NW, y2 = to.cy
      const cp = Math.abs(x2 - x1) * 0.4
      return { ...edge, path: `M ${x1} ${y1} C ${x1 + cp} ${y1}, ${x2 - cp} ${y2}, ${x2} ${y2}` }
    })
  }
  ```

- [ ] **Step 5.2: Write a smoke test for `Lineage.jsx` prop wiring**

  ```js
  // ui/src/admin/pages/__tests__/Lineage.liveEvents.test.jsx
  import { describe, it, expect } from 'vitest'
  import { render, screen } from '@testing-library/react'
  import { MemoryRouter } from 'react-router-dom'
  import Lineage from '../Lineage.jsx'
  import { EVENT_TYPES } from '../../../lib/eventSchema.js'

  function ev(event_type, details = {}) {
    return { id: `${event_type}:x:ts`, event_type, stage: 'progress', timestamp: 'ts', details }
  }

  describe('Lineage live events', () => {
    it('renders prompt node label when session.started event present', () => {
      const events = [ev(EVENT_TYPES.SESSION_STARTED, { prompt: 'test prompt' })]
      render(<MemoryRouter><Lineage simEvents={events} /></MemoryRouter>)
      expect(screen.getByText('User Prompt')).toBeInTheDocument()
    })

    it('renders empty state when no events and no simEvents prop', () => {
      render(<MemoryRouter><Lineage /></MemoryRouter>)
      // Graph canvas still renders; just no nodes (or shows placeholder)
      expect(document.querySelector('svg')).toBeInTheDocument()
    })
  })
  ```

- [ ] **Step 5.2a: Pre-implementation inspection — confirm SVG render inputs**

  Before modifying Lineage.jsx, read the file to confirm exactly which variables are consumed by the SVG render section:

  ```bash
  grep -n "cx\|cy\|NW\|NH\|NODES\|EDGES\|nodeEdges\|NODE_PATH\|NODE_EDGES" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src/admin/pages/Lineage.jsx | head -60
  ```

  Confirm: (a) `cx`/`cy` are consumed directly per node, (b) `NODE_EDGES` is used for highlight logic, (c) `NODE_PATH` is used for breadcrumbs (not SVG paths). Verify `assignCoords` output shape matches what the SVG section expects. If any field names differ, update `assignCoords` before proceeding.

- [ ] **Step 5.3: Run smoke test — verify it fails**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/admin/pages/__tests__/Lineage.liveEvents.test.jsx 2>&1 | tail -20
  ```
  Expected: FAIL — `simEvents` prop ignored, static mock nodes rendered instead

- [ ] **Step 5.4: Update `Lineage.jsx`**

  Remove `NODES`, `EDGES`, `NODE_EDGES`, `NODE_PATH`, `SESSIONS`, `TIMELINE`, `NODE_DETAIL` constants.
  Add import for `lineageFromEvents`, `assignCoords`, `assignEdgePaths`.
  Update the main `Lineage` component signature to accept `simEvents = []`.
  Compute `nodes` and `edges` from events:

  ```jsx
  import { lineageFromEvents, assignCoords, assignEdgePaths } from '../../lib/lineageFromEvents.js'

  export default function Lineage({ simEvents = [] }) {
    // ... existing useState for selectedNode, hoveredNode, etc.

    const { nodes: rawNodes, edges: rawEdges } = lineageFromEvents(simEvents)
    const nodes    = assignCoords(rawNodes)
    const nodeById = new Map(nodes.map(n => [n.id, n]))
    const edges    = assignEdgePaths(rawEdges, nodeById)

    // Build NODE_EDGES map dynamically from computed edges:
    const nodeEdges = {}
    for (const e of edges) {
      ;(nodeEdges[e.from] = nodeEdges[e.from] || []).push(e.id)
      ;(nodeEdges[e.to]   = nodeEdges[e.to]   || []).push(e.id)
    }

    // Show empty-state SVG when no events yet:
    if (nodes.length === 0) {
      return (
        <PageContainer>
          <PageHeader title="Data Lineage" subtitle="Run a simulation to see the live lineage graph." />
          <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
            No simulation data yet — run a simulation to populate the graph.
          </div>
        </PageContainer>
      )
    }

    // Rest of existing render code uses `nodes`, `edges`, `nodeEdges`
    // Replace all references to the old NODES/EDGES constants.
    // ...
  }
  ```

  **In `Simulation.jsx`:** `simEvents` must be shared with Lineage and Alerts, which are separate routes. Use React context.

  First, find the router structure:

  ```bash
  grep -rn "SimulationContext\|createContext" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src --include="*.jsx" --include="*.js" | head -20
  grep -rn "<Route\|<Router\|RouterProvider" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src --include="*.jsx" | head -20
  ```

  **If no SimulationContext exists:** create it.

  ```jsx
  // ui/src/context/SimulationContext.jsx
  import { createContext, useContext } from 'react'

  /** @type {React.Context<{ simEvents: import('../lib/eventSchema.js').SimulationEvent[] }>} */
  export const SimulationContext = createContext({ simEvents: [] })
  export const useSimulationContext = () => useContext(SimulationContext)
  ```

  **Where to add the Provider:** Find the file that renders the admin layout (likely `ui/src/admin/AdminLayout.jsx` or `ui/src/App.jsx`). That file must call `useSimulationState()` at its root so `simState.simEvents` is available, then wrap children:

  ```jsx
  // In AdminLayout.jsx (or equivalent):
  import { useSimulationState } from '../hooks/useSimulationState.js'
  import { SimulationContext }  from '../context/SimulationContext.jsx'

  export function AdminLayout({ children }) {
    const { simState, startSimulation, resetSimulation } = useSimulationState()
    return (
      <SimulationContext.Provider value={{ simEvents: simState.simEvents }}>
        {children}
      </SimulationContext.Provider>
    )
  }
  ```

  **Verify the call site:** If `useSimulationState` is currently called inside `Simulation.jsx` (page level), it must be hoisted to the layout level so the state persists across route changes. Check and adjust before proceeding.

- [ ] **Step 5.4a: Verify `useSimulationState` call site — hoist if needed**

  ```bash
  grep -rn "useSimulationState" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src --include="*.jsx" --include="*.js"
  ```

  If `useSimulationState` is called only inside `Simulation.jsx` (page-level), you must hoist it to the AdminLayout (or equivalent) so `simEvents` persists across route changes. Move the hook call to the layout wrapper before implementing the context provider. If it is already at a layout/root level, proceed directly to adding the Provider.

  In `Lineage.jsx`, consume context:

  ```jsx
  import { useSimulationContext } from '../../context/SimulationContext.jsx'
  // In component: const { simEvents } = useSimulationContext()
  ```

  Support both prop and context (prop takes precedence for testability):

  ```jsx
  export default function Lineage({ simEvents: simEventsProp } = {}) {
    const { simEvents: simEventsCtx } = useSimulationContext()
    const simEvents = simEventsProp ?? simEventsCtx
    // ...
  }
  ```

- [ ] **Step 5.5: Run smoke test — verify it passes**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/admin/pages/__tests__/Lineage.liveEvents.test.jsx 2>&1 | tail -20
  ```
  Expected: 2/2 PASS

- [ ] **Step 5.6: Run full test suite — verify no regressions**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run 2>&1 | tail -30
  ```
  Expected: 0 new failures

- [ ] **Step 5.7: Commit**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM && git add ui/src/lib/lineageFromEvents.js ui/src/admin/pages/Lineage.jsx ui/src/admin/pages/__tests__/Lineage.liveEvents.test.jsx && git commit -m "feat(lineage): replace 100% mock data with live SimulationEvent-derived graph"
  ```

---

## Task 6: Create `alertsFromEvents.js` + Wire Alerts Page

**Files:**
- Create: `ui/src/lib/alertsFromEvents.js`
- Create: `ui/src/lib/__tests__/alertsFromEvents.test.js`
- Modify: `ui/src/admin/pages/Alerts.jsx`

When a simulation produces a `policy.blocked` or `policy.escalated` event, a corresponding alert should appear in the Alerts page immediately (no poll delay). `alertsFromEvents` is a pure transform. `Alerts.jsx` merges the sim-derived alerts with the existing `useFindings` + `useCaseNotifications` live data.

- [ ] **Step 6.1: Write the failing tests**

  ```js
  // ui/src/lib/__tests__/alertsFromEvents.test.js
  import { describe, it, expect } from 'vitest'
  import { alertsFromEvents } from '../alertsFromEvents.js'
  import { EVENT_TYPES } from '../eventSchema.js'

  function ev(event_type, details = {}, ts = '2026-01-01T00:00:00Z') {
    return { id: `${event_type}:x:${ts}`, event_type, stage: 'progress', timestamp: ts, details }
  }

  describe('alertsFromEvents', () => {
    it('returns [] for empty events', () => {
      expect(alertsFromEvents([])).toEqual([])
    })

    it('returns [] for non-alert events', () => {
      const events = [ev(EVENT_TYPES.SESSION_STARTED), ev(EVENT_TYPES.RISK_CALCULATED)]
      expect(alertsFromEvents(events)).toEqual([])
    })

    it('generates alert for policy.blocked', () => {
      const events = [ev(EVENT_TYPES.POLICY_BLOCKED, { reason: 'pii detected', policy_version: 'v2' })]
      const alerts = alertsFromEvents(events)
      expect(alerts).toHaveLength(1)
      expect(alerts[0].severity).toBe('critical')
      expect(alerts[0].type).toBe('policy_blocked')
      expect(alerts[0].title).toMatch(/blocked/i)
    })

    it('generates alert for policy.escalated', () => {
      const events = [ev(EVENT_TYPES.POLICY_ESCALATED, { reason: 'high risk' })]
      const alerts = alertsFromEvents(events)
      expect(alerts).toHaveLength(1)
      expect(alerts[0].severity).toBe('high')
      expect(alerts[0].type).toBe('policy_escalated')
    })

    it('generates alert for tool.approval.required', () => {
      const events = [ev(EVENT_TYPES.TOOL_APPROVAL_REQUIRED, { tool_name: 'sql_query' })]
      const alerts = alertsFromEvents(events)
      expect(alerts).toHaveLength(1)
      expect(alerts[0].severity).toBe('medium')
      expect(alerts[0].detail).toMatch(/sql_query/i)
    })

    it('alert id is stable (derived from event id)', () => {
      const events = [ev(EVENT_TYPES.POLICY_BLOCKED, {})]
      const a1 = alertsFromEvents(events)
      const a2 = alertsFromEvents(events)
      expect(a1[0].id).toBe(a2[0].id)
    })

    it('multiple blocked events produce multiple alerts', () => {
      const events = [
        ev(EVENT_TYPES.POLICY_BLOCKED, {}, '2026-01-01T00:00:01Z'),
        ev(EVENT_TYPES.POLICY_BLOCKED, {}, '2026-01-01T00:00:02Z'),
      ]
      expect(alertsFromEvents(events)).toHaveLength(2)
    })

    it('is pure — same input same output', () => {
      const events = [ev(EVENT_TYPES.POLICY_BLOCKED)]
      expect(alertsFromEvents(events)).toEqual(alertsFromEvents(events))
    })
  })
  ```

- [ ] **Step 6.2: Run tests — verify they fail**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/lib/__tests__/alertsFromEvents.test.js 2>&1 | tail -20
  ```
  Expected: FAIL — module not found

- [ ] **Step 6.3: Implement `alertsFromEvents.js`**

  ```js
  /**
   * lib/alertsFromEvents.js
   * ────────────────────────
   * Pure function: SimulationEvent[] → SimAlert[]
   *
   * Converts simulation policy/tool events into alert objects compatible
   * with the shape used by Alerts.jsx.
   *
   * SimAlert shape
   * ──────────────
   * {
   *   id:        string   — derived from event.id (stable)
   *   type:      string   — 'policy_blocked' | 'policy_escalated' | 'tool_approval'
   *   severity:  string   — 'critical' | 'high' | 'medium'
   *   title:     string
   *   detail:    string
   *   timestamp: string   — ISO-8601
   *   source:    'simulation'
   * }
   */
  import { EVENT_TYPES } from './eventSchema.js'

  const _ALERT_EVENT_TYPES = new Set([
    EVENT_TYPES.POLICY_BLOCKED,
    EVENT_TYPES.POLICY_ESCALATED,
    EVENT_TYPES.TOOL_APPROVAL_REQUIRED,
  ])

  /**
   * @param {import('./eventSchema.js').SimulationEvent[]} events
   * @returns {object[]} SimAlert[]
   */
  export function alertsFromEvents(events) {
    if (!events || events.length === 0) return []

    return events
      .filter(ev => _ALERT_EVENT_TYPES.has(ev.event_type))
      .map(ev => {
        const d = ev.details || {}

        switch (ev.event_type) {
          case EVENT_TYPES.POLICY_BLOCKED:
            return {
              id:        `sim-alert-${ev.id}`,
              type:      'policy_blocked',
              severity:  'critical',
              title:     'Request Blocked by Policy',
              detail:    d.reason || d.policy_version || 'Policy engine terminated the request.',
              timestamp: ev.timestamp,
              source:    'simulation',
            }

          case EVENT_TYPES.POLICY_ESCALATED:
            return {
              id:        `sim-alert-${ev.id}`,
              type:      'policy_escalated',
              severity:  'high',
              title:     'Request Escalated for Review',
              detail:    d.reason || 'Request exceeded escalation threshold — manual approval required.',
              timestamp: ev.timestamp,
              source:    'simulation',
            }

          case EVENT_TYPES.TOOL_APPROVAL_REQUIRED:
            return {
              id:        `sim-alert-${ev.id}`,
              type:      'tool_approval',
              severity:  'medium',
              title:     'Tool Approval Required',
              detail:    `Tool "${d.tool_name || 'unknown'}" requires human approval before execution.`,
              timestamp: ev.timestamp,
              source:    'simulation',
            }

          default:
            return null
        }
      })
      .filter(Boolean)
  }
  ```

- [ ] **Step 6.4: Run tests — verify all pass**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/lib/__tests__/alertsFromEvents.test.js 2>&1 | tail -20
  ```
  Expected: 8/8 PASS

- [ ] **Step 6.5: Wire `Alerts.jsx` to consume simulation alerts**

  First, read `Alerts.jsx` top 100 lines to understand exact shape of existing findings data:

  ```bash
  head -100 /sessions/sweet-zen-johnson/mnt/AISPM/ui/src/admin/pages/Alerts.jsx
  ```

  Then merge sim-derived alerts into the existing findings list. The merge should:
  - Read `simEvents` from `SimulationContext` (created in Task 5)
  - Compute `simAlerts = alertsFromEvents(simEvents)`
  - Prepend `simAlerts` to the rendered alert list (most recent sim alerts first)
  - Show a `source: 'simulation'` badge on sim-derived alerts

  Minimal diff to `Alerts.jsx`:

  ```jsx
  import { alertsFromEvents } from '../../lib/alertsFromEvents.js'
  import { useSimulationContext } from '../../context/SimulationContext.jsx'

  export default function Alerts() {
    const { simEvents } = useSimulationContext()
    const simAlerts     = alertsFromEvents(simEvents)

    // ... existing useFindings, useCaseNotifications hooks ...

    // When rendering the alerts list, prepend simAlerts:
    const allAlerts = [...simAlerts, ...findings]  // findings = existing data

    // Map allAlerts for display, showing 'simulation' badge for source === 'simulation'
  }
  ```

- [ ] **Step 6.5a: Write integration test for merged alerts**

  ```jsx
  // ui/src/admin/pages/__tests__/Alerts.simAlerts.test.jsx
  import { describe, it, expect, vi } from 'vitest'
  import { render, screen } from '@testing-library/react'
  import { MemoryRouter } from 'react-router-dom'
  import { SimulationContext } from '../../../context/SimulationContext.jsx'
  import { EVENT_TYPES } from '../../../lib/eventSchema.js'

  // Mock useFindings to return one finding
  vi.mock('../../../hooks/useFindings', () => ({
    useFindings: () => ({ findings: [{ id: 'f1', title: 'Existing finding', severity: 'medium', timestamp: 'ts' }], loading: false }),
  }))
  vi.mock('../../../hooks/useCaseNotifications', () => ({
    useCaseNotifications: () => ({ notifications: [] }),
  }))

  // Lazy import after mocks
  const { default: Alerts } = await import('../Alerts.jsx')

  function ev(event_type) {
    return { id: `${event_type}:x:ts`, event_type, stage: 'blocked', timestamp: '2026-01-01T00:00:00Z', details: { reason: 'pii detected' } }
  }

  describe('Alerts + simAlerts integration', () => {
    it('shows sim-generated blocked alert alongside existing findings', () => {
      const simEvents = [ev(EVENT_TYPES.POLICY_BLOCKED)]
      render(
        <MemoryRouter>
          <SimulationContext.Provider value={{ simEvents }}>
            <Alerts />
          </SimulationContext.Provider>
        </MemoryRouter>
      )
      expect(screen.getByText(/blocked by policy/i)).toBeInTheDocument()
      expect(screen.getByText(/existing finding/i)).toBeInTheDocument()
    })

    it('shows no sim alerts when no blocked/escalated events', () => {
      const simEvents = [ev(EVENT_TYPES.SESSION_STARTED)]
      render(
        <MemoryRouter>
          <SimulationContext.Provider value={{ simEvents }}>
            <Alerts />
          </SimulationContext.Provider>
        </MemoryRouter>
      )
      // Only the existing finding should appear
      expect(screen.getByText(/existing finding/i)).toBeInTheDocument()
      expect(screen.queryByText(/blocked by policy/i)).toBeNull()
    })
  })
  ```

- [ ] **Step 6.5b: Run integration test — verify it passes**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run src/admin/pages/__tests__/Alerts.simAlerts.test.jsx 2>&1 | tail -20
  ```
  Expected: 2/2 PASS

- [ ] **Step 6.6: Run full test suite — verify no regressions**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run 2>&1 | tail -30
  ```
  Expected: 0 new failures

- [ ] **Step 6.7: Commit**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM && git add ui/src/lib/alertsFromEvents.js ui/src/lib/__tests__/alertsFromEvents.test.js ui/src/admin/pages/Alerts.jsx && git commit -m "feat(alerts): wire sim policy.blocked/escalated events to Alerts page in real time"
  ```

---

## Task 7: Verification

- [ ] **Step 7.1: Run the full test suite — confirm all pass**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM/ui && npx vitest run 2>&1 | tail -40
  ```
  Expected: all tests pass, 0 failures

- [ ] **Step 7.2: Confirm no `toSimulationEvent` inline logic remains**

  ```bash
  grep -r "EVENT_TYPE_STAGE\|let stage\b" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src --include="*.js" --include="*.jsx"
  ```
  Expected: 0 matches (all stage derivation goes through `eventSchema.js`)

- [ ] **Step 7.3: Confirm no hardcoded mock nodes/edges in Lineage**

  ```bash
  grep -n "cx: 65\|cx: 210\|n1.*prompt\|const NODES" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src/admin/pages/Lineage.jsx
  ```
  Expected: 0 matches — static data is gone

- [ ] **Step 7.4: Confirm `normalizeEvent` is the only normalization path**

  ```bash
  grep -r "canonicalise\|_RAW_TO_CANONICAL" /sessions/sweet-zen-johnson/mnt/AISPM/ui/src --include="*.js" --include="*.jsx" | grep -v "sessionResults.js\|eventSchema.js\|__tests__"
  ```
  Expected: 0 matches in product code outside the two canonical files

- [ ] **Step 7.5: Final commit — tag the milestone**

  ```bash
  cd /sessions/sweet-zen-johnson/mnt/AISPM && git tag unified-event-schema-v1 && echo "Tagged."
  ```
