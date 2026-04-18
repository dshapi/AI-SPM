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

/**
 * Parse a WsEvent into a SimulationEvent.
 * event_type format: "simulation.{stage}" (e.g. "simulation.started", "simulation.blocked")
 */
function toSimulationEvent(wsEvent) {
  const parts = (wsEvent.event_type || '').split('.')
  // parts[0] = "simulation", parts[1] = stage
  const stage  = parts[1] || 'unknown'
  const status = parts[2] || stage

  return {
    id:             `${wsEvent.event_type}:${wsEvent.correlation_id || ''}:${wsEvent.timestamp}`,
    event_type:     wsEvent.event_type,
    stage,
    status,
    timestamp:      wsEvent.timestamp,
    source_service: wsEvent.source_service,
    details:        wsEvent.payload || {},
  }
}

export function useSimulationStream() {
  const { connectionStatus, liveEvents, connectWs, disconnectWs } = useSessionSocket()
  const [simEvents, setSimEvents] = useState([])
  const seenRef = useRef(new Set())

  // Transform incoming WsEvents → SimulationEvents, filtering to simulation.* only
  useEffect(() => {
    const latest = liveEvents[liveEvents.length - 1]
    if (!latest) return
    if (!latest.event_type?.startsWith('simulation.')) return

    // Dedup key includes timestamp to allow multiple progress events
    const key = `${latest.event_type}:${latest.correlation_id || ''}:${latest.timestamp}`
    if (seenRef.current.has(key)) return
    seenRef.current.add(key)

    const simEvent = toSimulationEvent(latest)
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
