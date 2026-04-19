import { describe, it, expect } from 'vitest'
import { canonicalise, CANONICAL_EVENT_TYPES } from '../sessionResults.js'

const C = CANONICAL_EVENT_TYPES

describe('canonicalise — simulation.* backend events', () => {
  it('simulation.started → SESSION_STARTED', () => {
    expect(canonicalise({ event_type: 'simulation.started' })).toBe(C.SESSION_STARTED)
  })
  it('simulation.blocked → SESSION_BLOCKED', () => {
    expect(canonicalise({ event_type: 'simulation.blocked' })).toBe(C.SESSION_BLOCKED)
  })
  it('simulation.allowed → POLICY_ALLOWED', () => {
    expect(canonicalise({ event_type: 'simulation.allowed' })).toBe(C.POLICY_ALLOWED)
  })
  it('simulation.completed → SESSION_COMPLETED', () => {
    expect(canonicalise({ event_type: 'simulation.completed' })).toBe(C.SESSION_COMPLETED)
  })
  it('simulation.error → SESSION_FAILED', () => {
    expect(canonicalise({ event_type: 'simulation.error' })).toBe(C.SESSION_FAILED)
  })
  it('simulation.progress → falls through as-is (no canonical)', () => {
    // No canonical equivalent — returns raw string unchanged, stage='progress'
    expect(canonicalise({ event_type: 'simulation.progress' })).toBe('simulation.progress')
  })
})
