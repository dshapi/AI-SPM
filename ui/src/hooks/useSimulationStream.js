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

  // Transform incoming WsEvents → SimulationEvents
  useEffect(() => {
    const latest = liveEvents[liveEvents.length - 1]
    if (!latest) return

    // Dedup key: type + correlation + timestamp — allows multiple events of the
    // same type (e.g. several policy.decision events in a Garak multi-probe run)
    const key = `${latest.event_type}:${latest.correlation_id || ''}:${latest.timestamp}`
    if (seenRef.current.has(key)) return
    seenRef.current.add(key)

    const simEvent = toSimulationEvent(latest)
    console.log('[PIPELINE] emit:', simEvent.event_type, '→ stage:', simEvent.stage, '| id:', simEvent.id)
    setSimEvents(prev => {
      const next = [...prev, simEvent]
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
