/**
 * Explainability.jsx
 * ──────────────────
 * Explainability tab content.
 *
 * • Garak mode: shows per-probe execution trace
 *   (Prompt → Guard Input → Guard Decision → Response).
 * • Single-prompt mode: shows per-event detail for the selected Timeline event.
 */
import { useState }            from 'react'
import { Info, ChevronDown, ChevronRight, ShieldCheck, ShieldAlert } from 'lucide-react'
import { ExplainabilityPanel } from '../ExplainabilityPanel.jsx'
import { EmptyState }          from './EmptyState.jsx'
import { cn }                  from '../../lib/utils.js'

// ── TraceRow ──────────────────────────────────────────────────────────────────

function TraceRow({ label, value, mono = true, highlight, scroll = false }) {
  if (value == null || value === '') return null
  return (
    <div className="mb-2">
      <p className="text-[9.5px] font-bold uppercase tracking-wide text-gray-400 mb-0.5">{label}</p>
      <div
        className={cn(
          'rounded px-2 py-1.5 text-[10.5px] leading-relaxed whitespace-pre-wrap break-words border',
          mono ? 'font-mono' : '',
          highlight === 'block'
            ? 'bg-red-50 border-red-200 text-red-800'
            : highlight === 'allow'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
            : highlight === 'error'
            ? 'bg-orange-50 border-orange-200 text-orange-800'
            : 'bg-gray-50 border-gray-200 text-gray-700',
        )}
        style={scroll ? { maxHeight: '4.5rem', overflowY: 'auto' } : undefined}
      >
        {value}
      </div>
    </div>
  )
}

// ── ProbeTraceCard ────────────────────────────────────────────────────────────

function ProbeTraceCard({ probeName, attempts }) {
  const [open, setOpen] = useState(false)
  const hasBlock = attempts.some(a => a.decision === 'block')
  const hasError = attempts.some(a => a.decision === 'error')

  const headerBg    = hasError ? 'bg-orange-50/60' : hasBlock ? 'bg-red-50/60'    : 'bg-gray-50'
  const borderColor = hasError ? 'border-orange-200' : hasBlock ? 'border-red-200' : 'border-gray-200'
  const badgeCls    = hasError
    ? 'bg-orange-100 border-orange-200 text-orange-700'
    : hasBlock
    ? 'bg-red-100 border-red-200 text-red-700'
    : 'bg-emerald-100 border-emerald-200 text-emerald-700'
  const badgeLabel  = hasError ? 'ERROR' : hasBlock ? 'BLOCKED' : 'ALLOWED'

  return (
    <div className={cn('rounded-xl border mb-3', borderColor)}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={cn('w-full flex items-center gap-2 px-3 py-2.5 text-left', headerBg)}
      >
        <span className="shrink-0 text-gray-400">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
        {hasError
          ? <ShieldAlert size={13} className="text-orange-500 shrink-0" strokeWidth={2} />
          : hasBlock
          ? <ShieldAlert size={13} className="text-red-500 shrink-0" strokeWidth={2} />
          : <ShieldCheck size={13} className="text-emerald-500 shrink-0" strokeWidth={2} />
        }
        <span className="text-[11.5px] font-semibold text-gray-800 flex-1 truncate">
          {probeName}
        </span>
        <span className={cn('text-[9.5px] font-bold px-2 py-0.5 rounded-full border shrink-0', badgeCls)}>
          {attempts.length} attempt{attempts.length !== 1 ? 's' : ''} · {badgeLabel}
        </span>
      </button>

      {open && (
        <div
          className="divide-y divide-gray-100"
          style={{ maxHeight: '14rem', overflowY: 'auto' }}
        >
          {attempts.map((attempt, idx) => (
            <div key={idx} className="px-3 py-2">
              {attempts.length > 1 && (
                <p className="text-[9.5px] font-bold text-gray-400 uppercase tracking-wide mb-1.5">
                  Attempt {idx + 1}
                </p>
              )}
              <TraceRow label="Prompt" value={attempt.prompt} scroll />
              <TraceRow label="Raw prompt (pre-sanitization)" value={attempt.raw_prompt} scroll />
              <TraceRow
                label={`Guard decision · score ${attempt.score?.toFixed(2) ?? '--'}`}
                value={`${(attempt.decision ?? 'allow').toUpperCase()} — ${attempt.reason || 'no reason recorded'}`}
                mono={false}
                highlight={
                  attempt.decision === 'block' ? 'block'
                  : attempt.decision === 'error' ? 'error'
                  : 'allow'
                }
              />
              <TraceRow
                label="Model response"
                value={attempt.response}
                scroll
                highlight={attempt.passed === false ? 'block' : null}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── GarakTraceView ────────────────────────────────────────────────────────────

export function GarakTraceView({ prompts, guardInputs, guardDecisions, responses }) {
  // Build a map: correlation_id → merged attempt object
  const byCorr = new Map()

  const ensure = (key, probe) => {
    if (!byCorr.has(key)) byCorr.set(key, { probe, correlation_id: key })
    return byCorr.get(key)
  }

  for (const p of (prompts ?? [])) {
    const key = p.correlation_id || p.probe
    Object.assign(ensure(key, p.probe), { prompt: p.prompt, attempt_index: p.attempt_index ?? 0 })
  }
  for (const gi of (guardInputs ?? [])) {
    const key = gi.correlation_id || gi.probe
    Object.assign(ensure(key, gi.probe), { raw_prompt: gi.raw_prompt })
  }
  for (const gd of (guardDecisions ?? [])) {
    const key = gd.correlation_id || gd.probe
    Object.assign(ensure(key, gd.probe), { decision: gd.decision, reason: gd.reason, score: gd.score })
  }
  for (const r of (responses ?? [])) {
    const key = r.correlation_id || r.probe
    Object.assign(ensure(key, r.probe), { response: r.response, passed: r.passed })
  }

  if (byCorr.size === 0) {
    return (
      <EmptyState
        icon={Info}
        title="No trace data yet"
        subtitle="Trace data accumulates as probes run. Start a Garak scan to see full execution traces."
      />
    )
  }

  // Group by probe name
  const byProbe = new Map()
  for (const attempt of byCorr.values()) {
    const probe = attempt.probe ?? '(unknown probe)'
    if (!byProbe.has(probe)) byProbe.set(probe, [])
    byProbe.get(probe).push(attempt)
  }

  return (
    <div>
      <p className="text-[11px] text-gray-400 mb-4">
        Full per-probe execution trace — Prompt → Guard Input → Guard Decision → Response
      </p>
      {Array.from(byProbe.entries()).map(([probeName, attempts]) => (
        <ProbeTraceCard key={probeName} probeName={probeName} attempts={attempts} />
      ))}
    </div>
  )
}

// ── ExplainabilityTab ─────────────────────────────────────────────────────────

export function ExplainabilityTab({ selectedEvent, simulationState, mode }) {
  // Garak mode → always show the trace view (even if empty)
  if (mode === 'garak') {
    return (
      <div className="p-4">
        <GarakTraceView
          prompts={simulationState?.prompts ?? []}
          guardInputs={simulationState?.guardInputs ?? []}
          guardDecisions={simulationState?.guardDecisions ?? []}
          responses={simulationState?.responses ?? []}
        />
      </div>
    )
  }

  // Single-prompt mode → original behaviour
  if (!selectedEvent) {
    return (
      <div className="p-4">
        <EmptyState
          icon={Info}
          title="No event selected"
          subtitle="Click a Timeline event that has an explanation to view policy reasoning and decision details."
        />
      </div>
    )
  }

  return (
    <div className="p-4">
      <ExplainabilityPanel event={selectedEvent} />
    </div>
  )
}
