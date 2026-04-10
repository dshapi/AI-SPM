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

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useSessionSocket() {
  const [connectionStatus, setConnectionStatus] = useState('idle')
  const [liveEvents,       setLiveEvents]       = useState([])

  // Mutable refs — never cause re-renders
  const wsRef            = useRef(null)
  const timerRef         = useRef(null)
  const attemptsRef      = useRef(0)
  const seenRef          = useRef(new Set())   // dedup keys
  const intentionalRef   = useRef(false)       // true when we called disconnectWs

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
      intentionalRef.current = true
      wsRef.current.close()
      wsRef.current = null
    }
  }, [_clearTimer])

  // ── Core connect ────────────────────────────────────────────────────────────

  const _doConnect = useCallback((sessionId) => {
    // Don't re-use old socket
    if (wsRef.current) {
      intentionalRef.current = true
      wsRef.current.close()
      wsRef.current = null
    }
    intentionalRef.current = false

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
      attemptsRef.current = 0
      setConnectionStatus('connected')
    }

    ws.onmessage = (evt) => {
      let msg
      try { msg = JSON.parse(evt.data) } catch { return }

      // Skip control frames
      if (msg.type === 'ping' || msg.type === 'connected') return

      // Deduplicate: each pipeline step fires exactly once, so event_type is
      // a good key. For services that could emit the same type twice, we append
      // the truncated timestamp.
      const dedup = msg.event_type
        ? `${msg.event_type}`
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
      setConnectionStatus('error')
    }

    ws.onclose = () => {
      wsRef.current = null
      if (intentionalRef.current) return    // deliberate close — do not reconnect

      if (attemptsRef.current < MAX_RECONNECTS) {
        attemptsRef.current++
        const delay = BACKOFF_BASE_MS * (2 ** (attemptsRef.current - 1))
        setConnectionStatus('reconnecting')
        timerRef.current = setTimeout(() => _doConnect(sessionId), delay)
      } else {
        setConnectionStatus('closed')
      }
    }
  }, [_clearTimer])   // _clearTimer is stable

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

  // Ensure socket is closed when the component unmounts
  useEffect(() => () => _closeSocket(), [_closeSocket])

  return { connectionStatus, liveEvents, connectWs, disconnectWs }
}
