/**
 * hooks/useSimulationStream.js
 * ─────────────────────────────
 * Wraps useSessionSocket to provide simulation-specific event handling.
 *
 * Translates raw WsEvent frames into typed SimulationEvent objects:
 *   { id, event_type, stage, status, timestamp, details }
 *
 * Dedup strategy (task #13 fix D — defense-in-depth)
 * ──────────────────────────────────────────────────
 * The backend emits each simulation event through two independent paths —
 * a direct WebSocket broadcast AND a Kafka mirror that the SessionEventConsumer
 * forwards back to the same socket.  Fix C wires one shared timestamp through
 * both paths so they collide on `event_type:correlation_id:timestamp`, but we
 * keep defensive dedup here in case future backends regress or a different
 * emitter is plugged in.
 *
 * Rules:
 *   • Session-wide events (session.started / .blocked / .completed / .failed)
 *     fire AT MOST ONCE per session — keyed on `sid:<session_id>:<canonical>`,
 *     independent of timestamp.
 *   • Any event with a correlation_id (Garak per-probe attempts, policy
 *     decisions, llm.prompt / llm.response trace records) is keyed on
 *     `cid:<canonical>:<correlation_id>` — one event per (probe, decision,
 *     trace phase), independent of timestamp.
 *   • Everything else (progress, lineage, etc.) falls back to the legacy
 *     `<canonical>:<correlation_id>:<timestamp>` key.
 *
 * We key on the CANONICAL event type (post-normalizeEvent) so legacy and
 * canonical names never create apparent duplicates — e.g. `simulation.started`
 * and `session.started` both canonicalise to `session.started` and collide.
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

// Session-wide canonical event types that fire AT MOST ONCE per session.
// Duplicates of these are always double-emits, never legitimate.
const _SESSION_WIDE_TYPES = new Set([
  'session.started',
  'session.blocked',
  'session.completed',
  'session.failed',
])

function _dedupKey(normalized, raw) {
  const canonical = normalized.event_type
  const sid       = raw.session_id     || normalized.session_id     || ''
  const cid       = raw.correlation_id || normalized.correlation_id || ''

  // Correlation-scoped events (Garak per-probe blocked/allowed, policy
  // decisions, llm.* trace records) must use the correlation_id as the
  // primary dedup anchor — each probe has its own correlation_id and they
  // are ALL legitimate.  Two events with the SAME correlation_id are the
  // double-emit case; two events with DIFFERENT correlation_ids are two
  // distinct probes.  Check this BEFORE the session-wide fallback so
  // session.blocked events with per-probe correlation_ids survive.
  if (cid) {
    return `cid:${canonical}:${cid}`
  }
  // Session-wide events WITHOUT a correlation_id fire at most once per
  // session (single-prompt session.started / .completed / .blocked /
  // .failed) — key on session_id + canonical type.
  if (_SESSION_WIDE_TYPES.has(canonical) && sid) {
    return `sid:${sid}:${canonical}`
  }
  return `${canonical}:${raw.timestamp || ''}`
}

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
      // Normalise first so we dedup on the CANONICAL event_type — otherwise
      // `simulation.started` and `session.started` (which both canonicalise
      // to `session.started`) would look like two different events.
      const normalized = toSimulationEvent(raw)
      const key = _dedupKey(normalized, raw)
      if (seenRef.current.has(key)) continue
      seenRef.current.add(key)
      unseen.push(normalized)
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
