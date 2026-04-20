// ui/src/simulation/simulationStore.ts   (v2.2 — final hardening)
// ────────────────────────────────────────────────────────────────
// Single source of truth for the Simulation Lab UI.
//
// v2.2 changes over v2.1
// ──────────────────────
//   * `arrivalById` + `arrivalCounter` added.  Every reducer pass
//     stamps the attempt with a monotonic arrival index — used as
//     the tie-breaker when multiple attempts share (or lack) an
//     envelope sequence.
//   * `attemptSequenceById: Record<string, number | null>` added.
//     Since `sequence` is an envelope concern (never on Attempt),
//     we record the envelope.sequence at ingest time.  Selectors
//     use this to sort deterministically by (sequence asc, arrival asc).
//   * Probe counts FREEZE on `simulation.probe_completed.completed === true`.
//     After that, any late attempt for that probe is ingested into the
//     global attempt store but does NOT mutate per-probe totals.
//   * Warnings carry arrival index for stable ordering in the side panel.
//
// The load-bearing invariants (from the hardening spec)
// ──────────────────────────────────────────────────────
//   1.  Attempt is the ONLY source of truth.
//   2.  STRICT dedup by attempt_id — never overwrite.
//   3.  Stable ordering — (envelope.sequence asc, arrival asc).
//   4.  No fragment event handling anywhere in this file.
//   5.  Probe freeze after probe_completed.

import { create } from 'zustand'
import type {
  Attempt,
  AttemptPhase,
  SimulationEvent,
  SimulationSummary,
} from './types'
import { isTerminal } from './types'

// ── Public state shape ─────────────────────────────────────────────────────

export type SimulationStatus =
  | 'idle'
  | 'connecting'
  | 'running'
  | 'completed'
  | 'failed'

export interface SessionInfo {
  session_id:     string
  profile:        string
  execution_mode: string
  max_attempts:   number
  probes:         string[]
}

export interface ProbeRunState {
  probe:              string
  probe_raw:          string
  category:           string
  phase:              AttemptPhase
  index:              number
  total:              number
  started_at:         string
  ended_at:           string | null
  probe_duration_ms:  number | null
  attempt_count:      number
  blocked_count:      number
  allowed_count:      number
  error_count:        number
  /** Authoritative "probe lifecycle closed" from the backend.  After this
   *  is true, per-attempt counter increments STOP.  */
  completed:          boolean
}

export interface WarningEntry {
  /** Envelope sequence.  null for out-of-band transport frames. */
  sequence:  number | null
  /** Monotonic arrival index — stable fallback for sort. */
  arrival:   number
  code:      string
  message:   string
  detail?:   Record<string, unknown>
  timestamp: string
}

export interface SimulationStoreState {
  status:          SimulationStatus
  session:         SessionInfo | null
  startedAt:       number | null   // ms since epoch
  completedAt:     number | null
  error:           string | null

  // ── Canonical attempt store ──────────────────────────────────────────────
  attemptsById:          Record<string, Attempt>
  attemptOrder:          string[]
  /** Monotonic arrival index per attempt_id.  Used as the tie-breaker
   *  when envelope sequence is null or repeated.  */
  arrivalById:           Record<string, number>
  /** Envelope sequence per attempt_id.  May be null for out-of-band frames
   *  (shouldn't happen for attempts, but we defend). */
  attemptSequenceById:   Record<string, number | null>

  /** Global monotonic counter — incremented on every reducer pass that
   *  accepts a new item (attempt or warning).  */
  arrivalCounter:        number

  // Probe lifecycle (for Probe Results / Timeline headings).
  probeRunState:         Record<string, ProbeRunState>
  activeProbe:           string | null

  // Terminal summary as provided by the backend.
  summary:               SimulationSummary | null

  // Non-fatal issues surfaced in a persistent side panel.
  warnings:              WarningEntry[]
}

// ── Action surface ─────────────────────────────────────────────────────────

export interface BeginSessionArgs {
  session_id: string
  /** If true AND the current session matches, preserve the attempt map. */
  inherit?: boolean
}

export interface SimulationStoreActions {
  /** Start or resume a session. */
  beginSession(args: BeginSessionArgs): void
  /** Ingest exactly one event.  Pure; safe to call from any subscription. */
  ingest(event: SimulationEvent): void
  /** Ingest a batch.  Order-preserving — relies on reducer + arrival stamp
   *  to keep things deterministic. */
  ingestMany(events: SimulationEvent[]): void
  /** Reset to idle (e.g. user clicks "Run again"). */
  reset(): void
}

type FullState = SimulationStoreState & SimulationStoreActions

// ── Initial state ──────────────────────────────────────────────────────────

const initialState: SimulationStoreState = {
  status:              'idle',
  session:             null,
  startedAt:           null,
  completedAt:         null,
  error:               null,
  attemptsById:        {},
  attemptOrder:        [],
  arrivalById:         {},
  attemptSequenceById: {},
  arrivalCounter:      0,
  probeRunState:       {},
  activeProbe:         null,
  summary:             null,
  warnings:            [],
}

// ── Store ───────────────────────────────────────────────────────────────────

export const useSimulationStore = create<FullState>((set, get) => ({
  ...initialState,

  beginSession({ session_id, inherit = false }) {
    const prev = get()
    const sameSession = inherit && prev.session?.session_id === session_id
    if (sameSession) {
      // Reconnect path — keep attempts/warnings, clear only terminal flags.
      set({
        ...prev,
        status:      'connecting',
        error:       null,
        completedAt: null,
      })
      return
    }
    set({
      ...initialState,
      status: 'connecting',
      session: {
        session_id,
        profile:        'default',
        execution_mode: 'live',
        max_attempts:   0,
        probes:         [],
      },
      startedAt: Date.now(),
    })
  },

  ingest(event) {
    const state = get()
    if (!state.session) return
    if (event.session_id !== state.session.session_id) {
      // Stale event from a previous run — drop silently.
      return
    }
    set(reduce(state, event))
  },

  ingestMany(events) {
    // Sort numeric sequences ascending; nulls go last (preserving input
    // order among nulls).  `Array.prototype.sort` is stable in V8 / Safari
    // so null ties are receive-order.
    const ordered = [...events].sort((a, b) => {
      const sa = a.sequence
      const sb = b.sequence
      if (sa === null && sb === null) return 0
      if (sa === null) return 1
      if (sb === null) return -1
      return sa - sb
    })
    let state = get()
    if (!state.session) return
    for (const ev of ordered) {
      if (ev.session_id !== state.session.session_id) continue
      state = reduce(state, ev)
    }
    set(state)
  },

  reset() {
    set({ ...initialState })
  },
}))

// ── Pure reducer ────────────────────────────────────────────────────────────

function reduce(state: SimulationStoreState, ev: SimulationEvent): SimulationStoreState {
  switch (ev.type) {
    case 'simulation.started': {
      return {
        ...state,
        status: 'running',
        session: state.session
          ? { ...state.session, ...ev.data }
          : { session_id: ev.session_id, ...ev.data },
        startedAt: state.startedAt ?? Date.now(),
      }
    }

    case 'simulation.probe_started': {
      const { probe, probe_raw, category, phase, index, total } = ev.data
      const existing = state.probeRunState[probe]
      if (existing) {
        // Reconnect / duplicate — do not reset counts.
        return { ...state, activeProbe: probe }
      }
      return {
        ...state,
        activeProbe: probe,
        probeRunState: {
          ...state.probeRunState,
          [probe]: {
            probe, probe_raw, category, phase, index, total,
            started_at:        ev.timestamp,
            ended_at:          null,
            probe_duration_ms: null,
            attempt_count:     0,
            blocked_count:     0,
            allowed_count:     0,
            error_count:       0,
            completed:         false,
          },
        },
      }
    }

    case 'simulation.probe_completed': {
      const d = ev.data
      const existing = state.probeRunState[d.probe]
      // Backend counts are authoritative at probe_completed time.  Bootstrap
      // if we never saw probe_started (e.g. mid-run reconnect).
      const next: ProbeRunState = {
        probe:             d.probe,
        probe_raw:         d.probe_raw,
        category:          d.category,
        phase:             d.phase,
        index:             d.index,
        total:             d.total,
        started_at:        existing?.started_at ?? ev.timestamp,
        ended_at:          ev.timestamp,
        probe_duration_ms: d.probe_duration_ms,
        attempt_count:     d.attempt_count,
        blocked_count:     d.blocked_count,
        allowed_count:     d.allowed_count,
        error_count:       d.error_count,
        // Honor the backend's authoritative "completed" signal.  If it's
        // somehow absent default to true (we're in probe_completed, after all).
        completed:         d.completed ?? true,
      }
      return {
        ...state,
        activeProbe: state.activeProbe === d.probe ? null : state.activeProbe,
        probeRunState: { ...state.probeRunState, [d.probe]: next },
      }
    }

    case 'simulation.attempt': {
      const a = ev.data
      // STRICT dedup: never overwrite an existing attempt.
      if (state.attemptsById[a.attempt_id]) return state

      const arrival = state.arrivalCounter + 1
      const prs = state.probeRunState[a.probe]
      // Only bump per-probe counters when the probe is NOT frozen.  After
      // probe_completed, counts come from the authoritative backend signal.
      const nextPrs: ProbeRunState | undefined = prs && !prs.completed
        ? {
            ...prs,
            attempt_count: prs.attempt_count + 1,
            blocked_count: prs.blocked_count + (a.result === 'blocked' ? 1 : 0),
            allowed_count: prs.allowed_count + (a.result === 'allowed' ? 1 : 0),
            error_count:   prs.error_count   + (a.result === 'error'   ? 1 : 0),
          }
        : prs
      return {
        ...state,
        arrivalCounter:      arrival,
        attemptsById:        { ...state.attemptsById, [a.attempt_id]: a },
        attemptOrder:        [...state.attemptOrder, a.attempt_id],
        arrivalById:         { ...state.arrivalById, [a.attempt_id]: arrival },
        attemptSequenceById: { ...state.attemptSequenceById, [a.attempt_id]: ev.sequence },
        probeRunState: nextPrs
          ? { ...state.probeRunState, [a.probe]: nextPrs }
          : state.probeRunState,
      }
    }

    case 'simulation.summary': {
      return { ...state, summary: ev.data }
    }

    case 'simulation.completed': {
      return {
        ...state,
        status:      'completed',
        summary:     ev.data.summary,
        completedAt: Date.now(),
        activeProbe: null,
      }
    }

    case 'simulation.warning': {
      const arrival = state.arrivalCounter + 1
      return {
        ...state,
        arrivalCounter: arrival,
        warnings: [...state.warnings, {
          sequence:  ev.sequence,
          arrival,
          code:      ev.data.code,
          message:   ev.data.message,
          detail:    ev.data.detail,
          timestamp: ev.timestamp,
        }],
      }
    }

    case 'simulation.error': {
      return {
        ...state,
        status:      'failed',
        error:       ev.data.error_message,
        completedAt: Date.now(),
        activeProbe: null,
      }
    }

    default: {
      // Exhaustiveness guard.  Record unknown event types as warnings
      // so regressions surface loudly instead of silently dropping.
      const unknown = ev as { type?: string; sequence?: number | null; timestamp?: string }
      const arrival = state.arrivalCounter + 1
      return {
        ...state,
        arrivalCounter: arrival,
        warnings: [...state.warnings, {
          sequence:  unknown.sequence ?? null,
          arrival,
          code:      'UNKNOWN_EVENT_TYPE',
          message:   `Unknown event type received: ${unknown.type ?? '<none>'}`,
          detail:    { event: ev },
          timestamp: unknown.timestamp ?? new Date().toISOString(),
        }],
      }
    }
  }
}

// ── WebSocket connector ────────────────────────────────────────────────────

/**
 * Open a WS connection and pipe every frame into the store.
 *
 * Returns a close function.  Heartbeat `ping` frames are silently
 * filtered.  Anything else that starts with `simulation.` reaches the
 * reducer — unknown subtypes surface in warnings.
 */
export function connectSimulationWs(sessionId: string, baseUrl: string): () => void {
  const url = baseUrl.replace(/^http/, 'ws') + `/ws/simulation/${sessionId}`
  const ws  = new WebSocket(url)
  let closed = false

  ws.onmessage = (msg) => {
    try {
      const frame = JSON.parse(msg.data)
      if (!frame || typeof frame !== 'object') return
      if (frame.type === 'ping') return
      if (!isSimulationEvent(frame)) return
      useSimulationStore.getState().ingest(frame)
      if (isTerminal(frame)) {
        closed = true
        ws.close()
      }
    } catch (err) {
      console.error('[simulation.ws] parse error', err)
    }
  }

  ws.onerror = () => {
    if (!closed) {
      useSimulationStore.setState({ status: 'failed', error: 'WebSocket error' })
    }
  }

  ws.onclose = () => {
    closed = true
  }

  return () => {
    closed = true
    try { ws.close() } catch { /* ignore */ }
  }
}

function isSimulationEvent(x: unknown): x is SimulationEvent {
  if (!x || typeof x !== 'object') return false
  const obj = x as { type?: unknown; session_id?: unknown; data?: unknown }
  return (
    typeof obj.type === 'string' &&
    obj.type.startsWith('simulation.') &&
    typeof obj.session_id === 'string' &&
    typeof obj.data === 'object' &&
    obj.data !== null
  )
}
