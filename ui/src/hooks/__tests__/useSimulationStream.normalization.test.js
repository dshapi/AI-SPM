import { describe, it, expect } from 'vitest'
import { toSimulationEvent } from '../useSimulationStream.js'

describe('toSimulationEvent (delegates to normalizeEvent)', () => {
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
