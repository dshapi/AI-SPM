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
 * Maps backend event_type → timeline stage used by PHASE_MAP in phaseGrouping.js.
 *
 * Backend emits dot-namespaced types (e.g. "prompt.received", "risk.calculated",
 * "policy.decision") — NOT "simulation.{stage}".  This table normalises them
 * into the stage values the timeline UI understands.
 */
const EVENT_TYPE_STAGE = {
  'prompt.received':  'started',
  'posture.enriched': 'progress',
  'risk.scored':      'progress',
  'risk.calculated':  'progress',
}

/**
 * Parse a WsEvent into a SimulationEvent.
 *
 * Handles two event_type conventions:
 *   Legacy assumption: "simulation.{stage}" (e.g. "simulation.blocked")
 *   Real backend:      "{category}.{action}" (e.g. "policy.decision")
 *
 * For "policy.decision" the stage is driven by payload.decision so that
 * the event lands in the correct timeline phase (blocked/allowed).
 */
export function toSimulationEvent(wsEvent) {
  const et      = wsEvent.event_type || ''
  const payload = wsEvent.payload    || {}

  let stage

  if (et === 'policy.decision') {
    // Decision is "block" | "allow" | "escalate" — map to timeline stage
    const dec = (payload.decision || '').toLowerCase()
    if      (dec === 'block')    stage = 'blocked'
    else if (dec === 'allow')    stage = 'allowed'
    else if (dec === 'escalate') stage = 'progress'  // escalated → show in Injection phase
    else                         stage = 'progress'
  } else if (EVENT_TYPE_STAGE[et]) {
    stage = EVENT_TYPE_STAGE[et]
  } else if (et.startsWith('simulation.')) {
    // Legacy/future "simulation.{stage}" convention
    stage = et.split('.')[1] || 'progress'
  } else {
    // Unknown event type — show in Injection phase as generic progress
    stage = 'progress'
  }

  return {
    id:             `${et}:${wsEvent.correlation_id || ''}:${wsEvent.timestamp}`,
    event_type:     et,
    stage,
    status:         stage,
    timestamp:      wsEvent.timestamp,
    source_service: wsEvent.source_service,
    details:        payload,
  }
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
    console.log('[SimStream] event', simEvent.event_type, 'stage:', simEvent.stage)
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
