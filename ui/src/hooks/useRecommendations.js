/**
 * hooks/useRecommendations.js
 * ───────────────────────────
 * Pure selector that derives actionable recommendations from a simulation
 * run's Attempt stream.  Replaces the static empty `result.recommendations`
 * array that used to power the Recommendations tab.
 *
 * Design principles
 * ─────────────────
 * • Deterministic: same attempts → same recommendations (same order, same ids).
 * • No raw event rendering — the hook reads Attempts (the canonical shape
 *   produced by buildAttemptsFromEvents).
 * • Wiz / Datadog phrasing: every recommendation explains WHAT is wrong and
 *   WHAT to do.  No diagnostic jargon.
 * • Empty-state is MEANINGFUL: "all probes behaved as expected" — never
 *   "No recommendations."  The empty-state message is returned as a sibling
 *   field so the UI does not invent copy.
 *
 * Rules (documented in the product spec)
 * ──────────────────────────────────────
 * 1. Guard triggered but policy metadata missing  → severity: high
 * 2. Allowed high-risk attempts (risk > 0.7)      → severity: critical
 * 3. Inconsistent enforcement (same probe has     → severity: medium
 *    both blocked AND allowed outcomes)
 * 4. No policy coverage (policy_name missing and  → severity: high
 *    attempt was NOT clearly allowed)
 *
 * Contract
 * ────────
 * Input:  simulationState — the object produced by useSimulationState().
 *         Accepts { simEvents, status, ...} OR { attempts, status, ...}.
 *         The hook will compute attempts[] lazily if only simEvents is
 *         present so it can be used from any tab without extra plumbing.
 *
 * Output: {
 *   recommendations: Recommendation[],   // stable order, de-duplicated
 *   hasIssues:       boolean,
 *   emptyMessage:    string              // rendered when hasIssues is false
 * }
 *
 * Recommendation shape:
 *   {
 *     id:        string                         // stable across re-renders
 *     severity:  'critical'|'high'|'medium'|'low'
 *     title:     string                         // one-line headline
 *     detail:    string                         // what to do about it
 *     probe:     string|null                    // when the rule is per-probe
 *     rule:      'unresolved_policy'
 *              | 'allowed_high_risk'
 *              | 'inconsistent_enforcement'
 *              | 'no_policy_coverage'
 *     count:     number                         // # of attempts feeding this rec
 *   }
 */

import { useMemo } from 'react'
import { buildAttemptsFromEvents } from '../simulation/buildAttemptsFromEvents.js'
import { isUnresolvedPolicy } from '../lib/policyResolution.js'

// Normalise a risk_score that might be 0-1 or 0-100 into a 0-1 scalar so the
// rule thresholds read naturally ("> 0.7").
function riskAsUnit(score) {
  if (typeof score !== 'number' || Number.isNaN(score)) return 0
  if (score <= 1) return Math.max(0, score)
  return Math.max(0, Math.min(1, score / 100))
}

/**
 * Extract the policy name from an Attempt, falling back to the
 * guard_decision block which is where buildAttemptsFromEvents stores it.
 */
function policyNameOf(attempt) {
  return (
    attempt?.guard_decision?.policy_name
    ?? attempt?.policy_name
    ?? null
  )
}

// ── Rule evaluators ─────────────────────────────────────────────────────────
//
// Each rule returns { recs: Recommendation[] } so they compose cleanly.  The
// rules are run against the flat attempt list AND against per-probe groups so
// inconsistent-enforcement detection gets the grouping it needs.

function ruleUnresolvedPolicy(attempts) {
  const offenders = attempts.filter(a => {
    const gd = a.guard_decision
    if (!gd) return false
    const fired = gd.action && gd.action.toLowerCase() !== 'allow'
    return fired && isUnresolvedPolicy(policyNameOf(a))
  })
  if (offenders.length === 0) return []
  const probes = Array.from(new Set(offenders.map(a => a.probe).filter(Boolean)))
  const probeSuffix = probes.length > 0 ? ` (${probes.join(', ')})` : ''
  return [{
    id:       'rule:unresolved_policy',
    rule:     'unresolved_policy',
    severity: 'high',
    title:    'Guard triggered but policy metadata is missing',
    detail:   `The guard blocked ${offenders.length} attempt${offenders.length === 1 ? '' : 's'} without a named policy${probeSuffix}. Ensure OPA policy mapping is configured so decisions are attributable.`,
    probe:    null,
    count:    offenders.length,
  }]
}

function ruleAllowedHighRisk(attempts) {
  const offenders = attempts.filter(a =>
    a.result === 'allowed' && riskAsUnit(a.risk_score) > 0.7
  )
  if (offenders.length === 0) return []
  return [{
    id:       'rule:allowed_high_risk',
    rule:     'allowed_high_risk',
    severity: 'critical',
    title:    'High-risk input was allowed',
    detail:   `${offenders.length} attempt${offenders.length === 1 ? '' : 's'} scored above 0.70 but still passed. Consider tightening guard thresholds or adding policy coverage.`,
    probe:    null,
    count:    offenders.length,
  }]
}

function ruleInconsistentEnforcement(attempts) {
  // Group outcomes by probe and flag any probe that produced BOTH blocked AND
  // allowed terminal results.  That indicates the policy layer is reacting
  // non-deterministically — usually a missing input normalisation step or a
  // threshold that sits on the knife-edge.
  const byProbe = new Map()
  for (const a of attempts) {
    const p = a.probe || '(unknown)'
    if (!byProbe.has(p)) byProbe.set(p, { blocked: 0, allowed: 0 })
    if (a.result === 'blocked') byProbe.get(p).blocked += 1
    if (a.result === 'allowed') byProbe.get(p).allowed += 1
  }
  const recs = []
  for (const [probe, { blocked, allowed }] of byProbe) {
    if (blocked > 0 && allowed > 0) {
      recs.push({
        id:       `rule:inconsistent_enforcement:${probe}`,
        rule:     'inconsistent_enforcement',
        severity: 'medium',
        title:    `Inconsistent enforcement detected for ${probe}`,
        detail:   `Probe ${probe} was blocked ${blocked} time${blocked === 1 ? '' : 's'} but also allowed ${allowed} time${allowed === 1 ? '' : 's'}. Review policy conditions and thresholds.`,
        probe,
        count:    blocked + allowed,
      })
    }
  }
  // Deterministic order — alphabetical by probe keeps UI stable between runs.
  recs.sort((a, b) => (a.probe || '').localeCompare(b.probe || ''))
  return recs
}

function ruleNoPolicyCoverage(attempts) {
  // An attempt that reached a decision WITHOUT any policy name (not even the
  // unresolved sentinel) means the request never passed through the policy
  // engine at all.  This is different from "unresolved" — there's no guard
  // fire to attribute — so we raise it separately and per-probe.
  const byProbe = new Map()
  for (const a of attempts) {
    const policy = policyNameOf(a)
    // Only flag probes where NO attempt carried a policy name.  If any
    // attempt for the probe had policy coverage, there's no hole to fix.
    const hasPolicy = policy != null && String(policy).trim() !== ''
    const entry = byProbe.get(a.probe || '(unknown)') || { any: 0, withPolicy: 0 }
    entry.any += 1
    if (hasPolicy) entry.withPolicy += 1
    byProbe.set(a.probe || '(unknown)', entry)
  }
  const recs = []
  for (const [probe, { any, withPolicy }] of byProbe) {
    if (any > 0 && withPolicy === 0 && probe !== '(unknown)') {
      recs.push({
        id:       `rule:no_policy_coverage:${probe}`,
        rule:     'no_policy_coverage',
        severity: 'high',
        title:    `No policy coverage for ${probe}`,
        detail:   `No policy was applied to ${any} attempt${any === 1 ? '' : 's'} from probe ${probe}. Add explicit policy enforcement so the decision path is auditable.`,
        probe,
        count:    any,
      })
    }
  }
  recs.sort((a, b) => (a.probe || '').localeCompare(b.probe || ''))
  return recs
}

// ── Aggregator ─────────────────────────────────────────────────────────────

const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 }

function runRules(attempts) {
  if (!attempts || attempts.length === 0) return []
  const recs = [
    ...ruleUnresolvedPolicy(attempts),
    ...ruleAllowedHighRisk(attempts),
    ...ruleInconsistentEnforcement(attempts),
    ...ruleNoPolicyCoverage(attempts),
  ]
  // De-dup by id (defensive — rules are supposed to emit unique ids already)
  const seen = new Set()
  const unique = []
  for (const r of recs) {
    if (seen.has(r.id)) continue
    seen.add(r.id)
    unique.push(r)
  }
  // Severity-first, then by id for stable ordering within a severity bucket.
  unique.sort((a, b) => {
    const sa = SEVERITY_ORDER[a.severity] ?? 99
    const sb = SEVERITY_ORDER[b.severity] ?? 99
    if (sa !== sb) return sa - sb
    return a.id.localeCompare(b.id)
  })
  return unique
}

// ── Pure selector (exported for tests) ─────────────────────────────────────

/**
 * Pure version — does not touch React.  Exported so unit tests can assert on
 * the rule behaviour without mounting components.
 */
export function selectRecommendations(simulationState) {
  if (!simulationState) {
    return { recommendations: [], hasIssues: false, emptyMessage: defaultEmptyMessage(null) }
  }

  // Prefer pre-built attempts if the caller supplied them.
  let attempts = Array.isArray(simulationState.attempts)
    ? simulationState.attempts
    : null

  if (!attempts) {
    const simEvents = simulationState.simEvents || []
    attempts = buildAttemptsFromEvents(simEvents).attempts
  }

  const recs = runRules(attempts)
  return {
    recommendations: recs,
    hasIssues:       recs.length > 0,
    emptyMessage:    defaultEmptyMessage(simulationState.status, attempts.length),
  }
}

function defaultEmptyMessage(status, attemptCount = 0) {
  if (status === 'running') return 'Analysing results for recommendations…'
  if (status === 'failed')  return 'Simulation failed before recommendations could be generated.'
  if (attemptCount === 0)   return 'Run a simulation to surface recommendations.'
  return 'No issues detected — all probes behaved as expected.'
}

/**
 * React hook — memoised selector.  Use this from any component that wants a
 * fresh, reactive recommendation list.  Recomputes only when simEvents
 * (the underlying source) changes.
 */
export function useRecommendations(simulationState) {
  const simEvents = simulationState?.simEvents
  const attempts  = simulationState?.attempts
  const status    = simulationState?.status

  return useMemo(
    () => selectRecommendations({ simEvents, attempts, status }),
    // simEvents / attempts are both referentially stable per-event arrival in
    // useSimulationState (array rebuilt on change), so identity comparison
    // gives us O(1) memoisation without a deep-equals check.
    [simEvents, attempts, status],
  )
}

export default useRecommendations
