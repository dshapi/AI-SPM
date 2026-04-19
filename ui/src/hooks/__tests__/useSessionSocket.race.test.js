/**
 * useSessionSocket.race.test.js
 * ──────────────────────────────
 * Regression tests for the rapid-reconnect race that produced the
 * "simulation stays in running" bug.
 *
 * Root cause (see hooks/useSessionSocket.js for full notes):
 *   When the hook closed an old WebSocket and immediately opened a new one
 *   (e.g. user ran another simulation before the previous socket's onclose
 *   fired), the OLD socket's onclose callback would later
 *     (a) null out wsRef.current, wiping the NEW socket, and
 *     (b) schedule a reconnect to the OLD sessionId.
 *
 *   The backend would then see the WS appear for the WRONG sessionId while
 *   the session it actually launched waited in the pre-connect buffer
 *   forever, and the browser's watchdog eventually fired "Simulation
 *   timeout".
 *
 * Fix: _detachAndClose nulls every handler on the old socket BEFORE calling
 * close(), and every handler now guards with `if (wsRef.current !== ws) return`
 * so any straggling delivery is a no-op.
 *
 * These tests install a fake WebSocket and drive the full lifecycle.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

import { useSessionSocket } from '../useSessionSocket.js'

// ── Fake WebSocket ───────────────────────────────────────────────────────────
// Tracks every instance and lets tests drive open / message / close manually.

class FakeWebSocket {
  static instances = []
  static CONNECTING = 0
  static OPEN       = 1
  static CLOSING    = 2
  static CLOSED     = 3

  constructor(url) {
    this.url       = url
    this.readyState = FakeWebSocket.CONNECTING
    this.onopen    = null
    this.onmessage = null
    this.onerror   = null
    this.onclose   = null
    this.closed    = false
    this._closeArgs = null
    FakeWebSocket.instances.push(this)
  }

  // Drive opening from the test.
  _open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.({})
  }

  // Simulate a message arriving.
  _message(data) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  // Simulate a server-side close with a code/reason.
  _serverClose(code = 1000, reason = '') {
    this.readyState = FakeWebSocket.CLOSED
    this._closeArgs = { code, reason }
    this.onclose?.({ code, reason })
  }

  // close() is called by the hook itself. We just mark state and fire onclose
  // on the NEXT microtask so the hook has a chance to detach handlers first
  // (which matches the real-browser async behaviour).
  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return
    this.closed = true
    this.readyState = FakeWebSocket.CLOSED
    // Schedule async delivery — mirrors browser close semantics.
    queueMicrotask(() => this.onclose?.({ code: 1000, reason: '' }))
  }
}

beforeEach(() => {
  FakeWebSocket.instances = []
  // Expose the fake as the global WebSocket. The constants on the class make
  // it compatible with `ws.readyState === WebSocket.OPEN` checks inside the
  // hook.
  globalThis.WebSocket = FakeWebSocket
})

afterEach(() => {
  vi.useRealTimers()
})

// ── Tests ────────────────────────────────────────────────────────────────────

describe('useSessionSocket — rapid reconnect race', () => {
  it('connectWs(new_sid) detaches old handlers so stale onclose is a no-op', async () => {
    const { result } = renderHook(() => useSessionSocket())

    // First connect
    act(() => result.current.connectWs('sid-old'))
    const oldWs = FakeWebSocket.instances[0]
    expect(oldWs.url).toMatch(/sid-old$/)

    // Second connect before old socket's close event has a chance to propagate.
    act(() => result.current.connectWs('sid-new'))
    const newWs = FakeWebSocket.instances[1]
    expect(newWs.url).toMatch(/sid-new$/)

    // The old ws's handlers MUST have been detached — this is the core fix.
    expect(oldWs.onclose).toBeNull()
    expect(oldWs.onopen).toBeNull()
    expect(oldWs.onmessage).toBeNull()
    expect(oldWs.onerror).toBeNull()
    // And the old ws was actually close()d (marked, not just detached).
    expect(oldWs.closed).toBe(true)

    // Simulate the old ws's server-side close firing AFTER the new connect.
    // This must NOT null out wsRef (the new socket) or schedule a reconnect.
    act(() => oldWs._serverClose(1006, 'network'))

    // The new WS should still be the one we'd use to send/receive.
    act(() => newWs._open())
    expect(result.current.connectionStatus).toBe('connected')

    // And only TWO sockets exist — no third "reconnect to sid-old" attempt.
    expect(FakeWebSocket.instances.length).toBe(2)
  })

  it('messages from a superseded socket are dropped', () => {
    const { result } = renderHook(() => useSessionSocket())

    act(() => result.current.connectWs('sid-old'))
    const oldWs = FakeWebSocket.instances[0]
    act(() => oldWs._open())

    act(() => result.current.connectWs('sid-new'))
    const newWs = FakeWebSocket.instances[1]
    act(() => newWs._open())

    // Even if the old socket somehow delivers a message (runtime might queue),
    // it must be ignored — the ownership check guards against this.
    // Note: after _detachAndClose, onmessage is null and this never runs;
    // we simulate the message via the fake by re-attaching a handler to
    // check that the guard in the hook's ORIGINAL handler (if somehow
    // re-attached) would drop it. Because we can't reattach externally to
    // the hook's closure, we instead assert the hook detached it.
    expect(oldWs.onmessage).toBeNull()

    // Now the NEW socket delivers a real event — it must be captured.
    act(() => newWs._message({
      event_type:     'simulation.started',
      session_id:     'sid-new',
      correlation_id: '',
      timestamp:      '2025-01-01T00:00:00Z',
      source_service: 'api-simulation',
      payload:        {},
    }))

    expect(result.current.liveEvents.length).toBe(1)
    expect(result.current.liveEvents[0].event_type).toBe('simulation.started')
  })

  it('disconnectWs detaches the socket so no spurious reconnect fires', () => {
    const { result } = renderHook(() => useSessionSocket())

    act(() => result.current.connectWs('sid-1'))
    const ws = FakeWebSocket.instances[0]
    act(() => ws._open())

    act(() => result.current.disconnectWs())

    // Handlers detached (intentional close) → onclose is a no-op even if
    // the runtime later fires it.
    expect(ws.onclose).toBeNull()
    expect(ws.closed).toBe(true)

    // Simulate a late close callback anyway — must NOT create a new socket.
    act(() => ws._serverClose(1006))
    expect(FakeWebSocket.instances.length).toBe(1)
    expect(result.current.connectionStatus).toBe('idle')
  })

  it('unexpected server close on the CURRENT socket DOES schedule reconnect', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useSessionSocket())

    act(() => result.current.connectWs('sid-keep'))
    const ws = FakeWebSocket.instances[0]
    act(() => ws._open())

    // Server drops the connection — this is NOT intentional, so we expect a
    // reconnect attempt.
    act(() => ws._serverClose(1006, 'network'))

    // Advance the 1.5s back-off timer.
    act(() => { vi.advanceTimersByTime(1_600) })

    // A second socket must have been constructed for the same sid.
    expect(FakeWebSocket.instances.length).toBe(2)
    expect(FakeWebSocket.instances[1].url).toMatch(/sid-keep$/)
  })
})
