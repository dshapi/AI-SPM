/**
 * simulation/ProbeErrorCard.jsx
 * ──────────────────────────────
 * Compact Timeline card for attempts that represent a PROBE-LEVEL failure
 * (e.g. timeout, Garak runner crash, exception in probe setup) rather than
 * an attempt-level outcome.  These rows are synthesised in
 * buildAttemptsFromEvents.js from simulation.probe_error envelopes, so they
 * carry NO prompt, NO model response, and NO guard decision — the probe
 * never got far enough to emit those.
 *
 * Why a dedicated card?
 * ─────────────────────
 * FullAttemptCard would render empty Prompt / Response / Guard sections
 * (misleading), and GuardOnlyCard's copy says "guard intercepted" (also
 * misleading — the guard never ran).  A dedicated card lets the Timeline
 * honestly communicate: "this probe failed at the infrastructure layer
 * before any attempt could be evaluated."
 *
 * Contract
 * ────────
 * • Rendered by AttemptCard when row.type === 'probe_error'.
 * • Routed here by classifyAttempt when attempt.meta.probe_error === true.
 * • Header shows probe, error summary, severity pill.
 * • Expanding reveals the lineage (attempt_id, correlation_id, timestamps)
 *   plus the full error message.  Never shows prompt/response/guard
 *   sections — they don't exist for this event.
 *
 * Visual language mirrors GuardOnlyCard so probe-error rows sit as peers
 * next to full and guard-only rows in the same phase.  Palette is
 * intentionally orange (matches STATUS_STYLES.error in AttemptCard) so
 * it reads as "error", not as a guard decision.
 */

import { useState } from 'react'
import { AlertOctagon, Clock } from 'lucide-react'
import { cn } from '../lib/utils.js'

// Severity-to-palette map.  Garak reports severity as a free-form string;
// we bucket the common cases and fall back to the generic error palette.
const SEVERITY_STYLES = {
  critical: { label: 'CRITICAL', txt: 'text-red-700',    bg: 'bg-red-50',    border: 'border-red-200'    },
  high:     { label: 'HIGH',     txt: 'text-red-700',    bg: 'bg-red-50',    border: 'border-red-200'    },
  medium:   { label: 'MEDIUM',   txt: 'text-orange-700', bg: 'bg-orange-50', border: 'border-orange-200' },
  low:      { label: 'LOW',      txt: 'text-amber-700',  bg: 'bg-amber-50',  border: 'border-amber-200'  },
  info:     { label: 'INFO',     txt: 'text-gray-600',   bg: 'bg-gray-50',   border: 'border-gray-200'   },
}

// Default palette when no severity is reported — keeps the card orange so
// it reads as an error without overclaiming severity.
const DEFAULT_STYLE = {
  label: 'ERROR',
  txt:   'text-orange-700',
  bg:    'bg-orange-50',
  border:'border-orange-200',
}

function resolveSeverityStyle(severity) {
  const key = typeof severity === 'string' ? severity.toLowerCase() : ''
  return SEVERITY_STYLES[key] ?? DEFAULT_STYLE
}

function formatSeq(sequence, arrival) {
  if (sequence !== null && sequence !== undefined) return `#${sequence}`
  return `·${arrival}`
}

// A probe_error message that contains "timeout" (case-insensitive) is
// surfaced with a clock glyph — by far the most common probe-level
// failure, and operators tend to want to spot them at a glance.
function looksLikeTimeout(message) {
  if (typeof message !== 'string') return false
  return /timeout|timed out/i.test(message)
}

export function ProbeErrorCard({ row }) {
  const { attempt, sequence, arrival, is_straggler } = row
  const [expanded, setExpanded] = useState(false)

  const severity = attempt?.meta?.severity
  const style    = resolveSeverityStyle(severity)
  const message  = attempt.error || 'Probe errored before any attempt could complete'
  const isTimeout = looksLikeTimeout(message)
  const Icon     = isTimeout ? Clock : AlertOctagon

  const summaryId = `attempt-${attempt.attempt_id}-summary`
  const detailsId = `attempt-${attempt.attempt_id}-details`

  return (
    <article
      className={cn(
        'rounded-lg border bg-white overflow-hidden transition-colors',
        style.border,
        is_straggler && 'ring-1 ring-amber-300 ring-offset-0',
      )}
      aria-labelledby={summaryId}
      data-card-variant="probe-error"
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
        <Icon size={13} className={cn('shrink-0', style.txt)} strokeWidth={1.75} aria-hidden="true" />

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
          title={isTimeout
            ? 'Probe exceeded its per-probe timeout budget before any attempt completed.'
            : 'The probe failed at the infrastructure layer; no attempt was evaluated.'}
        >
          {isTimeout ? 'Probe Timeout' : 'Probe Error'}
        </span>

        {severity && (
          <span
            className={cn(
              'shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full border',
              style.bg, style.border, style.txt,
            )}
            title={`Severity reported by Garak: ${severity}`}
          >
            {style.label}
          </span>
        )}

        <span className="ml-auto shrink-0 text-[10px] text-gray-500 truncate max-w-[40%]" title={message}>
          {message}
        </span>

        {is_straggler && (
          <span
            className="shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200"
            title="This probe_error envelope arrived AFTER simulation.probe_completed was emitted for its probe."
            aria-label="Straggler"
          >
            ⚠ Straggler
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
          aria-label={`Probe error for ${attempt.probe}`}
          className="border-t border-gray-100 bg-gray-50/40 px-3 py-3 space-y-2"
        >
          <p className="inline-flex items-center gap-1.5 text-[11px] font-medium text-gray-700">
            <Icon size={12} className={style.txt} strokeWidth={2} />
            {isTimeout
              ? 'Probe exceeded its per-probe timeout — no attempts completed.'
              : 'Probe failed at the infrastructure layer — no attempts completed.'}
          </p>

          <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-gray-500 font-medium">Probe</dt>
            <dd className="text-gray-800">{attempt.probe}</dd>

            {attempt.probe_raw && attempt.probe_raw !== attempt.probe && (
              <>
                <dt className="text-gray-500 font-medium">Probe (raw)</dt>
                <dd className="text-gray-800 font-mono text-[10.5px]">{attempt.probe_raw}</dd>
              </>
            )}

            <dt className="text-gray-500 font-medium">Phase</dt>
            <dd className="text-gray-800">{attempt.phase}</dd>

            <dt className="text-gray-500 font-medium">Category</dt>
            <dd className="text-gray-800">{attempt.category}</dd>

            {severity && (
              <>
                <dt className="text-gray-500 font-medium">Severity</dt>
                <dd className="text-gray-800">{severity}</dd>
              </>
            )}

            <dt className="text-gray-500 font-medium">attempt_id</dt>
            <dd>
              <code className="font-mono text-[10.5px]">{attempt.attempt_id}</code>
            </dd>

            {attempt.session_id && (
              <>
                <dt className="text-gray-500 font-medium">session_id</dt>
                <dd>
                  <code className="font-mono text-[10.5px]">{attempt.session_id}</code>
                </dd>
              </>
            )}

            {attempt.started_at && (
              <>
                <dt className="text-gray-500 font-medium">started_at</dt>
                <dd className="text-gray-800">{attempt.started_at}</dd>
              </>
            )}

            {attempt.completed_at && (
              <>
                <dt className="text-gray-500 font-medium">completed_at</dt>
                <dd className="text-gray-800">{attempt.completed_at}</dd>
              </>
            )}
          </dl>

          <section>
            <h4 className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5">
              Error
            </h4>
            <pre
              className={cn(
                'text-[10.5px] font-mono whitespace-pre-wrap break-words rounded-lg px-3 py-2 border',
                style.txt, style.bg, style.border,
              )}
              data-testid="probe-error-message"
            >
              {message}
            </pre>
          </section>
        </div>
      )}
    </article>
  )
}

export default ProbeErrorCard
