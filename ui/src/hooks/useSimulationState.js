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
 *   running ──30s watchdog──────► failed  ("Simulation timeout")
 *   any ──resetSimulation()──────► idle
 */
import { useReducer, useEffect, useRef, useCallback } from 'react'
import { useSimulationStream } from './useSimulationStream'
import { buildResultFromSimEvents } from '../lib/buildResultFromSimEvents'
import { runSinglePromptSimulation, runGarakSimulation } from '../api/simulationApi'

// ── Constants ─────────────────────────────────────────────────────────────────
const TIMEOUT_MS      = 30_000

// ── Action types ──────────────────────────────────────────────────────────────
export const Actions = Object.freeze({
  SIMULATION_STARTED: 'SIMULATION_STARTED',
  EVENT_RECEIVED:     'EVENT_RECEIVED',
  WATCHDOG_FIRED:     'WATCHDOG_FIRED',
  API_ERROR:          'API_ERROR',
  SIMULATION_RESET:   'SIMULATION_RESET',
})

// ── Terminal stage set ────────────────────────────────────────────────────────
// terminatedRef.current guards against double-dispatch in useEffect.
// The reducer itself is pure and only sees each terminal event once.
const TERMINAL_STAGES = new Set(['completed', 'blocked', 'allowed', 'escalated', 'error'])

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

// ── Hook ──────────────────────────────────────────────────────────────────────
export function useSimulationState() {
  const { connectionStatus, simEvents, startStream, stopStream } =
    useSimulationStream()

  const [simState, dispatch] = useReducer(simReducer, makeIdle())

  // Watchdog timer ref — cleared on terminal event or reset
  const watchdogRef    = useRef(null)
  // Prevent double-processing the same terminal event across renders
  const terminatedRef  = useRef(false)

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

    // ── Session-ID isolation ──────────────────────────────────────────────
    // If the event carries a session_id (from its payload/details) that doesn't
    // match the current session, it's a stale event from a previous run — drop it.
    // Note: backend currently does not include session_id in event payload, so
    // this guard is a no-op for current events. It future-proofs the system.
    const eventSessionId = latest.details?.session_id
    if (eventSessionId != null && simState.sessionId && eventSessionId !== simState.sessionId) {
      console.warn('[PIPELINE] state: dropped stale event from session=', eventSessionId)
      return
    }
    // ─────────────────────────────────────────────────────────────────────

    console.log('[PIPELINE] state: event received stage=', latest.stage, 'steps_before=', simState.steps.length)

    if (!TERMINAL_STAGES.has(latest.stage)) {
      dispatch({ type: Actions.EVENT_RECEIVED, event: latest })
      return
    }

    // Terminal event — guard against double-processing
    if (terminatedRef.current) return
    terminatedRef.current = true
    clearWatchdog()

    console.log('[PIPELINE] state: terminal event stage=', latest.stage)

    const built = buildResultFromSimEvents(simEvents)
    dispatch({ type: Actions.EVENT_RECEIVED, event: latest, finalResults: built })
  }, [simEvents, simState.sessionId, clearWatchdog])

  // ── Start simulation ─────────────────────────────────────────────────────
  const startSimulation = useCallback(async (config) => {
    const sid = crypto.randomUUID()
    terminatedRef.current = false

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
      dispatch({ type: Actions.WATCHDOG_FIRED })
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
