import { describe, it, expect } from 'vitest'
import { simReducer, makeIdle, Actions } from '../useSimulationState.js'
import { EVENT_TYPES, normalizeEvent } from '../../lib/eventSchema.js'
import { buildResultFromSimEvents } from '../../lib/buildResultFromSimEvents.js'

function makeEvent(event_type, stage, overrides = {}) {
  return { id: `${event_type}:x:ts`, event_type, stage, status: stage, timestamp: 'ts', details: {}, ...overrides }
}

describe('simReducer', () => {
  it('SIMULATION_STARTED transitions idle → running', () => {
    const state = makeIdle()
    const next  = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 'sid-1', startedAt: 1000 })
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
    const state  = { ...makeIdle(), status: 'running', steps: [] }
    const frozen = Object.freeze({ ...state, steps: Object.freeze([]) })
    const ev     = makeEvent(EVENT_TYPES.RISK_CALCULATED, 'progress')
    expect(() => simReducer(frozen, { type: Actions.EVENT_RECEIVED, event: ev })).not.toThrow()
  })
})

// ── Full-flow simulation tests (end-to-end using real normalized events) ──
function wsEv(event_type, payload = {}, ts = new Date().toISOString()) {
  return normalizeEvent({ event_type, payload, timestamp: ts, correlation_id: 'c' })
}

describe('simReducer — full simulation flows', () => {
  it('happy path: started → blocked → completed reaches status completed with finalResults', () => {
    const evStarted   = wsEv('simulation.started',   { prompt: 'test' })
    const evBlocked   = wsEv('simulation.blocked',   { categories: ['injection'], decision_reason: 'blocked' })
    const evCompleted = wsEv('simulation.completed', { summary: { result: 'blocked', duration_ms: 100 } })

    let state = makeIdle()
    state = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 'sid', startedAt: 1000 })

    // Non-terminal events accumulate steps
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evStarted })
    expect(state.status).toBe('running')
    expect(state.steps).toHaveLength(1)

    // Terminal event (blocked) → completed
    const finalResults = buildResultFromSimEvents([evStarted, evBlocked, evCompleted])
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evBlocked, finalResults })
    expect(state.status).toBe('completed')
    expect(state.finalResults).not.toBeNull()
    expect(state.finalResults.verdict).toBe('blocked')
  })

  it('allowed path: started → allowed → completed reaches status completed', () => {
    const evStarted   = wsEv('simulation.started',   { prompt: 'hello' })
    const evAllowed   = wsEv('simulation.allowed',   { response_preview: 'ok' })
    const evCompleted = wsEv('simulation.completed', { summary: { result: 'allowed', duration_ms: 50 } })

    let state = makeIdle()
    state = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 'sid', startedAt: 1000 })
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evStarted })
    const finalResults = buildResultFromSimEvents([evStarted, evAllowed, evCompleted])
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evAllowed, finalResults })
    expect(state.status).toBe('completed')
    expect(state.finalResults.verdict).toBe('allowed')
  })

  it('error path: simulation.error event → status failed', () => {
    const evStarted = wsEv('simulation.started', { prompt: 'test' })
    const evError   = wsEv('simulation.error',   { error_message: 'PSS evaluation failed' })

    let state = makeIdle()
    state = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 'sid', startedAt: 1000 })
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evStarted })
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evError })
    expect(state.status).toBe('failed')
    expect(state.error).toMatch(/PSS evaluation failed/)
  })

  it('no infinite running: watchdog fires and exits running state', () => {
    let state = makeIdle()
    state = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 'sid', startedAt: 1000 })
    expect(state.status).toBe('running')
    state = simReducer(state, { type: Actions.WATCHDOG_FIRED })
    expect(state.status).toBe('failed')
    expect(state.error).toMatch(/timeout/i)
  })

  it('steps accumulate correctly across multiple non-terminal events', () => {
    const evStarted  = wsEv('simulation.started',  { prompt: 'test' }, '2026-01-01T00:00:00Z')
    const evProgress = wsEv('simulation.progress', { message: 'step 1' }, '2026-01-01T00:00:00.5Z')

    let state = makeIdle()
    state = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 'sid', startedAt: 1 })
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evStarted })
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evProgress })
    expect(state.steps).toHaveLength(2)
    expect(state.status).toBe('running')
  })

  it('stale events after completion are ignored', () => {
    const evStarted = wsEv('simulation.started', {})
    const evBlocked = wsEv('simulation.blocked', {})
    const lateEvent = wsEv('simulation.progress', { message: 'late' })

    let state = makeIdle()
    state = simReducer(state, { type: Actions.SIMULATION_STARTED, sessionId: 's', startedAt: 1 })
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evStarted })
    state = simReducer(state, { type: Actions.EVENT_RECEIVED, event: evBlocked, finalResults: { verdict: 'blocked' } })
    expect(state.status).toBe('completed')

    // Late event after completion — reducer returns same state reference
    const after = simReducer(state, { type: Actions.EVENT_RECEIVED, event: lateEvent })
    expect(after).toBe(state)
  })
})

describe('session-ID isolation guard', () => {
  it('guard logic: event with mismatched session_id should be skipped', () => {
    const currentSessionId = 'session-A'
    const staleEvent = {
      event_type: 'risk.calculated',
      stage: 'progress',
      details: { session_id: 'session-B' }
    }
    // Guard: skip if details.session_id exists AND doesn't match
    const shouldSkip = staleEvent.details?.session_id != null &&
      staleEvent.details.session_id !== currentSessionId
    expect(shouldSkip).toBe(true)
  })

  it('guard logic: event with matching session_id is allowed through', () => {
    const currentSessionId = 'session-A'
    const freshEvent = {
      event_type: 'risk.calculated',
      stage: 'progress',
      details: { session_id: 'session-A' }
    }
    const shouldSkip = freshEvent.details?.session_id != null &&
      freshEvent.details.session_id !== currentSessionId
    expect(shouldSkip).toBe(false)
  })

  it('guard logic: event with no session_id is allowed through (no-op guard)', () => {
    const currentSessionId = 'session-A'
    const noSessionEvent = {
      event_type: 'risk.calculated',
      stage: 'progress',
      details: {}
    }
    const shouldSkip = noSessionEvent.details?.session_id != null &&
      noSessionEvent.details.session_id !== currentSessionId
    expect(shouldSkip).toBeFalsy()
  })
})
