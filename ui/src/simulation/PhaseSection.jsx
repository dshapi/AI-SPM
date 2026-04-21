/**
 * simulation/PhaseSection.jsx
 * ─────────────────────────────
 * Collapsible phase group for the new attempt-based Timeline tab.  Header
 * shows the phase label plus a rollup bar (total / blocked / allowed / error
 * / running) — visible even when the section is collapsed so operators can
 * scan the kill chain at a glance without expanding every phase.
 *
 * The expand/collapse control is a single <button> so it's keyboard-
 * navigable and screen-reader friendly.  `aria-expanded` / `aria-controls`
 * wire the header to the attempt-list region per WAI-ARIA practice.
 *
 * Rollup semantics
 * ────────────────
 * A phase with any terminal activity (blocked + allowed + error > 0) is
 * expanded by default; a phase with only running attempts stays collapsed
 * so live-runs aren't overwhelming.  The header rollup still communicates
 * "in flight" without forcing the user to see every row.
 */

import { useState } from 'react'
import { cn } from '../lib/utils.js'
import { AttemptCard } from './AttemptCard.jsx'
import { RollupBar } from './Timeline.jsx'

// Phase accent colours — mirror the kill-chain reading direction so the
// user's eye moves through recon → exploit → … → exfiltration.
const PHASE_ACCENT = {
  recon:        'border-l-blue-400',
  exploit:      'border-l-red-400',
  evasion:      'border-l-amber-400',
  execution:    'border-l-purple-400',
  exfiltration: 'border-l-orange-400',
  other:        'border-l-gray-300',
}

export function PhaseSection({ group, defaultExpanded }) {
  const initialExpanded =
    defaultExpanded
    ?? (group.rollup.blocked + group.rollup.allowed + group.rollup.error) > 0

  const [expanded, setExpanded] = useState(initialExpanded)

  const headerId = `timeline-phase-${group.phase}-header`
  const bodyId   = `timeline-phase-${group.phase}-body`

  return (
    <section
      className={cn(
        'rounded-lg border border-gray-200 border-l-4 bg-white overflow-hidden',
        PHASE_ACCENT[group.phase] ?? 'border-l-gray-300',
      )}
      aria-labelledby={headerId}
      data-testid={`phase-section-${group.phase}`}
    >
      <button
        id={headerId}
        type="button"
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 text-left transition-colors',
          'hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-inset',
        )}
        aria-expanded={expanded}
        aria-controls={bodyId}
        onClick={() => setExpanded(v => !v)}
      >
        <span className="shrink-0 text-[10px] text-gray-400" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
        <span className="text-[11px] font-bold uppercase tracking-wider text-gray-700 shrink-0">
          {group.label}
        </span>
        <span
          className="text-[10px] text-gray-400 font-mono tabular-nums shrink-0"
          aria-label={`${group.rollup.total} attempts`}
        >
          ({group.rollup.total})
        </span>
        <span className="ml-auto shrink-0">
          <RollupBar rollup={group.rollup} variant="phase" />
        </span>
      </button>

      {expanded && (
        <ol
          id={bodyId}
          className="px-3 py-2 space-y-1.5 border-t border-gray-100"
          aria-label={`${group.label} attempts`}
        >
          {group.rows.map(row => (
            <li key={row.attempt.attempt_id}>
              <AttemptCard row={row} />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export default PhaseSection
