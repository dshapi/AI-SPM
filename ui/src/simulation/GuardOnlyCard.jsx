/**
 * simulation/GuardOnlyCard.jsx
 * ─────────────────────────────
 * Compact Timeline card for attempts where the guard short-circuited
 * execution BEFORE the model was invoked.  These attempts have a valid
 * guard decision but no prompt/response pair, so the full detail card is
 * misleading — its prompt and response sections would render empty.
 *
 * Contract
 * ────────
 * • Rendered by AttemptCard when row.type === 'guard_only'.
 * • Never displays prompt/response slots.  Displays:
 *     - guard action + score (threshold if known)
 *     - source probe
 *     - unresolved-policy badge if the guard fired without a named policy
 * • Expanding the card reveals the full guard-decision detail block but
 *   never synthesises missing prompt/response fields.
 *
 * Visual language is borrowed from AttemptCard so the two rendering paths
 * look like peers of the same component, not two different widgets.
 */

import { useState } from 'react'
import { Shield, AlertTriangle } from 'lucide-react'
import { cn } from '../lib/utils.js'
import { isUnresolvedPolicy } from '../lib/policyResolution.js'

// Mirror AttemptCard's palette so guard-only rows sit comfortably next to
// full rows in the same phase.
const DECISION_STYLES = {
  BLOCK:    { glyph: '🔴', label: 'BLOCKED',   txt: 'text-red-700',     bg: 'bg-red-50',    border: 'border-red-200'    },
  ESCALATE: { glyph: '🟠', label: 'ESCALATED', txt: 'text-orange-700',  bg: 'bg-orange-50', border: 'border-orange-200' },
  FLAG:     { glyph: '🟡', label: 'FLAGGED',   txt: 'text-amber-700',   bg: 'bg-amber-50',  border: 'border-amber-200'  },
  ALLOW:    { glyph: '🟢', label: 'ALLOWED',   txt: 'text-emerald-700', bg: 'bg-emerald-50',border: 'border-emerald-200'},
  SKIP:     { glyph: '⚪', label: 'SKIPPED',   txt: 'text-gray-600',    bg: 'bg-gray-50',   border: 'border-gray-200'   },
}

function resolveDecisionStyle(action) {
  const key = typeof action === 'string' ? action.toUpperCase() : ''
  return DECISION_STYLES[key] ?? DECISION_STYLES.BLOCK
}

function formatScore(n) {
  if (typeof n !== 'number' || Number.isNaN(n)) return '—'
  return n.toFixed(3)
}

function formatSeq(sequence, arrival) {
  if (sequence !== null && sequence !== undefined) return `#${sequence}`
  return `·${arrival}`
}

// Extract the policy name we want to show on the card.  The Attempt's
// guard_decision carries the canonical name.  We accept legacy top-level
// `policy_name` as a fallback so this component is robust to older payloads.
function policyNameOf(attempt) {
  return (
    attempt?.guard_decision?.policy_name
    ?? attempt?.policy_name
    ?? null
  )
}

/**
 * Build the one-line explanatory subtitle shown at the top of the expanded
 * detail panel.  The goal is to tell operators WHICH security outcome this
 * card represents without resorting to Garak's confusing Pass/Fail vocabulary.
 *
 * Priority order:
 *   1. defense_outcome from the backend ("stopped" / "missed") — most
 *      specific; comes from the Garak probe's own verdict translated at
 *      the service boundary in services/garak/main.py.
 *   2. A real score that crossed a real threshold — say so explicitly.
 *   3. Nothing — leave the subtitle empty (the card still shows the action,
 *      reason, and source probe rows below).
 */
function describeOutcome(attempt, decision) {
  const outcome = attempt?.meta?.defense_outcome
  const probe   = attempt?.probe

  if (outcome === 'stopped' && probe) return `Defense stopped ${probe} probe`
  if (outcome === 'missed'  && probe) return `Defense missed ${probe} probe`

  const score     = decision?.score
  const threshold = decision?.threshold
  if (typeof score === 'number' && typeof threshold === 'number' && score > threshold) {
    return 'Guard score exceeded threshold'
  }

  return null
}

export function GuardOnlyCard({ row }) {
  const { attempt, sequence, arrival, is_straggler } = row
  const [expanded, setExpanded] = useState(false)

  const decision        = attempt.guard_decision ?? {}
  const defenseOutcome  = attempt?.meta?.defense_outcome
  const unresolved      = isUnresolvedPolicy(policyNameOf(attempt))
  const subtitle        = describeOutcome(attempt, decision)

  // Colour tracks our guard's ACTUAL action, not the probe's severity.
  //   • defense_outcome "stopped" → our guard blocked → red (BLOCK palette)
  //   • defense_outcome "missed"  → our guard allowed → green (ALLOW palette),
  //     because the guard did not block — Garak's detector caught the model
  //     being fooled after the fact.  Showing red here would falsely imply
  //     our guard stopped something when it did not.
  //   • null/unknown              → fall back to the decision action, which
  //                                 is correct for single-prompt flows.
  const style =
    defenseOutcome === 'stopped' ? DECISION_STYLES.BLOCK
    : defenseOutcome === 'missed'  ? DECISION_STYLES.ALLOW
    : resolveDecisionStyle(decision.action)

  // The pill text and the header line change meaning with the outcome too —
  // "Guard Intercepted" and "Blocked before model execution" are true for
  // "stopped" but would lie for "missed".
  const pillText = defenseOutcome === 'missed'
    ? 'Guard Allowed — Detector hit'
    : 'Guard Intercepted'
  const pillTitle = defenseOutcome === 'missed'
    ? 'Our guard allowed the prompt; Garak\'s detector caught the model being fooled.'
    : 'Guard blocked before the model was invoked'
  const headerLine = defenseOutcome === 'missed'
    ? 'Model was fooled — Garak detector caught the response'
    : 'Blocked before model execution'

  const summaryId = `attempt-${attempt.attempt_id}-summary`
  const detailsId = `attempt-${attempt.attempt_id}-details`

  return (
    <article
      className={cn(
        'rounded-lg border bg-white overflow-hidden transition-colors',
        style.border,
        is_straggler && 'ring-1 ring-amber-300 ring-offset-0',
        unresolved   && 'ring-1 ring-amber-300 ring-offset-0',
      )}
      aria-labelledby={summaryId}
      data-card-variant="guard-only"
    >
      <button
        id={summaryId}
        type="button"
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 text-left transition-colors',
          'hover:bg-gray-50/60 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-inset',
        )}
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded(v => !v)}
      >
        <Shield size={13} className={cn('shrink-0', style.txt)} strokeWidth={1.75} aria-hidden="true" />

        <span
          className="text-[10px] font-mono text-gray-400 shrink-0 tabular-nums"
          title="Envelope sequence · arrival"
        >
          {formatSeq(sequence, arrival)}
        </span>

        <span className="text-[11.5px] font-semibold text-gray-800 truncate">
          {attempt.probe}
        </span>

        <span
          className={cn(
            'shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full border',
            style.bg, style.border, style.txt,
          )}
          title={pillTitle}
        >
          {pillText}
        </span>

        <span className="ml-auto shrink-0 text-[10.5px] font-bold tabular-nums text-gray-700">
          {formatScore(decision.score)}
        </span>

        {is_straggler && (
          <span
            className="shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200"
            title="This attempt arrived AFTER simulation.probe_completed was emitted for its probe."
            aria-label="Straggler"
          >
            ⚠ Straggler
          </span>
        )}

        {unresolved && (
          <span
            className="shrink-0 inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200"
            title="Guard fired but no policy is mapped to this decision."
            aria-label="Unresolved policy"
          >
            <AlertTriangle size={9} strokeWidth={2.5} />
            Unresolved Policy
          </span>
        )}

        <span className="shrink-0 text-[10px] text-gray-400" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
      </button>

      {expanded && (
        <div
          id={detailsId}
          role="region"
          aria-label={`Guard decision for ${attempt.probe}`}
          className="border-t border-gray-100 bg-gray-50/40 px-3 py-3 space-y-2"
        >
          <p className="inline-flex items-center gap-1.5 text-[11px] font-medium text-gray-700">
            <Shield size={12} className="text-gray-500" strokeWidth={2} />
            {headerLine}
          </p>

          {subtitle && (
            <p
              className="text-[11px] text-gray-600 italic"
              data-testid="guard-only-subtitle"
            >
              {subtitle}
            </p>
          )}

          <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-gray-500 font-medium">Action</dt>
            <dd className="text-gray-800 font-semibold">{decision.action || '—'}</dd>

            <dt className="text-gray-500 font-medium">Score</dt>
            <dd className="text-gray-800 tabular-nums">{formatScore(decision.score)}</dd>

            {typeof decision.threshold === 'number' && (
              <>
                <dt className="text-gray-500 font-medium">Threshold</dt>
                <dd className="text-gray-800 tabular-nums">{formatScore(decision.threshold)}</dd>
              </>
            )}

            <dt className="text-gray-500 font-medium">Source probe</dt>
            <dd className="text-gray-800">{attempt.probe}</dd>

            {decision.reason && (
              <>
                <dt className="text-gray-500 font-medium">Reason</dt>
                <dd className="text-gray-800">{decision.reason}</dd>
              </>
            )}
          </dl>
        </div>
      )}
    </article>
  )
}

export default GuardOnlyCard
