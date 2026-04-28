/**
 * hooks/useSimulationState.js
 * ────────────────────────────
 * Unified simulation lifecycle state.
 *
 * Wraps useSimulationStream and exposes a single SimulationState object plus
 * start/reset helpers.  Replaces the scattered running/result/sessionId state
 * that previously lived in Simulation.jsx.
 *
 * SimulationState shape
 * ─────────────────────
 * {
 *   status:         'idle' | 'running' | 'completed' | 'failed'
 *   steps:          SimulationStep[]     — ordered WS events as step objects
 *   partialResults: SimulationEvent[]    — intermediate probe results (Garak)
 *   finalResults:   object | null        — built from buildResultFromSimEvents
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
 *
 * State transitions
 * ─────────────────
 *   idle ──startSimulation()──► running
 *   running ──terminal WS event──► completed
 *   running ──error WS event────► failed
 *   running ──60s first-event watchdog──► failed  ("Simulation timeout")
 *   running ──60s activity watchdog────► failed  ("Simulation timeout")
 *   any ──resetSimulation()──────► idle
 */
import { useReducer, useEffect, useRef, useCallback } from 'react'
import { useSimulationStream } from './useSimulationStream'
import { buildResultFromSimEvents } from '../lib/buildResultFromSimEvents'
import { runSinglePromptSimulation, runGarakSimulation } from '../api/simulationApi'

// ── Constants ─────────────────────────────────────────────────────────────────
// Initial budget from sim start to first backend event.
//
// This MUST exceed the backend's WS-wait + PSS cold-start window plus a
// margin for the server's own hard timeout. Concretely:
//
//   WS_WAIT_TIMEOUT_S (default 10 s)
// + SIM_HARD_TIMEOUT_S (default 45 s, worst case when PSS hangs)
// + small safety buffer for message transit
//
// ≈ 60 s. With the backend hard-timeout emitting `simulation.error` at 45 s
// and the WS pre-connect buffer (added in ws/connection_manager.py) ensuring
// no events are lost during the handshake race, this budget is now
// deterministic: the backend will always produce a terminal event before we
// fire. 30 s was the previous value and could fire on cold Docker stacks
// BEFORE the backend's first event arrived, producing the false
// "Simulation timeout" that caused built-in prompts to look flaky.
const TIMEOUT_MS      = 60_000
// Budget from the LAST received (non-terminal) event to the terminal event.
// Heavy Garak probes (e.g. malwaregen.TopLevel) can take 2+ minutes per probe.
// 180 s gives a 3× safety margin over the 60 s per-probe HTTP timeout so the
// UI watchdog never fires mid-probe on slow-running probes.
const ACTIVITY_TIMEOUT_MS = 180_000

// ── Action types ──────────────────────────────────────────────────────────────
export const Actions = Object.freeze({
  SIMULATION_STARTED: 'SIMULATION_STARTED',
  EVENT_RECEIVED:     'EVENT_RECEIVED',
  WATCHDOG_FIRED:     'WATCHDOG_FIRED',
  API_ERROR:          'API_ERROR',
  SIMULATION_RESET:   'SIMULATION_RESET',
})

// ── Terminal stage set ────────────────────────────────────────────────────────
// Only true LIFECYCLE terminals transition the status out of 'running'.
// `blocked` / `allowed` / `escalated` are DECISION events — they record the
// verdict but the simulation is not finished until the backend emits
// `simulation.completed` (or `simulation.error`). This matters because:
//
//   • Backend always emits  started → blocked|allowed → completed.  If we
//     terminated on blocked/allowed we would discard `simulation.completed`,
//     losing summary fields (duration_ms, probes_run, etc.).
//   • In Garak multi-probe mode the backend emits `simulation.allowed` once
//     per probe.  Treating that as terminal breaks after probe 1.
//   • Decision events can race with completed; relying on the lifecycle
//     terminal removes the timing dependency.
//
// DECISION_STAGES are recorded and extend partialResults but do not flip the
// reducer out of 'running'.
//
// TRACE_STAGES carry per-attempt detail (llm.prompt, llm.response,
// guard.decision, tool.call).  They are accumulated into the trace arrays
// (prompts[], responses[], guardDecisions[], toolCalls[]) but do NOT create
// Timeline steps and do NOT trigger watchdog resets.
//
// terminatedRef.current guards against double-dispatch in useEffect.
// The reducer itself is pure and only sees each terminal event once.
const TERMINAL_STAGES = new Set(['completed', 'error'])
const DECISION_STAGES = new Set(['blocked', 'allowed', 'escalated'])
const TRACE_STAGES    = new Set(['trace'])

// ── Step label helper ─────────────────────────────────────────────────────────
function stepLabel(event) {
  const et = event?.event_type || ''
  if (et === 'simulation.started')   return 'Simulation started'
  if (et === 'simulation.blocked')   return 'Request blocked'
  if (et === 'simulation.allowed')   return 'Request allowed'
  if (et === 'simulation.completed') return 'Simulation complete'
  if (et === 'simulation.error')     return 'Simulation error'
  if (et === 'simulation.progress') {
    const msg = event.details?.message
    return msg ? `Probe: ${msg}` : 'Probe running'
  }
  // Garak trace events — shown in detail view, not in Timeline steps
  if (et === 'llm.prompt')    return `Prompt sent (${event.details?.probe ?? ''})`
  if (et === 'llm.response')  return `Model response (${event.details?.probe ?? ''})`
  if (et === 'guard.decision') return `Guard: ${event.details?.decision ?? ''} (${event.details?.probe ?? ''})`
  if (et === 'guard.input')    return `Guard input (${event.details?.probe ?? ''})`
  if (et === 'tool.call')     return `Tool call: ${event.details?.tool ?? ''}`
  // Generic: capitalise dot-namespaced type (e.g. "policy.decision" → "Policy Decision")
  return et.split('.').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') || 'Event'
}

// ── Initial state factory ─────────────────────────────────────────────────────
export function makeIdle() {
  return {
    status:         'idle',
    steps:          [],
    partialResults: [],
    finalResults:   null,
    error:          undefined,
    startedAt:      undefined,
    completedAt:    undefined,
    sessionId:      null,
    // ── Garak execution trace ─────────────────────────────────────────────
    // One entry per llm.prompt / llm.response / guard.decision / tool.call
    // event received during a Garak scan.  Each array is ordered by arrival
    // time and keyed by correlation_id so the detail view can group by probe.
    prompts:        [],   // { probe, prompt, attempt_index, correlation_id, timestamp }
    responses:      [],   // { probe, response, passed, attempt_index, correlation_id, timestamp }
    guardDecisions: [],   // { probe, decision, reason, score, correlation_id, timestamp }
    toolCalls:      [],   // { tool, args, correlation_id, timestamp }
    guardInputs:    [],   // { probe, raw_prompt, correlation_id, timestamp }
  }
}

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
      const isDecision = DECISION_STAGES.has(event.stage)
      const isTrace    = TRACE_STAGES.has(event.stage)

      // ── Garak execution trace events ───────────────────────────────────────
      // These carry per-attempt detail and are accumulated into the trace arrays.
      // They do NOT create Timeline steps and do NOT trigger lifecycle transitions.
      if (isTrace) {
        const ts = event.timestamp
        const d  = event.details ?? {}
        switch (event.event_type) {
          case 'llm.prompt':
            return {
              ...state,
              prompts: [...state.prompts, {
                probe:          d.probe           ?? '',
                prompt:         d.prompt          ?? '',
                attempt_index:  d.attempt_index   ?? 0,
                correlation_id: d.correlation_id  ?? event.correlation_id ?? '',
                timestamp:      ts,
              }],
            }
          case 'llm.response':
            return {
              ...state,
              responses: [...state.responses, {
                probe:          d.probe           ?? '',
                response:       d.response        ?? '',
                passed:         d.passed          ?? true,
                attempt_index:  d.attempt_index   ?? 0,
                correlation_id: d.correlation_id  ?? event.correlation_id ?? '',
                timestamp:      ts,
              }],
            }
          case 'guard.decision':
            return {
              ...state,
              guardDecisions: [...state.guardDecisions, {
                probe:          d.probe           ?? '',
                decision:       d.decision        ?? 'allow',
                reason:         d.reason          ?? '',
                score:          d.score           ?? 0,
                correlation_id: d.correlation_id  ?? event.correlation_id ?? '',
                timestamp:      ts,
              }],
            }
          case 'tool.call':
            return {
              ...state,
              toolCalls: [...state.toolCalls, {
                tool:           d.tool            ?? '',
                args:           d.args            ?? {},
                correlation_id: d.correlation_id  ?? event.correlation_id ?? '',
                timestamp:      ts,
              }],
            }
          case 'guard.input':
            return {
              ...state,
              guardInputs: [...state.guardInputs, {
                probe:          d.probe           ?? '',
                raw_prompt:     d.raw_prompt      ?? '',
                correlation_id: d.correlation_id  ?? event.correlation_id ?? '',
                timestamp:      ts,
              }],
            }
          default:
            return state
        }
      }

      const newStep = {
        id:        event.id,
        label:     stepLabel(event),
        // 'done' once we know it's a finished step, otherwise 'running'
        status:    isTerminal ? (isFailed ? 'failed' : 'done')
                              : (isDecision ? 'done' : 'running'),
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
        // Decision events (blocked / allowed / escalated) are also recorded
        // as partial results so the UI can show "decision reached" live while
        // we wait for the lifecycle terminal (`simulation.completed`).
        partialResults: isDecision
          ? [...state.partialResults, event]
          : state.partialResults,
      }
    }

    case Actions.WATCHDOG_FIRED:
      return {
        ...state,
        status:       'failed',
        error:        'Simulation timeout — no terminal event received from the backend.',
        // Show partial results (Policy Impact, Output) even on timeout.
        finalResults: action.finalResults ?? state.finalResults ?? null,
        completedAt:  Date.now(),
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

// ── Hook ──────────────────────────────────────────────────────────────────────
export function useSimulationState() {
  const { connectionStatus, simEvents, startStream, stopStream, loadEvents } =
    useSimulationStream()

  const [simState, dispatch] = useReducer(simReducer, makeIdle())

  // Watchdog timer ref — cleared on terminal event or reset
  const watchdogRef    = useRef(null)
  // Prevent double-processing the same terminal event across renders
  const terminatedRef  = useRef(false)
  // Always-current copy of simEvents so watchdog closures can read latest events
  const simEventsRef   = useRef([])

  // ── Clear watchdog helper ────────────────────────────────────────────────
  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current)
      watchdogRef.current = null
    }
  }, [])

  // Track which simEvents we have already dispatched to the reducer so we can
  // process EACH event exactly once, even when multiple new events arrive in
  // the same render cycle (the previous `latest-only` implementation silently
  // skipped anything that wasn't at the tail after the timestamp sort).
  const dispatchedRef = useRef(new Set())

  // ── React to incoming simEvents ──────────────────────────────────────────
  useEffect(() => {
    // Keep the always-current ref in sync so watchdog closures can call
    // buildResultFromSimEvents on the LATEST events, not a stale closure copy.
    simEventsRef.current = simEvents

    if (simEvents.length === 0) {
      // simEvents was cleared (fresh simulation / reset) — clear the dispatch
      // log too so the next run starts from scratch.
      dispatchedRef.current = new Set()
      return
    }

    // Process every NEW event in timestamp order so the reducer sees the
    // true sequence and terminal detection is deterministic.
    for (const ev of simEvents) {
      if (dispatchedRef.current.has(ev.id)) continue

      // ── Session-ID isolation ────────────────────────────────────────────
      // The backend puts session_id at the top level of every WS frame;
      // `normalizeEvent` now preserves it as `ev.session_id` (and we still
      // tolerate older events that carried it in payload as details.session_id).
      // If a session_id is present AND doesn't match the active one, it's a
      // leftover from a previous run — drop it.
      const eventSessionId = ev.session_id ?? ev.details?.session_id
      if (
        eventSessionId != null &&
        simState.sessionId &&
        eventSessionId !== simState.sessionId
      ) {
        console.warn('[PIPELINE] state: dropped stale event from session=', eventSessionId)
        dispatchedRef.current.add(ev.id)
        continue
      }

      dispatchedRef.current.add(ev.id)

      // ── [TRACE] debug logging for per-attempt execution trace events ──────
      if (TRACE_STAGES.has(ev.stage)) {
        console.log('[TRACE]', ev.event_type, ev.details)
        dispatch({ type: Actions.EVENT_RECEIVED, event: ev })
        continue
      }

      console.log(
        '[PIPELINE] state: event received stage=', ev.stage,
        'type=', ev.event_type,
        'steps_before=', simState.steps.length
      )

      if (TERMINAL_STAGES.has(ev.stage)) {
        // True lifecycle terminal — completed / error.
        if (terminatedRef.current) continue
        terminatedRef.current = true
        clearWatchdog()

        console.log('[PIPELINE] state: terminal event stage=', ev.stage)

        // Build the final result from the ENTIRE event history (includes any
        // prior blocked/allowed decision events so verdict is correct).
        const built = buildResultFromSimEvents(simEvents)
        dispatch({ type: Actions.EVENT_RECEIVED, event: ev, finalResults: built })
        continue
      }

      // Non-terminal (incl. decision events) — backend is alive, reset the
      // activity watchdog so the 180 s idle budget runs from this event.
      clearWatchdog()
      watchdogRef.current = setTimeout(() => {
        if (terminatedRef.current) return
        terminatedRef.current = true
        console.warn('[PIPELINE] state: activity watchdog fired timeout_ms=', ACTIVITY_TIMEOUT_MS)
        // Build result from whatever partial events arrived — so Policy Impact
        // and Output tabs show data even when the simulation timed out.
        const builtOnTimeout = buildResultFromSimEvents(simEventsRef.current)
        dispatch({ type: Actions.WATCHDOG_FIRED, finalResults: builtOnTimeout })
      }, ACTIVITY_TIMEOUT_MS)
      dispatch({ type: Actions.EVENT_RECEIVED, event: ev })
    }
  }, [simEvents, simState.sessionId, clearWatchdog])

  // ── Start simulation ─────────────────────────────────────────────────────
  const startSimulation = useCallback(async (config) => {
    // crypto.randomUUID() requires a secure context (HTTPS). Fall back to a
    // Math.random UUID for http://aispm.local dev environments.
    const sid = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
          const r = Math.random() * 16 | 0
          return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16)
        })
    terminatedRef.current = false
    dispatchedRef.current = new Set()

    console.log('[PIPELINE] state: simulation started session=', sid, 'type=', config.attackType)

    // Transition to running state and reset everything
    dispatch({ type: Actions.SIMULATION_STARTED, sessionId: sid, startedAt: Date.now() })

    // Connect WS before POST so no events are missed
    startStream(sid)

    // Watchdog: auto-fail after TIMEOUT_MS if no terminal event arrives
    clearWatchdog()
    watchdogRef.current = setTimeout(() => {
      if (terminatedRef.current) return
      terminatedRef.current = true
      console.warn('[PIPELINE] state: watchdog fired timeout_ms=', TIMEOUT_MS)
      const builtOnTimeout = buildResultFromSimEvents(simEventsRef.current)
      dispatch({ type: Actions.WATCHDOG_FIRED, finalResults: builtOnTimeout })
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
      console.log('[PIPELINE] state: POST returned background_task_started')
    } catch (err) {
      console.error('[PIPELINE] state: API call failed:', err.message)
      clearWatchdog()
      terminatedRef.current = true
      dispatch({ type: Actions.API_ERROR, error: err.message })
    }

    return sid
  }, [startStream, clearWatchdog])

  // ── Reset simulation ─────────────────────────────────────────────────────
  const resetSimulation = useCallback(() => {
    console.log('[PIPELINE] state: reset')
    clearWatchdog()
    terminatedRef.current = false
    dispatchedRef.current = new Set()
    stopStream()
    dispatch({ type: Actions.SIMULATION_RESET })
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
    // Low-level WS subscription — opens /ws/sessions/{sessionId} and starts
    // collecting session events into `simEvents` WITHOUT going through the
    // simulation API.  Used by the Chat page so chat-originated sessions
    // populate the shared event stream (and thus the Lineage graph).
    subscribeToSession: startStream,
    unsubscribeFromSession: stopStream,
    // Hydrate simEvents from a prior session (localStorage or explicit array)
    // WITHOUT opening a WebSocket. Used by Lineage session picker for backfill.
    loadSessionEvents: loadEvents,
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Add a step, replacing any existing entry with the same id (idempotent). */
function addOrReplaceStep(steps, newStep) {
  const idx = steps.findIndex(s => s.id === newStep.id)
  if (idx === -1) return [...steps, newStep]
  const next = [...steps]
  next[idx] = newStep
  return next
}
