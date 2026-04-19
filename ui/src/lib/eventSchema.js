/**
 * lib/eventSchema.js
 * ───────────────────
 * Single source of truth for simulation event types and normalization.
 *
 * Re-exports CANONICAL_EVENT_TYPES as EVENT_TYPES and provides
 * normalizeEvent() — the single place raw WS frames become typed
 * SimulationEvent objects. Delegates canonicalization to sessionResults.js
 * to avoid duplicate normalization logic.
 */
import { CANONICAL_EVENT_TYPES, canonicalise } from './sessionResults.js'

// ── Public registry ──────────────────────────────────────────────────────────
export { CANONICAL_EVENT_TYPES }
export const EVENT_TYPES = CANONICAL_EVENT_TYPES

// ── Stage derivation ─────────────────────────────────────────────────────────
const _TYPE_TO_STAGE = {
  [CANONICAL_EVENT_TYPES.SESSION_STARTED]:        'started',
  [CANONICAL_EVENT_TYPES.SESSION_CREATED]:        'started',
  [CANONICAL_EVENT_TYPES.SESSION_COMPLETED]:      'completed',
  [CANONICAL_EVENT_TYPES.SESSION_BLOCKED]:        'blocked',
  [CANONICAL_EVENT_TYPES.SESSION_FAILED]:         'error',
  [CANONICAL_EVENT_TYPES.POLICY_ALLOWED]:         'allowed',
  [CANONICAL_EVENT_TYPES.POLICY_BLOCKED]:         'blocked',
  [CANONICAL_EVENT_TYPES.POLICY_ESCALATED]:       'escalated',
  [CANONICAL_EVENT_TYPES.CONTEXT_RETRIEVED]:      'progress',
  [CANONICAL_EVENT_TYPES.RISK_ENRICHED]:          'progress',
  [CANONICAL_EVENT_TYPES.RISK_CALCULATED]:        'progress',
  [CANONICAL_EVENT_TYPES.AGENT_MEMORY_REQUESTED]: 'progress',
  [CANONICAL_EVENT_TYPES.AGENT_MEMORY_RESOLVED]:  'progress',
  [CANONICAL_EVENT_TYPES.AGENT_TOOL_PLANNED]:     'progress',
  [CANONICAL_EVENT_TYPES.AGENT_RESPONSE_READY]:   'progress',
  [CANONICAL_EVENT_TYPES.TOOL_INVOKED]:           'progress',
  [CANONICAL_EVENT_TYPES.TOOL_APPROVAL_REQUIRED]: 'progress',
  [CANONICAL_EVENT_TYPES.TOOL_COMPLETED]:         'progress',
  [CANONICAL_EVENT_TYPES.TOOL_OBSERVED]:          'progress',
  [CANONICAL_EVENT_TYPES.OUTPUT_GENERATED]:       'progress',
  [CANONICAL_EVENT_TYPES.OUTPUT_SCANNED]:         'progress',
  [CANONICAL_EVENT_TYPES.AUDIT_LOGGED]:           'progress',
}

function deriveStage(canonicalType) {
  return _TYPE_TO_STAGE[canonicalType] ?? 'progress'
}

/**
 * @typedef {Object} SimulationEvent
 * @property {string}  id             — dedup key: `event_type:correlation_id:timestamp`
 * @property {string}  event_type     — canonical event type from EVENT_TYPES
 * @property {string}  stage          — UI timeline stage
 * @property {string}  status         — alias for stage (legacy compat)
 * @property {string}  timestamp      — ISO-8601 from WS frame
 * @property {string}  [source_service]
 * @property {object}  details        — raw payload from WS frame
 */

/**
 * Normalize a raw WebSocket frame into a typed SimulationEvent.
 * This is the ONLY place in the codebase that converts raw WS events.
 *
 * @param {object} wsEvent
 * @returns {SimulationEvent}
 */
export function normalizeEvent(wsEvent) {
  const canonicalType = canonicalise(wsEvent)
  const stage         = deriveStage(canonicalType)

  return {
    id:             `${canonicalType}:${wsEvent.correlation_id || ''}:${wsEvent.timestamp}`,
    event_type:     canonicalType,
    stage,
    status:         stage,
    timestamp:      wsEvent.timestamp,
    source_service: wsEvent.source_service,
    details:        wsEvent.payload || {},
  }
}
