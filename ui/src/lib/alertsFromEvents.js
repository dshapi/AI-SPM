/**
 * lib/alertsFromEvents.js
 * ────────────────────────
 * Pure function: SimulationEvent[] → SimAlert[]
 *
 * Converts simulation policy/tool events into alert objects compatible
 * with the shape used by Alerts.jsx (merged alongside useFindings data).
 *
 * SimAlert shape
 * ──────────────
 * {
 *   id:        string   — derived from event.id (stable, deterministic)
 *   type:      string   — 'policy_blocked' | 'policy_escalated' | 'tool_approval'
 *   severity:  string   — 'critical' | 'high' | 'medium'
 *   title:     string
 *   detail:    string
 *   timestamp: string   — ISO-8601
 *   source:    'simulation'
 * }
 */
import { EVENT_TYPES } from './eventSchema.js'

const _ALERT_EVENT_TYPES = new Set([
  EVENT_TYPES.POLICY_BLOCKED,
  EVENT_TYPES.POLICY_ESCALATED,
  EVENT_TYPES.TOOL_APPROVAL_REQUIRED,
])

/**
 * @param {import('./eventSchema.js').SimulationEvent[]} events
 * @returns {object[]} SimAlert[]
 */
export function alertsFromEvents(events) {
  if (!events || events.length === 0) return []

  return events
    .filter(ev => _ALERT_EVENT_TYPES.has(ev.event_type))
    .map(ev => {
      const d = ev.details || {}

      switch (ev.event_type) {
        case EVENT_TYPES.POLICY_BLOCKED:
          return {
            id:        `sim-alert-${ev.id}`,
            type:      'policy_blocked',
            severity:  'critical',
            title:     'Request Blocked by Policy',
            detail:    d.reason || d.policy_version || 'Policy engine terminated the request.',
            timestamp: ev.timestamp,
            source:    'simulation',
          }

        case EVENT_TYPES.POLICY_ESCALATED:
          return {
            id:        `sim-alert-${ev.id}`,
            type:      'policy_escalated',
            severity:  'high',
            title:     'Request Escalated for Review',
            detail:    d.reason || 'Request exceeded escalation threshold — manual approval required.',
            timestamp: ev.timestamp,
            source:    'simulation',
          }

        case EVENT_TYPES.TOOL_APPROVAL_REQUIRED:
          return {
            id:        `sim-alert-${ev.id}`,
            type:      'tool_approval',
            severity:  'medium',
            title:     'Tool Approval Required',
            detail:    `Tool "${d.tool_name || 'unknown'}" requires human approval before execution.`,
            timestamp: ev.timestamp,
            source:    'simulation',
          }

        default:
          return null
      }
    })
    .filter(Boolean)
}
