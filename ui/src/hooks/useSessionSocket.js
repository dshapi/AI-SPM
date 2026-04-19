/**
 * hooks/useSessionSocket.js
 * ──────────────────────────
 * Custom React hook — WebSocket connection to /ws/sessions/{sessionId}.
 *
 * Manages the full socket lifecycle: connect, message fan-in, reconnect
 * (up to 3 attempts with exponential back-off), deliberate disconnect,
 * and per-event deduplication with stable timestamp ordering.
 *
 * Returns
 * ───────
 *   connectionStatus  'idle' | 'connecting' | 'connected' | 'reconnecting' | 'closed' | 'error'
 *   liveEvents        WsEvent[] — deduplicated, sorted by ISO timestamp
 *   connectWs(id)     Open a connection for the given session ID; resets prior state
 *   disconnectWs()    Tear down the socket and reset all state to idle
 *
 * Wire format expected (from WsEvent / WsPingFrame / WsConnectedFrame):
 *   { type: "ping" }                                    — heartbeat, ignored
 *   { type: "connected", session_id, message }          — handshake, ignored
 *   { session_id, correlation_id, event_type,           — live pipeline event
 *     source_service, timestamp, payload }
 *
 * Concurrency model
 * ─────────────────
 * Each _doConnect call DETACHES the previous socket's event handlers before
 * calling close().  This is critical to prevent a class of races where the
 * OLD socket's onclose fires AFTER we've already started a new connection,
 * which would otherwise:
 *   1. Wipe wsRef.current (the new socket) via `wsRef.current = null`, and
 *   2. Schedule a spurious reconnect to the OLD sessionId.
 *
 * In addition, every handler guards with `if (wsRef.current !== ws) return`
 * so any straggling event from a detached/superseded socket is a strict
 * no-op — even if the runtime delivers it after detach.
 */

import { useState, useRef, useEffect, useCallback } from 'react'

// ── WebSocket base URL ─────────────────────────────────────────────────────────
// Converts the configured HTTP API base to a WS base.
// Examples:
//   VITE_API_URL = "http://localhost:8090"   → ws://localhost:8090
//   VITE_API_URL = "https://api.example.com" → wss://api.example.com
//   VITE_API_URL = "/api"  (relative)        → ws://localhost:PORT/api
//   (unset)                                  → ws://localhost:PORT
function resolveWsBase() {
  const raw = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
  if (/^https?:\/\//.test(raw)) {
    return raw.replace(/^http/, 'ws')
  }
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${raw}`
}

const WS_BASE         = resolveWsBase()
const MAX_RECONNECTS  = 3
const BACKOFF_BASE_MS = 1_500   // 1.5 s → 3 s → 6 s

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Detach every handler from `ws` and close it. Safe to call on any state.
 *
 * Detaching the handlers BEFORE calling close() guarantees that the old
 * socket cannot deliver any future onclose / onerror / onmessage callback —
 * which would otherwise race with a newer connection and either wipe its
 * wsRef or schedule a reconnect to a stale sessionId.
 */
function _detachAndClose(ws) {
  if (!ws) return
  try {
    ws.onopen    = null
    ws.onmessage = null
    ws.onerror   = null
    ws.onclose   = null
    if (
      ws.readyState === WebSocket.OPEN ||
      ws.readyState === WebSocket.CONNECTING
    ) {
      ws.close()
    }
  } catch {
    /* noop — close() can throw on already-closed sockets */
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useSessionSocket() {
  const [connectionStatus, setConnectionStatus] = useState('idle')
  const [liveEvents,       setLiveEvents]       = useState([])

  // Mutable refs — never cause re-renders
  const wsRef       = useRef(null)
  const timerRef    = useRef(null)
  const attemptsRef = useRef(0)
  const seenRef     = useRef(new Set())   // dedup keys

  // ── Internal helpers ────────────────────────────────────────────────────────

  const _clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const _closeSocket = useCallback(() => {
    _clearTimer()
    if (wsRef.current) {
      _detachAndClose(wsRef.current)
      wsRef.current = null
    }
  }, [_clearTimer])

  // ── Core connect ────────────────────────────────────────────────────────────

  const _doConnect = useCallback((sessionId) => {
    // Tear down any previous socket FIRST — handlers detached so its later
    // onclose cannot interfere with this new connection.
    if (wsRef.current) {
      _detachAndClose(wsRef.current)
      wsRef.current = null
    }
    _clearTimer()

    setConnectionStatus(attemptsRef.current > 0 ? 'reconnecting' : 'connecting')

    const url = `${WS_BASE}/ws/sessions/${sessionId}`
    let ws
    try {
      ws = new WebSocket(url)
    } catch (err) {
      console.error('[SimLab WS] WebSocket construction failed:', err.message)
      setConnectionStatus('error')
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      // If a newer connection has already replaced us, ignore.
      if (wsRef.current !== ws) return
      attemptsRef.current = 0
      setConnectionStatus('connected')
    }

    ws.onmessage = (evt) => {
      // Drop messages from any superseded socket.
      if (wsRef.current !== ws) return

      let msg
      try { msg = JSON.parse(evt.data) } catch { return }

      // Skip control frames
      if (msg.type === 'ping' || msg.type === 'connected') return

      // Deduplicate using event_type + correlation_id + timestamp so that
      // Garak multi-probe runs (which emit the same event_type for every probe,
      // each with a distinct correlation_id) are all passed through.
      // Using event_type alone was the bug: the 2nd+ simulation.allowed /
      // simulation.progress events per run were silently dropped.
      const dedup = msg.event_type
        ? `${msg.event_type}:${msg.correlation_id || ''}:${msg.timestamp || ''}`
        : `${msg.source_service}:${msg.timestamp}`
      if (seenRef.current.has(dedup)) return
      seenRef.current.add(dedup)

      setLiveEvents(prev => {
        const next = [...prev, msg]
        // Stable sort by ISO-8601 timestamp (missing ↦ epoch 0)
        next.sort((a, b) => {
          const ta = a.timestamp ? new Date(a.timestamp).getTime() : 0
          const tb = b.timestamp ? new Date(b.timestamp).getTime() : 0
          return ta - tb
        })
        return next
      })
    }

    ws.onerror = () => {
      // onerror is always followed by onclose; handle reconnect there
      if (wsRef.current !== ws) return
      setConnectionStatus('error')
    }

    ws.onclose = () => {
      // ── Ownership check ────────────────────────────────────────────────
      // If a newer connection has already replaced us in wsRef.current,
      // this close event belongs to an OBSOLETE socket and must NOT:
      //   • clear wsRef.current (would wipe the new connection), or
      //   • schedule a reconnect to this stale sessionId.
      // _detachAndClose nulls handlers before close() so we should rarely
      // even reach here for a superseded socket — this guard is the
      // belt-and-braces complement.
      if (wsRef.current !== ws) return

      wsRef.current = null

      // Auto-reconnect for unexpected disconnects (server bounce, network
      // glitch).  We never reach this branch for intentional closes because
      // _closeSocket detaches `onclose` before calling close().
      if (attemptsRef.current < MAX_RECONNECTS) {
        attemptsRef.current++
        const delay = BACKOFF_BASE_MS * (2 ** (attemptsRef.current - 1))
        setConnectionStatus('reconnecting')
        timerRef.current = setTimeout(() => _doConnect(sessionId), delay)
      } else {
        setConnectionStatus('closed')
      }
    }
  }, [_clearTimer])

  // ── Public API ──────────────────────────────────────────────────────────────

  /**
   * Open a WebSocket for the given session.
   * Resets all accumulated state (events, dedup set, retry counter).
   */
  const connectWs = useCallback((sessionId) => {
    _closeSocket()
    attemptsRef.current = 0
    seenRef.current     = new Set()
    setLiveEvents([])
    _doConnect(sessionId)
  }, [_closeSocket, _doConnect])

  /**
   * Deliberately close the WebSocket and reset to idle.
   */
  const disconnectWs = useCallback(() => {
    _closeSocket()
    attemptsRef.current = 0
    seenRef.current     = new Set()
    setLiveEvents([])
    setConnectionStatus('idle')
  }, [_closeSocket])

  // Ensure socket is closed when the component unmounts.
  // _closeSocket detaches handlers first, so this cleanup is StrictMode-safe:
  // the post-first-mount fake unmount is a no-op (wsRef is null) and a real
  // unmount tears down cleanly without triggering reconnect logic.
  useEffect(() => () => _closeSocket(), [_closeSocket])

  return { connectionStatus, liveEvents, connectWs, disconnectWs }
}
