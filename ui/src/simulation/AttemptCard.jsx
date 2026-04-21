/**
 * simulation/AttemptCard.jsx
 * ───────────────────────────
 * One row per attempt in the Timeline.  The component is a SWITCH — it
 * routes to GuardOnlyCard, ProbeErrorCard, or FullAttemptCard based on
 * row.type (stamped by buildTimelineView via classifyAttempt).  Invalid
 * attempts are filtered upstream and never reach this component.
 *
 * Variants
 * ────────
 *   row.type === 'guard_only'  → GuardOnlyCard    (compact; guard short-circuit)
 *   row.type === 'probe_error' → ProbeErrorCard   (compact; probe-level failure)
 *   row.type === 'full'        → FullAttemptCard  (detailed; prompt + response)
 *
 * Status resolution (FullAttemptCard)
 * ───────────────────────────────────
 *   status==='running' or no result    → 🟡 RUNNING
 *   result==='blocked'                 → 🔴 BLOCKED
 *   result==='allowed'                 → 🟢 ALLOWED
 *   result==='error'                   → 🟠 ERROR
 *
 * Badges (FullAttemptCard)
 * ────────────────────────
 *   ⚠ STRAGGLER — row.is_straggler === true
 *   ⚠ UNRESOLVED POLICY — guard_decision.policy_id startsWith '__unresolved__:'
 *
 * Non-negotiable UX rules
 * ───────────────────────
 * • NEVER render a placeholder like "Prompt not recorded".  If the field is
 *   missing, OMIT the section entirely.  Missing data is handled by
 *   classifyAttempt upstream — a row that reaches this component has one
 *   of: a prompt+response pair (full), a guard decision (guard_only), or
 *   a probe-level error envelope (probe_error).  The specialised cards
 *   never synthesise data that isn't on the wire.
 * • NEVER render a section with a null/empty value — the whole tab must
 *   look intentional, not broken.
 */

import { useState } from 'react'
import { cn } from '../lib/utils.js'
import { GuardOnlyCard } from './GuardOnlyCard.jsx'
import { ProbeErrorCard } from './ProbeErrorCard.jsx'
import { isUnresolvedPolicy as isUnresolvedPolicyName } from '../lib/policyResolution.js'

// ── Status resolution ──────────────────────────────────────────────────────

const STATUS_STYLES = {
  running: { glyph: '🟡', label: 'RUNNING', txt: 'text-amber-700',   bg: 'bg-amber-50',  border: 'border-amber-200'   },
  blocked: { glyph: '🔴', label: 'BLOCKED', txt: 'text-red-700',     bg: 'bg-red-50',    border: 'border-red-200'     },
  allowed: { glyph: '🟢', label: 'ALLOWED', txt: 'text-emerald-700', bg: 'bg-emerald-50',border: 'border-emerald-200' },
  error:   { glyph: '🟠', label: 'ERROR',   txt: 'text-orange-700',  bg: 'bg-orange-50', border: 'border-orange-200'  },
}

function resolveStatus(attempt) {
  if (attempt.status === 'running') return STATUS_STYLES.running

  // Colour tracks our guard's actual action, not the probe's severity.
  // A Garak probe whose attack succeeded emits simulation.blocked (high
  // severity) but the GUARD allowed the prompt — showing red here would
  // falsely credit the guard for a block it didn't make.  When we know
  // defense_outcome, use it as the authoritative colour source.
  const outcome = attempt?.meta?.defense_outcome
  if (outcome === 'stopped') return STATUS_STYLES.blocked   // guard blocked → red
  if (outcome === 'missed')  return STATUS_STYLES.allowed   // guard allowed → green

  switch (attempt.result) {
    case 'blocked': return STATUS_STYLES.blocked
    case 'allowed': return STATUS_STYLES.allowed
    case 'error':   return STATUS_STYLES.error
    default:        return STATUS_STYLES.running
  }
}

function isUnresolvedPolicy(decision) {
  if (!decision) return false
  return typeof decision.policy_id === 'string'
    && decision.policy_id.startsWith('__unresolved__:')
}

function formatSeq(sequence, arrival) {
  if (sequence !== null && sequence !== undefined) return `#${sequence}`
  return `·${arrival}`
}

// ── Component ──────────────────────────────────────────────────────────────

/**
 * AttemptCard — switches on row.type (stamped by buildTimelineView).
 * Legacy rows that forgot to set row.type are treated as 'full' so old
 * callers keep working.
 */
export function AttemptCard({ row }) {
  const type = row?.type ?? 'full'
  if (type === 'guard_only')  return <GuardOnlyCard row={row} />
  if (type === 'probe_error') return <ProbeErrorCard row={row} />
  return <FullAttemptCard row={row} />
}

function FullAttemptCard({ row }) {
  const { attempt, sequence, arrival, is_straggler } = row
  const [expanded, setExpanded] = useState(false)
  const status = resolveStatus(attempt)
  const unresolved = isUnresolvedPolicy(attempt.guard_decision)

  const summaryId = `attempt-${attempt.attempt_id}-summary`
  const detailsId = `attempt-${attempt.attempt_id}-details`

  return (
    <article
      className={cn(
        'rounded-lg border bg-white overflow-hidden transition-colors',
        status.border,
        is_straggler && 'ring-1 ring-amber-300 ring-offset-0',
        unresolved   && 'ring-1 ring-amber-300 ring-offset-0',
      )}
      aria-labelledby={summaryId}
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
        <span
          className="text-[13px] leading-none shrink-0"
          role="img"
          aria-label={status.label}
          title={status.label}
        >
          {status.glyph}
        </span>

        <span
          className="text-[10px] font-mono text-gray-400 shrink-0 tabular-nums"
          title="Envelope sequence · arrival"
        >
          {formatSeq(sequence, arrival)}
        </span>

        <span className="text-[11.5px] font-semibold text-gray-800 truncate">
          {attempt.probe}
        </span>

        <span className="text-[10px] text-gray-500 truncate">
          {attempt.category}
        </span>

        <span
          className={cn(
            'ml-auto shrink-0 text-[10.5px] font-bold tabular-nums',
            attempt.risk_score >= 80 ? 'text-red-600'
              : attempt.risk_score >= 50 ? 'text-amber-600'
              : 'text-emerald-600',
          )}
          title="Risk score (0..100)"
        >
          {Math.round(attempt.risk_score)}
        </span>

        {is_straggler && (
          <span
            className="shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200"
            title="This attempt arrived AFTER simulation.probe_completed was emitted for its probe. Per-probe counts in other tabs are frozen and may not include it."
            aria-label="Straggler"
          >
            ⚠ Straggler
          </span>
        )}

        {unresolved && (
          <span
            className="shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200"
            title="The guard fired but the pipeline returned no policy metadata. Rendered using the __unresolved__: marker. Add a policy mapping to your guard config."
            aria-label="Unresolved policy"
          >
            ⚠ Unresolved
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
          aria-label={`Details for attempt ${attempt.attempt_id}`}
          className="border-t border-gray-100 bg-gray-50/40 px-3 py-3 space-y-3"
        >
          <AttemptLineage attempt={attempt} sequence={sequence} arrival={arrival} />
          <AttemptGuardDecision decision={attempt.guard_decision} />
          <AttemptBody attempt={attempt} />
          {attempt.error && (
            <section>
              <SectionHeader>Error</SectionHeader>
              <pre className="text-[10.5px] font-mono text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 whitespace-pre-wrap break-words">
                {attempt.error}
              </pre>
            </section>
          )}
        </div>
      )}
    </article>
  )
}

// ── Sub-sections ───────────────────────────────────────────────────────────

function SectionHeader({ children }) {
  return (
    <h4 className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1.5">
      {children}
    </h4>
  )
}

function DL({ children }) {
  return (
    <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-3 gap-y-1 text-[11px]">
      {children}
    </dl>
  )
}

function DLRow({ k, v }) {
  return (
    <>
      <dt className="text-gray-500 font-medium">{k}</dt>
      <dd className="text-gray-800 break-words">{v}</dd>
    </>
  )
}

function AttemptLineage({ attempt, sequence, arrival }) {
  return (
    <section>
      <SectionHeader>Lineage</SectionHeader>
      <DL>
        <DLRow k="attempt_id"        v={<code className="font-mono text-[10.5px]">{attempt.attempt_id}</code>} />
        <DLRow k="session_id"        v={<code className="font-mono text-[10.5px]">{attempt.session_id || '—'}</code>} />
        <DLRow k="probe (canonical)" v={attempt.probe} />
        <DLRow k="probe (raw)"       v={attempt.probe_raw || '—'} />
        <DLRow k="phase"             v={attempt.phase} />
        <DLRow k="category"          v={attempt.category} />
        <DLRow k="sequence"          v={sequence === null || sequence === undefined ? '—' : sequence} />
        <DLRow k="arrival"           v={arrival} />
        <DLRow k="started_at"        v={attempt.started_at ?? '—'} />
        <DLRow k="completed_at"      v={attempt.completed_at ?? '—'} />
        <DLRow k="latency_ms"        v={attempt.latency_ms ?? '—'} />
        <DLRow k="status"            v={attempt.status} />
        <DLRow k="model_invoked"     v={attempt.model_invoked ? 'yes' : 'no'} />
        {attempt.meta?.garak_probe_class && (
          <DLRow k="garak_probe_class" v={String(attempt.meta.garak_probe_class)} />
        )}
        {attempt.meta?.detector && (
          <DLRow k="detector" v={String(attempt.meta.detector)} />
        )}
      </DL>
    </section>
  )
}

// Guard decision block.  Omitted entirely when no decision was recorded —
// we do not show placeholder text.  When present, individual fields render
// a row only if they carry data, and an unresolved-policy badge replaces
// the policy name rather than rendering "—".
function AttemptGuardDecision({ decision }) {
  if (!decision) return null

  const unresolved = isUnresolvedPolicy(decision) || isUnresolvedPolicyName(decision.policy_name)
  const score      = typeof decision.score === 'number' ? decision.score : null
  const threshold  = typeof decision.threshold === 'number' ? decision.threshold : null

  return (
    <section className={unresolved ? 'opacity-90' : undefined}>
      <SectionHeader>Guard decision</SectionHeader>
      <DL>
        {decision.action && <DLRow k="action" v={decision.action} />}
        {score     !== null && <DLRow k="score"     v={score.toFixed(3)} />}
        {threshold !== null && <DLRow k="threshold" v={threshold.toFixed(3)} />}
        {decision.policy_id && (
          <DLRow
            k="policy_id"
            v={<code className="font-mono text-[10.5px]">{decision.policy_id}</code>}
          />
        )}
        <DLRow
          k="policy"
          v={
            unresolved ? (
              <span
                className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200"
                title="Guard fired but no policy is mapped to this decision."
              >
                ⚠ Unresolved Policy
              </span>
            ) : (
              decision.policy_name
            )
          }
        />
        {decision.reason && <DLRow k="reason" v={decision.reason} />}
      </DL>
    </section>
  )
}

// Omit sections entirely when data is missing — no placeholder text, no
// "not recorded" strings.  classifyAttempt() guarantees a 'full' row has
// both prompt and response, but defensive checks are kept because backend
// payloads can still ship partial data during a live run.
function AttemptBody({ attempt }) {
  const hasPrompt          = typeof attempt.prompt_raw === 'string' && attempt.prompt_raw.length > 0
  const hasResponse        = attempt.model_response != null && String(attempt.model_response).length > 0
  const sanitizedDiffers   = attempt.prompt_sanitized && attempt.prompt_sanitized !== attempt.prompt_raw
  const guardInputDiffers  = attempt.guard_input && attempt.guard_input !== attempt.prompt_sanitized && attempt.guard_input !== attempt.prompt_raw

  return (
    <>
      {hasPrompt && (
        <section>
          <SectionHeader>Prompt (raw)</SectionHeader>
          <pre className="text-[10.5px] font-mono text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2 whitespace-pre-wrap break-words">
            {attempt.prompt_raw}
          </pre>

          {sanitizedDiffers && (
            <div className="mt-2">
              <SectionHeader>Prompt (sanitized)</SectionHeader>
              <pre className="text-[10.5px] font-mono text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2 whitespace-pre-wrap break-words">
                {attempt.prompt_sanitized}
              </pre>
            </div>
          )}

          {guardInputDiffers && (
            <div className="mt-2">
              <SectionHeader>Guard input</SectionHeader>
              <pre className="text-[10.5px] font-mono text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2 whitespace-pre-wrap break-words">
                {attempt.guard_input}
              </pre>
            </div>
          )}
        </section>
      )}

      {hasResponse && (
        <section>
          <SectionHeader>Model response</SectionHeader>
          <pre className="text-[10.5px] font-mono text-gray-800 bg-white border border-gray-200 rounded-lg px-3 py-2 whitespace-pre-wrap break-words">
            {attempt.model_response}
          </pre>
        </section>
      )}
    </>
  )
}

export default AttemptCard
