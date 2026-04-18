/**
 * lib/buildResultFromSimEvents.js
 * ─────────────────────────────────
 * Pure function — builds the MOCK_RESULTS-compatible result object from an
 * array of SimulationEvents received over the WS stream.
 *
 * Exported so both Simulation.jsx and useSimulationState.js can use it
 * without creating a circular dependency.
 *
 * Information extracted:
 *   simulation.blocked   → verdict, categories, decision_reason, explanation
 *   simulation.allowed   → verdict, response_preview
 *   simulation.completed → summary (probes_run for Garak, duration_ms for timing)
 *   All events           → decision trace timeline
 */

export function buildResultFromSimEvents(simEvents) {
  if (!simEvents || simEvents.length === 0) return null

  // Find terminal event
  const blockedEv   = simEvents.find(e => e.stage === 'blocked')
  const allowedEv   = simEvents.find(e => e.stage === 'allowed')
  const completedEv = simEvents.find(e => e.stage === 'completed')
  const terminal    = blockedEv || allowedEv

  if (!terminal && !completedEv) return null   // no useful data yet

  const summary = completedEv?.details?.summary || {}

  // If terminal event was dropped by the WS race condition, fall back to the
  // verdict recorded in simulation.completed summary (always emitted last).
  const isBlocked = blockedEv
    ? true
    : allowedEv
      ? false
      : summary.result === 'blocked'    // completedEv-only fallback
  const verdict = isBlocked ? 'blocked' : 'allowed'
  const d       = (terminal || completedEv).details || {}

  // Decision trace — one entry per sim event
  const decisionTrace = simEvents.map((e, idx) => {
    const rawLabel = (e.event_type || '')
      .split('.').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
    const ts = e.timestamp
      ? (() => {
          try {
            return new Date(e.timestamp).toLocaleTimeString('en-US', {
              hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
            })
          } catch { return '' }
        })()
      : ''
    return { step: idx + 1, label: rawLabel, status: e.status, detail: e.details?.message || rawLabel, ts }
  })

  // Policy impact — derive from categories on blocked event
  const categories   = d.categories || summary.categories || []
  const policyAction = isBlocked ? 'BLOCK' : 'ALLOW'
  const policyImpact = categories.map(cat => ({
    policy:   cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    action:   policyAction,
    trigger:  d.decision_reason || cat,
    severity: isBlocked ? 'critical' : 'ok',
  }))
  if (policyImpact.length === 0) {
    policyImpact.push({
      policy:   'Policy Engine v1',
      action:   policyAction,
      trigger:  d.decision_reason || (isBlocked ? 'Blocked by policy engine' : 'Allowed through policy gate'),
      severity: isBlocked ? 'critical' : 'ok',
    })
  }

  const policiesTriggered = categories.length > 0 ? categories : ['Policy Engine v1']

  // Garak summary info
  const probesRun  = summary.probes_run
  const outputText = isBlocked
    ? null
    : probesRun
      ? `[Garak scan completed — ${probesRun} probe${probesRun !== 1 ? 's' : ''} run, profile: ${summary.profile || 'default'}]`
      : (d.response_preview || '[Session allowed through policy gate]')

  return {
    verdict,
    riskScore:         isBlocked ? 85 : 20,
    riskLevel:         isBlocked ? 'High' : 'Low',
    executionMs:       summary.duration_ms ?? 0,
    policiesTriggered,
    decisionTrace,
    output:            outputText,
    blockedMessage:    isBlocked
      ? `Your request was terminated by the policy engine. ${d.decision_reason || ''} This event has been logged for security review.`.trim()
      : null,
    policyImpact,
    risk: {
      injectionDetected: categories.some(c => c.includes('injection')),
      anomalyScore:      isBlocked ? 0.85 : 0.2,
      techniques:        categories.map(c => c.replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase())),
      explanation:       d.decision_reason || (isBlocked ? 'Blocked by policy engine.' : 'No elevated risk signals detected.'),
    },
    recommendations: [],
  }
}
