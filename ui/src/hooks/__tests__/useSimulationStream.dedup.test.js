/**
 * useSimulationStream.dedup.test.js
 * ──────────────────────────────────
 * Regression tests for task #13 fix D — defense-in-depth dedup for the
 * double-emit bug where every simulation event fires through two paths
 * (direct WS + Kafka→WS bridge) and the old dedup key
 * (event_type:correlation_id:timestamp) failed to collapse them because
 * each path stamps an independent timestamp.
 *
 * We exercise the hook directly via React Testing Library's renderHook,
 * feeding raw WsEvent frames through the inner useSessionSocket's
 * liveEvents state.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// Mock useSessionSocket to control liveEvents directly — we don't need a real
// WebSocket for this test.
let _mockLiveEvents = []
vi.mock('../useSessionSocket', () => ({
  useSessionSocket: () => ({
    connectionStatus: 'connected',
    liveEvents: _mockLiveEvents,
    connectWs: vi.fn(),
    disconnectWs: vi.fn(),
  }),
}))

import { useSimulationStream } from '../useSimulationStream.js'

beforeEach(() => {
  _mockLiveEvents = []
})

describe('useSimulationStream dedup — task #13 fix D', () => {
  it('collapses two session.started frames with different timestamps (double-emit defense)', () => {
    // This is the scenario the bug creates: direct WS emits at T1,
    // Kafka bridge emits the SAME event at T2 a few ms later.
    _mockLiveEvents = [
      {
        event_type: 'simulation.started',
        session_id: 's1', correlation_id: '',
        timestamp: '2026-04-21T10:00:00.100Z',
        payload: { prompt: 'hi' },
      },
      {
        event_type: 'simulation.started',
        session_id: 's1', correlation_id: '',
        timestamp: '2026-04-21T10:00:00.103Z',   // 3ms later — Kafka lag
        payload: { prompt: 'hi' },
      },
    ]
    const { result, rerender } = renderHook(() => useSimulationStream())
    rerender()
    expect(result.current.simEvents).toHaveLength(1)
    expect(result.current.simEvents[0].event_type).toBe('session.started')
  })

  it('collapses simulation.blocked across direct + kafka mirror (same correlation_id, different ts)', () => {
    _mockLiveEvents = [
      {
        event_type: 'simulation.blocked',
        session_id: 's1', correlation_id: 'probe-1',
        timestamp: '2026-04-21T10:00:01.200Z',
        payload: { decision_reason: 'r' },
      },
      {
        event_type: 'simulation.blocked',
        session_id: 's1', correlation_id: 'probe-1',
        timestamp: '2026-04-21T10:00:01.215Z',   // different ts, same correlation
        payload: { decision_reason: 'r' },
      },
    ]
    const { result, rerender } = renderHook(() => useSimulationStream())
    rerender()
    expect(result.current.simEvents).toHaveLength(1)
    expect(result.current.simEvents[0].event_type).toBe('session.blocked')
  })

  it('preserves legitimate duplicates: two blocked events with DIFFERENT correlation_ids', () => {
    // Garak runs 2 probes, each produces its own simulation.blocked with a
    // unique correlation_id. These are legitimate and must both show up.
    _mockLiveEvents = [
      {
        event_type: 'simulation.blocked',
        session_id: 's1', correlation_id: 'probe-a',
        timestamp: '2026-04-21T10:00:01.200Z',
        payload: {},
      },
      {
        event_type: 'simulation.blocked',
        session_id: 's1', correlation_id: 'probe-b',
        timestamp: '2026-04-21T10:00:01.200Z',
        payload: {},
      },
    ]
    const { result, rerender } = renderHook(() => useSimulationStream())
    rerender()
    expect(result.current.simEvents).toHaveLength(2)
  })

  it('collapses legacy + canonical event types that share the same canonical form', () => {
    // simulation.started and session.started both canonicalise to session.started.
    // Before fix D, dedup was on raw event_type, so these looked different.
    _mockLiveEvents = [
      {
        event_type: 'simulation.started',
        session_id: 's1', correlation_id: '',
        timestamp: '2026-04-21T10:00:00.100Z',
        payload: {},
      },
      {
        event_type: 'session.started',
        session_id: 's1', correlation_id: '',
        timestamp: '2026-04-21T10:00:00.150Z',
        payload: {},
      },
    ]
    const { result, rerender } = renderHook(() => useSimulationStream())
    rerender()
    expect(result.current.simEvents).toHaveLength(1)
  })
})
