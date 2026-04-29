import { useState, useEffect } from 'react'
import {
  Search, X, Download, Bookmark, FileText,
  ShieldCheck, ShieldAlert, Shield, Activity,
  Bot, Database, AlertTriangle, CheckCircle2,
  Filter, ChevronDown, Minus,
  TrendingUp, TrendingDown, Zap, Sparkles, RefreshCw,
  Lock, Clock, Eye,
  Wrench, Fingerprint, FlaskConical,
  ArrowRight, ExternalLink, BarChart2, Workflow,
  LayoutGrid, Settings,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { fetchPostureSummary } from '../api/spm.js'

// ── Design tokens ──────────────────────────────────────────────────────────────

const SCORE_TIER_CFG = {
  Healthy:  {
    label: 'Healthy',  strip: 'bg-emerald-500', bar: 'bg-emerald-400',
    scoreColor: 'text-emerald-600', iconBg: 'bg-emerald-50', iconBorder: 'border-emerald-200',
    iconColor:  'text-emerald-600', pill: 'text-emerald-700 bg-emerald-50 border-emerald-200',
    bdr: 'border-l-emerald-400',
  },
  Warning:  {
    label: 'Warning',  strip: 'bg-yellow-400',  bar: 'bg-yellow-400',
    scoreColor: 'text-yellow-600',  iconBg: 'bg-yellow-50',  iconBorder: 'border-yellow-200',
    iconColor:  'text-yellow-600',  pill: 'text-yellow-700 bg-yellow-50 border-yellow-200',
    bdr: 'border-l-yellow-400',
  },
  Critical: {
    label: 'Critical', strip: 'bg-red-500',     bar: 'bg-red-500',
    scoreColor: 'text-red-600',     iconBg: 'bg-red-50',     iconBorder: 'border-red-200',
    iconColor:  'text-red-600',     pill: 'text-red-700 bg-red-50 border-red-200',
    bdr: 'border-l-red-500',
  },
}

const SEVERITY_CFG = {
  Critical: { dot: 'bg-red-500',     pill: 'text-red-700 bg-red-50 border-red-200',         bdr: 'border-l-red-500',     priorityBg: 'bg-red-50'    },
  High:     { dot: 'bg-orange-500',  pill: 'text-orange-700 bg-orange-50 border-orange-200', bdr: 'border-l-orange-500',  priorityBg: 'bg-orange-50' },
  Medium:   { dot: 'bg-yellow-400',  pill: 'text-yellow-700 bg-yellow-50 border-yellow-200', bdr: 'border-l-yellow-400',  priorityBg: 'bg-yellow-50' },
  Low:      { dot: 'bg-blue-400',    pill: 'text-blue-700 bg-blue-50 border-blue-200',       bdr: 'border-l-blue-400',    priorityBg: 'bg-blue-50'   },
}

const IMPACT_CFG = {
  High:   { dot: 'bg-red-500',    pill: 'text-red-700 bg-red-50 border-red-100',         bdr: 'border-l-red-500'    },
  Medium: { dot: 'bg-yellow-400', pill: 'text-yellow-700 bg-yellow-50 border-yellow-100', bdr: 'border-l-yellow-400' },
  Low:    { dot: 'bg-blue-400',   pill: 'text-blue-700 bg-blue-50 border-blue-100',       bdr: 'border-l-blue-400'   },
}

const DRIFT_STATUS_CFG = {
  Detected: 'text-red-600 bg-red-50 border-red-100',
  Warning:  'text-yellow-700 bg-yellow-50 border-yellow-100',
  Pending:  'text-orange-700 bg-orange-50 border-orange-100',
  Resolved: 'text-emerald-700 bg-emerald-50 border-emerald-100',
}

const DOMAIN_COLOR_CFG = {
  'Context Security':        { color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  'Runtime Enforcement':     { color: 'text-yellow-600',  bg: 'bg-yellow-50',  border: 'border-yellow-200'  },
  'Tool Access Governance':  { color: 'text-blue-600',    bg: 'bg-blue-50',    border: 'border-blue-200'    },
  'Identity & Trust':        { color: 'text-violet-600',  bg: 'bg-violet-50',  border: 'border-violet-200'  },
  'Data & Knowledge':        { color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200'     },
  'Policy Coverage':         { color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200'  },
  'Simulation Readiness':    { color: 'text-pink-600',    bg: 'bg-pink-50',    border: 'border-pink-200'    },
  'Observability / Audit':   { color: 'text-cyan-600',    bg: 'bg-cyan-50',    border: 'border-cyan-200'    },
}

// ── Mock data ──────────────────────────────────────────────────────────────────

const DOMAINS = [
  {
    id: 'd1', name: 'Context Security', icon: Shield,
    score: 88, prevScore: 84, trend: +4,
    summary: '14 agents with validated context bounds. 2 sources pending re-validation.',
    covered: 14, uncovered: 2, warnings: 1, lastUpdated: '2h ago',
    scoreHistory: [80, 82, 81, 83, 84, 85, 88],
  },
  {
    id: 'd2', name: 'Runtime Enforcement', icon: Zap,
    score: 71, prevScore: 74, trend: -3,
    summary: '9 agents in monitor-only mode. 4 missing active enforcement policy.',
    covered: 22, uncovered: 9, warnings: 4, lastUpdated: '30m ago',
    scoreHistory: [74, 75, 74, 73, 74, 74, 71],
  },
  {
    id: 'd3', name: 'Tool Access Governance', icon: Wrench,
    score: 76, prevScore: 76, trend: 0,
    summary: '4 high-risk tools without scoped enforcement. 2 over-privileged principals.',
    covered: 18, uncovered: 4, warnings: 3, lastUpdated: '1h ago',
    scoreHistory: [73, 74, 75, 76, 76, 76, 76],
  },
  {
    id: 'd4', name: 'Identity & Trust', icon: Fingerprint,
    score: 79, prevScore: 77, trend: +2,
    summary: '18 identities with elevated access pending review. 3 with expiring credentials.',
    covered: 61, uncovered: 18, warnings: 5, lastUpdated: '45m ago',
    scoreHistory: [74, 75, 76, 77, 77, 78, 79],
  },
  {
    id: 'd5', name: 'Data & Knowledge', icon: Database,
    score: 63, prevScore: 68, trend: -5,
    summary: '3 sensitive knowledge sources unvalidated. finance-rag-bucket 2d stale.',
    covered: 7, uncovered: 3, warnings: 4, lastUpdated: '2h ago',
    scoreHistory: [68, 67, 68, 67, 66, 65, 63],
  },
  {
    id: 'd6', name: 'Policy Coverage', icon: FileText,
    score: 79, prevScore: 76, trend: +3,
    summary: '12 production agents missing strict prompt policy assignment.',
    covered: 34, uncovered: 12, warnings: 2, lastUpdated: '3h ago',
    scoreHistory: [72, 73, 74, 75, 76, 77, 79],
  },
  {
    id: 'd7', name: 'Simulation Readiness', icon: FlaskConical,
    score: 54, prevScore: 54, trend: 0,
    summary: 'Critical flows lack simulation coverage. Last simulation run 14 days ago.',
    covered: 6, uncovered: 11, warnings: 0, lastUpdated: '14d ago',
    scoreHistory: [52, 54, 55, 54, 53, 54, 54],
  },
  {
    id: 'd8', name: 'Observability / Audit', icon: Activity,
    score: 83, prevScore: 80, trend: +3,
    summary: 'Telemetry active on 19 of 22 agents. 3 missing audit trail configuration.',
    covered: 19, uncovered: 3, warnings: 1, lastUpdated: '15m ago',
    scoreHistory: [78, 79, 79, 80, 80, 81, 83],
  },
]

const POSTURE_GAPS = [
  {
    id: 'gap-001', severity: 'Critical', domain: 'Policy Coverage', domainIcon: FileText,
    title: '12 production agents missing strict prompt policy',
    affectedCount: 12, affectedLabel: 'agents', age: '3d',
    remediation: 'Bulk-assign Prompt-Guard v3 to all production agents via Policy Manager.',
    action: 'Open Policy Manager',
  },
  {
    id: 'gap-002', severity: 'Critical', domain: 'Tool Access Governance', domainIcon: Wrench,
    title: '4 high-risk tools operating without scoped enforcement',
    affectedCount: 4, affectedLabel: 'tools', age: '1d',
    remediation: 'Enable scoped enforcement for PII-capable and network-access tools.',
    action: 'Open Tool Controls',
  },
  {
    id: 'gap-003', severity: 'Critical', domain: 'Data & Knowledge', domainIcon: Database,
    title: '3 sensitive knowledge sources have not been validated',
    affectedCount: 3, affectedLabel: 'sources', age: '2d',
    remediation: 'Run validation scan on Restricted and Confidential sources; check for content drift.',
    action: 'View Sources',
  },
  {
    id: 'gap-004', severity: 'High', domain: 'Identity & Trust', domainIcon: Fingerprint,
    title: '18 identities have elevated access without completed review',
    affectedCount: 18, affectedLabel: 'identities', age: '5d',
    remediation: 'Trigger access review workflow for all identities flagged with Elevated Access.',
    action: 'Review Access',
  },
  {
    id: 'gap-005', severity: 'High', domain: 'Simulation Readiness', domainIcon: FlaskConical,
    title: '11 critical simulation flows have no test coverage',
    affectedCount: 11, affectedLabel: 'flows', age: '14d',
    remediation: 'Schedule simulation runs for all untested production agent workflows.',
    action: 'Launch Simulation',
  },
  {
    id: 'gap-006', severity: 'Medium', domain: 'Runtime Enforcement', domainIcon: Zap,
    title: '9 agents operating in monitor-only enforcement mode',
    affectedCount: 9, affectedLabel: 'agents', age: '7d',
    remediation: 'Review and upgrade monitor-only agents to enforce mode where policy permits.',
    action: 'View Agents',
  },
]

const COVERAGE_ROWS = [
  { label: 'Agents',           total: 31, covered: 22, icon: Bot,         color: 'text-violet-600' },
  { label: 'Tools',            total: 22, covered: 18, icon: Wrench,      color: 'text-blue-600'   },
  { label: 'Knowledge Sources',total: 10, covered: 7,  icon: Database,    color: 'text-amber-600'  },
  { label: 'Identities',       total: 79, covered: 61, icon: Fingerprint, color: 'text-indigo-600' },
  { label: 'Policies',         total: 46, covered: 34, icon: FileText,    color: 'text-emerald-600'},
  { label: 'Simulation Flows', total: 17, covered: 6,  icon: FlaskConical,color: 'text-pink-600'   },
]

const ENFORCEMENT_DIST = [
  { mode: 'Enforce', count: 22, pct: 71, bar: 'bg-emerald-400', textColor: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  { mode: 'Monitor', count: 7,  pct: 23, bar: 'bg-yellow-400',  textColor: 'text-yellow-700',  bg: 'bg-yellow-50',  border: 'border-yellow-200'  },
  { mode: 'Disabled',count: 2,  pct: 6,  bar: 'bg-gray-300',    textColor: 'text-gray-500',    bg: 'bg-gray-100',   border: 'border-gray-200'    },
]

const SUB_SCORES = [
  { label: 'Prevention',  score: 79, icon: ShieldCheck,  description: 'Policy enforcement & tool control', strip: 'bg-yellow-400',  bar: 'bg-yellow-400',  scoreColor: 'text-yellow-600'  },
  { label: 'Visibility',  score: 83, icon: Eye,          description: 'Observability & audit coverage',     strip: 'bg-emerald-400', bar: 'bg-emerald-400', scoreColor: 'text-emerald-600' },
  { label: 'Governance',  score: 74, icon: Workflow,     description: 'Identity, access & policy hygiene',  strip: 'bg-yellow-400',  bar: 'bg-yellow-400',  scoreColor: 'text-yellow-600'  },
  { label: 'Resilience',  score: 54, icon: FlaskConical, description: 'Simulation & recovery readiness',    strip: 'bg-red-500',     bar: 'bg-red-500',     scoreColor: 'text-red-600'     },
]

const FRAMEWORKS = [
  { name: 'Internal Controls', aligned: 18, total: 24 },
  { name: 'NIST AI RMF',       aligned: 14, total: 22 },
  { name: 'AI Governance v2',  aligned: 21, total: 28 },
]

const DRIFT_EVENTS = [
  { id: 'dr-001', ts: 'Apr 8 · 14:33', domain: 'Runtime Enforcement',   domainIcon: Zap,        change: '5 agents moved from enforce to monitor-only mode',           impact: 'Medium', status: 'Detected' },
  { id: 'dr-002', ts: 'Apr 8 · 13:12', domain: 'Data & Knowledge',      domainIcon: Database,   change: 'finance-rag-bucket marked stale — sync overdue by 2 days',   impact: 'High',   status: 'Detected' },
  { id: 'dr-003', ts: 'Apr 8 · 11:45', domain: 'Policy Coverage',       domainIcon: FileText,   change: '3 new policies deployed across production agents',            impact: 'Low',    status: 'Resolved' },
  { id: 'dr-004', ts: 'Apr 8 · 09:00', domain: 'Identity & Trust',      domainIcon: Fingerprint,change: 'Elevated permission review overdue for 5 identities',         impact: 'High',   status: 'Pending'  },
  { id: 'dr-005', ts: 'Apr 7 · 16:30', domain: 'Tool Access Governance',domainIcon: Wrench,     change: 'web-search-tool scope expanded to include external domains',  impact: 'Medium', status: 'Warning'  },
  { id: 'dr-006', ts: 'Apr 7 · 14:22', domain: 'Context Security',      domainIcon: Shield,     change: 'Prompt injection pattern detected in 2 agent sessions',       impact: 'High',   status: 'Detected' },
  { id: 'dr-007', ts: 'Apr 7 · 10:15', domain: 'Observability / Audit', domainIcon: Activity,   change: 'telemetry-agent-7 — 45 min audit trail gap detected',         impact: 'Medium', status: 'Warning'  },
  { id: 'dr-008', ts: 'Apr 6 · 09:00', domain: 'Simulation Readiness',  domainIcon: FlaskConical,change:'Simulation coverage report generated — 6 flows passing',      impact: 'Low',    status: 'Resolved' },
  { id: 'dr-009', ts: 'Apr 5 · 14:00', domain: 'Policy Coverage',       domainIcon: FileText,   change: 'Prompt-Guard v3 rolled out — 22 agents now covered',          impact: 'Low',    status: 'Resolved' },
  { id: 'dr-010', ts: 'Apr 4 · 11:30', domain: 'Runtime Enforcement',   domainIcon: Zap,        change: 'finance-agent-3 enforcement downgraded — policy review pending',impact:'High',   status: 'Pending'  },
]

const DOMAIN_OPTIONS  = ['All Domains',  ...DOMAINS.map(d => d.name)]
const SEVERITY_OPTIONS = ['All Severities', 'Critical', 'High', 'Medium', 'Low']
const ENV_OPTIONS      = ['All Environments', 'Production', 'Staging', 'Development']
const TIME_OPTIONS     = ['Last 7 days', 'Last 30 days', 'Last 90 days', 'Custom']

// ── Helpers ───────────────────────────────────────────────────────────────────

function getScoreTier(score) {
  if (score >= 80) return 'Healthy'
  if (score >= 65) return 'Warning'
  return 'Critical'
}

function coveragePct(covered, total) {
  return total === 0 ? 0 : Math.round((covered / total) * 100)
}

// ── Primitive components ──────────────────────────────────────────────────────

function FilterSelect({ value, onChange, options }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className={cn(
          'h-8 pl-3 pr-8 text-[12px] font-medium text-gray-600 bg-white',
          'border border-gray-200 rounded-lg appearance-none cursor-pointer',
          'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400',
          'hover:border-gray-300 transition-colors',
        )}
      >
        {options.map(o => <option key={o}>{o}</option>)}
      </select>
      <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
    </div>
  )
}

function Toggle({ checked, onChange }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex w-9 h-5 rounded-full transition-colors duration-200 focus:outline-none shrink-0',
        'focus:ring-2 focus:ring-offset-1',
        checked
          ? 'bg-emerald-500 focus:ring-emerald-400/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]'
          : 'bg-gray-200 focus:ring-gray-300/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.10)]',
      )}
    >
      <span className={cn(
        'absolute top-[3px] left-[3px] w-[14px] h-[14px] rounded-full bg-white shadow-sm transition-transform duration-200',
        checked ? 'translate-x-[16px]' : 'translate-x-0',
      )} />
    </button>
  )
}

function SectionLabel({ children }) {
  return (
    <div className="flex items-center gap-2 mb-2.5">
      <p className="text-[10px] font-black uppercase tracking-[0.1em] text-gray-400 whitespace-nowrap">{children}</p>
      <div className="flex-1 h-px bg-gray-100" />
    </div>
  )
}

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, icon: Icon, iconBg, valueTint, stripColor }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm hover:border-gray-300 transition-colors overflow-hidden">
      {stripColor && <div className={cn('h-[3px] w-full', stripColor)} />}
      <div className="px-5 py-4 flex items-center gap-4">
        <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm', iconBg)}>
          <Icon size={17} className="text-white" strokeWidth={1.75} />
        </div>
        <div className="min-w-0">
          <p className={cn('text-[22px] font-black tabular-nums leading-none', valueTint ?? 'text-gray-900')}>{value}</p>
          <p className="text-[11px] font-semibold text-gray-500 mt-0.5">{label}</p>
          {sub && <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>}
        </div>
      </div>
    </div>
  )
}

// ── Trend chip ────────────────────────────────────────────────────────────────

function TrendChip({ trend }) {
  if (trend > 0) return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9.5px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200">
      <TrendingUp size={9} /> +{trend}
    </span>
  )
  if (trend < 0) return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9.5px] font-bold text-red-600 bg-red-50 border border-red-200">
      <TrendingDown size={9} /> {trend}
    </span>
  )
  return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9.5px] font-bold text-gray-500 bg-gray-100 border border-gray-200">
      <Minus size={9} /> 0
    </span>
  )
}

// ── Sparkline ─────────────────────────────────────────────────────────────────

function Sparkline({ history, barColor }) {
  const max = Math.max(...history)
  const min = Math.min(...history) - 4
  const range = max - min || 1
  return (
    <div className="flex items-end gap-[2px] h-6">
      {history.map((v, i) => {
        const ht = Math.round(((v - min) / range) * 20) + 2
        return (
          <div
            key={i}
            className={cn('w-[3px] rounded-full opacity-70', barColor)}
            style={{ height: `${ht}px` }}
          />
        )
      })}
    </div>
  )
}

// ── Domain Card ───────────────────────────────────────────────────────────────

function DomainCard({ domain, isSelected, onSelect }) {
  const tier   = getScoreTier(domain.score)
  const cfg    = SCORE_TIER_CFG[tier]
  const DIcon  = domain.icon

  return (
    <div
      onClick={() => onSelect(domain.id)}
      className={cn(
        'bg-white border rounded-xl shadow-sm overflow-hidden cursor-pointer transition-all duration-150',
        isSelected
          ? 'border-blue-300 shadow-[0_0_0_2px_rgba(59,130,246,0.15)]'
          : 'border-gray-200 hover:border-gray-300 hover:shadow-md',
      )}
    >
      {/* Accent strip */}
      <div className={cn('h-[3px] w-full shrink-0', cfg.strip)} />

      <div className="p-4">
        {/* Header: icon + name + trend */}
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center border shadow-sm shrink-0', cfg.iconBg, cfg.iconBorder)}>
              <DIcon size={15} className={cfg.iconColor} />
            </div>
            <p className="text-[12.5px] font-bold text-gray-800 leading-snug truncate">{domain.name}</p>
          </div>
          <TrendChip trend={domain.trend} />
        </div>

        {/* Score + sparkline row */}
        <div className="flex items-end justify-between mb-2">
          <div className="flex items-end gap-1.5">
            <span className={cn('text-[32px] font-black tabular-nums leading-none', cfg.scoreColor)}>
              {domain.score}
            </span>
            <span className="text-[10px] text-gray-400 mb-1.5 font-medium">/100</span>
          </div>
          <Sparkline history={domain.scoreHistory} barColor={cfg.bar} />
        </div>

        {/* Full-width score bar + status pill inline */}
        <div className="flex items-center gap-2.5 mb-3">
          <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
            <div className={cn('h-full rounded-full transition-all', cfg.bar)} style={{ width: `${domain.score}%` }} />
          </div>
          <span className={cn('inline-flex items-center text-[9px] font-black px-2 py-0.5 rounded-full border tracking-[0.05em] shrink-0', cfg.pill)}>
            {cfg.label}
          </span>
        </div>

        {/* Summary */}
        <p className="text-[11.5px] text-gray-500 leading-snug mb-3">{domain.summary}</p>

        {/* Indicators */}
        <div className="flex items-center gap-3 text-[10.5px] font-semibold pt-2.5 border-t border-gray-100">
          <span className="flex items-center gap-1 text-emerald-600">
            <CheckCircle2 size={10} /> {domain.covered} covered
          </span>
          {domain.uncovered > 0 && (
            <span className="flex items-center gap-1 text-red-500">
              <ShieldAlert size={10} /> {domain.uncovered} uncovered
            </span>
          )}
          {domain.warnings > 0 && (
            <span className="flex items-center gap-1 text-yellow-600">
              <AlertTriangle size={10} /> {domain.warnings} warn
            </span>
          )}
          <span className="ml-auto text-[10px] text-gray-300 font-normal tabular-nums">{domain.lastUpdated}</span>
        </div>
      </div>
    </div>
  )
}

// ── Score Overview Panel ──────────────────────────────────────────────────────

function ScoreOverviewPanel() {
  const sorted = [...DOMAINS].sort((a, b) => b.score - a.score)
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-5 flex-1 min-w-0">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-[13px] font-bold text-gray-900">Domain Score Overview</p>
          <p className="text-[11px] text-gray-400 mt-0.5">Current posture score per domain — sorted by score</p>
        </div>
        <BarChart2 size={16} className="text-gray-300" />
      </div>
      <div className="space-y-3">
        {sorted.map(domain => {
          const tier = getScoreTier(domain.score)
          const cfg  = SCORE_TIER_CFG[tier]
          const DIcon = domain.icon
          return (
            <div key={domain.id} className="group flex items-center gap-3 px-2 py-1 rounded-lg hover:bg-gray-50 transition-colors -mx-2">
              {/* Icon */}
              <div className={cn('w-6 h-6 rounded-md flex items-center justify-center border shrink-0', cfg.iconBg, cfg.iconBorder)}>
                <DIcon size={11} className={cfg.iconColor} />
              </div>
              {/* Name */}
              <span className="text-[11.5px] font-semibold text-gray-600 w-[168px] shrink-0 truncate">{domain.name}</span>
              {/* Bar track */}
              <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all duration-500', cfg.bar)}
                  style={{ width: `${domain.score}%` }}
                />
              </div>
              {/* Score + trend */}
              <div className="flex items-center gap-1.5 shrink-0 w-[68px] justify-end">
                <span className={cn('text-[12.5px] font-black tabular-nums', cfg.scoreColor)}>{domain.score}</span>
                <TrendChip trend={domain.trend} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Sub-scores + Framework Panel ──────────────────────────────────────────────

function SubScoresPanel() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-5 w-[320px] shrink-0 flex flex-col gap-5">
      {/* Sub-scores */}
      <div>
        <div className="flex items-center justify-between mb-3.5">
          <p className="text-[13px] font-bold text-gray-900">Posture Breakdown</p>
          <Sparkles size={14} className="text-gray-300" />
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          {SUB_SCORES.map(s => {
            const SIcon = s.icon
            return (
              <div key={s.label} className="bg-gray-50 border border-gray-100 rounded-xl px-3 py-3.5 overflow-hidden relative">
                <div className={cn('absolute top-0 left-0 right-0 h-[3px]', s.strip)} />
                <div className="flex items-center gap-1.5 mb-2 mt-0.5">
                  <SIcon size={11} className={cn('shrink-0', s.scoreColor)} />
                  <span className="text-[10px] font-black uppercase tracking-[0.06em] text-gray-400">{s.label}</span>
                </div>
                <p className={cn('text-[24px] font-black tabular-nums leading-none mb-2', s.scoreColor)}>{s.score}</p>
                <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div className={cn('h-full rounded-full', s.bar)} style={{ width: `${s.score}%` }} />
                </div>
                <p className="text-[9.5px] text-gray-400 mt-1.5 leading-tight">{s.description}</p>
              </div>
            )
          })}
        </div>
      </div>

      {/* Framework alignment */}
      <div>
        <SectionLabel>Framework Alignment</SectionLabel>
        <div className="space-y-2">
          {FRAMEWORKS.map(fw => {
            const pct = Math.round((fw.aligned / fw.total) * 100)
            const barColor = pct >= 80 ? 'bg-emerald-400' : pct >= 65 ? 'bg-yellow-400' : 'bg-red-500'
            const textColor = pct >= 80 ? 'text-emerald-600' : pct >= 65 ? 'text-yellow-600' : 'text-red-600'
            return (
              <div key={fw.name}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] font-medium text-gray-600">{fw.name}</span>
                  <span className={cn('text-[10.5px] font-black tabular-nums', textColor)}>
                    {fw.aligned}/{fw.total} <span className="font-medium text-gray-400">({pct}%)</span>
                  </span>
                </div>
                <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className={cn('h-full rounded-full', barColor)} style={{ width: `${pct}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Posture Gap Row ───────────────────────────────────────────────────────────

function PostureGapRow({ gap, index }) {
  const sev  = SEVERITY_CFG[gap.severity] || SEVERITY_CFG.Medium
  const DomainIcon = gap.domainIcon
  const domCfg = DOMAIN_COLOR_CFG[gap.domain] || { color: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200' }

  return (
    <div className={cn(
      'flex items-start gap-4 px-4 py-3.5 bg-white border border-gray-150 rounded-xl',
      'hover:border-gray-200 hover:bg-gray-50/40 transition-colors',
      'border-l-[3px] shadow-[0_1px_2px_rgba(0,0,0,0.04)]',
      sev.bdr,
    )}>
      {/* Priority index */}
      <div className="w-7 h-7 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center shrink-0 mt-0.5 shadow-[0_1px_2px_rgba(0,0,0,0.06)]">
        <span className="text-[10.5px] font-black text-gray-500">{index + 1}</span>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3 mb-1.5">
          <p className="text-[12.5px] font-bold text-gray-800 leading-snug">{gap.title}</p>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-black border', sev.pill)}>
              <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', sev.dot)} />
              {gap.severity}
            </span>
          </div>
        </div>

        {/* Domain + affected + age */}
        <div className="flex items-center gap-2 mb-2">
          <div className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-semibold', domCfg.color, domCfg.bg, domCfg.border)}>
            <DomainIcon size={9} />
            {gap.domain}
          </div>
          <span className="text-[10.5px] font-black text-gray-700 tabular-nums">
            {gap.affectedCount} <span className="font-medium text-gray-500">{gap.affectedLabel} affected</span>
          </span>
          <span className="text-[10px] text-gray-300">·</span>
          <span className="flex items-center gap-0.5 text-[10px] text-gray-400 font-medium">
            <Clock size={9} /> {gap.age}
          </span>
        </div>

        {/* Remediation */}
        <p className="text-[11px] text-gray-500 leading-snug mb-2.5 pl-3 border-l-2 border-gray-150">{gap.remediation}</p>

        {/* Action */}
        <Button size="sm" variant="outline" className="h-7 gap-1 text-[10.5px] text-blue-600 border-blue-200 hover:bg-blue-50">
          <ArrowRight size={9} /> {gap.action}
        </Button>
      </div>
    </div>
  )
}

// ── Coverage Card ─────────────────────────────────────────────────────────────

function CoverageCard() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-5 flex-1 min-w-0">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-[13px] font-bold text-gray-900">Coverage by Asset Type</p>
          <p className="text-[11px] text-gray-400 mt-0.5">Posture coverage across all managed asset classes</p>
        </div>
        <ShieldCheck size={15} className="text-gray-300" />
      </div>
      <div className="space-y-3">
        {COVERAGE_ROWS.map(row => {
          const pct   = coveragePct(row.covered, row.total)
          const barColor   = pct >= 90 ? 'bg-emerald-400' : pct >= 70 ? 'bg-yellow-400' : pct >= 50 ? 'bg-orange-400' : 'bg-red-500'
          const textColor  = pct >= 90 ? 'text-emerald-600' : pct >= 70 ? 'text-yellow-600' : pct >= 50 ? 'text-orange-600' : 'text-red-600'
          const RowIcon = row.icon
          return (
            <div key={row.label} className="group">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <RowIcon size={11} className={row.color} />
                  <span className="text-[11.5px] font-semibold text-gray-600">{row.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10.5px] text-gray-400 font-medium tabular-nums font-mono">{row.covered}/{row.total}</span>
                  <span className={cn('text-[11px] font-mono font-black tabular-nums w-10 text-right', textColor)}>{pct}%</span>
                </div>
              </div>
              <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden mt-0.5">
                <div className={cn('h-full rounded-full transition-all duration-500', barColor)} style={{ width: `${pct}%` }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Enforcement Card ──────────────────────────────────────────────────────────

function EnforcementCard() {
  const total = ENFORCEMENT_DIST.reduce((s, e) => s + e.count, 0)

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-5 w-[320px] shrink-0">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-[13px] font-bold text-gray-900">Enforcement Distribution</p>
          <p className="text-[11px] text-gray-400 mt-0.5">Across {total} monitored agents</p>
        </div>
        <Zap size={15} className="text-gray-300" />
      </div>

      {/* Segmented bar */}
      <div className="flex h-3 rounded-full overflow-hidden gap-0.5 mb-4">
        {ENFORCEMENT_DIST.map(e => (
          <div
            key={e.mode}
            className={cn('h-full rounded-sm first:rounded-l-full last:rounded-r-full', e.bar)}
            style={{ width: `${e.pct}%` }}
            title={`${e.mode}: ${e.pct}%`}
          />
        ))}
      </div>

      {/* Breakdown rows */}
      <div className="space-y-2 mb-5">
        {ENFORCEMENT_DIST.map(e => (
          <div key={e.mode} className={cn('flex items-center justify-between px-3 py-2 rounded-lg border shadow-[0_1px_2px_rgba(0,0,0,0.04)]', e.bg, e.border)}>
            <div className="flex items-center gap-2">
              <span className={cn('w-2 h-2 rounded-full shrink-0', e.bar)} />
              <span className={cn('text-[11.5px] font-semibold', e.textColor)}>{e.mode}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={cn('text-[12px] font-black tabular-nums', e.textColor)}>{e.count}</span>
              <span className={cn('text-[10px] font-semibold tabular-nums', e.textColor)}>({e.pct}%)</span>
            </div>
          </div>
        ))}
      </div>

      {/* Assets missing telemetry */}
      <div>
        <SectionLabel>Assets Missing Telemetry</SectionLabel>
        <div className="space-y-1.5">
          {[
            { label: 'Agents without trust scoring',    count: 5, icon: Bot,    color: 'text-violet-500' },
            { label: 'Sources missing validation',      count: 3, icon: Database,color: 'text-amber-500' },
            { label: 'Identities without session log',  count: 8, icon: Fingerprint, color: 'text-indigo-500' },
          ].map(item => {
            const IIcon = item.icon
            return (
              <div key={item.label} className="flex items-center justify-between px-3 py-2 bg-gray-50 border border-gray-100 rounded-lg">
                <div className="flex items-center gap-1.5">
                  <IIcon size={11} className={item.color} />
                  <span className="text-[11px] text-gray-600 font-semibold">{item.label}</span>
                </div>
                <span className="text-[13px] font-black text-red-500 tabular-nums font-mono">{item.count}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Drift Events Table ────────────────────────────────────────────────────────

function DriftEventsTable({ events }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between bg-white">
        <div className="flex items-center gap-3">
          <p className="text-[13px] font-bold text-gray-900">Recent Posture Changes</p>
          <span className="text-[10px] font-black uppercase tracking-[0.06em] text-gray-400 bg-gray-100 rounded-full px-2 py-0.5">{events.length} events</span>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <RefreshCw size={11} /> Refresh
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <ExternalLink size={11} /> Full Log
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="w-0 p-0" />
              {['Timestamp', 'Domain', 'Change', 'Impact', 'Status'].map(col => (
                <th key={col} className="px-3.5 py-2.5 text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-75">
            {events.map(ev => {
              const impCfg  = IMPACT_CFG[ev.impact]  || IMPACT_CFG.Low
              const statCls = DRIFT_STATUS_CFG[ev.status] || DRIFT_STATUS_CFG.Info
              const EVIcon  = ev.domainIcon
              const domCfg  = DOMAIN_COLOR_CFG[ev.domain] || { color: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200' }
              return (
                <tr key={ev.id} className={cn('hover:bg-gray-50/50 transition-colors border-l-[3px] group', impCfg.bdr)}>
                  <td className="w-0 p-0" />
                  {/* Timestamp */}
                  <td className="px-3.5 py-2.5 whitespace-nowrap">
                    <span className="text-[10.5px] font-mono text-gray-400">{ev.ts}</span>
                  </td>
                  {/* Domain */}
                  <td className="px-3.5 py-2.5">
                    <div className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-semibold whitespace-nowrap', domCfg.color, domCfg.bg, domCfg.border)}>
                      <EVIcon size={9} />
                      {ev.domain}
                    </div>
                  </td>
                  {/* Change */}
                  <td className="px-3.5 py-2.5">
                    <span className="text-[11.5px] font-semibold text-gray-700">{ev.change}</span>
                  </td>
                  {/* Impact */}
                  <td className="px-3.5 py-2.5 whitespace-nowrap">
                    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold border', impCfg.pill)}>
                      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', impCfg.dot)} />
                      {ev.impact}
                    </span>
                  </td>
                  {/* Status */}
                  <td className="px-3.5 py-2.5 whitespace-nowrap">
                    <span className={cn('inline-flex items-center text-[10.5px] font-semibold px-2 py-0.5 rounded-full border', statCls)}>
                      {ev.status}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Posture() {
  const [search,         setSearch]         = useState('')
  const [filterDomain,   setFilterDomain]   = useState('All Domains')
  const [filterSeverity, setFilterSeverity] = useState('All Severities')
  const [filterEnv,      setFilterEnv]      = useState('All Environments')
  const [filterTime,     setFilterTime]     = useState('Last 7 days')
  const [onlyUncovered,  setOnlyUncovered]  = useState(false)
  const [selectedDomain, setSelectedDomain] = useState(null)

  // ── Live posture summary from spm-api /posture/summary ────────────────────
  // Backed by the seeded posture_snapshots table (30 daily rows from
  // seed_db.py). Hits a real endpoint, falls back to null on failure so
  // the page still renders its (still-mocked) rich sub-sections offline.
  // Key takeaway: this is the ONE thing on the Posture page sourced from
  // real data today — the rest of the constants below are placeholders
  // pending corresponding backend tables.
  const [liveSummary, setLiveSummary] = useState(null)
  useEffect(() => {
    let cancelled = false
    fetchPostureSummary({ days: 30 }).then(s => {
      if (!cancelled) setLiveSummary(s)
    })
    return () => { cancelled = true }
  }, [])

  // Filtered domains
  const filteredDomains = DOMAINS.filter(d => {
    if (filterDomain !== 'All Domains' && d.name !== filterDomain) return false
    if (onlyUncovered && d.uncovered === 0) return false
    const q = search.toLowerCase()
    if (q && !d.name.toLowerCase().includes(q) && !d.summary.toLowerCase().includes(q)) return false
    return true
  })

  // Filtered gaps
  const filteredGaps = POSTURE_GAPS.filter(g => {
    if (filterDomain !== 'All Domains' && g.domain !== filterDomain) return false
    if (filterSeverity !== 'All Severities' && g.severity !== filterSeverity) return false
    return true
  })

  // Overall score
  const overallScore   = Math.round(DOMAINS.reduce((s, d) => s + d.score, 0) / DOMAINS.length)
  const criticalGaps   = POSTURE_GAPS.filter(g => g.severity === 'Critical').length
  const avgCoverage    = Math.round(
    COVERAGE_ROWS.reduce((s, r) => s + coveragePct(r.covered, r.total), 0) / COVERAGE_ROWS.length
  )
  const domainsAtRisk  = DOMAINS.filter(d => getScoreTier(d.score) === 'Critical').length

  const overallTier = getScoreTier(overallScore)

  return (
    <PageContainer>
      {/* ── Page header ── */}
      <PageHeader
        title="Posture"
        subtitle="Measure AI security coverage, posture gaps, and enforcement readiness across your environment"
        actions={
          <>
            <Button size="sm" variant="outline" className="gap-1.5">
              <Bookmark size={13} /> Saved Views
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5">
              <Download size={13} /> Export
            </Button>
            <Button size="sm" className="gap-1.5">
              <Sparkles size={13} /> Generate Report
            </Button>
          </>
        }
      />

      {/* ── KPI strip ── */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard
          label="Overall Posture Score"
          value={`${overallScore}/100`}
          sub={`${overallTier} — across 8 domains`}
          icon={ShieldCheck}
          iconBg={overallTier === 'Healthy' ? 'bg-emerald-500' : overallTier === 'Warning' ? 'bg-yellow-500' : 'bg-red-500'}
          valueTint={overallTier === 'Healthy' ? 'text-emerald-600' : overallTier === 'Warning' ? 'text-yellow-600' : 'text-red-600'}
          stripColor={overallTier === 'Healthy' ? 'bg-emerald-500' : overallTier === 'Warning' ? 'bg-yellow-400' : 'bg-red-500'}
        />
        <KpiCard
          label="Critical Gaps"
          value={criticalGaps}
          sub="Require immediate remediation"
          icon={ShieldAlert}
          iconBg="bg-red-500"
          valueTint={criticalGaps > 0 ? 'text-red-600' : 'text-gray-900'}
          stripColor={criticalGaps > 0 ? 'bg-red-500' : 'bg-gray-200'}
        />
        <KpiCard
          label="Average Coverage"
          value={`${avgCoverage}%`}
          sub="Across all asset types"
          icon={LayoutGrid}
          iconBg="bg-blue-500"
          valueTint={avgCoverage >= 80 ? 'text-emerald-600' : avgCoverage >= 60 ? 'text-yellow-600' : 'text-red-600'}
          stripColor={avgCoverage >= 80 ? 'bg-emerald-500' : avgCoverage >= 60 ? 'bg-yellow-400' : 'bg-red-500'}
        />
        <KpiCard
          label="Domains at Risk"
          value={domainsAtRisk}
          sub="Score below 65 — Critical tier"
          icon={AlertTriangle}
          iconBg="bg-orange-500"
          valueTint={domainsAtRisk > 0 ? 'text-orange-600' : 'text-gray-900'}
          stripColor={domainsAtRisk > 0 ? 'bg-orange-500' : 'bg-gray-200'}
        />
      </div>

      {/* ── Live Activity strip (real data from posture_snapshots) ──
          Sourced from spm-api GET /posture/summary, which aggregates the
          30 daily rows seeded by services/spm_api/seed_db.py. The block
          renders only when the API returns data — if spm-api is offline
          or the seed hasn't run, the strip silently disappears so the
          rest of the page (still mocked) keeps rendering. */}
      {liveSummary && liveSummary.snapshot_count > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-[0.06em] px-2 py-0.5 rounded-full border text-emerald-700 bg-emerald-50 border-emerald-200">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live
            </span>
            <p className="text-[12px] font-semibold text-gray-700">
              Platform activity — last {liveSummary.window_days} days
              <span className="text-[11px] font-medium text-gray-400 ml-2">
                ({liveSummary.snapshot_count} daily snapshots)
              </span>
            </p>
          </div>
          <div className="grid grid-cols-4 gap-4">
            <KpiCard
              label="Total Requests"
              value={liveSummary.total_requests.toLocaleString()}
              sub={`${liveSummary.total_blocks.toLocaleString()} blocked (${liveSummary.block_rate_pct}%)`}
              icon={Activity}
              iconBg="bg-blue-500"
              valueTint="text-gray-900"
              stripColor="bg-blue-500"
            />
            <KpiCard
              label="Avg Risk Score"
              value={liveSummary.avg_risk_score.toFixed(2)}
              sub={`Peak ${liveSummary.max_risk_score.toFixed(2)} over window`}
              icon={ShieldAlert}
              iconBg={liveSummary.avg_risk_score >= 0.6 ? 'bg-red-500'
                    : liveSummary.avg_risk_score >= 0.4 ? 'bg-yellow-500' : 'bg-emerald-500'}
              valueTint={liveSummary.avg_risk_score >= 0.6 ? 'text-red-600'
                       : liveSummary.avg_risk_score >= 0.4 ? 'text-yellow-600' : 'text-emerald-600'}
              stripColor={liveSummary.avg_risk_score >= 0.6 ? 'bg-red-500'
                        : liveSummary.avg_risk_score >= 0.4 ? 'bg-yellow-400' : 'bg-emerald-500'}
            />
            <KpiCard
              label="Avg Intent Drift"
              value={liveSummary.avg_intent_drift.toFixed(3)}
              sub="Lower is better — semantic stability"
              icon={Workflow}
              iconBg="bg-purple-500"
              valueTint={liveSummary.avg_intent_drift >= 0.15 ? 'text-red-600'
                       : liveSummary.avg_intent_drift >= 0.08 ? 'text-yellow-600' : 'text-emerald-600'}
              stripColor="bg-purple-500"
            />
            <KpiCard
              label="TTP Hits"
              value={liveSummary.total_ttp_hits}
              sub={`${liveSummary.total_escalations} escalations triggered`}
              icon={Zap}
              iconBg="bg-orange-500"
              valueTint={liveSummary.total_ttp_hits > 0 ? 'text-orange-600' : 'text-gray-900'}
              stripColor={liveSummary.total_ttp_hits > 0 ? 'bg-orange-500' : 'bg-gray-200'}
            />
          </div>
        </div>
      )}

      {/* ── Filter bar ── */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-[280px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search domains or gaps…"
            className={cn(
              'w-full h-8 pl-8 pr-3 text-[12px] text-gray-700 bg-white',
              'border border-gray-200 rounded-lg',
              'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400',
              'placeholder:text-gray-400',
            )}
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500">
              <X size={12} />
            </button>
          )}
        </div>

        <FilterSelect value={filterDomain}   onChange={setFilterDomain}   options={DOMAIN_OPTIONS}   />
        <FilterSelect value={filterSeverity} onChange={setFilterSeverity} options={SEVERITY_OPTIONS} />
        <FilterSelect value={filterEnv}      onChange={setFilterEnv}      options={ENV_OPTIONS}      />
        <FilterSelect value={filterTime}     onChange={setFilterTime}     options={TIME_OPTIONS}     />

        {/* Uncovered toggle */}
        <div className="flex items-center gap-2 ml-auto">
          <Toggle checked={onlyUncovered} onChange={setOnlyUncovered} />
          <span className="text-[12px] font-medium text-gray-500">Only uncovered controls</span>
        </div>
      </div>

      {/* ── Domain grid ── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <p className="text-[13px] font-bold text-gray-800">Posture Domains</p>
            <span className="text-[10px] font-black uppercase tracking-[0.06em] text-gray-400 bg-gray-100 rounded-full px-2 py-0.5">
              {filteredDomains.length} of {DOMAINS.length}
            </span>
          </div>
          <Button size="sm" variant="ghost" className="h-7 gap-1 text-[11px] text-gray-500">
            <Settings size={11} /> Configure Weights
          </Button>
        </div>

        {filteredDomains.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm py-14 flex flex-col items-center gap-2 text-center">
            <Filter size={20} className="text-gray-300" />
            <p className="text-[12.5px] text-gray-400 font-medium">No domains match your filters</p>
            <p className="text-[11px] text-gray-300">Try adjusting the search or filter criteria</p>
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-4">
            {filteredDomains.map(domain => (
              <DomainCard
                key={domain.id}
                domain={domain}
                isSelected={selectedDomain === domain.id}
                onSelect={id => setSelectedDomain(prev => prev === id ? null : id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Trend panels ── */}
      <div className="flex gap-4 items-stretch">
        <ScoreOverviewPanel />
        <SubScoresPanel />
      </div>

      {/* ── Top posture gaps ── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <p className="text-[13px] font-bold text-gray-800">Top Posture Gaps</p>
            <span className="text-[10px] font-black uppercase tracking-[0.06em] text-gray-400 bg-gray-100 rounded-full px-2 py-0.5">
              {filteredGaps.length} gaps
            </span>
            {criticalGaps > 0 && (
              <span className="inline-flex items-center gap-1 text-[10px] font-black px-2 py-0.5 rounded-full border text-red-700 bg-red-50 border-red-200">
                <ShieldAlert size={9} /> {criticalGaps} critical
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <FilterSelect
              value={filterSeverity}
              onChange={setFilterSeverity}
              options={SEVERITY_OPTIONS}
            />
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
              <ExternalLink size={11} /> View All
            </Button>
          </div>
        </div>

        {filteredGaps.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl shadow-sm py-12 flex flex-col items-center gap-2">
            <CheckCircle2 size={20} className="text-emerald-400" />
            <p className="text-[12.5px] text-gray-500 font-medium">No posture gaps match the current filters</p>
          </div>
        ) : (
          <div className="space-y-2">
            {filteredGaps.map((gap, idx) => (
              <PostureGapRow key={gap.id} gap={gap} index={idx} />
            ))}
          </div>
        )}
      </div>

      {/* ── Coverage & enforcement ── */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <p className="text-[13px] font-bold text-gray-800">Coverage &amp; Enforcement</p>
          <div className="flex-1 h-px bg-gray-150" />
        </div>
        <div className="flex gap-4 items-start">
          <CoverageCard />
          <EnforcementCard />
        </div>
      </div>

      {/* ── Recent posture changes ── */}
      <DriftEventsTable events={DRIFT_EVENTS} />
    </PageContainer>
  )
}
