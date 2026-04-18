import { useState, useEffect } from 'react'
import {
  Target, RefreshCw, FlaskConical, Clock, Info,
  AlertTriangle, XCircle,
  CheckCircle2, AlertCircle, Copy,
} from 'lucide-react'
import { cn }                    from '../../lib/utils.js'
import { Badge }                 from '../ui/Badge.jsx'
import { Button }                from '../ui/Button.jsx'
import { ExplainabilityPanel }   from '../ExplainabilityPanel.jsx'
import { RiskTrend }             from './RiskTrend.jsx'
import { PhaseSection }          from './PhaseSection.jsx'
import { groupByPhase, groupByPhaseAndProbe } from '../../lib/phaseGrouping.js'

// ── Constants ──────────────────────────────────────────────────────────────────

const RESULT_TABS = ['Summary', 'Decision Trace', 'Output', 'Policy Impact', 'Risk Analysis', 'Recommendations', 'Timeline', 'Explainability']

const VERDICT_CFG = {
  blocked:   { label: 'BLOCKED',   icon: XCircle,       bg: 'bg-red-50',     border: 'border-red-300',   txt: 'text-red-700',     dot: 'bg-red-500'     },
  escalated: { label: 'ESCALATED', icon: AlertTriangle,  bg: 'bg-orange-50',  border: 'border-orange-300', txt: 'text-orange-700',  dot: 'bg-orange-500'  },
  flagged:   { label: 'FLAGGED',   icon: AlertCircle,   bg: 'bg-amber-50',   border: 'border-amber-300',  txt: 'text-amber-700',   dot: 'bg-amber-500'   },
  allowed:   { label: 'ALLOWED',   icon: CheckCircle2,  bg: 'bg-emerald-50', border: 'border-emerald-300', txt: 'text-emerald-700', dot: 'bg-emerald-500' },
}

const STAGE_RISK = { started: 10, progress: 50, blocked: 90, allowed: 30, error: 70, completed: 10 }

function getRiskScore(event) {
  const explicit = event?.details?.risk_score
  if (typeof explicit === 'number') return Math.min(100, Math.max(0, explicit))
  return STAGE_RISK[event?.stage] ?? 50
}

function TabEmpty({ label = 'No data yet' }) {
  return (
    <div className="flex items-center justify-center py-16 px-8 text-center">
      <p className="text-[12px] text-gray-400">{label}</p>
    </div>
  )
}

function SectionLabel({ children, className }) {
  return (
    <p className={cn('text-[10.5px] font-bold uppercase tracking-wider text-gray-400', className)}>
      {children}
    </p>
  )
}

// ── Status indicators ──────────────────────────────────────────────────────────

function StatusChip({ state, connectionStatus, sessionId, apiError }) {
  if (!sessionId || apiError) return null
  if (state === 'running' && connectionStatus === 'connected') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-[9.5px] font-semibold text-emerald-700 shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
        Live
      </span>
    )
  }
  if (state === 'connecting') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-[9.5px] font-semibold text-amber-700 shrink-0">
        <RefreshCw size={8} className="animate-spin" strokeWidth={2.5} />
        Connecting…
      </span>
    )
  }
  if (state === 'completed' && connectionStatus === 'closed') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 border border-gray-200 text-[9.5px] font-semibold text-gray-500 shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
        Stream ended
      </span>
    )
  }
  if (state === 'error') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 border border-red-200 text-[9.5px] font-semibold text-red-600 shrink-0 cursor-help">
        <AlertCircle size={9} strokeWidth={2.5} />
        Stream error
      </span>
    )
  }
  return null
}

// ── Timeline tab content ────────────────────────────────────────────────────────

function TimelineTab({ simulation, selectedId, onSelect }) {
  const { events = [], mode, state } = simulation
  const isGarak = mode === 'garak'

  // Status label
  const statusLabel = state === 'running'
    ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#22c55e', fontWeight: 600 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#22c55e', display: 'inline-block', animation: 'pulse 1s infinite' }} />
        LIVE
      </span>
    : state === 'connecting'
      ? <span style={{ fontSize: 11, color: '#f59e0b' }}>Connecting…</span>
      : state === 'completed'
        ? <span style={{ fontSize: 11, color: '#9ca3af' }}>Completed</span>
        : <span style={{ fontSize: 11, color: '#9ca3af' }}>Idle</span>

  if (events.length === 0) {
    return (
      <div style={{ padding: '16px 0' }}>
        <div style={{ marginBottom: 8 }}>{statusLabel}</div>
        <p style={{ color: '#9ca3af', fontSize: 13 }}>
          {state === 'idle' ? 'Run a simulation to see events here.' : 'No events yet…'}
        </p>
      </div>
    )
  }

  const grouped = isGarak
    ? groupByPhaseAndProbe(events)
    : groupByPhase(events)

  // Phase display order
  const PHASE_ORDER = ['Recon', 'Injection', 'Exploitation', 'Exfiltration', 'System', 'Other']
  const sortedPhases = [
    ...PHASE_ORDER.filter(p => grouped[p]),
    ...Object.keys(grouped).filter(p => !PHASE_ORDER.includes(p)),
  ]

  return (
    <div style={{ padding: '12px 0' }}>
      <div style={{ marginBottom: 12 }}>{statusLabel}</div>
      {sortedPhases.map(phase => (
        <PhaseSection
          key={phase}
          phase={phase}
          events={grouped[phase]}
          isGarak={isGarak}
          selectedId={selectedId}
          onSelect={onSelect}
          getRiskScore={getRiskScore}
        />
      ))}
    </div>
  )
}

// ── Garak Output Summary ───────────────────────────────────────────────────────

function GarakOutputSummary({ events }) {
  const probeSet = new Set(events.map(e => e.details?.probe_name).filter(Boolean))
  const blocked  = events.filter(e => e.stage === 'blocked').length
  const allowed  = events.filter(e => e.stage === 'allowed').length
  const errors   = events.filter(e => e.stage === 'error').length

  return (
    <div style={{ padding: '12px 0' }}>
      <p style={{ fontSize: 12, fontWeight: 700, color: '#374151', marginBottom: 12 }}>Garak Scan Summary</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {[
          { label: 'Probes executed', value: probeSet.size, color: '#374151' },
          { label: 'Blocked',         value: blocked,       color: '#ef4444' },
          { label: 'Allowed',         value: allowed,       color: '#22c55e' },
          { label: 'Errors',          value: errors,        color: '#f97316' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            background: '#f9fafb',
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            padding: '10px 12px',
          }}>
            <div style={{ fontSize: 22, fontWeight: 800, color }}>{value}</div>
            <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main ResultsPanel ──────────────────────────────────────────────────────────

/**
 * ResultsPanel
 * ─────────────
 * Props
 * ─────
 *   simulation    { state: 'idle'|'connecting'|'running'|'completed'|'error', events: SimulationEvent[], mode: 'single'|'garak'|null }
 *   result        mock/live result object | null
 *   attackType    string
 *   config        config object
 *   running       boolean
 *   apiError      string | null
 *   sessionId     string | null
 *   connectionStatus   string (from useSimulationStream)
 */
export function ResultsPanel({
  simulation = { state: 'idle', events: [], mode: null },
  result,
  attackType,
  config,
  running,
  apiError,
  sessionId,
  connectionStatus,
}) {
  const [activeTab,    setActiveTab]    = useState('Summary')
  const [copied,       setCopied]       = useState(false)
  const [selectedEvent, setSelectedEvent] = useState(null)

  const { state, events: simEvents = [], mode } = simulation

  // Auto-switch to Timeline when simulation starts streaming
  useEffect(() => {
    if (state === 'connecting' || state === 'running') {
      setActiveTab('Timeline')
    }
  }, [state])

  // Auto-switch to Decision Trace when static result arrives
  useEffect(() => {
    if (result) setActiveTab('Decision Trace')
  }, [result])

  // Clear selected event on new run
  useEffect(() => {
    if (simEvents.length === 0) setSelectedEvent(null)
  }, [simEvents])

  const handleSelectEvent = (ev) => {
    setSelectedEvent(ev)
    if (ev?.details?.explanation) setActiveTab('Explainability')
  }

  const vcfg = result ? (VERDICT_CFG[result.verdict] ?? VERDICT_CFG.allowed) : null

  // Determine if spinner should show (overlaid on content, not replacing tab bar)
  const isConnecting = connectionStatus === 'connecting' || connectionStatus === 'reconnecting'
  const showSpinner  = running || (isConnecting && !result)

  // ── ALWAYS render tab bar — no early returns for layout ────────────────────

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* Panel header */}
      <div className="h-10 px-4 flex items-center justify-between border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <Target size={13} className="text-gray-400 shrink-0" strokeWidth={1.75} />
          <span className="text-[12px] font-semibold text-gray-700 shrink-0">Results</span>

          {/* Verdict chip — only when result exists */}
          {vcfg && (
            <span className={cn(
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold shrink-0',
              vcfg.bg, vcfg.border, vcfg.txt,
            )}>
              <span className={cn('w-1.5 h-1.5 rounded-full', vcfg.dot)} />
              {vcfg.label}
            </span>
          )}

          <StatusChip
            state={state}
            connectionStatus={connectionStatus}
            sessionId={sessionId}
            apiError={apiError}
          />

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

        {result && (
          <div className="flex items-center gap-2 text-[10px] text-gray-400 shrink-0">
            <Clock size={10} strokeWidth={2} />
            <span className="font-mono">{result.executionMs}ms</span>
          </div>
        )}
      </div>

      {/* ALWAYS-RENDERED tab bar */}
      <div className="flex items-center gap-0 border-b border-gray-100 px-4 shrink-0 overflow-x-auto">
        {RESULT_TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'h-9 px-3 text-[11px] font-medium border-b-2 shrink-0 transition-colors whitespace-nowrap',
              activeTab === tab
                ? 'text-blue-600 border-blue-600'
                : 'text-gray-500 border-transparent hover:text-gray-700',
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content area */}
      <div className="flex-1 overflow-y-auto">

        {/* ── Timeline tab: always rendered so events appear live during run ── */}
        {activeTab === 'Timeline' && (
          <TimelineTab
            simulation={simulation}
            selectedId={selectedEvent?.id}
            onSelect={handleSelectEvent}
          />
        )}

        {/* ── Explainability: always visible so users can read it after clicking event ── */}
        {activeTab === 'Explainability' && (
          <div className="p-4">
            {selectedEvent
              ? <ExplainabilityPanel event={selectedEvent} />
              : <TabEmpty label="Click a timeline event with an explanation to view details." />}
          </div>
        )}

        {/* ── Empty / Spinner overlay for all other tabs while running ── */}
        {showSpinner && activeTab !== 'Timeline' && activeTab !== 'Explainability' && (
          <div className="flex flex-col items-center justify-center gap-4 text-center px-8 py-16">
            <div className="w-12 h-12 rounded-full bg-blue-50 border border-blue-100 flex items-center justify-center">
              <RefreshCw size={20} className="text-blue-500 animate-spin" strokeWidth={1.5} />
            </div>
            <div>
              <p className="text-[13px] font-semibold text-gray-700">
                {state === 'connecting' ? 'Connecting…' : 'Simulating attack…'}
              </p>
              <p className="text-[11px] text-gray-400 mt-1">Evaluating policies and tracing decisions</p>
            </div>
          </div>
        )}

        {/* Tab panels for all non-Timeline/Explainability tabs — rendered after spinner clears */}
        {!showSpinner && activeTab !== 'Timeline' && activeTab !== 'Explainability' && (

          <>
            {/* ── Summary ── */}
            {activeTab === 'Summary' && !result && <TabEmpty label="Run a simulation to see the verdict and risk summary." />}
            {activeTab === 'Summary' && result && (
              <div className="p-4 space-y-4">
                {/* Verdict hero */}
                <div className={cn('rounded-xl border-2 p-5', vcfg.bg, vcfg.border)}>
                  <div className="flex items-center gap-4">
                    <div className={cn('w-12 h-12 rounded-xl flex items-center justify-center shrink-0 border-2', vcfg.border,
                      result.verdict === 'blocked'   ? 'bg-red-100'
                      : result.verdict === 'escalated' ? 'bg-orange-100'
                      : result.verdict === 'flagged' ? 'bg-amber-100'
                      : 'bg-emerald-100',
                    )}>
                      <vcfg.icon size={26} className={vcfg.txt} strokeWidth={1.75} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={cn('text-[22px] font-black tracking-tight leading-none uppercase', vcfg.txt)}>
                        {vcfg.label}
                      </p>
                      <p className="text-[11.5px] text-gray-600 mt-1.5 leading-snug">
                        {result.verdict === 'blocked'   && 'Request terminated before reaching the model.'}
                        {result.verdict === 'escalated' && 'Risk exceeded escalation threshold. Manual approval required.'}
                        {result.verdict === 'flagged'   && 'Request processed with restrictions. Alert raised.'}
                        {result.verdict === 'allowed'   && 'All policy checks passed. Request processed normally.'}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className={cn('text-[32px] font-black tabular-nums leading-none', vcfg.txt)}>{result.riskScore}</p>
                      <p className="text-[9.5px] font-bold uppercase tracking-wide text-gray-400 mt-0.5">Risk Score</p>
                    </div>
                  </div>
                </div>

                {/* Stats row */}
                <div className="grid grid-cols-3 gap-2">
                  {[
                    {
                      label: 'Risk Level',
                      value: result.riskLevel,
                      sub: `Score: ${result.riskScore}/100`,
                      accent: result.riskScore >= 80 ? 'border-l-red-500' : result.riskScore >= 50 ? 'border-l-amber-500' : 'border-l-emerald-500',
                      valColor: result.riskScore >= 80 ? 'text-red-600 text-[16px]' : result.riskScore >= 50 ? 'text-amber-600 text-[16px]' : 'text-emerald-600 text-[16px]',
                    },
                    {
                      label: 'Policies Hit',
                      value: result.policiesTriggered?.length ?? 0,
                      sub: result.policiesTriggered?.slice(0, 1).join(', ') || '—',
                      accent: 'border-l-blue-500',
                      valColor: 'text-blue-600 text-[16px]',
                    },
                    {
                      label: 'Latency',
                      value: `${result.executionMs}ms`,
                      sub: result.executionMs < 50 ? 'Fast' : result.executionMs < 200 ? 'Normal' : 'Slow',
                      accent: 'border-l-gray-400',
                      valColor: 'text-gray-700 text-[15px]',
                    },
                  ].map(({ label, value, sub, accent, valColor }) => (
                    <div key={label} className={cn('bg-white rounded-xl border border-gray-200 border-l-4 p-3', accent)}>
                      <SectionLabel className="mb-1">{label}</SectionLabel>
                      <p className={cn('font-bold tabular-nums leading-tight', valColor)}>{value}</p>
                      <p className="text-[9.5px] text-gray-400 mt-0.5 truncate">{sub}</p>
                    </div>
                  ))}
                </div>

                {/* Policies triggered */}
                {result.policiesTriggered?.length > 0 && (
                  <div>
                    <SectionLabel className="mb-2">Policies Triggered</SectionLabel>
                    <div className="flex flex-wrap gap-1.5">
                      {result.policiesTriggered.map(p => (
                        <span key={p} className="px-2 py-0.5 bg-red-50 border border-red-200 rounded-full text-[10.5px] text-red-700 font-medium">
                          {p}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Decision Trace ── */}
            {activeTab === 'Decision Trace' && !result && <TabEmpty label="Decision trace will appear here after a simulation runs." />}
            {activeTab === 'Decision Trace' && result && (
              <div className="p-4">
                <div className="space-y-2">
                  {result.decisionTrace?.map(step => {
                    const statusCfg = {
                      ok:       { bg: 'bg-emerald-50',  border: 'border-emerald-200', dot: 'bg-emerald-500', txt: 'text-emerald-700' },
                      critical: { bg: 'bg-red-50',      border: 'border-red-200',     dot: 'bg-red-500',     txt: 'text-red-700'     },
                      blocked:  { bg: 'bg-red-100',     border: 'border-red-300',     dot: 'bg-red-600',     txt: 'text-red-800'     },
                      warning:  { bg: 'bg-amber-50',    border: 'border-amber-200',   dot: 'bg-amber-500',   txt: 'text-amber-700'   },
                    }[step.status] ?? { bg: 'bg-gray-50', border: 'border-gray-200', dot: 'bg-gray-400', txt: 'text-gray-700' }
                    return (
                      <div key={step.step} className={cn('flex items-start gap-3 rounded-xl border p-3', statusCfg.bg, statusCfg.border)}>
                        <div className={cn('w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5', statusCfg.dot)}>
                          <span className="text-[9px] font-bold text-white">{step.step}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className={cn('text-[11.5px] font-semibold', statusCfg.txt)}>{step.label}</p>
                          <p className="text-[10.5px] text-gray-500 mt-0.5 leading-snug">{step.detail}</p>
                        </div>
                        <span className="text-[9.5px] text-gray-400 font-mono shrink-0">{step.ts}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* ── Output ── */}
            {activeTab === 'Output' && !result && <TabEmpty label="AI output will appear here after a simulation runs." />}
            {activeTab === 'Output' && result && (
              <div className="p-4">
                {mode === 'garak' ? (
                  <GarakOutputSummary events={simEvents} />
                ) : result.verdict === 'blocked' ? (
                  <div className="bg-red-50 border border-red-200 rounded-xl p-4">
                    <SectionLabel className="mb-2 text-red-400">Blocked Message</SectionLabel>
                    <p className="text-[12px] text-red-700 leading-relaxed">{result.blockedMessage}</p>
                  </div>
                ) : (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <SectionLabel>AI Output</SectionLabel>
                      <button
                        type="button"
                        onClick={() => { navigator.clipboard?.writeText(result.output ?? ''); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
                        className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-600"
                      >
                        <Copy size={10} strokeWidth={2} />
                        {copied ? 'Copied!' : 'Copy'}
                      </button>
                    </div>
                    <div className="bg-gray-900 rounded-xl p-4 font-mono text-[11.5px] text-gray-100 leading-relaxed whitespace-pre-wrap max-h-96 overflow-y-auto">
                      {result.output ?? <span className="text-gray-500 italic">No output.</span>}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Policy Impact ── */}
            {activeTab === 'Policy Impact' && !result && <TabEmpty label="Policy evaluation results will appear here after a simulation runs." />}
            {activeTab === 'Policy Impact' && result && (
              <div className="p-4 space-y-2">
                <p className="text-[11px] text-gray-400 mb-3">Policy evaluation results for this simulation.</p>
                {result.policyImpact?.map((p, i) => {
                  const actionCfg = {
                    BLOCK: { bg: 'bg-red-50',     border: 'border-red-200',    badge: 'bg-red-100 text-red-700 border-red-300'     },
                    FLAG:  { bg: 'bg-amber-50',   border: 'border-amber-200',  badge: 'bg-amber-100 text-amber-700 border-amber-300'  },
                    ALLOW: { bg: 'bg-emerald-50', border: 'border-emerald-200', badge: 'bg-emerald-100 text-emerald-700 border-emerald-300' },
                    SKIP:  { bg: 'bg-gray-50',    border: 'border-gray-200',   badge: 'bg-gray-100 text-gray-500 border-gray-300'   },
                  }[p.action] ?? { bg: 'bg-gray-50', border: 'border-gray-200', badge: 'bg-gray-100 text-gray-500 border-gray-300' }
                  return (
                    <div key={i} className={cn('flex items-center gap-3 rounded-xl border p-3', actionCfg.bg, actionCfg.border)}>
                      <div className="flex-1 min-w-0">
                        <p className="text-[12px] font-semibold text-gray-800">{p.policy}</p>
                        <p className="text-[10.5px] text-gray-500 mt-0.5 leading-snug">{p.trigger}</p>
                      </div>
                      <span className={cn('px-2 py-0.5 rounded-full border text-[10px] font-bold shrink-0', actionCfg.badge)}>
                        {p.action}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}

            {/* ── Risk Analysis ── */}
            {activeTab === 'Risk Analysis' && (
              <div className="p-4 space-y-4">
                {/* Live risk trend (always shown when events exist) */}
                {simEvents.length > 0 && (
                  <div className="bg-white rounded-xl border border-gray-200 p-4">
                    <div className="flex items-center justify-between mb-3">
                      <SectionLabel>Risk Over Time</SectionLabel>
                      {state === 'running' && (
                        <span className="text-[10px] text-emerald-600 font-semibold flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse inline-block" />
                          Live
                        </span>
                      )}
                    </div>
                    <RiskTrend events={simEvents} live={state === 'running'} />
                  </div>
                )}

                {/* Static risk analysis from result */}
                {result?.risk && (
                  <>
                    {/* Anomaly score bar */}
                    <div className="bg-white rounded-xl border border-gray-200 p-4">
                      <div className="flex items-center justify-between mb-3">
                        <div>
                          <SectionLabel>Anomaly Score</SectionLabel>
                          <p className="text-[10px] text-gray-400 mt-0.5">0.85 block · 0.50 flag thresholds</p>
                        </div>
                        <span className={cn(
                          'text-[28px] font-black tabular-nums leading-none',
                          result.risk.anomalyScore >= 0.8 ? 'text-red-600' : result.risk.anomalyScore >= 0.5 ? 'text-amber-600' : 'text-emerald-600',
                        )}>
                          {result.risk.anomalyScore.toFixed(2)}
                        </span>
                      </div>
                      <div className="relative h-3 rounded-full overflow-visible bg-gray-100">
                        <div className="absolute inset-0 rounded-full overflow-hidden"
                          style={{ background: 'linear-gradient(to right, #10b981 0%, #f59e0b 50%, #ef4444 85%, #dc2626 100%)' }}
                        >
                          <div
                            className="absolute top-0 right-0 bottom-0 bg-gray-100 transition-all duration-700"
                            style={{ width: `${(1 - result.risk.anomalyScore) * 100}%` }}
                          />
                        </div>
                        <div className="absolute top-[-3px] bottom-[-3px] w-px bg-red-600 z-10" style={{ left: '85%' }}>
                          <div className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap">
                            <span className="text-[8px] font-bold text-red-600 bg-white px-0.5">0.85</span>
                          </div>
                        </div>
                        <div className="absolute top-[-3px] bottom-[-3px] w-px bg-amber-500 z-10" style={{ left: '50%' }}>
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
                            <div key={i} className="flex items-center gap-2 text-[11px] text-gray-700 bg-red-50/60 border border-red-100 rounded-lg px-3 py-1.5">
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
                          <p className="text-[11.5px] text-gray-700 leading-relaxed">{result.risk.explanation}</p>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ── Recommendations ── */}
            {activeTab === 'Recommendations' && !result && <TabEmpty label="Recommendations will appear here after a simulation runs." />}
            {activeTab === 'Recommendations' && result && (
              <div className="p-4 space-y-3">
                <p className="text-[11px] text-gray-400">Suggested actions based on simulation results.</p>
                {result.recommendations?.map((rec, i) => (
                  <div key={i} className="bg-white rounded-xl border border-gray-200 p-3.5 flex items-start gap-3">
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
                ))}
              </div>
            )}

          </>
        )}

      </div>
    </div>
  )
}
