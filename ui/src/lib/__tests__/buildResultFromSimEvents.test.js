import { describe, it, expect } from 'vitest'
import { buildResultFromSimEvents } from '../buildResultFromSimEvents.js'
import { normalizeEvent } from '../eventSchema.js'

// Helper: build a SimulationEvent the same way the live pipeline does
function ws(event_type, payload = {}, ts = '2026-01-01T00:00:00.000Z') {
  return normalizeEvent({ event_type, payload, timestamp: ts, correlation_id: 'test-corr' })
}

const STARTED   = ws('simulation.started',   { prompt: 'test prompt', attack_type: 'custom' }, '2026-01-01T00:00:00.000Z')
const BLOCKED   = ws('simulation.blocked',   { categories: ['prompt_injection'], decision_reason: 'blocked by policy', correlation_id: 'c1' }, '2026-01-01T00:00:01.000Z')
const ALLOWED   = ws('simulation.allowed',   { response_preview: 'ok', correlation_id: 'c2' }, '2026-01-01T00:00:01.000Z')
const COMPLETED_BLOCKED = ws('simulation.completed', { summary: { result: 'blocked', categories: ['prompt_injection'], duration_ms: 120 } }, '2026-01-01T00:00:02.000Z')
const COMPLETED_ALLOWED = ws('simulation.completed', { summary: { result: 'allowed', duration_ms: 80 } }, '2026-01-01T00:00:02.000Z')
const PROGRESS  = ws('simulation.progress',  { message: 'evaluating...' }, '2026-01-01T00:00:00.500Z')

describe('buildResultFromSimEvents', () => {
  it('returns null for empty events array', () => {
    expect(buildResultFromSimEvents([])).toBeNull()
  })

  it('returns null for null/undefined input', () => {
    expect(buildResultFromSimEvents(null)).toBeNull()
    expect(buildResultFromSimEvents(undefined)).toBeNull()
  })

  it('blocked flow: started → blocked → completed → verdict blocked', () => {
    const result = buildResultFromSimEvents([STARTED, BLOCKED, COMPLETED_BLOCKED])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('blocked')
  })

  it('allowed flow: started → allowed → completed → verdict allowed', () => {
    const result = buildResultFromSimEvents([STARTED, ALLOWED, COMPLETED_ALLOWED])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('allowed')
  })

  it('completed-only flow (terminal dropped): uses summary.result as fallback', () => {
    // Simulates WS event loss where blocked/allowed was dropped
    const result = buildResultFromSimEvents([STARTED, COMPLETED_BLOCKED])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('blocked')
  })

  it('blocked result includes policiesTriggered from categories', () => {
    const result = buildResultFromSimEvents([STARTED, BLOCKED, COMPLETED_BLOCKED])
    expect(result.policiesTriggered).toContain('prompt_injection')
  })

  it('executionMs is populated from duration_ms in completed summary', () => {
    const result = buildResultFromSimEvents([STARTED, BLOCKED, COMPLETED_BLOCKED])
    expect(result.executionMs).toBe(120)
  })

  it('decisionTrace contains one entry per event', () => {
    const result = buildResultFromSimEvents([STARTED, BLOCKED, COMPLETED_BLOCKED])
    expect(result.decisionTrace).toHaveLength(3)
  })

  it('no crash when events have missing/malformed payload fields', () => {
    const malformed = normalizeEvent({ event_type: 'simulation.blocked', payload: null, timestamp: 'ts' })
    expect(() => buildResultFromSimEvents([STARTED, malformed])).not.toThrow()
  })

  it('no crash when completed summary is missing', () => {
    const noSummary = normalizeEvent({ event_type: 'simulation.completed', payload: {}, timestamp: '2026-01-01T00:00:02Z' })
    const result = buildResultFromSimEvents([STARTED, BLOCKED, noSummary])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('blocked')
  })

  it('progress events are included in decisionTrace', () => {
    const result = buildResultFromSimEvents([STARTED, PROGRESS, BLOCKED, COMPLETED_BLOCKED])
    expect(result.decisionTrace).toHaveLength(4)
  })

  it('completed summary WINS over a misleading allowed decision event', () => {
    // Garak / race scenario: an `allowed` event can appear before the
    // authoritative `simulation.completed` whose summary.result = "blocked".
    // The builder must trust the completed summary.
    const result = buildResultFromSimEvents([STARTED, ALLOWED, COMPLETED_BLOCKED])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('blocked')
  })

  it('completed summary WINS over a misleading blocked decision event too', () => {
    const result = buildResultFromSimEvents([STARTED, BLOCKED, COMPLETED_ALLOWED])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('allowed')
  })

  it('no completed + only allowed decision → verdict allowed', () => {
    const result = buildResultFromSimEvents([STARTED, ALLOWED])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('allowed')
  })

  it('no completed + only blocked decision → verdict blocked', () => {
    const result = buildResultFromSimEvents([STARTED, BLOCKED])
    expect(result).not.toBeNull()
    expect(result.verdict).toBe('blocked')
  })
})
