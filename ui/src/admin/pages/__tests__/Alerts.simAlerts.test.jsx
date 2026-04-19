import { describe, it, expect } from 'vitest'
import { alertsFromEvents } from '../../../lib/alertsFromEvents.js'
import { EVENT_TYPES } from '../../../lib/eventSchema.js'

/**
 * Integration test: verify that sim alerts can be merged with findings
 * in the Alerts component data flow.
 */

function simEv(event_type, details = {}) {
  return {
    id: `${event_type}:x:2026-01-01T00:00:00Z`,
    event_type,
    stage: 'blocked',
    timestamp: '2026-01-01T00:00:00Z',
    details,
  }
}

function mockFinding() {
  return {
    id: 'f1',
    title: 'Existing finding',
    severity: 'Medium',
    timestamp: '2026-01-01T00:00:00Z',
    status: 'Open',
    type: 'Vulnerability',
    asset: { name: 'web-server-1', type: 'Server' },
    confidence: 0.85,
    risk_score: 0.72,
  }
}

describe('Alerts + simAlerts integration', () => {
  it('simAlerts can be merged with findings for rendering', () => {
    const simEvents = [simEv(EVENT_TYPES.POLICY_BLOCKED, { reason: 'pii detected' })]
    const findings = [mockFinding()]

    const simAlerts = alertsFromEvents(simEvents)
    const allItems = [...simAlerts, ...findings]

    // Verify we have both
    expect(allItems).toHaveLength(2)
    expect(allItems[0].source).toBe('simulation')
    expect(allItems[1].asset).toBeDefined()
  })

  it('handles empty simEvents correctly', () => {
    const simEvents = []
    const findings = [mockFinding()]

    const simAlerts = alertsFromEvents(simEvents)
    const allItems = [...simAlerts, ...findings]

    expect(allItems).toHaveLength(1)
    expect(allItems[0].id).toBe('f1')
  })

  it('handles multiple sim alerts merged with findings', () => {
    const simEvents = [
      simEv(EVENT_TYPES.POLICY_BLOCKED, { reason: 'pii detected' }),
      simEv(EVENT_TYPES.TOOL_APPROVAL_REQUIRED, { tool_name: 'sql_query' }),
    ]
    const findings = [mockFinding()]

    const simAlerts = alertsFromEvents(simEvents)
    const allItems = [...simAlerts, ...findings]

    expect(allItems).toHaveLength(3)
    expect(allItems[0].type).toBe('policy_blocked')
    expect(allItems[1].type).toBe('tool_approval')
    expect(allItems[2].asset).toBeDefined()
  })

  it('sim alerts have required fields for rendering', () => {
    const simEvents = [
      simEv(EVENT_TYPES.POLICY_BLOCKED, { reason: 'pii detected' }),
      simEv(EVENT_TYPES.POLICY_ESCALATED, { reason: 'high risk' }),
      simEv(EVENT_TYPES.TOOL_APPROVAL_REQUIRED, { tool_name: 'sql_query' }),
    ]

    const simAlerts = alertsFromEvents(simEvents)

    // All should have the fields needed by FindingsTable
    simAlerts.forEach(alert => {
      expect(alert.id).toBeDefined()
      expect(alert.title).toBeDefined()
      expect(alert.severity).toBeDefined()
      expect(alert.timestamp).toBeDefined()
      expect(alert.source).toBe('simulation')
      // Detail instead of type for alerts
      expect(alert.detail).toBeDefined()
    })
  })

  it('sim alerts handle null/missing details gracefully', () => {
    const simEvents = [
      simEv(EVENT_TYPES.POLICY_BLOCKED, {}),
      simEv(EVENT_TYPES.POLICY_ESCALATED),
      simEv(EVENT_TYPES.TOOL_APPROVAL_REQUIRED, { tool_name: undefined }),
    ]

    const simAlerts = alertsFromEvents(simEvents)

    expect(simAlerts).toHaveLength(3)
    simAlerts.forEach(alert => {
      expect(alert.detail).toBeTruthy()
      expect(alert.severity).toBeTruthy()
      expect(alert.title).toBeTruthy()
    })
  })
})
