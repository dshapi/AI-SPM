/**
 * phaseGrouping.js
 * ────────────────
 * Pure utilities for mapping simulation event stages to attack phases
 * and grouping events for timeline rendering.
 *
 * Stage values come from toSimulationEvent() in useSimulationStream.js:
 *   event_type "simulation.blocked" → stage = "blocked"
 */

/** Maps event stage → attack phase label */
export const PHASE_MAP = {
  started:   'Recon',
  progress:  'Injection',
  blocked:   'Exploitation',
  allowed:   'Exfiltration',
  completed: 'System',
  error:     'System',
}

/**
 * Group events by phase (for single-prompt mode).
 * Returns { [phase: string]: SimulationEvent[] } preserving insertion order.
 */
export function groupByPhase(events) {
  const map = {}
  for (const event of events) {
    const phase = PHASE_MAP[event.stage] ?? 'Other'
    if (!map[phase]) map[phase] = []
    map[phase].push(event)
  }
  return map
}

/**
 * Group events by phase → probe (for Garak mode).
 * Probe name comes from event.details.probe_name.
 * Returns { [phase: string]: { [probe: string]: SimulationEvent[] } }
 */
export function groupByPhaseAndProbe(events) {
  const map = {}
  for (const event of events) {
    const phase = PHASE_MAP[event.stage] ?? 'Other'
    const probe = event.details?.probe_name || 'unknown_probe'
    if (!map[phase]) map[phase] = {}
    if (!map[phase][probe]) map[phase][probe] = []
    map[phase][probe].push(event)
  }
  return map
}
