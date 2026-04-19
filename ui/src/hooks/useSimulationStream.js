/**
 * hooks/useSimulationStream.js
 * ─────────────────────────────
 * Wraps useSessionSocket to provide simulation-specific event handling.
 *
 * Translates raw WsEvent frames into typed SimulationEvent objects:
 *   { id, event_type, stage, status, timestamp, details }
 *
 * Unlike useSessionSocket's dedup (event_type only), this hook uses
 * event_type + correlation_id + timestamp so multiple progress events for
 * different Garak probes are all preserved.
 *
 * Returns
 * ───────
 *   connectionStatus   'idle' | 'connecting' | 'connected' | 'reconnecting' | 'closed' | 'error'
 *   simEvents          SimulationEvent[] — ordered by timestamp
 *   startStream(id)    Connect WS for given session_id; clears prior events
 *   stopStream()       Disconnect and reset
 */
import { useState, useRef, useCallback, useEffect } from 'react'
import { useSessionSocket } from './useSessionSocket'
import { normalizeEvent } from '../lib/eventSchema.js'

/**
 * Parse a WsEvent into a SimulationEvent.
 * Delegates to normalizeEvent() from eventSchema.js — single source of truth.
 * Kept as a named export for backward compatibility with tests and consumers.
 */
export function toSimulationEvent(wsEvent) {
  return normalizeEvent(wsEvent)
}

export function useSimulationStream() {
  const { connectionStatus, liveEvents, connectWs, disconnectWs } = useSessionSocket()
  const [simEvents, setSimEvents] = useState([])
  const seenRef = useRef(new Set())

  // Transform incoming WsEvents → SimulationEvents.
  //
  // We intentionally do NOT rely on `liveEvents[length-1]`: that value is the
  // event with the latest TIMESTAMP, not the most recently arrived one. When
  // events arrive out-of-order (slow network, retransmit, or two events with
  // the same millisecond-precision timestamp), the tail stabilises on the
  // first seen event and any later-arriving events mid-array would be
  // silently skipped.
  //
  // Instead we walk the whole sorted `liveEvents` array each render, filter
  // anything already in `seenRef`, normalise the new ones, and append. This is
  // O(N) per render but N is small (< a few hundred events per simulation).
  useEffect(() => {
    if (liveEvents.length === 0) return

    const unseen = []
    for (const raw of liveEvents) {
      const key = `${raw.event_type}:${raw.correlation_id || ''}:${raw.timestamp || ''}`
      if (seenRef.current.has(key)) continue
      seenRef.current.add(key)
      unseen.push(toSimulationEvent(raw))
    }
    if (unseen.length === 0) return

    for (const ev of unseen) {
      console.log('[PIPELINE] emit:', ev.event_type, '→ stage:', ev.stage, '| id:', ev.id)
    }

    setSimEvents(prev => {
      const next = [...prev, ...unseen]
      next.sort((a, b) => {
        const ta = a.timestamp ? new Date(a.timestamp).getTime() : 0
        const tb = b.timestamp ? new Date(b.timestamp).getTime() : 0
        return ta - tb
      })
      return next
    })
  }, [liveEvents])

  const startStream = useCallback((sessionId) => {
    seenRef.current = new Set()
    setSimEvents([])
    connectWs(sessionId)
  }, [connectWs])

  const stopStream = useCallback(() => {
    seenRef.current = new Set()
    setSimEvents([])
    disconnectWs()
  }, [disconnectWs])

  return { connectionStatus, simEvents, startStream, stopStream }
}
