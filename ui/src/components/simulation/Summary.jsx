/**
 * Summary.jsx
 * ───────────
 * Summary tab for the ResultsPanel.
 *
 * Handles all four simulation lifecycle states:
 *
 *   idle      → EmptyState prompt
 *   running   → Spinner + live step feed + partial results indicator
 *   completed → Verdict hero, stats row, triggered policies, config detail
 *   failed    → ErrorState panel
 *
 * Props
 * ─────
 *   simulationState  SimulationState  — full state from useSimulationState
 *   config           object | null    — simulation config (agent, model, etc.)
 */
import {
  RefreshCw,
  XCircle,
  AlertTriangle,
  CheckCircle2,
  Shield,
  ChevronRight,
  FlaskConical,
} from 'lucide-react'
import { cn }         from '../../lib/utils.js'
import { EmptyState } from './EmptyState.jsx'
import { ErrorState } from './ErrorState.jsx'

// ── Constants ──────────────────────────────────────────────────────────────────

const VERDICT_CFG = {
  blocked: {
    label:  'BLOCKED',
    icon:   XCircle,
    bg:     'bg-red-50',
    border: 'border-red-200',
    txt:    'text-red-700',
    iconBg: 'bg-red-100',
  },
  escalated: {
    label:  'ESCALATED',
    icon:   AlertTriangle,
    bg:     'bg-orange-50',
    border: 'border-orange-200',
    txt:    'text-orange-700',
    iconBg: 'bg-orange-100',
  },
  flagged: {
    label:  'FLAGGED',
    icon:   AlertTriangle,
    bg:     'bg-amber-50',
    border: 'border-amber-200',
    txt:    'text-amber-700',
    iconBg: 'bg-amber-100',
  },
  allowed: {
    label:  'ALLOWED',
    icon:   CheckCircle2,
    bg:     'bg-emerald-50',
    border: 'border-emerald-200',
    txt:    'text-emerald-700',
    iconBg: 'bg-emerald-100',
  },
}

const VERDICT_DESCRIPTIONS = {
  blocked:   'Request terminated before reaching the model. No AI output was generated.',
  escalated: 'Risk exceeded the escalation threshold. The pipeline halted at the policy gate — manual approval is required.',
  flagged:   'Request processed with restrictions. Security alert raised and audit log updated.',
  allowed:   'All policy checks passed. Request processed and response returned normally.',
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function SectionLabel({ children, className }) {
  return (
    <p className={cn('text-[10.5px] font-bold uppercase tracking-wider text-gray-400', className)}>
      {children}
    </p>
  )
}

// ── Sub-panels ────────────────────────────────────────────────────────────────

/** Animated spinner shown while the simulation is running. */
function RunningPanel({ steps = [], partialResults = [], connectionStatus }) {
  const isConnecting = connectionStatus === 'connecting' || connectionStatus === 'reconnecting'

  return (
    <div className="flex flex-col items-center justify-center gap-4 text-center px-8 py-12">
      <div className="w-12 h-12 rounded-full bg-blue-50 border border-blue-100 flex items-center justify-center">
        <RefreshCw size={20} className="text-blue-500 animate-spin" strokeWidth={1.5} />
      </div>

      <div>
        <p className="text-[13px] font-semibold text-gray-700">
          {isConnecting ? 'Connecting to simulation engine…' : 'Simulating attack…'}
        </p>
        {steps.length > 0 ? (
          <p className="text-[11px] text-gray-400 mt-1">
            {steps.length} event{steps.length !== 1 ? 's' : ''} received
          </p>
        ) : (
          <p className="text-[11px] text-gray-400 mt-1">
            Evaluating policies and tracing decisions…
          </p>
        )}
      </div>

      {/* Live step feed — last 5 events */}
      {steps.length > 0 && (
        <div className="w-full max-w-xs text-left space-y-1.5">
          {steps.slice(-5).map(step => (
            <div
              key={step.id}
              className="flex items-center gap-2 text-[11px] text-gray-600"
            >
              <span className={cn(
                'w-1.5 h-1.5 rounded-full shrink-0',
                step.status === 'done'   ? 'bg-emerald-500'
                : step.status === 'failed' ? 'bg-red-500'
                : 'bg-blue-400 animate-pulse',
              )} />
              <span className="truncate">{step.label}</span>
            </div>
          ))}
        </div>
      )}

      {/* Partial results indicator (Garak multi-probe) */}
      {partialResults.length > 0 && (
        <p className="text-[10.5px] text-gray-400 font-medium">
          {partialResults.length} partial result{partialResults.length !== 1 ? 's' : ''} received
        </p>
      )}
    </div>
  )
}

/** Full result view shown when status === 'completed'. */
function CompletedPanel({ result, config }) {
  const vcfg = VERDICT_CFG[result.verdict] ?? VERDICT_CFG.allowed

  const riskScore        = result.riskScore ?? 0
  const policiesHit      = result.policiesTriggered?.length ?? 0
  const riskAccent       = riskScore >= 80 ? 'border-l-red-500'   : riskScore >= 50 ? 'border-l-amber-500'   : 'border-l-emerald-500'
  const riskValueColor   = riskScore >= 80 ? 'text-red-600'        : riskScore >= 50 ? 'text-amber-600'        : 'text-emerald-600'

  return (
    <div className="p-4 space-y-4">

      {/* ── Verdict hero ── */}
      <div className={cn('rounded-xl border-2 p-5', vcfg.bg, vcfg.border)}>
        <div className="flex items-center gap-4">
          <div className={cn(
            'w-12 h-12 rounded-xl flex items-center justify-center shrink-0 border-2',
            vcfg.border,
            vcfg.iconBg,
          )}>
            <vcfg.icon size={26} className={vcfg.txt} strokeWidth={1.75} />
          </div>

          <div className="flex-1 min-w-0">
            <p className={cn('text-[22px] font-black tracking-tight leading-none uppercase', vcfg.txt)}>
              {vcfg.label}
            </p>
            <p className="text-[11.5px] text-gray-600 mt-1.5 leading-snug">
              {VERDICT_DESCRIPTIONS[result.verdict]}
            </p>
          </div>

          <div className="shrink-0 text-right">
            <p className={cn('text-[32px] font-black tabular-nums leading-none', vcfg.txt)}>
              {riskScore}
            </p>
            <p className="text-[9.5px] font-bold uppercase tracking-wide text-gray-400 mt-0.5">
              Risk Score
            </p>
          </div>
        </div>
      </div>

      {/* ── Stats row ── */}
      <div className="grid grid-cols-3 gap-2">
        {[
          {
            label:    'Risk Level',
            value:    result.riskLevel,
            sub:      `Score: ${riskScore}/100`,
            accent:   riskAccent,
            valColor: cn('text-[16px]', riskValueColor),
          },
          {
            label:    'Policies Hit',
            value:    policiesHit,
            sub:      policiesHit === 0 ? 'None triggered' : `${policiesHit} polic${policiesHit === 1 ? 'y' : 'ies'}`,
            accent:   policiesHit > 0 ? 'border-l-violet-500' : 'border-l-gray-300',
            valColor: 'text-gray-900 text-[22px]',
          },
          {
            label:    'Exec Time',
            value:    `${result.executionMs ?? 0}ms`,
            sub:      'Policy chain eval',
            accent:   'border-l-blue-400',
            valColor: 'text-gray-900 text-[18px]',
          },
        ].map(stat => (
          <div
            key={stat.label}
            className={cn(
              'bg-white rounded-lg border border-gray-200 border-l-[3px] px-3 py-2.5',
              stat.accent,
            )}
          >
            <p className="text-[9.5px] font-bold uppercase tracking-[0.08em] text-gray-400 leading-none mb-1.5">
              {stat.label}
            </p>
            <p className={cn('font-bold leading-none tabular-nums', stat.valColor)}>
              {stat.value}
            </p>
            <p className="text-[9.5px] text-gray-400 mt-1">{stat.sub}</p>
          </div>
        ))}
      </div>

      {/* ── Triggered policies ── */}
      {policiesHit > 0 && (
        <div>
          <SectionLabel className="mb-2">Policies Triggered</SectionLabel>
          <div className="flex flex-wrap gap-1.5">
            {result.policiesTriggered.map(p => (
              <span
                key={p}
                className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold bg-violet-50 text-violet-700 border border-violet-200 px-2.5 py-1 rounded-lg"
              >
                <Shield size={9} strokeWidth={2.5} />
                {p}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Simulation config (collapsible) ── */}
      {config && (
        <details className="group">
          <summary className="flex items-center gap-1.5 cursor-pointer list-none text-[10.5px] text-gray-400 hover:text-gray-600 transition-colors select-none">
            <ChevronRight
              size={11}
              className="group-open:rotate-90 transition-transform"
              strokeWidth={2}
            />
            Simulation config
          </summary>
          <div className="mt-2 bg-gray-50/80 rounded-lg border border-gray-100 divide-y divide-gray-100 overflow-hidden">
            {[
              ['Agent',       config.agent],
              ['Model',       config.model],
              ['Environment', config.environment],
              ['Attack type', config.attackType],
              ['Exec mode',   config.execMode],
            ].map(([k, v]) => v && (
              <div key={k} className="flex items-center justify-between px-3 py-1.5">
                <span className="text-[10px] text-gray-400 font-medium">{k}</span>
                <span className="text-[10px] text-gray-600 font-semibold text-right truncate ml-3">{v}</span>
              </div>
            ))}
          </div>
        </details>
      )}

    </div>
  )
}

// ── Main Summary component ────────────────────────────────────────────────────

export function Summary({ simulationState, config }) {
  const {
    status,
    steps          = [],
    partialResults = [],
    finalResults,
    error,
    connectionStatus,
  } = simulationState ?? {}

  // Normalize: use finalResults (completed object) or fall back to partialResults check
  const result = finalResults

  // ── Idle ──────────────────────────────────────────────────────────────────
  if (status === 'idle' && !result) {
    return (
      <EmptyState
        icon={FlaskConical}
        title="No simulation run yet"
        subtitle="Configure an attack type and click Run Simulation to see results here."
      />
    )
  }

  // ── Failed ────────────────────────────────────────────────────────────────
  if (status === 'failed') {
    return (
      <ErrorState
        error={error || 'An unexpected error occurred. Check the console for details.'}
      />
    )
  }

  // ── Running (no result yet) ───────────────────────────────────────────────
  if (status === 'running' && !result) {
    return (
      <RunningPanel
        steps={steps}
        partialResults={partialResults}
        connectionStatus={connectionStatus}
      />
    )
  }

  // ── Completed — result present ────────────────────────────────────────────
  if (result) {
    return <CompletedPanel result={result} config={config} />
  }

  // ── Fallback (e.g. completed state but no result built yet) ──────────────
  return (
    <EmptyState
      icon={FlaskConical}
      title="No results yet"
      subtitle="Run a simulation to see the verdict and risk summary."
    />
  )
}
