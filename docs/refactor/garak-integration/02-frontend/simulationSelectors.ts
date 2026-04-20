// ui/src/simulation/simulationSelectors.ts   (v2.2 — final hardening)
// ────────────────────────────────────────────────────────────────────
// Derived views over the canonical attempt store.
//
// v2.2 changes over v2.1
// ──────────────────────
//   * ALL attempt-ordered selectors now use the deterministic
//     (envelope.sequence asc, arrival asc) comparator via
//     `sortedAttempts()`.  This is the single source of ordering
//     truth — every tab uses the same order, so Summary counts,
//     Timeline order, Risk x-axis, and Decision Trace cannot drift.
//   * `useRiskSeries` x-axis is now envelope.sequence (with nullable
//     sequences falling to their arrival index for stable plotting).
//   * `useOutputView` unchanged — still filters by `model_invoked`.
//   * Policy Impact still sinks unresolved rows to the bottom.
//
// Contract the UI relies on
// ─────────────────────────
//   1.  Attempt is the ONLY source of truth.
//   2.  Every ordered view uses the same (sequence, arrival) comparator.
//   3.  Probe Results prefers authoritative counts from probe_completed.
//   4.  Policy Impact shows unresolved policies explicitly, never as
//       the fabricated "Unknown".
//   5.  Output tab shows only model_invoked attempts.
//
// Components never read attemptsById / attemptSequenceById directly —
// that's the boundary that keeps the UI and the data contract decoupled.

import { useMemo } from 'react'
import {
  useSimulationStore,
  type SimulationStoreState,
  type ProbeRunState,
} from './simulationStore'
import {
  isUnresolvedPolicy,
  type Attempt,
  type AttemptPhase,
  type GuardDecision,
} from './types'

// ── Deterministic ordering comparator ──────────────────────────────────────
//
// Primary key: envelope.sequence (ascending, nulls after numerics).
// Tie-breaker: arrival index (the order the reducer stamped on intake).
//
// Non-null sequences first, then nulls, matches the spec's "sort by
// sequence (non-null first)" wording.

export interface OrderedAttempt {
  attempt:   Attempt
  sequence:  number | null
  arrival:   number
}

function orderAttempts(
  attempts: Attempt[],
  seqById:  Record<string, number | null>,
  arrById:  Record<string, number>,
): OrderedAttempt[] {
  const rows: OrderedAttempt[] = attempts.map((a) => ({
    attempt:  a,
    sequence: seqById[a.attempt_id] ?? null,
    arrival:  arrById[a.attempt_id] ?? Number.MAX_SAFE_INTEGER,
  }))
  rows.sort((x, y) => {
    // Non-null sequences first; among non-nulls, ascending.
    if (x.sequence === null && y.sequence !== null) return 1
    if (x.sequence !== null && y.sequence === null) return -1
    if (x.sequence !== null && y.sequence !== null) {
      if (x.sequence !== y.sequence) return x.sequence - y.sequence
    }
    // Tie-breaker.
    return x.arrival - y.arrival
  })
  return rows
}

// ── Straggler flag ─────────────────────────────────────────────────────────
//
// Backend stamps `meta.is_straggler = true` on attempts that arrived AFTER
// simulation.probe_completed was emitted for their probe.  These are late
// frames / replay — they are valid attempts but the authoritative
// per-probe counts are already frozen.  The UI renders a ⚠ badge on
// stragglers so operators aren't confused by Timeline/ProbeResults drift.

export const isStraggler = (a: Attempt): boolean =>
  a.meta?.is_straggler === true

// ── Primitive accessors ─────────────────────────────────────────────────────

/**
 * The canonical ordered list of attempts.  Every other selector that
 * needs order MUST go through this so all views agree.
 */
export function useOrderedAttempts(): OrderedAttempt[] {
  const order   = useSimulationStore((s) => s.attemptOrder)
  const byId    = useSimulationStore((s) => s.attemptsById)
  const seqById = useSimulationStore((s) => s.attemptSequenceById)
  const arrById = useSimulationStore((s) => s.arrivalById)
  return useMemo(() => {
    const attempts = order.map((id) => byId[id]).filter((a): a is Attempt => Boolean(a))
    return orderAttempts(attempts, seqById, arrById)
  }, [order, byId, seqById, arrById])
}

/** Convenience — just the attempts in canonical order. */
export const useAttempts = (): Attempt[] => {
  const ordered = useOrderedAttempts()
  return useMemo(() => ordered.map((r) => r.attempt), [ordered])
}

export const useStatus      = () => useSimulationStore((s) => s.status)
export const useSummary     = () => useSimulationStore((s) => s.summary)
export const useWarnings    = () => useSimulationStore((s) => s.warnings)
export const useSession     = () => useSimulationStore((s) => s.session)
export const useActiveProbe = () => useSimulationStore((s) => s.activeProbe)
export const useProbeRuns   = () => useSimulationStore((s) => s.probeRunState)

// ── Summary tab ─────────────────────────────────────────────────────────────

export interface SummaryView {
  disposition:    'blocked' | 'allowed' | 'mixed' | 'error' | 'pending'
  probe_count:    number
  attempt_count:  number
  blocked:        number
  allowed:        number
  errors:         number
  peak_risk:      number
  elapsed_ms:     number
  triggered_policies: string[]
}

export function useSummaryView(): SummaryView {
  const summary  = useSummary()
  const attempts = useAttempts()
  const status   = useStatus()
  const started  = useSimulationStore((s) => s.startedAt)
  const done     = useSimulationStore((s) => s.completedAt)

  return useMemo(() => {
    // Prefer backend summary; derive if not yet received.
    const blocked = summary?.blocked_count ?? attempts.filter((a) => a.result === 'blocked').length
    const allowed = summary?.allowed_count ?? attempts.filter((a) => a.result === 'allowed').length
    const errors  = summary?.error_count   ?? attempts.filter((a) => a.result === 'error').length
    const peak    = summary?.peak_risk_score ?? attempts.reduce((m, a) => Math.max(m, a.risk_score), 0)
    const elapsed = summary?.elapsed_ms ?? ((done ?? Date.now()) - (started ?? Date.now()))
    const policies = summary?.triggered_policies ?? Array.from(
      new Set(attempts.flatMap((a) => (a.guard_decision?.policy_id ? [a.guard_decision.policy_id] : []))),
    ).sort()
    const probe_count = summary?.probe_count ?? new Set(attempts.map((a) => a.probe)).size

    let disposition: SummaryView['disposition']
    if (status === 'failed')                     disposition = 'error'
    else if (attempts.length === 0)              disposition = 'pending'
    else if (errors === attempts.length)         disposition = 'error'
    else if (blocked > 0 && allowed > 0)         disposition = 'mixed'
    else if (blocked > 0)                        disposition = 'blocked'
    else                                         disposition = 'allowed'

    return {
      disposition,
      probe_count,
      attempt_count: summary?.attempt_count ?? attempts.length,
      blocked, allowed, errors,
      peak_risk:  peak,
      elapsed_ms: elapsed,
      triggered_policies: policies,
    }
  }, [summary, attempts, status, started, done])
}

// ── Decision Trace ─────────────────────────────────────────────────────────

export function useDecisionTrace(): Attempt[] {
  return useAttempts()   // already in canonical order
}

// ── Output tab — attempts that reached the model ───────────────────────────

export interface OutputRow {
  attempt_id:      string
  probe:           string
  probe_raw:       string
  category:        string
  phase:           AttemptPhase
  prompt:          string
  response:        string
  started_at:      string
  completed_at:    string | null
  latency_ms:      number | null
  risk_score:      number
  result:          Attempt['result']
}

/**
 * Output tab — shows ONLY attempts that actually invoked the model.
 *
 * Blocked-pre-model attempts have `model_invoked === false` and no
 * response — they belong on the Decision Trace, not here.  The schema
 * guarantees `model_response === null` when `model_invoked === false`,
 * so this filter also lets us type-narrow `response` to a string.
 */
export function useOutputView(): OutputRow[] {
  const attempts = useAttempts()
  return useMemo(
    () =>
      attempts
        .filter((a) => a.model_invoked && a.model_response !== null)
        .map<OutputRow>((a) => ({
          attempt_id:   a.attempt_id,
          probe:        a.probe,
          probe_raw:    a.probe_raw,
          category:     a.category,
          phase:        a.phase,
          prompt:       a.prompt_raw,
          response:     a.model_response ?? '',
          started_at:   a.started_at,
          completed_at: a.completed_at,
          latency_ms:   a.latency_ms,
          risk_score:   a.risk_score,
          result:       a.result,
        })),
    [attempts],
  )
}

// ── Timeline grouped by phase ──────────────────────────────────────────────

export interface PhaseGroup {
  phase:    AttemptPhase
  label:    string
  attempts: Attempt[]   // already in canonical (sequence,arrival) order
}

const PHASE_LABELS: Record<AttemptPhase, string> = {
  recon:        'Recon',
  exploit:      'Exploit',
  evasion:      'Evasion',
  execution:    'Execution',
  exfiltration: 'Exfiltration',
  other:        'Other',
}
const PHASE_ORDER: AttemptPhase[] = [
  'recon', 'exploit', 'evasion', 'execution', 'exfiltration', 'other',
]

export function useTimelineByPhase(): PhaseGroup[] {
  const attempts = useAttempts()
  return useMemo(() => {
    const buckets = new Map<AttemptPhase, Attempt[]>(PHASE_ORDER.map((p) => [p, []]))
    for (const a of attempts) {
      const bucket = buckets.get(a.phase)
      if (bucket) bucket.push(a)
      else buckets.set(a.phase, [a])
    }
    return PHASE_ORDER
      .map<PhaseGroup>((p) => ({ phase: p, label: PHASE_LABELS[p], attempts: buckets.get(p) ?? [] }))
      .filter((g) => g.attempts.length > 0)
  }, [attempts])
}

// ── Probe timeline headings ────────────────────────────────────────────────

export interface ProbeTimelineRow {
  probe:              string
  probe_raw:          string
  category:           string
  phase:              AttemptPhase
  started_at:         string
  ended_at:           string | null
  probe_duration_ms:  number | null
  completed:          boolean
  attempt_count:      number
}

export function useProbeTimeline(): ProbeTimelineRow[] {
  const runs = useProbeRuns()
  return useMemo(() => {
    return Object.values(runs)
      .sort((a, b) => a.index - b.index)
      .map<ProbeTimelineRow>((r) => ({
        probe:             r.probe,
        probe_raw:         r.probe_raw,
        category:          r.category,
        phase:             r.phase,
        started_at:        r.started_at,
        ended_at:          r.ended_at,
        probe_duration_ms: r.probe_duration_ms,
        completed:         r.completed,
        attempt_count:     r.attempt_count,
      }))
  }, [runs])
}

// ── Explainability grouped by probe → attempts ─────────────────────────────

export interface ProbeGroup {
  probe:    string
  category: string
  phase:    AttemptPhase
  attempts: Attempt[]
  run:      ProbeRunState | undefined
}

export function useAttemptsByProbe(): ProbeGroup[] {
  const attempts = useAttempts()
  const runs     = useProbeRuns()
  return useMemo(() => {
    const order: string[] = []
    const map = new Map<string, Attempt[]>()
    for (const a of attempts) {
      if (!map.has(a.probe)) { map.set(a.probe, []); order.push(a.probe) }
      map.get(a.probe)!.push(a)
    }
    return order.map<ProbeGroup>((probe) => ({
      probe,
      category: map.get(probe)![0].category,
      phase:    map.get(probe)![0].phase,
      attempts: map.get(probe)!,
      run:      runs[probe],
    }))
  }, [attempts, runs])
}

// ── Policy Impact ──────────────────────────────────────────────────────────

export interface PolicyImpactRow {
  policy_id:       string
  policy_name:     string
  is_unresolved:   boolean    // true iff policy_id starts with '__unresolved__:'
  blocked_count:   number
  allowed_count:   number
  review_count:    number
  affected_probes: string[]
  avg_score:       number
  reasons:         Array<{ reason: string; count: number }>
}

export function usePolicyImpact(): PolicyImpactRow[] {
  const attempts = useAttempts()
  return useMemo(() => {
    type Agg = {
      name:       string
      unresolved: boolean
      blocked:    number
      allowed:    number
      review:     number
      probes:     Set<string>
      scoreSum:   number
      scoreN:     number
      reasons:    Map<string, number>
    }
    const by = new Map<string, Agg>()
    for (const a of attempts) {
      const gd: GuardDecision | null = a.guard_decision
      if (!gd) continue
      const agg = by.get(gd.policy_id) ?? {
        name:       gd.policy_name,
        unresolved: isUnresolvedPolicy(gd),
        blocked: 0, allowed: 0, review: 0,
        probes: new Set<string>(), scoreSum: 0, scoreN: 0,
        reasons: new Map<string, number>(),
      }
      agg.probes.add(a.probe)
      agg.scoreSum += gd.score; agg.scoreN += 1
      if (gd.action === 'block')       agg.blocked++
      else if (gd.action === 'allow')  agg.allowed++
      else if (gd.action === 'review') agg.review++
      if (gd.reason) agg.reasons.set(gd.reason, (agg.reasons.get(gd.reason) ?? 0) + 1)
      by.set(gd.policy_id, agg)
    }
    return [...by.entries()]
      .map<PolicyImpactRow>(([policy_id, agg]) => ({
        policy_id,
        policy_name:     agg.name,
        is_unresolved:   agg.unresolved,
        blocked_count:   agg.blocked,
        allowed_count:   agg.allowed,
        review_count:    agg.review,
        affected_probes: [...agg.probes].sort(),
        avg_score:       agg.scoreN ? agg.scoreSum / agg.scoreN : 0,
        reasons:         [...agg.reasons.entries()]
                          .map(([reason, count]) => ({ reason, count }))
                          .sort((a, b) => b.count - a.count),
      }))
      // Unresolved rows sink to the bottom so real policies lead the tab.
      .sort((a, b) => {
        if (a.is_unresolved !== b.is_unresolved) return a.is_unresolved ? 1 : -1
        return (b.blocked_count + b.review_count) - (a.blocked_count + a.review_count)
      })
  }, [attempts])
}

// ── Risk over time ─────────────────────────────────────────────────────────

export interface RiskPoint {
  /** X-axis — envelope sequence when available; arrival index otherwise.
   *  This is stable and monotonic; chart libraries can scale directly. */
  x:          number
  attempt_id: string
  sequence:   number | null
  arrival:    number
  timestamp:  string
  probe:      string
  category:   string
  risk:       number
  result:     Attempt['result']
}

export function useRiskSeries(): RiskPoint[] {
  const ordered = useOrderedAttempts()
  return useMemo(
    () =>
      ordered.map<RiskPoint>((o) => ({
        x:          o.sequence ?? o.arrival,
        attempt_id: o.attempt.attempt_id,
        sequence:   o.sequence,
        arrival:    o.arrival,
        timestamp:  o.attempt.started_at,
        probe:      o.attempt.probe,
        category:   o.attempt.category,
        risk:       o.attempt.risk_score,
        result:     o.attempt.result,
      })),
    [ordered],
  )
}

// ── Probe Results tab ──────────────────────────────────────────────────────

export interface ProbeResultRow {
  probe:        string
  category:     string
  phase:        AttemptPhase
  status:       'running' | 'completed' | 'failed'
  attempts:     number
  blocked:      number
  allowed:      number
  errors:       number
  avg_score:    number
  last_update:  string | null
  duration_ms:  number | null
}

export function useProbeResults(): ProbeResultRow[] {
  const groups = useAttemptsByProbe()
  const active = useActiveProbe()
  return useMemo(
    () =>
      groups.map<ProbeResultRow>((g) => {
        const run = g.run
        const scored = g.attempts.filter((a) => a.guard_decision)
        const avg = scored.length
          ? scored.reduce((s, a) => s + (a.guard_decision?.score ?? 0), 0) / scored.length
          : 0
        const last = g.attempts.reduce<string | null>(
          (m, a) => (a.completed_at && (!m || a.completed_at > m) ? a.completed_at : m),
          null,
        )
        // Prefer authoritative probe_completed counts when present.
        const attemptsN = run?.completed ? run.attempt_count : g.attempts.length
        const blocked   = run?.completed ? run.blocked_count : g.attempts.filter((a) => a.result === 'blocked').length
        const allowed   = run?.completed ? run.allowed_count : g.attempts.filter((a) => a.result === 'allowed').length
        const errors    = run?.completed ? run.error_count   : g.attempts.filter((a) => a.result === 'error').length
        const status: ProbeResultRow['status'] =
          active === g.probe ? 'running' :
          attemptsN > 0 && errors === attemptsN ? 'failed' :
          'completed'
        return {
          probe:       g.probe,
          category:    g.category,
          phase:       g.phase,
          status,
          attempts:    attemptsN,
          blocked, allowed, errors,
          avg_score:   avg,
          last_update: last,
          duration_ms: run?.probe_duration_ms ?? null,
        }
      }),
    [groups, active],
  )
}

// ── Coverage by category ───────────────────────────────────────────────────

export interface CoverageRow {
  category:     string
  probes_run:   string[]
  attempts:     number
  blocked:      number
  block_rate:   number   // 0..1
  confidence:   number   // 0..1 — attempts / expected
}

const EXPECTED_ATTEMPTS_PER_CATEGORY = 5

export function useCoverage(): CoverageRow[] {
  const attempts = useAttempts()
  return useMemo(() => {
    const by = new Map<string, { probes: Set<string>; attempts: number; blocked: number }>()
    for (const a of attempts) {
      const row = by.get(a.category) ?? { probes: new Set(), attempts: 0, blocked: 0 }
      row.probes.add(a.probe)
      row.attempts += 1
      if (a.result === 'blocked') row.blocked += 1
      by.set(a.category, row)
    }
    return [...by.entries()]
      .map<CoverageRow>(([category, r]) => ({
        category,
        probes_run:  [...r.probes].sort(),
        attempts:    r.attempts,
        blocked:     r.blocked,
        block_rate:  r.attempts ? r.blocked / r.attempts : 0,
        confidence:  Math.min(1, r.attempts / EXPECTED_ATTEMPTS_PER_CATEGORY),
      }))
      .sort((a, b) => b.attempts - a.attempts)
  }, [attempts])
}

// ── Recommendations (deterministic, rule-based) ────────────────────────────

export interface Recommendation {
  id:       string
  severity: 'info' | 'warning' | 'high'
  title:    string
  detail:   string
}

export function useRecommendations(): Recommendation[] {
  const attempts = useAttempts()
  const policies = usePolicyImpact()
  const warnings = useWarnings()
  return useMemo(() => {
    const out: Recommendation[] = []

    // 1.  Any unknown-probe warning → actionable gap.
    for (const w of warnings) {
      if (w.code === 'unknown_probe') {
        const raw = (w.detail as { raw?: string; probe_name?: string } | undefined)?.raw
                 ?? (w.detail as { probe_name?: string } | undefined)?.probe_name
                 ?? '?'
        out.push({
          id: `unknown_probe:${raw}:${w.sequence ?? w.arrival}`,
          severity: 'warning',
          title: 'Unmapped probe detected',
          detail: `Probe ${raw} has no registry entry — add a policy mapping.`,
        })
      }
    }

    // 2.  Unresolved-policy rows → mapping gap between pipeline + guard config.
    for (const p of policies) {
      if (p.is_unresolved) {
        out.push({
          id: `unresolved_policy:${p.policy_id}`,
          severity: 'warning',
          title: 'Guard fired without policy metadata',
          detail: `Probe(s) ${p.affected_probes.join(', ')} triggered a guard decision but the pipeline returned no policy_id/policy_name.  Add the mapping to your guard config.`,
        })
      }
    }

    // 3.  Policies with block-rate = 0 but avg score ≥ 0.4 → threshold tuning.
    for (const p of policies) {
      if (!p.is_unresolved && p.blocked_count === 0 && p.avg_score >= 0.4 && p.allowed_count > 0) {
        out.push({
          id: `tune_threshold:${p.policy_id}`,
          severity: 'warning',
          title: `Consider lowering threshold on ${p.policy_name}`,
          detail: `Policy never blocked despite avg score ${p.avg_score.toFixed(2)} across ${p.allowed_count} attempts.`,
        })
      }
    }

    // 4.  High-risk allowed attempts → secondary sanitisation.
    const risky = attempts.filter((a) => a.result === 'allowed' && a.risk_score >= 70)
    if (risky.length > 0) {
      out.push({
        id: 'secondary_sanitisation',
        severity: 'high',
        title: 'High-risk content was allowed',
        detail: `${risky.length} attempt(s) scored ≥70 but were not blocked. Consider an output-side scan.`,
      })
    }

    // 5.  Tool-abuse allowed → review.
    const toolAbuseAllowed = attempts.filter((a) => a.probe === 'tooluse' && a.result === 'allowed')
    if (toolAbuseAllowed.length > 0) {
      out.push({
        id: 'tool_use_review',
        severity: 'high',
        title: 'Tool-abuse attempts were not blocked',
        detail: `${toolAbuseAllowed.length} tool-abuse attempt(s) succeeded. Review tool-permission policies.`,
      })
    }

    // 6.  Every attempt errored → runtime health.
    if (attempts.length > 0 && attempts.every((a) => a.result === 'error')) {
      out.push({
        id: 'all_errors',
        severity: 'high',
        title: 'All attempts errored',
        detail: 'The simulation produced no successful attempts.  Check runner logs and pipeline connectivity before interpreting results.',
      })
    }

    // 7.  Transport stress (queue overflow / slow client) → capacity issue.
    const transportIssues = warnings.filter((w) =>
      w.code === 'WS_QUEUE_OVERFLOW' ||
      w.code === 'SLOW_CLIENT' ||
      w.code === 'PRECONNECT_BUFFER_OVERFLOW')
    if (transportIssues.length > 0) {
      out.push({
        id: 'ws_transport_pressure',
        severity: 'warning',
        title: 'WebSocket transport reported backpressure',
        detail: `${transportIssues.length} transport warning(s) during this run — some frames may have been dropped before reaching the browser.  Verify UI state matches backend summary.`,
      })
    }

    return out
  }, [attempts, policies, warnings])
}
