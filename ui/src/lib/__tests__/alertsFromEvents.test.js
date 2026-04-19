import { describe, it, expect } from 'vitest'
import { alertsFromEvents } from '../alertsFromEvents.js'
import { EVENT_TYPES } from '../eventSchema.js'

function ev(event_type, details = {}, ts = '2026-01-01T00:00:00Z') {
  return { id: `${event_type}:x:${ts}`, event_type, stage: 'progress', timestamp: ts, details }
}

describe('alertsFromEvents', () => {
  it('returns [] for empty events', () => {
    expect(alertsFromEvents([])).toEqual([])
  })

  it('returns [] for non-alert events', () => {
    const events = [ev(EVENT_TYPES.SESSION_STARTED), ev(EVENT_TYPES.RISK_CALCULATED)]
    expect(alertsFromEvents(events)).toEqual([])
  })

  it('generates alert for policy.blocked', () => {
    const events = [ev(EVENT_TYPES.POLICY_BLOCKED, { reason: 'pii detected', policy_version: 'v2' })]
    const alerts = alertsFromEvents(events)
    expect(alerts).toHaveLength(1)
    expect(alerts[0].severity).toBe('critical')
    expect(alerts[0].type).toBe('policy_blocked')
    expect(alerts[0].title).toMatch(/blocked/i)
  })

  it('generates alert for policy.escalated', () => {
    const events = [ev(EVENT_TYPES.POLICY_ESCALATED, { reason: 'high risk' })]
    const alerts = alertsFromEvents(events)
    expect(alerts).toHaveLength(1)
    expect(alerts[0].severity).toBe('high')
    expect(alerts[0].type).toBe('policy_escalated')
  })

  it('generates alert for tool.approval.required', () => {
    const events = [ev(EVENT_TYPES.TOOL_APPROVAL_REQUIRED, { tool_name: 'sql_query' })]
    const alerts = alertsFromEvents(events)
    expect(alerts).toHaveLength(1)
    expect(alerts[0].severity).toBe('medium')
    expect(alerts[0].detail).toMatch(/sql_query/i)
  })

  it('alert id is stable (derived from event id)', () => {
    const events = [ev(EVENT_TYPES.POLICY_BLOCKED, {})]
    const a1 = alertsFromEvents(events)
    const a2 = alertsFromEvents(events)
    expect(a1[0].id).toBe(a2[0].id)
  })

  it('multiple blocked events produce multiple alerts', () => {
    const events = [
      ev(EVENT_TYPES.POLICY_BLOCKED, {}, '2026-01-01T00:00:01Z'),
      ev(EVENT_TYPES.POLICY_BLOCKED, {}, '2026-01-01T00:00:02Z'),
    ]
    expect(alertsFromEvents(events)).toHaveLength(2)
  })

  it('is pure — same input same output', () => {
    const events = [ev(EVENT_TYPES.POLICY_BLOCKED)]
    expect(alertsFromEvents(events)).toEqual(alertsFromEvents(events))
  })
})
