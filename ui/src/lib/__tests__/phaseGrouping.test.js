import { describe, it, expect } from 'vitest'
import { PHASE_MAP, groupByPhase, groupByPhaseAndProbe } from '../phaseGrouping.js'

const makeEvent = (stage, extra = {}) => ({
  id: `${stage}-1`,
  event_type: `simulation.${stage}`,
  stage,
  timestamp: '2024-01-01T00:00:00Z',
  details: {},
  ...extra,
})

describe('PHASE_MAP', () => {
  it('maps known stages to phases', () => {
    expect(PHASE_MAP['started']).toBe('Recon')
    expect(PHASE_MAP['progress']).toBe('Injection')
    expect(PHASE_MAP['blocked']).toBe('Exploitation')
    expect(PHASE_MAP['allowed']).toBe('Exfiltration')
    expect(PHASE_MAP['completed']).toBe('System')
    expect(PHASE_MAP['error']).toBe('System')
  })
})

describe('groupByPhase', () => {
  it('groups events by their phase', () => {
    const events = [
      makeEvent('started'),
      makeEvent('blocked'),
      makeEvent('allowed'),
    ]
    const grouped = groupByPhase(events)
    expect(grouped['Recon']).toHaveLength(1)
    expect(grouped['Exploitation']).toHaveLength(1)
    expect(grouped['Exfiltration']).toHaveLength(1)
  })

  it('groups unknown stages into Other', () => {
    const events = [makeEvent('mystery')]
    const grouped = groupByPhase(events)
    expect(grouped['Other']).toHaveLength(1)
  })

  it('returns empty object for empty events', () => {
    expect(groupByPhase([])).toEqual({})
  })

  it('preserves phase insertion order', () => {
    const events = [makeEvent('started'), makeEvent('blocked'), makeEvent('completed')]
    const phases = Object.keys(groupByPhase(events))
    expect(phases).toEqual(['Recon', 'Exploitation', 'System'])
  })
})

describe('groupByPhaseAndProbe', () => {
  it('groups Garak events by phase → probe', () => {
    const events = [
      makeEvent('progress', { details: { probe_name: 'promptinject' } }),
      makeEvent('progress', { details: { probe_name: 'promptinject' } }),
      makeEvent('progress', { details: { probe_name: 'encoding' } }),
      makeEvent('blocked',  { details: { probe_name: 'promptinject' } }),
    ]
    const grouped = groupByPhaseAndProbe(events)
    expect(grouped['Injection']['promptinject']).toHaveLength(2)
    expect(grouped['Injection']['encoding']).toHaveLength(1)
    expect(grouped['Exploitation']['promptinject']).toHaveLength(1)
  })

  it('uses unknown_probe for events without probe_name', () => {
    const events = [makeEvent('blocked')]
    const grouped = groupByPhaseAndProbe(events)
    expect(grouped['Exploitation']['unknown_probe']).toHaveLength(1)
  })

  it('returns empty object for empty events', () => {
    expect(groupByPhaseAndProbe([])).toEqual({})
  })
})
