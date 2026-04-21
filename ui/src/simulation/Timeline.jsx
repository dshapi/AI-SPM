/**
 * simulation/Timeline.jsx
 * ────────────────────────
 * Attempt-based Timeline tab for the Simulation Lab.
 *
 * Contract (non-negotiable — see docs/refactor/garak-integration/02-frontend/
 * TIMELINE_MIGRATION.md):
 *   • Renders ONLY Attempt rows, grouped by kill-chain phase.
 *   • Does NOT render raw envelope events — they're aggregated into
 *     Attempts by buildAttemptsFromEvents() before rendering.
 *   • Lineage metadata appears ONLY inside an expanded AttemptCard.
 *   • Ordering within a phase is currently arrival-asc; once the backend
 *     emits envelope sequences per attempt, the comparator will switch to
 *     (sequence asc nulls last, arrival asc) without a UI change.
 *
 * Props
 * ─────
 * Matches the legacy components/simulation/Timeline.jsx props so this is a
 * drop-in replacement at the ResultsPanel call site:
 *   simulationState  SimulationState  — from useSimulationState()
 *   mode             'single'|'garak' — reserved (not used yet — attempt
 *                                       grouping is mode-agnostic)
 *   selectedId       string|null      — reserved for future selection UX
 *   onSelect         function         — reserved for future selection UX
 */

import { useMemo } from 'react'
import { cn } from '../lib/utils.js'
import { buildAttemptsFromEvents, buildTimelineView } from './buildAttemptsFromEvents.js'
import { PhaseSection } from './PhaseSection.jsx'

// ── Status label (mirrors legacy Timeline so the header looks familiar) ───

function StatusLabel({ status }) {
  if (status === 'running') {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-emerald-600 font-semibold">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse inline-block" />
        LIVE
      </span>
    )
  }
  if (status === 'completed') return <span className="text-[11px] text-gray-400">Completed</span>
  if (status === 'failed')    return <span className="text-[11px] text-red-500 font-medium">Failed</span>
  return <span className="text-[11px] text-gray-400">Idle</span>
}

// ── Timeline ──────────────────────────────────────────────────────────────

export function Timeline({ simulationState /* , mode, selectedId, onSelect */ }) {
  const {
    status    = 'idle',
    simEvents = [],
  } = simulationState ?? {}

  // useMemo so re-ordering / re-grouping happens only when the event list
  // changes — the parent re-renders on every tab switch, and we don't want
  // to pay the full aggregation cost each time.
  const view = useMemo(
    () => buildTimelineView(buildAttemptsFromEvents(simEvents).attempts),
    [simEvents],
  )

  // Empty state — still show the status label so operators know whether
  // they're waiting for events or simply haven't run anything.
  if (view.phases.length === 0) {
    return (
      <div className="p-4" role="region" aria-label="Timeline">
        <div className="mb-3">
          <StatusLabel status={status} />
        </div>
        <p className="text-[12px] text-gray-400">
          {status === 'idle'
            ? 'Run a simulation to see attempts here.'
            : status === 'running'
              ? 'Waiting for probe results…'
              : 'No attempts recorded.'}
        </p>
      </div>
    )
  }

  return (
    <section className="p-4 space-y-3" role="region" aria-label="Timeline">
      <header className="flex items-center gap-3">
        <StatusLabel status={status} />
        <div className="ml-auto">
          <RollupBar rollup={view.rollup} variant="total" />
        </div>
      </header>
      <ol className="space-y-2">
        {view.phases.map(group => (
          <li key={group.phase}>
            <PhaseSection group={group} />
          </li>
        ))}
      </ol>
    </section>
  )
}

// ── RollupBar ─────────────────────────────────────────────────────────────
//
// Shared between the Timeline header (grand total) and PhaseSection (per
// phase).  Same visual component, same semantics, different data source.
// `variant` tunes whitespace — the total bar sits in a bigger header; the
// phase bar is tucked next to the phase label.

export function RollupBar({ rollup, variant = 'total' }) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1',
        variant === 'phase' ? 'text-[9.5px]' : 'text-[10.5px]',
      )}
      role="group"
      aria-label={variant === 'total' ? 'Total attempts' : 'Phase attempts'}
    >
      <RollupChip tone="total"   glyph="Σ"  count={rollup.total}   label="Total"   variant={variant} />
      <RollupChip tone="blocked" glyph="🔴" count={rollup.blocked} label="Blocked" variant={variant} />
      <RollupChip tone="allowed" glyph="🟢" count={rollup.allowed} label="Allowed" variant={variant} />
      <RollupChip tone="error"   glyph="🟠" count={rollup.error}   label="Error"   variant={variant} />
      <RollupChip tone="running" glyph="🟡" count={rollup.running} label="Running" variant={variant} />
    </div>
  )
}

function RollupChip({ tone, glyph, count, label, variant }) {
  // Zero chips stay visible but dimmed so operators can tell the difference
  // between "genuinely zero" and "missing data".
  const isZero = count === 0
  const toneClass =
    tone === 'blocked' ? 'text-red-600'
      : tone === 'allowed' ? 'text-emerald-600'
      : tone === 'error'   ? 'text-orange-600'
      : tone === 'running' ? 'text-amber-600'
      : 'text-gray-700'

  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 rounded-full border px-1.5',
        variant === 'phase' ? 'py-0' : 'py-0.5',
        isZero ? 'border-gray-200 bg-gray-50 opacity-60' : 'border-gray-200 bg-white',
      )}
      title={`${label}: ${count}`}
    >
      <span aria-hidden="true">{glyph}</span>
      <span className={cn('font-bold tabular-nums', toneClass)}>{count}</span>
    </span>
  )
}

export default Timeline
