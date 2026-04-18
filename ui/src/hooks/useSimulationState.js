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
import { useState, useEffect, useRef, useCallback } from 'react'
import { useSimulationStream } from './useSimulationStream'
import { buildResultFromSimEvents } from '../lib/buildResultFromSimEvents'
import { runSinglePromptSimulation, runGarakSimulation } from '../api/simulationApi'

// ── Constants ─────────────────────────────────────────────────────────────────
const TIMEOUT_MS      = 30_000
const TERMINAL_STAGES = new Set(['completed', 'error', 'blocked', 'allowed'])

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

    // Build step object for this event
    const newStep = {
      id:        latest.id,
      label:     stepLabel(latest),
      status:    TERMINAL_STAGES.has(latest.stage) ? 'done' : 'running',
      timestamp: latest.timestamp ? new Date(latest.timestamp).getTime() : Date.now(),
    }

    console.log('[SimState] event received', latest.event_type, 'stage:', latest.stage)

    // ── Terminal event ────────────────────────────────────────────────────
    if (TERMINAL_STAGES.has(latest.stage) && !terminatedRef.current) {
      terminatedRef.current = true
      clearWatchdog()

      const built    = buildResultFromSimEvents(simEvents)
      const isFailed = latest.stage === 'error'
      const errMsg   = isFailed
        ? (latest.details?.error_message || 'Simulation failed')
        : undefined

      console.log('[SimState] terminal event', latest.stage, '— built result:', !!built)

      setSimState(prev => ({
        ...prev,
        status:       isFailed ? 'failed' : 'completed',
        steps:        addOrReplaceStep(prev.steps, { ...newStep, status: isFailed ? 'failed' : 'done' }),
        finalResults: built,
        error:        errMsg,
        completedAt:  Date.now(),
      }))
      return
    }

    // ── Non-terminal: accumulate step + partial results ───────────────────
    // Per-probe allowed/blocked events during Garak are partial results
    const isProbeResult = latest.stage === 'allowed' || latest.stage === 'blocked'

    console.log('[SimState] step added:', newStep.label)

    setSimState(prev => {
      if (prev.status !== 'running') return prev   // stale event after completion
      return {
        ...prev,
        steps:          addOrReplaceStep(prev.steps, newStep),
        partialResults: isProbeResult
          ? [...prev.partialResults, latest]
          : prev.partialResults,
      }
    })
  }, [simEvents, clearWatchdog])

  // ── Start simulation ─────────────────────────────────────────────────────
  const startSimulation = useCallback(async (config) => {
    const sid = crypto.randomUUID()
    terminatedRef.current = false

    console.log('[SimState] simulation started | session:', sid, '| type:', config.attackType)

    // Transition to running state and reset everything
    setSimState({
      ...makeIdle(),
      status:    'running',
      sessionId: sid,
      startedAt: Date.now(),
    })

    // Connect WS before POST so no events are missed
    startStream(sid)

    // Watchdog: auto-fail after TIMEOUT_MS if no terminal event arrives
    clearWatchdog()
    watchdogRef.current = setTimeout(() => {
      if (terminatedRef.current) return
      terminatedRef.current = true
      console.warn('[SimState] watchdog fired — no terminal event after', TIMEOUT_MS, 'ms')
      setSimState(prev => ({
        ...prev,
        status:      'failed',
        error:       'Simulation timeout — no response received within 30 seconds.',
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
      console.log('[SimState] POST returned — background task started')
    } catch (err) {
      console.error('[SimState] API call failed:', err.message)
      clearWatchdog()
      terminatedRef.current = true
      setSimState(prev => ({
        ...prev,
        status:      'failed',
        error:       err.message || 'Failed to start simulation',
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

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Add a step, replacing any existing entry with the same id (idempotent). */
function addOrReplaceStep(steps, newStep) {
  const idx = steps.findIndex(s => s.id === newStep.id)
  if (idx === -1) return [...steps, newStep]
  const next = [...steps]
  next[idx] = newStep
  return next
}
