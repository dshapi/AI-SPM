import { describe, it, expect } from 'vitest'
import { simReducer, makeIdle, Actions } from '../useSimulationState.js'
import { EVENT_TYPES } from '../../lib/eventSchema.js'

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
