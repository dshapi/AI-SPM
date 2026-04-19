/**
 * ResultsPanel.jsx
 * ────────────────
 * Production-grade simulation results panel.
 *
 * Design principles
 * ─────────────────
 * • Consumes SimulationState directly from useSimulationState — no separate
 *   result/running/sessionId props.
 * • Tabs are ALWAYS visible regardless of status (idle, running, completed,
 *   failed). Each tab renders its own appropriate empty/loading/error state.
 * • Summary, Timeline, and Explainability are extracted into dedicated
 *   sub-components. All other tab panels live inline here.
 * • Supports progressive rendering: Timeline and Summary update live as
 *   WebSocket events arrive during a running simulation.
 * • Extensible for Garak: probe grouping, multi-attack coverage, and
 *   per-probe results are already wired in.
 *
 * Props
 * ─────
 *   simulationState  SimulationState      — from useSimulationState()
 *   mode             'single'|'garak'     — determines tab set + grouping
 *   attackType       string               — for display in header/config
 *   config           object | null        — simulation config object
 *   apiError         string | null        — non-null → "Simulated" fallback badge
 */
import { useState, useEffect } from 'react'
import {
  Target, Clock,
  AlertTriangle, XCircle, Shield, ArrowRight,
  CheckCircle2, AlertCircle, Copy, Info,
  ChevronRight, RefreshCw,
} from 'lucide-react'
import { cn }               from '../../lib/utils.js'
import { Badge }            from '../ui/Badge.jsx'
import { Button }           from '../ui/Button.jsx'
import { Summary }          from './Summary.jsx'
import { Timeline }         from './Timeline.jsx'
import { ExplainabilityTab } from './Explainability.jsx'
import { TabEmpty }         from './EmptyState.jsx'
import { RiskTrend }        from './RiskTrend.jsx'
import { PhaseSection }     from './PhaseSection.jsx'
import { groupByPhase, groupByPhaseAndProbe } from '../../lib/phaseGrouping.js'

// ── Tab configuration ─────────────────────────────────────────────────────────

const BASE_TABS  = [
  'Summary',
  'Decision Trace',
  'Output',
  'Policy Impact',
  'Risk Analysis',
  'Recommendations',
  'Timeline',
  'Explainability',
]
const GARAK_TABS = ['Probe Results', 'Coverage']

// ── Config maps ───────────────────────────────────────────────────────────────

const VERDICT_CFG = {
  blocked: {
    label: 'BLOCKED',   icon: XCircle,       bg: 'bg-red-50',     border: 'border-red-200',
    txt:   'text-red-700',    dot: 'bg-red-500',
  },
  escalated: {
    label: 'ESCALATED', icon: AlertTriangle, bg: 'bg-orange-50',  border: 'border-orange-200',
    txt:   'text-orange-700', dot: 'bg-orange-500',
  },
  flagged: {
    label: 'FLAGGED',   icon: AlertTriangle, bg: 'bg-amber-50',   border: 'border-amber-200',
    txt:   'text-amber-700',  dot: 'bg-amber-500',
  },
  allowed: {
    label: 'ALLOWED',   icon: CheckCircle2,  bg: 'bg-emerald-50', border: 'border-emerald-200',
    txt:   'text-emerald-700',dot: 'bg-emerald-500',
  },
}

const TRACE_CFG = {
  ok:       { label: 'OK'       },
  warn:     { label: 'Warn'     },
  critical: { label: 'Critical' },
  blocked:  { label: 'Blocked'  },
  flagged:  { label: 'Flagged'  },
}

const POLICY_ACTION_CFG = {
  BLOCK:    { badge: 'critical', icon: XCircle       },
  ESCALATE: { badge: 'high',     icon: AlertTriangle },
  FLAG:     { badge: 'high',     icon: AlertTriangle },
  ALLOW:    { badge: 'success',  icon: CheckCircle2  },
  SKIP:     { badge: 'neutral',  icon: ArrowRight    },
}

const STAGE_RISK = {
  started: 10, progress: 50, blocked: 90, allowed: 30, error: 70, completed: 10,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getRiskScore(event) {
  const explicit = event?.details?.risk_score
  if (typeof explicit === 'number') return Math.min(100, Math.max(0, explicit))
  return STAGE_RISK[event?.stage] ?? 50
}

function SectionLabel({ children, className }) {
  return (
    <p className={cn('text-[10.5px] font-bold uppercase tracking-wider text-gray-400', className)}>
      {children}
    </p>
  )
}

/** Format elapsed duration for display in the header. */
function formatDuration(startedAt, completedAt) {
  if (!startedAt) return null
  const ms = (completedAt ?? Date.now()) - startedAt
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// ── DecisionTrace ─────────────────────────────────────────────────────────────
// Vertical connector-line rendering of a policy decision trace.
// Restored from bbdff80 and kept here (not extracted) since it is tightly
// coupled to the TRACE_CFG colour mapping above.

function DecisionTrace({ trace }) {
  return (
    <div>
      {trace.map((step, idx) => {
        const scfg   = TRACE_CFG[step.status] ?? TRACE_CFG.ok
        const isLast = idx === trace.length - 1

        const numBg =
          step.status === 'ok'                                        ? 'bg-emerald-500'
          : step.status === 'warn' || step.status === 'flagged'      ? 'bg-amber-400'
          : step.status === 'critical' || step.status === 'blocked'  ? 'bg-red-500'
          : 'bg-gray-400'

        const cardAccent =
          step.status === 'ok'                                        ? 'border-l-emerald-400'
          : step.status === 'warn' || step.status === 'flagged'      ? 'border-l-amber-400'
          : step.status === 'critical' || step.status === 'blocked'  ? 'border-l-red-500'
          : 'border-l-gray-300'

        const cardBg =
          step.status === 'warn' || step.status === 'flagged'        ? 'bg-amber-50/30'
          : step.status === 'critical' || step.status === 'blocked'  ? 'bg-red-50/30'
          : 'bg-white'

        const statusChip = cn(
          'text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full',
          step.status === 'ok'       && 'bg-emerald-100 text-emerald-700',
          step.status === 'warn'     && 'bg-amber-100   text-amber-700',
          step.status === 'critical' && 'bg-red-100     text-red-700',
          step.status === 'blocked'  && 'bg-red-100     text-red-700',
          step.status === 'flagged'  && 'bg-amber-100   text-amber-700',
        )

        return (
          <div key={step.step} className="flex gap-3">
            {/* Number + vertical connector */}
            <div className="flex flex-col items-center shrink-0">
              <div className={cn('w-6 h-6 rounded-full flex items-center justify-center text-white shrink-0 mt-2.5', numBg)}>
                <span className="text-[9px] font-bold tabular-nums">
                  {String(step.step).padStart(2, '0')}
                </span>
              </div>
              {!isLast && (
                <div className="flex-1 mt-1.5 mb-1.5 w-px border-l-2 border-dashed border-gray-200" />
              )}
            </div>

            {/* Step card */}
            <div className={cn(
              'flex-1 min-w-0 rounded-lg border border-l-[3px] border-gray-200 px-3 py-2.5 mt-1',
              isLast ? 'mb-0' : 'mb-2',
              cardAccent, cardBg,
            )}>
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <span className="text-[11.5px] font-semibold text-gray-800 leading-snug">
                  {step.label}
                </span>
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className={statusChip}>{scfg.label}</span>
                  <span className="text-[9.5px] text-gray-400 font-mono">{step.ts}</span>
                </div>
              </div>
              <div className="bg-gray-900/[0.03] border border-gray-100 rounded px-2 py-1.5">
                <p className="text-[10.5px] font-mono text-gray-600 leading-snug">{step.detail}</p>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── StatusChip ────────────────────────────────────────────────────────────────
// Live / Connecting / Stream-ended chip shown in the header.

function StatusChip({ status, connectionStatus, sessionId, apiError }) {
  if (!sessionId || apiError) return null

  if (connectionStatus === 'connected' && status === 'running') {
    return (
      <span
        title={`Live stream · session: ${sessionId}`}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-[9.5px] font-semibold text-emerald-700 shrink-0"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
        Live
      </span>
    )
  }

  if (connectionStatus === 'connecting' || connectionStatus === 'reconnecting') {
    return (
      <span
        title="Opening WebSocket stream…"
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-[9.5px] font-semibold text-amber-700 shrink-0"
      >
        <RefreshCw size={8} className="animate-spin" strokeWidth={2.5} />
        {connectionStatus === 'reconnecting' ? 'Reconnecting…' : 'Connecting…'}
      </span>
    )
  }

  if (connectionStatus === 'closed') {
    return (
      <span
        title={`Stream closed · session: ${sessionId}`}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 border border-gray-200 text-[9.5px] font-semibold text-gray-500 shrink-0"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
        Stream ended
      </span>
    )
  }

  if (connectionStatus === 'error') {
    return (
      <span
        title="WebSocket error — data may be incomplete"
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 border border-red-200 text-[9.5px] font-semibold text-red-600 shrink-0 cursor-help"
      >
        <AlertCircle size={9} strokeWidth={2.5} />
        Stream error
      </span>
    )
  }

  return null
}

// ── GarakOutputSummary ────────────────────────────────────────────────────────

function GarakOutputSummary({ events }) {
  const probeSet = new Set(events.map(e => e.details?.probe_name).filter(Boolean))
  const blocked  = events.filter(e => e.stage === 'blocked').length
  const allowed  = events.filter(e => e.stage === 'allowed').length
  const errors   = events.filter(e => e.stage === 'error').length

  return (
    <div className="p-4 space-y-3">
      <p className="text-[12px] font-bold text-gray-700 mb-3">Garak Scan Summary</p>
      <div className="grid grid-cols-2 gap-2">
        {[
          { label: 'Probes executed', value: probeSet.size, color: 'text-gray-700'    },
          { label: 'Blocked',          value: blocked,       color: 'text-red-600'     },
          { label: 'Allowed',          value: allowed,       color: 'text-emerald-600' },
          { label: 'Errors',           value: errors,        color: 'text-orange-600'  },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-gray-50 border border-gray-200 rounded-xl p-3">
            <div className={cn('text-[22px] font-black tabular-nums', color)}>{value}</div>
            <div className="text-[10px] text-gray-400 mt-0.5">{label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── ProbeResultsTab ───────────────────────────────────────────────────────────

const OUTCOME_CFG = {
  blocked:  { label: 'Blocked', bg: 'bg-red-50',     border: 'border-red-200',     dot: 'bg-red-500',     txt: 'text-red-700'     },
  allowed:  { label: 'Allowed', bg: 'bg-emerald-50', border: 'border-emerald-200', dot: 'bg-emerald-500', txt: 'text-emerald-700' },
  progress: { label: 'Running', bg: 'bg-amber-50',   border: 'border-amber-200',   dot: 'bg-amber-400',   txt: 'text-amber-700'   },
  error:    { label: 'Error',   bg: 'bg-orange-50',  border: 'border-orange-200',  dot: 'bg-orange-500',  txt: 'text-orange-700'  },
}

function ProbeResultsTab({ events, status }) {
  if (events.length === 0) {
    return (
      <TabEmpty
        label={status === 'idle'
          ? 'Run a Garak scan to see per-probe results.'
          : 'Waiting for probe results…'}
      />
    )
  }

  // Reduce events to the highest-priority outcome per probe name
  const PRIORITY = { blocked: 3, allowed: 3, error: 2, progress: 1 }
  const probeMap = new Map()
  for (const ev of events) {
    const name = ev.details?.probe_name
    if (!name) continue
    const existing = probeMap.get(name)
    if (!existing || (PRIORITY[ev.stage] ?? 0) >= (PRIORITY[existing.stage] ?? 0)) {
      probeMap.set(name, ev)
    }
  }

  const probes = Array.from(probeMap.entries())
  if (probes.length === 0) return <TabEmpty label="No probe events yet…" />

  const blocked = probes.filter(([, e]) => e.stage === 'blocked').length
  const allowed = probes.filter(([, e]) => e.stage === 'allowed').length
  const errors  = probes.filter(([, e]) => e.stage === 'error').length

  return (
    <div className="p-4 space-y-3">
      {/* Summary strip */}
      <div className="grid grid-cols-3 gap-2 mb-1">
        {[
          { label: 'Blocked', value: blocked, color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200'     },
          { label: 'Allowed', value: allowed, color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
          { label: 'Errors',  value: errors,  color: 'text-orange-600',  bg: 'bg-orange-50',  border: 'border-orange-200'  },
        ].map(({ label, value, color, bg, border }) => (
          <div key={label} className={cn('rounded-xl border p-3 text-center', bg, border)}>
            <div className={cn('text-[24px] font-black tabular-nums', color)}>{value}</div>
            <div className="text-[9.5px] text-gray-400 font-medium mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Per-probe list */}
      <div className="space-y-1.5">
        {probes.map(([probeName, ev]) => {
          const cfg   = OUTCOME_CFG[ev.stage] ?? OUTCOME_CFG.progress
          const step  = ev.details?.step
          const total = ev.details?.total
          return (
            <div
              key={probeName}
              className={cn('flex items-center gap-3 rounded-xl border px-3 py-2.5', cfg.bg, cfg.border)}
            >
              <span className={cn('w-2 h-2 rounded-full shrink-0', cfg.dot)} />
              <div className="flex-1 min-w-0">
                <p className="text-[11.5px] font-semibold text-gray-800 truncate">{probeName}</p>
                {ev.details?.message && (
                  <p className="text-[10px] text-gray-400 mt-0.5 truncate">{ev.details.message}</p>
                )}
              </div>
              <div className="shrink-0 flex items-center gap-2">
                {step != null && total != null && (
                  <span className="text-[9.5px] text-gray-400 font-mono">{step}/{total}</span>
                )}
                <span className={cn(
                  'text-[10px] font-bold px-2 py-0.5 rounded-full border',
                  cfg.bg, cfg.border, cfg.txt,
                )}>
                  {cfg.label}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── CoverageTab ───────────────────────────────────────────────────────────────

const PROBE_CATEGORY_MAP = {
  injection:    'Prompt Injection',
  jailbreak:    'Jailbreak',
  exfil:        'Exfiltration',
  pii:          'PII Leakage',
  hallucination:'Hallucination',
  toxicity:     'Toxicity',
  dan:          'DAN / Role-play',
  encoding:     'Encoding Bypass',
  continuation: 'Continuation Attack',
  default:      'General',
}

function inferCategory(probeName = '') {
  const lower = probeName.toLowerCase()
  for (const [prefix, cat] of Object.entries(PROBE_CATEGORY_MAP)) {
    if (lower.includes(prefix)) return cat
  }
  return 'Other'
}

function CoverageTab({ events, status }) {
  if (events.length === 0) {
    return (
      <TabEmpty
        label={status === 'idle'
          ? 'Run a Garak scan to see attack coverage.'
          : 'Waiting for probe data…'}
      />
    )
  }

  // Deduplicate by probe name, keeping the highest-priority stage
  const PRIORITY = { blocked: 3, allowed: 3, error: 2, progress: 1 }
  const seenProbes = new Map()
  for (const ev of events) {
    const name = ev.details?.probe_name
    if (!name) continue
    const existing = seenProbes.get(name)
    if (!existing || (PRIORITY[ev.stage] ?? 0) >= (PRIORITY[existing] ?? 0)) {
      seenProbes.set(name, ev.stage)
    }
  }

  // Group by attack category
  const catMap = new Map()
  for (const [probeName, stage] of seenProbes) {
    const cat   = inferCategory(probeName)
    const entry = catMap.get(cat) ?? { total: 0, blocked: 0 }
    entry.total++
    if (stage === 'blocked') entry.blocked++
    catMap.set(cat, entry)
  }

  const categories = Array.from(catMap.entries()).sort((a, b) => b[1].total - a[1].total)
  if (categories.length === 0) return <TabEmpty label="No probe category data yet." />

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <SectionLabel>Attack Category Coverage</SectionLabel>
        <span className="text-[10px] text-gray-400">
          {seenProbes.size} probe{seenProbes.size !== 1 ? 's' : ''} run
        </span>
      </div>
      {categories.map(([cat, { total, blocked }]) => {
        const pct      = total > 0 ? Math.round((blocked / total) * 100) : 0
        const barColor = pct >= 80 ? 'bg-red-500' : pct >= 40 ? 'bg-amber-500' : 'bg-emerald-500'
        return (
          <div key={cat} className="bg-white rounded-xl border border-gray-200 p-3">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[12px] font-semibold text-gray-800">{cat}</p>
              <div className="flex items-center gap-2 text-[10.5px]">
                <span className="text-red-600 font-bold">{blocked} blocked</span>
                <span className="text-gray-400">/ {total} probes</span>
              </div>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full transition-all duration-500', barColor)}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-[9.5px] text-gray-400 mt-1">{pct}% block rate</p>
          </div>
        )
      })}
    </div>
  )
}

// ── Main ResultsPanel ─────────────────────────────────────────────────────────

export function ResultsPanel({
  simulationState,
  mode        = 'single',
  attackType,
  config,
  apiError,
}) {
  // ── Destructure simulationState (safe-default so the panel never crashes) ───
  const {
    status           = 'idle',
    steps            = [],
    partialResults   = [],
    finalResults,
    error,
    startedAt,
    completedAt,
    sessionId,
    simEvents        = [],
    connectionStatus = 'idle',
  } = simulationState ?? {}

  const [activeTab,     setActiveTab]     = useState('Summary')
  const [copied,        setCopied]        = useState(false)
  const [selectedEvent, setSelectedEvent] = useState(null)

  // ── Derived flags ───────────────────────────────────────────────────────────
  const isGarak    = mode === 'garak'
  const RESULT_TABS = isGarak ? [...BASE_TABS, ...GARAK_TABS] : BASE_TABS

  // Data normalization: finalResults is the built result object; may be null
  const result = finalResults

  // ── Auto-switch logic ────────────────────────────────────────────────────────
  // Garak: jump to Timeline when stream opens — many live probe events.
  // Single: stay on Summary — spinner shows progress before result arrives.
  useEffect(() => {
    if (status === 'running') {
      if (isGarak) setActiveTab('Timeline')
      else setActiveTab('Summary')
    }
  }, [status, isGarak])

  // When result arrives: Garak → Decision Trace; single → Summary.
  useEffect(() => {
    if (result) {
      if (isGarak) setActiveTab('Decision Trace')
      else setActiveTab('Summary')
    }
  }, [result, isGarak])

  // Clear selected event at the start of a new run.
  useEffect(() => {
    if (simEvents.length === 0) setSelectedEvent(null)
  }, [simEvents])

  // ── Event selection handler ─────────────────────────────────────────────────
  const handleSelectEvent = (ev) => {
    setSelectedEvent(ev)
    // Auto-jump to Explainability if the event carries an explanation payload
    if (ev?.details?.explanation) setActiveTab('Explainability')
  }

  // ── Header state values ─────────────────────────────────────────────────────
  const vcfg     = result ? (VERDICT_CFG[result.verdict] ?? VERDICT_CFG.allowed) : null
  const duration = formatDuration(startedAt, completedAt)

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* ── Panel header ── */}
      <div className="h-10 px-4 flex items-center justify-between border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Target size={13} className="text-gray-400 shrink-0" strokeWidth={1.75} />
          <span className="text-[12px] font-semibold text-gray-700 shrink-0">
            Simulation Results
          </span>

          {/* Verdict chip — only once a result is available */}
          {vcfg && (
            <span className={cn(
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold shrink-0',
              vcfg.bg, vcfg.border, vcfg.txt,
            )}>
              <span className={cn('w-1.5 h-1.5 rounded-full', vcfg.dot)} />
              {vcfg.label}
            </span>
          )}

          {/* Live / Connecting / Stream-ended chip */}
          <StatusChip
            status={status}
            connectionStatus={connectionStatus}
            sessionId={sessionId}
            apiError={apiError}
          />

          {/* Step count badge */}
          {steps.length > 0 && (
            <span className="text-[9.5px] text-gray-400 font-mono shrink-0">
              {steps.length} step{steps.length !== 1 ? 's' : ''}
            </span>
          )}

          {/* Simulated (API error / mock fallback) badge */}
          {apiError && (
            <span
              title={`API error: ${apiError}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-[9.5px] font-semibold text-amber-700 shrink-0 cursor-help"
            >
              <AlertCircle size={9} strokeWidth={2.5} />
              Simulated
            </span>
          )}
        </div>

        {/* Duration */}
        {duration && (
          <div className="flex items-center gap-1.5 text-[10px] text-gray-400 shrink-0">
            <Clock size={10} strokeWidth={2} />
            <span className="font-mono">{duration}</span>
          </div>
        )}
      </div>

      {/* ── Tab bar — ALWAYS rendered, regardless of status ── */}
      <div className="flex items-center gap-0 border-b border-gray-100 px-4 shrink-0 overflow-x-auto">
        {RESULT_TABS.map(tab => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={cn(
              'h-9 px-3 text-[11px] font-medium border-b-2 shrink-0 transition-colors whitespace-nowrap inline-flex items-center gap-1',
              activeTab === tab
                ? 'text-blue-600 border-blue-600'
                : 'text-gray-500 border-transparent hover:text-gray-700',
            )}
          >
            {tab}
            {/* Event count pill on Timeline tab */}
            {tab === 'Timeline' && simEvents.length > 0 && (
              <span className="px-1 py-0.5 rounded text-[9px] bg-blue-100 text-blue-600 font-bold tabular-nums leading-none">
                {simEvents.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Tab content ── */}
      <div className="flex-1 overflow-y-auto">

        {/* Summary — delegates to Summary.jsx (handles all 4 states) */}
        {activeTab === 'Summary' && (
          <Summary
            simulationState={simulationState}
            config={config}
          />
        )}

        {/* Timeline — always rendered so events appear live */}
        {activeTab === 'Timeline' && (
          <Timeline
            simulationState={simulationState}
            mode={mode}
            selectedId={selectedEvent?.id}
            onSelect={handleSelectEvent}
          />
        )}

        {/* Explainability — renders selected event or empty state */}
        {activeTab === 'Explainability' && (
          <ExplainabilityTab
            selectedEvent={selectedEvent}
            simulationState={simulationState}
            mode={mode}
          />
        )}

        {/* ── Decision Trace ── */}
        {activeTab === 'Decision Trace' && !result && (
          <TabEmpty
            label={status === 'running'
              ? 'Building decision trace…'
              : 'Decision trace will appear here after a simulation runs.'}
          />
        )}
        {activeTab === 'Decision Trace' && result && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-4">
              <p className="text-[11px] text-gray-500">
                Step-by-step evaluation path through the policy engine.
              </p>
              <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
                <Clock size={10} strokeWidth={2} />
                <span className="font-mono">{result.executionMs}ms total</span>
              </div>
            </div>
            <DecisionTrace trace={result.decisionTrace ?? []} />
          </div>
        )}

        {/* ── Output ── */}
        {activeTab === 'Output' && !result && (
          <TabEmpty
            label={status === 'running'
              ? 'Waiting for simulation output…'
              : 'AI output will appear here after a simulation runs.'}
          />
        )}
        {activeTab === 'Output' && result && (
          <div className="p-4 space-y-3">
            {mode === 'garak' ? (
              <GarakOutputSummary events={simEvents} />
            ) : result.verdict === 'blocked' ? (
              /* REQUEST TERMINATED chrome */
              <div className="rounded-xl border-2 border-red-200 overflow-hidden">
                <div className="bg-red-600 px-4 py-3 flex items-center gap-3">
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-red-400/60" />
                    <span className="w-3 h-3 rounded-full bg-red-400/40" />
                    <span className="w-3 h-3 rounded-full bg-red-400/30" />
                  </div>
                  <span className="text-[11px] font-bold text-red-100 uppercase tracking-wide flex-1 text-center">
                    REQUEST TERMINATED
                  </span>
                  <XCircle size={14} className="text-red-200" strokeWidth={2} />
                </div>
                <div className="bg-red-50 px-5 py-5">
                  <div className="flex flex-col items-center text-center mb-4">
                    <div className="w-12 h-12 rounded-full bg-red-100 border-2 border-red-200 flex items-center justify-center mb-3">
                      <XCircle size={24} className="text-red-500" strokeWidth={1.75} />
                    </div>
                    <p className="text-[13px] font-bold text-red-700">Attack Blocked</p>
                    <p className="text-[10.5px] text-red-500 mt-0.5">No model output was generated</p>
                  </div>
                  <div className="bg-white rounded-lg border border-red-200 px-3.5 py-3">
                    <p className="text-[9.5px] font-bold uppercase tracking-wide text-red-400 mb-1.5">
                      Safety message returned to user
                    </p>
                    <p className="text-[11.5px] text-gray-700 leading-relaxed">
                      {result.blockedMessage}
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              /* Terminal chrome for allowed / flagged */
              <>
                <div className="rounded-xl border border-gray-800 overflow-hidden shadow-md">
                  <div className="bg-gray-800 px-4 py-2.5 flex items-center gap-3">
                    <div className="flex items-center gap-1.5">
                      <span className="w-3 h-3 rounded-full bg-red-500" />
                      <span className="w-3 h-3 rounded-full bg-amber-400" />
                      <span className="w-3 h-3 rounded-full bg-emerald-500" />
                    </div>
                    <div className="flex-1 text-center">
                      <span className="text-[10.5px] text-gray-400 font-mono">
                        {config?.model ?? 'model'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {result.verdict === 'flagged' && (
                        <span className="text-[9px] font-bold uppercase tracking-wide bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded-full">
                          Restricted
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          navigator.clipboard?.writeText(result.output ?? '')
                          setCopied(true)
                          setTimeout(() => setCopied(false), 1500)
                        }}
                        className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-200 transition-colors"
                      >
                        <Copy size={10} strokeWidth={2} />
                        {copied ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </div>
                  <div className="bg-gray-950 px-4 py-4">
                    <div className="flex items-center gap-2 mb-3 text-[10px] text-gray-500">
                      <span className="text-emerald-500 font-mono">$</span>
                      <span className="font-mono">model_response --agent {config?.agent ?? 'agent'}</span>
                    </div>
                    <pre className="text-[11.5px] font-mono text-gray-200 leading-relaxed whitespace-pre-wrap break-words">
                      {result.output}
                    </pre>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-gray-400">
                  <CheckCircle2 size={10} className="text-emerald-500" strokeWidth={2} />
                  <span className="font-mono">{result.output?.length ?? 0} chars</span>
                  <span>·</span>
                  <span>~{Math.round((result.output?.length ?? 0) / 4)} tokens</span>
                  <span>·</span>
                  <span>{result.executionMs}ms total</span>
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Policy Impact ── */}
        {activeTab === 'Policy Impact' && !result && (
          <TabEmpty
            label={status === 'running'
              ? 'Evaluating policies…'
              : 'Policy evaluation results will appear here after a simulation runs.'}
          />
        )}
        {activeTab === 'Policy Impact' && result && (
          <div className="p-4 space-y-3">
            <p className="text-[11px] text-gray-400">How each policy evaluated this request.</p>
            {(result.policyImpact?.length ?? 0) === 0 ? (
              <div className="text-center py-6 text-[12px] text-gray-400">
                No policies triggered.
              </div>
            ) : (
              result.policyImpact.map((pi, i) => {
                const acfg = POLICY_ACTION_CFG[pi.action] ?? POLICY_ACTION_CFG.SKIP
                return (
                  <div
                    key={i}
                    className={cn(
                      'rounded-xl border p-3.5 flex items-start gap-3',
                      pi.severity === 'critical' ? 'bg-red-50/60 border-red-200'
                        : pi.severity === 'high' ? 'bg-amber-50/60 border-amber-200'
                        : 'bg-gray-50 border-gray-200',
                    )}
                  >
                    <div className={cn(
                      'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
                      pi.severity === 'critical' ? 'bg-red-100'
                        : pi.severity === 'high' ? 'bg-amber-100'
                        : 'bg-gray-100',
                    )}>
                      <Shield
                        size={14}
                        className={
                          pi.severity === 'critical' ? 'text-red-600'
                          : pi.severity === 'high' ? 'text-amber-600'
                          : 'text-gray-500'
                        }
                        strokeWidth={1.75}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-[12px] font-semibold text-gray-800">{pi.policy}</span>
                        <Badge variant={acfg.badge}>{pi.action}</Badge>
                      </div>
                      <p className="text-[10.5px] text-gray-500 leading-snug">{pi.trigger}</p>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        )}

        {/* ── Risk Analysis ── */}
        {activeTab === 'Risk Analysis' && (
          <div className="p-4 space-y-4">

            {/* Live risk trend — always shown when events exist, even during run */}
            {simEvents.length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center justify-between mb-3">
                  <SectionLabel>Risk Over Time</SectionLabel>
                  {status === 'running' && (
                    <span className="text-[10px] text-emerald-600 font-semibold flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse inline-block" />
                      Live
                    </span>
                  )}
                </div>
                <RiskTrend events={simEvents} live={status === 'running'} />
              </div>
            )}

            {!result?.risk && simEvents.length === 0 && (
              <TabEmpty label="Risk analysis will appear after a simulation runs." />
            )}

            {result?.risk && (
              <>
                {/* Anomaly score bar */}
                <div className="bg-white rounded-xl border border-gray-200 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <SectionLabel>Anomaly Score</SectionLabel>
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        0.85 block threshold · 0.50 flag threshold
                      </p>
                    </div>
                    <span className={cn(
                      'text-[28px] font-black tabular-nums leading-none',
                      result.risk.anomalyScore >= 0.8 ? 'text-red-600'
                        : result.risk.anomalyScore >= 0.5 ? 'text-amber-600'
                        : 'text-emerald-600',
                    )}>
                      {result.risk.anomalyScore.toFixed(2)}
                    </span>
                  </div>
                  <div className="relative h-3 rounded-full overflow-visible bg-gray-100">
                    <div
                      className="absolute inset-0 rounded-full overflow-hidden"
                      style={{ background: 'linear-gradient(to right, #10b981 0%, #f59e0b 50%, #ef4444 85%, #dc2626 100%)' }}
                    >
                      <div
                        className="absolute top-0 right-0 bottom-0 bg-gray-100 transition-all duration-700"
                        style={{ width: `${(1 - result.risk.anomalyScore) * 100}%` }}
                      />
                    </div>
                    <div
                      className="absolute top-[-3px] bottom-[-3px] w-px bg-red-600 z-10"
                      style={{ left: '85%' }}
                    >
                      <div className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap">
                        <span className="text-[8px] font-bold text-red-600 bg-white px-0.5">0.85</span>
                      </div>
                    </div>
                    <div
                      className="absolute top-[-3px] bottom-[-3px] w-px bg-amber-500 z-10"
                      style={{ left: '50%' }}
                    >
                      <div className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap">
                        <span className="text-[8px] font-bold text-amber-600 bg-white px-0.5">0.50</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex justify-between text-[9px] text-gray-400 mt-2">
                    <span className="text-emerald-600 font-medium">Benign</span>
                    <span className="text-red-600 font-medium">Critical</span>
                  </div>
                </div>

                <div className="flex items-center justify-between py-2 px-3 bg-white rounded-lg border border-gray-200">
                  <span className="text-[11.5px] font-medium text-gray-700">Injection Detected</span>
                  {result.risk.injectionDetected
                    ? <Badge variant="critical">Yes</Badge>
                    : <Badge variant="success">No</Badge>}
                </div>

                {result.risk.techniques?.length > 0 && (
                  <div>
                    <SectionLabel className="mb-2">Techniques Identified</SectionLabel>
                    <div className="space-y-1.5">
                      {result.risk.techniques.map((t, i) => (
                        <div
                          key={i}
                          className="flex items-center gap-2 text-[11px] text-gray-700 bg-red-50/60 border border-red-100 rounded-lg px-3 py-1.5"
                        >
                          <AlertTriangle size={10} className="text-red-500 shrink-0" strokeWidth={2} />
                          {t}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <SectionLabel className="mb-2">Analyst Explanation</SectionLabel>
                  <div className="bg-blue-50/60 border border-blue-100 rounded-xl px-3.5 py-3">
                    <div className="flex items-start gap-2">
                      <Info size={12} className="text-blue-500 shrink-0 mt-0.5" strokeWidth={2} />
                      <p className="text-[11.5px] text-gray-700 leading-relaxed">
                        {result.risk.explanation}
                      </p>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Recommendations ── */}
        {activeTab === 'Recommendations' && !result && (
          <TabEmpty
            label={status === 'running'
              ? 'Analyzing results for recommendations…'
              : 'Recommendations will appear here after a simulation runs.'}
          />
        )}
        {activeTab === 'Recommendations' && result && (
          <div className="p-4 space-y-3">
            <p className="text-[11px] text-gray-400">Suggested actions based on simulation results.</p>
            {(result.recommendations?.length ?? 0) === 0 ? (
              <div className="text-center py-6 text-[12px] text-gray-400">No recommendations.</div>
            ) : (
              result.recommendations.map((rec, i) => (
                <div
                  key={i}
                  className="bg-white rounded-xl border border-gray-200 p-3.5 flex items-start gap-3"
                >
                  <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center shrink-0">
                    <rec.icon size={14} className="text-gray-600" strokeWidth={1.75} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[12px] font-semibold text-gray-800">{rec.label}</p>
                    <p className="text-[10.5px] text-gray-500 mt-0.5 leading-snug">{rec.desc}</p>
                  </div>
                  {rec.action && (
                    <Button variant="outline" size="sm" className="shrink-0 text-[10.5px] h-7 px-2.5">
                      {rec.action}
                    </Button>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* ── Probe Results (Garak only) ── */}
        {activeTab === 'Probe Results' && (
          <ProbeResultsTab events={simEvents} status={status} />
        )}

        {/* ── Coverage (Garak only) ── */}
        {activeTab === 'Coverage' && (
          <CoverageTab events={simEvents} status={status} />
        )}

      </div>
    </div>
  )
}
