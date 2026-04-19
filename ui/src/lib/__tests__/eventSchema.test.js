import { describe, it, expect } from 'vitest'
import { EVENT_TYPES, normalizeEvent } from '../eventSchema.js'

describe('EVENT_TYPES', () => {
  it('exports SESSION_STARTED', () => {
    expect(EVENT_TYPES.SESSION_STARTED).toBe('session.started')
  })
  it('exports POLICY_BLOCKED', () => {
    expect(EVENT_TYPES.POLICY_BLOCKED).toBe('policy.blocked')
  })
  it('exports 22 canonical types', () => {
    expect(Object.keys(EVENT_TYPES).length).toBeGreaterThanOrEqual(22)
  })
})

describe('normalizeEvent', () => {
  it('preserves canonical event_type unchanged', () => {
    const raw = { event_type: 'session.started', timestamp: '2026-01-01T00:00:00Z' }
    const ev  = normalizeEvent(raw)
    expect(ev.event_type).toBe('session.started')
  })

  it('maps legacy raw_event → session.started', () => {
    const raw = { event_type: 'raw_event', timestamp: '2026-01-01T00:00:00Z' }
    const ev  = normalizeEvent(raw)
    expect(ev.event_type).toBe('session.started')
  })

  it('maps policy.decision + block → policy.blocked', () => {
    const raw = { event_type: 'policy.decision', payload: { decision: 'block' }, timestamp: '2026-01-01T00:00:00Z' }
    const ev  = normalizeEvent(raw)
    expect(ev.event_type).toBe('policy.blocked')
  })

  it('maps policy.decision + allow → policy.allowed', () => {
    const raw = { event_type: 'policy.decision', payload: { decision: 'allow' }, timestamp: '2026-01-01T00:00:00Z' }
    const ev  = normalizeEvent(raw)
    expect(ev.event_type).toBe('policy.allowed')
  })

  it('sets dedup id as event_type:correlation_id:timestamp', () => {
    const raw = { event_type: 'risk.calculated', correlation_id: 'abc', timestamp: '2026-01-01T00:00:00Z' }
    const ev  = normalizeEvent(raw)
    expect(ev.id).toBe('risk.calculated:abc:2026-01-01T00:00:00Z')
  })

  it('sets stage for policy.blocked → blocked', () => {
    const raw = { event_type: 'policy.decision', payload: { decision: 'block' }, timestamp: '2026-01-01T00:00:00Z' }
    expect(normalizeEvent(raw).stage).toBe('blocked')
  })

  it('sets stage for session.started → started', () => {
    const raw = { event_type: 'session.started', timestamp: 'ts' }
    expect(normalizeEvent(raw).stage).toBe('started')
  })

  it('copies source_service and details from payload', () => {
    const raw = { event_type: 'audit.logged', source_service: 'svc-a', payload: { foo: 1 }, timestamp: 'ts' }
    const ev  = normalizeEvent(raw)
    expect(ev.source_service).toBe('svc-a')
    expect(ev.details.foo).toBe(1)
  })

  it('returns valid event for completely unknown event_type', () => {
    const raw = { event_type: 'some.unknown.type', timestamp: 'ts' }
    const ev  = normalizeEvent(raw)
    expect(ev.id).toBeTruthy()
    expect(ev.stage).toBe('progress')
  })
})
