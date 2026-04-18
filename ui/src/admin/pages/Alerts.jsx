import { useState, useCallback, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ActionPanel }         from '../../findings/actions/ActionPanel.jsx'
import { getActionsForFinding } from '../../findings/actions/actionRegistry.js'
import { useFilterParams }  from '../../hooks/useFilterParams.js'
import { useFindings, useFinding } from '../../hooks/useFindings.js'
import {
  Search, SlidersHorizontal, Plus, Download,
  ChevronRight, X, AlertTriangle,
  Bot, Cpu, Wrench, Database, Activity,
  Shield, ShieldAlert, ShieldCheck, ShieldOff,
  User, Clock, Globe, Tag,
  GitBranch, Play, Bell,
  CheckCheck, UserPlus, ArrowUpRight, Zap,
  FileText, TriangleAlert, Link, Loader2,
  Brain, Layers, Network, TrendingUp,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { Avatar }        from '../../components/ui/Avatar.jsx'

// ── Design tokens ──────────────────────────────────────────────────────────────

const RISK_VARIANT    = { Critical: 'critical', High: 'high', Medium: 'medium', Low: 'low' }
const RISK_DOT        = { Critical: 'bg-red-500', High: 'bg-orange-500', Medium: 'bg-yellow-400', Low: 'bg-emerald-500' }
const RISK_ROW_BORDER = { Critical: 'border-l-red-500', High: 'border-l-orange-500', Medium: 'border-l-yellow-400', Low: 'border-l-emerald-400' }
const RISK_HEADER_BG  = {
  Critical: 'bg-red-50/60 border-b-red-100',
  High:     'bg-orange-50/60 border-b-orange-100',
  Medium:   'bg-yellow-50/60 border-b-yellow-100',
  Low:      'bg-emerald-50/60 border-b-emerald-100',
}
const RISK_STRIP = { Critical: 'bg-red-500', High: 'bg-orange-500', Medium: 'bg-yellow-400', Low: 'bg-emerald-500' }

const STATUS_VARIANT = { Open: 'critical', Investigating: 'info', Resolved: 'success' }
const STATUS_DOT     = { Open: 'bg-red-400', Investigating: 'bg-blue-400', Resolved: 'bg-emerald-400' }

const TYPE_ICON  = { Agent: Bot, Model: Cpu, Tool: Wrench, Data: Database }
const TYPE_COLOR = { Agent: 'text-violet-500', Model: 'text-blue-500', Tool: 'text-amber-500', Data: 'text-cyan-500' }

// Risk score → colour band (for the mini bar and inline badge)
function riskColor(score) {
  if (score == null)  return 'text-gray-300'
  if (score >= 0.80)  return 'text-red-500'
  if (score >= 0.60)  return 'text-orange-500'
  if (score >= 0.40)  return 'text-yellow-500'
  return 'text-emerald-500'
}

function confidenceColor(conf) {
  if (conf == null)  return 'text-gray-300'
  if (conf >= 0.85)  return 'text-blue-600'
  if (conf >= 0.60)  return 'text-blue-400'
  return 'text-gray-400'
}

// ── Network-finding helpers ────────────────────────────────────────────────────

/**
 * Returns true when a finding is related to unexpected network exposure
 * (proc-network collector or title heuristics).
 */
function isNetworkFinding(finding) {
  const title  = (finding.title  ?? '').toLowerCase()
  const source = (finding.source ?? '').toLowerCase()
  return source === 'unexpected_listen_ports' ||
    title.includes('listen port') ||
    title.includes('network exposure') ||
    title.includes('unexpected port')
}

/**
 * Parses evidence items for port/severity data.
 * Returns [{port, severity, raw}] for any item that contains a port number.
 */
function parseNetworkEvidence(evidence) {
  return (evidence ?? []).flatMap(item => {
    const str = typeof item === 'string' ? item : JSON.stringify(item)
    // Match "port <anything non-digit> <digits>" or a bare ":digits" (e.g. ":9090")
    const portMatch = /port[^0-9]*(\d+)/i.exec(str) ?? /:\s*(\d{2,5})\b/.exec(str)
    const sevMatch  = /severity[:\s]+(\w+)/i.exec(str)
    if (!portMatch) return []
    return [{ port: parseInt(portMatch[1], 10), severity: sevMatch?.[1] ?? 'unknown', raw: str }]
  })
}

// ── Filter options ─────────────────────────────────────────────────────────────

const SEVERITIES  = ['All Severity', 'Critical', 'High', 'Medium', 'Low']
const STATUSES    = ['All Status',   'Open', 'Investigating', 'Resolved']
const TIME_RANGES = ['Last 1h', 'Last 24h', 'Last 7d', 'Last 30d']

// ── Summary strip ──────────────────────────────────────────────────────────────

function FindingsSummaryStrip({ findings, total, loading }) {
  const critical = findings.filter(f => f.severity === 'Critical').length
  const active   = findings.filter(f => f.status   === 'Investigating').length
  const resolved = findings.filter(f => f.status   === 'Resolved').length

  const items = [
    { label: 'Total Findings',   value: loading ? '…' : total,    icon: Bell,        iconColor: 'text-blue-600',    iconBg: 'bg-blue-50',    accent: 'border-blue-200'    },
    { label: 'Critical',         value: loading ? '…' : critical, icon: TriangleAlert,iconColor: 'text-red-500',    iconBg: 'bg-red-50',     accent: 'border-red-300'     },
    { label: 'Investigating',    value: loading ? '…' : active,   icon: Activity,    iconColor: 'text-orange-500',  iconBg: 'bg-orange-50',  accent: 'border-orange-200'  },
    { label: 'Resolved (24h)',   value: loading ? '…' : resolved, icon: ShieldCheck, iconColor: 'text-emerald-600', iconBg: 'bg-emerald-50', accent: 'border-emerald-200' },
  ]

  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map(({ label, value, icon: Icon, iconColor, iconBg, accent }) => (
        <div
          key={label}
          className={cn(
            'bg-white border-l-[3px] border border-gray-200 rounded-xl pl-4 pr-5 py-3.5',
            'flex items-center gap-3.5 shadow-sm hover:shadow transition-shadow duration-150',
            accent,
          )}
        >
          <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0', iconBg)}>
            <Icon size={15} className={iconColor} />
          </div>
          <div className="min-w-0">
            <p className="text-xl font-semibold text-gray-900 leading-none tabular-nums">{value}</p>
            <p className="text-[11px] text-gray-400 mt-1 whitespace-nowrap">{label}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Filter controls ────────────────────────────────────────────────────────────

function FilterSelect({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className={cn(
        'h-9 px-2.5 pr-7 rounded-lg border border-gray-200 bg-white',
        'text-[12px] text-gray-600 font-medium appearance-none',
        'hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400',
        'transition-colors duration-150 cursor-pointer',
        'bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'10\' height=\'10\' viewBox=\'0 0 24 24\'%3E%3Cpath d=\'M6 9l6 6 6-6\' stroke=\'%239ca3af\' stroke-width=\'2.5\' fill=\'none\' stroke-linecap=\'round\'/%3E%3C/svg%3E")]',
        'bg-no-repeat bg-[right_0.5rem_center]',
      )}
    >
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  )
}

function Toggle({ checked, onChange, label }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2 group select-none"
    >
      <div className={cn('relative w-8 h-4 rounded-full transition-colors duration-200', checked ? 'bg-blue-600' : 'bg-gray-200 group-hover:bg-gray-300')}>
        <span className={cn('absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white shadow-sm transition-transform duration-200', checked && 'translate-x-4')} />
      </div>
      <span className={cn('text-[12px] font-medium whitespace-nowrap', checked ? 'text-blue-600' : 'text-gray-500')}>
        {label}
      </span>
    </button>
  )
}

function FindingsFilterBar({
  search, setSearch,
  severity, setSeverity,
  status, setStatus,
  timeRange, setTimeRange,
  minRisk, setMinRisk,
  highRiskOnly, setHighRiskOnly,
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">

      {/* Search */}
      <div className="relative w-56 shrink-0">
        <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder="Search findings…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className={cn(
            'w-full h-9 pl-[26px] pr-3 rounded-lg border border-gray-200 bg-white',
            'text-[12px] text-gray-700 placeholder:text-gray-400',
            'hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400',
            'transition-colors duration-150',
          )}
        />
      </div>

      <div className="w-px h-5 bg-gray-200 shrink-0" />

      <FilterSelect value={severity}  onChange={setSeverity}  options={SEVERITIES}  />
      <FilterSelect value={status}    onChange={setStatus}    options={STATUSES}    />
      <FilterSelect value={timeRange} onChange={setTimeRange} options={TIME_RANGES} />

      {/* Min risk score */}
      <div className="flex items-center gap-1.5 shrink-0">
        <TrendingUp size={11} className="text-gray-400 shrink-0" />
        <span className="text-[11px] text-gray-400 whitespace-nowrap">Min risk</span>
        <input
          type="number"
          min="0" max="1" step="0.05"
          value={minRisk}
          onChange={e => setMinRisk(e.target.value)}
          placeholder="0.0"
          className={cn(
            'w-16 h-9 px-2 rounded-lg border border-gray-200 bg-white',
            'text-[12px] text-gray-700 tabular-nums text-center',
            'hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400',
          )}
        />
      </div>

      <div className="w-px h-5 bg-gray-200 shrink-0" />

      <Toggle checked={highRiskOnly} onChange={setHighRiskOnly} label="High risk only" />

      <div className="flex-1" />

      <Button variant="ghost" size="sm" className="h-9 px-3 gap-1.5 text-[12px] text-gray-500 shrink-0">
        <SlidersHorizontal size={12} />
        More filters
      </Button>
    </div>
  )
}

// ── Severity + status chips ────────────────────────────────────────────────────

function SeverityChip({ severity }) {
  return (
    <Badge variant={RISK_VARIANT[severity] ?? 'neutral'} className="gap-1.5 pl-2 pr-2.5 py-0.5 whitespace-nowrap font-semibold">
      <span className={cn('w-2 h-2 rounded-full shrink-0 ring-1 ring-white/60', RISK_DOT[severity] ?? 'bg-gray-400')} />
      {severity}
    </Badge>
  )
}

function StatusChip({ status }) {
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'neutral'} className="gap-1.5 pl-2 pr-2.5 py-0.5 whitespace-nowrap">
      <span className={cn(
        'w-2 h-2 rounded-full shrink-0',
        STATUS_DOT[status] ?? 'bg-gray-400',
        status === 'Open' && 'animate-pulse',
      )} />
      {status}
    </Badge>
  )
}

function AssetTypeTag({ type }) {
  const Icon  = TYPE_ICON[type]  ?? Activity
  const color = TYPE_COLOR[type] ?? 'text-gray-400'
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-gray-400 font-medium">
      <Icon size={10} className={color} />
      {type}
    </span>
  )
}

// ── AI metric mini-badges ──────────────────────────────────────────────────────

function ConfidenceBadge({ value }) {
  if (value == null) return <span className="text-[11px] text-gray-300 tabular-nums">—</span>
  const pct   = Math.round(value * 100)
  const color = confidenceColor(value)
  return (
    <span className={cn('text-[11.5px] font-semibold tabular-nums', color)}>
      {pct}%
    </span>
  )
}

function RiskScoreBadge({ value }) {
  if (value == null) return <span className="text-[11px] text-gray-300 tabular-nums">—</span>
  const color = riskColor(value)
  return (
    <span className={cn('text-[11.5px] font-semibold tabular-nums', color)}>
      {value.toFixed(2)}
    </span>
  )
}

// ── Findings table ─────────────────────────────────────────────────────────────

const TABLE_HEADERS = [
  { label: 'Severity',    className: 'w-[106px]'           },
  { label: 'Conf',        className: 'w-14 text-center'    },
  { label: 'Risk',        className: 'w-14 text-center'    },
  { label: 'Finding',     className: ''                     },
  { label: 'Asset',       className: 'w-40'                },
  { label: 'Status',      className: 'w-32'                },
  { label: 'Case',        className: 'w-28'                },
  { label: '',            className: 'w-6'                 },
]

function LoadingRows() {
  return Array.from({ length: 5 }).map((_, i) => (
    <tr key={i} className="border-b border-gray-100/70 last:border-0">
      <td className="pl-4 pr-3 py-[11px]"><div className="h-5 w-20 bg-gray-100 rounded animate-pulse" /></td>
      <td className="px-3 py-[11px] text-center"><div className="h-4 w-8 bg-gray-100 rounded animate-pulse mx-auto" /></td>
      <td className="px-3 py-[11px] text-center"><div className="h-4 w-8 bg-gray-100 rounded animate-pulse mx-auto" /></td>
      <td className="px-3 py-[11px]">
        <div className="h-4 w-48 bg-gray-100 rounded animate-pulse mb-1.5" />
        <div className="h-3 w-24 bg-gray-100 rounded animate-pulse" />
      </td>
      <td className="px-3 py-[11px]"><div className="h-4 w-28 bg-gray-100 rounded animate-pulse" /></td>
      <td className="px-3 py-[11px]"><div className="h-5 w-20 bg-gray-100 rounded animate-pulse" /></td>
      <td className="px-3 py-[11px]"><div className="h-4 w-16 bg-gray-100 rounded animate-pulse" /></td>
      <td className="pr-4 py-[11px]" />
    </tr>
  ))
}

function FindingsTable({ findings, selectedId, onSelect, loading }) {
  if (!loading && findings.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 gap-2">
        <ShieldCheck size={26} className="text-gray-200" />
        <p className="text-[13px] font-semibold text-gray-400">No findings match your filters</p>
        <p className="text-xs text-gray-300">Adjust search or filter criteria</p>
      </div>
    )
  }

  return (
    <table className="w-full border-collapse" data-testid="findings-table">
      <thead>
        <tr className="border-b border-gray-100">
          <th className="w-0.5 bg-[#f6f7fb]" />
          {TABLE_HEADERS.map((h, i) => (
            <th
              key={h.label || i}
              className={cn(
                'px-3 py-2 text-[10px] font-bold uppercase tracking-[0.07em] text-gray-400/80 text-left bg-[#f6f7fb]',
                i === 0 && 'pl-4',
                h.className,
              )}
            >
              {h.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {loading ? <LoadingRows /> : findings.map(finding => {
          const selected   = selectedId === finding.id
          const rowBorder  = RISK_ROW_BORDER[finding.severity] ?? 'border-l-gray-200'
          return (
            <tr
              key={finding.id}
              onClick={() => onSelect(selected ? null : finding)}
              className={cn(
                'group border-b border-gray-100/70 last:border-0 cursor-pointer border-l-[3px]',
                'transition-colors duration-100',
                rowBorder,
                selected ? 'bg-blue-50/40' : 'hover:bg-gray-50/50',
              )}
              data-testid={`finding-row-${finding.id}`}
            >
              {/* Severity */}
              <td className="pl-4 pr-3 py-[11px]">
                <SeverityChip severity={finding.severity} />
              </td>

              {/* Confidence */}
              <td className="px-3 py-[11px] text-center">
                <ConfidenceBadge value={finding.confidence} />
              </td>

              {/* Risk score */}
              <td className="px-3 py-[11px] text-center">
                <RiskScoreBadge value={finding.risk_score} />
              </td>

              {/* Title + source */}
              <td className="px-3 py-[11px]">
                <p className="text-[12.5px] font-semibold text-gray-800 leading-snug whitespace-nowrap">
                  {finding.title}
                </p>
                <p className="text-[11px] text-gray-400 mt-0.5 font-medium">{finding.type}</p>
              </td>

              {/* Asset */}
              <td className="px-3 py-[11px]">
                <p className="text-[12px] font-medium text-gray-700 whitespace-nowrap leading-snug truncate max-w-[144px]">
                  {finding.asset.name}
                </p>
                <AssetTypeTag type={finding.asset.type} />
              </td>

              {/* Status */}
              <td className="px-3 py-[11px]">
                <StatusChip status={finding.status} />
              </td>

              {/* Case */}
              <td className="px-3 py-[11px]">
                {finding.case_id
                  ? <span className="text-[11px] text-blue-600 font-medium whitespace-nowrap truncate max-w-[100px] block">
                      Case #{finding.case_id.slice(-6)}
                    </span>
                  : <span className="text-[11px] text-gray-300">—</span>}
              </td>

              {/* Expand chevron */}
              <td className="pr-4 py-[11px]">
                <ChevronRight size={12} className={cn(
                  'text-gray-300 transition-all duration-150',
                  selected ? 'text-blue-400 translate-x-0.5' : 'group-hover:text-gray-400',
                )} />
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Mini timeline ──────────────────────────────────────────────────────────────

const TIMELINE_STYLE = {
  alert:   { dot: 'bg-red-400',     icon: AlertTriangle, label: 'text-red-600'    },
  policy:  { dot: 'bg-orange-400',  icon: Shield,        label: 'text-orange-600' },
  action:  { dot: 'bg-blue-400',    icon: Zap,           label: 'text-blue-600'   },
  notify:  { dot: 'bg-purple-400',  icon: Bell,          label: 'text-purple-600' },
  assign:  { dot: 'bg-gray-400',    icon: UserPlus,      label: 'text-gray-600'   },
  resolve: { dot: 'bg-emerald-400', icon: CheckCheck,    label: 'text-emerald-600'},
}

function MiniTimeline({ events }) {
  if (!events || events.length === 0) {
    return <p className="text-[12px] text-gray-300 italic">No timeline events recorded.</p>
  }
  return (
    <div>
      {events.map((ev, i) => {
        const style  = TIMELINE_STYLE[ev.type] ?? TIMELINE_STYLE.action
        const isLast = i === events.length - 1
        return (
          <div key={i} className="flex gap-3 min-w-0">
            <div className="flex flex-col items-center shrink-0 w-3">
              <div className={cn('w-2 h-2 rounded-full mt-[5px] ring-2 ring-white shrink-0', style.dot)} />
              {!isLast && <div className="w-px flex-1 bg-gray-200 mt-1 mb-1" />}
            </div>
            <div className={cn('pb-3 min-w-0 flex-1', isLast && 'pb-0')}>
              <p className="text-[11.5px] text-gray-700 leading-snug">{ev.event}</p>
              <p className="text-[10px] text-gray-400 mt-0.5 tabular-nums font-medium">{ev.time}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Detail panel section wrapper ───────────────────────────────────────────────

function PanelSection({ label, icon: Icon, children, className }) {
  return (
    <div className={cn('px-5 py-3.5', className)}>
      <p className="text-[9.5px] font-bold uppercase tracking-[0.1em] text-gray-400/70 mb-2.5 flex items-center gap-2">
        {Icon && <Icon size={9} className="shrink-0" />}
        <span>{label}</span>
        <span className="flex-1 h-px bg-gray-100" />
      </p>
      {children}
    </div>
  )
}

// ── Network Investigation section ─────────────────────────────────────────────

/**
 * Shows parsed port/severity rows for network-exposure findings.
 * Action buttons are intentionally omitted — they live in ActionPanel.
 */
function NetworkInvestigationSection({ finding }) {
  const networkFinding = isNetworkFinding(finding)
  const ports          = parseNetworkEvidence(finding.evidence)

  if (!networkFinding && ports.length === 0) return null

  return (
    <PanelSection label="Network Investigation" icon={Network}>
      {ports.length > 0 ? (
        <div className="space-y-1.5" data-testid="network-ports-list">
          {ports.map(({ port, severity, raw }, i) => {
            const sev    = severity.toLowerCase()
            const rowCls = (sev === 'high' || sev === 'critical')
              ? 'bg-red-50/60 border-red-100'
              : sev === 'medium'
              ? 'bg-orange-50/50 border-orange-100'
              : 'bg-gray-50 border-gray-100'
            const txtCls = (sev === 'high' || sev === 'critical')
              ? 'text-red-700'
              : sev === 'medium' ? 'text-orange-700' : 'text-gray-600'
            return (
              <div key={i} className={cn('flex items-center gap-2 px-2.5 py-1.5 rounded-lg border', rowCls)}>
                <Network size={9} className="text-gray-400 shrink-0" />
                <span className={cn('font-mono text-[11.5px] font-semibold', txtCls)}>:{port}</span>
                <span className={cn('text-[9.5px] uppercase font-bold tracking-wide', txtCls)}>{severity}</span>
                <span className="text-[10px] text-gray-400 truncate flex-1 min-w-0">{raw}</span>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-[12px] text-gray-400" data-testid="network-no-data">
          Network exposure data unavailable.
        </p>
      )}
    </PanelSection>
  )
}

// ── Link Case inline widget ────────────────────────────────────────────────────

function LinkCaseWidget({ findingId, currentCaseId, onLink }) {
  const navigate    = useNavigate()
  const [open,       setOpen]       = useState(false)
  const [caseInput,  setCaseInput]  = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err,        setErr]        = useState(null)

  const handleSubmit = async () => {
    if (!caseInput.trim()) return
    setSubmitting(true)
    setErr(null)
    try {
      await onLink(findingId, caseInput.trim())
      setOpen(false)
      setCaseInput('')
    } catch (e) {
      setErr(e.message || 'Failed to link case')
    } finally {
      setSubmitting(false)
    }
  }

  if (currentCaseId) {
    return (
      <button
        onClick={() => navigate('/admin/cases')}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-50 border border-blue-100
                   hover:bg-blue-100 hover:border-blue-200 transition-colors text-left group"
      >
        <Link size={11} className="text-blue-400 shrink-0" />
        <span className="text-[12px] text-blue-700 font-medium flex-1">Case #{currentCaseId.slice(-6)}</span>
        <ArrowUpRight size={10} className="text-blue-300 group-hover:text-blue-500 transition-colors" />
      </button>
    )
  }

  return (
    <div>
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-[12px] font-medium
                     border border-gray-200 text-gray-600 bg-white hover:bg-gray-50 transition-colors group"
        >
          <Link size={11} className="shrink-0 text-gray-400" />
          <span className="flex-1 text-left">Link to Case</span>
          <ChevronRight size={11} className="text-gray-300 group-hover:text-gray-400" />
        </button>
      ) : (
        <div className="flex gap-2 items-center">
          <input
            autoFocus
            type="text"
            value={caseInput}
            onChange={e => setCaseInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSubmit()}
            placeholder="Case ID…"
            className="flex-1 h-8 px-2.5 rounded-lg border border-blue-300 text-[12px] focus:outline-none focus:ring-2 focus:ring-blue-500/40"
          />
          <Button size="sm" className="h-8 px-3 text-[11px]" onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 size={11} className="animate-spin" /> : 'Link'}
          </Button>
          <button onClick={() => { setOpen(false); setCaseInput('') }} className="text-gray-400 hover:text-gray-600">
            <X size={13} />
          </button>
        </div>
      )}
      {err && <p className="text-[11px] text-red-500 mt-1">{err}</p>}
    </div>
  )
}

// ── Finding detail panel ───────────────────────────────────────────────────────

function FindingDetailPanel({ finding, onClose, onMarkStatus, onLinkCase }) {
  const navigate = useNavigate()
  const [statusPending, setStatusPending] = useState(false)
  const [statusError,   setStatusError]   = useState(null)

  if (!finding) return null

  const headerBg   = RISK_HEADER_BG[finding.severity]  ?? 'bg-gray-50/60 border-b-gray-100'
  const stripColor = RISK_STRIP[finding.severity]       ?? 'bg-gray-300'
  const isResolved = finding.status === 'Resolved'

  // Derive a session ID for Runtime links: prefer correlated_events[0], fall back to finding.id
  const sessionId = finding.correlated_events?.[0] ?? finding.id

  const handleMarkStatus = async (newStatus) => {
    setStatusPending(true)
    setStatusError(null)
    try {
      await onMarkStatus(finding.id, newStatus)
    } catch (e) {
      setStatusError(e.message || 'Status update failed')
    } finally {
      setStatusPending(false)
    }
  }

  return (
    <div className="w-[360px] shrink-0 flex flex-col bg-white" data-testid="finding-detail-panel">

      {/* Severity accent strip */}
      <div className={cn('h-[3px] w-full shrink-0', stripColor)} />

      {/* Header */}
      <div className={cn('px-5 py-4 border-b flex items-start justify-between gap-3', headerBg)}>
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold text-gray-900 leading-snug pr-2">{finding.title}</p>
          <div className="flex items-center gap-2 mt-2">
            <SeverityChip severity={finding.severity} />
            <StatusChip   status={finding.status} />
          </div>
          {/* Confidence + Risk inline in header */}
          {(finding.confidence != null || finding.risk_score != null) && (
            <div className="flex items-center gap-3 mt-2.5">
              {finding.confidence != null && (
                <span className="flex items-center gap-1 text-[11px] text-gray-500">
                  <Brain size={10} className="text-blue-400" />
                  <span>Conf</span>
                  <ConfidenceBadge value={finding.confidence} />
                </span>
              )}
              {finding.risk_score != null && (
                <span className="flex items-center gap-1 text-[11px] text-gray-500">
                  <TrendingUp size={10} className="text-orange-400" />
                  <span>Risk</span>
                  <RiskScoreBadge value={finding.risk_score} />
                </span>
              )}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors shrink-0"
        >
          <X size={14} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100/80">

        {/* ── Overview (existing) ───────────────────────────────────────── */}
        <PanelSection label="Overview">
          <p className="text-[12px] text-gray-600 leading-relaxed mb-3">{finding.description}</p>
          <div className="bg-gray-50/70 rounded-lg border border-gray-100 divide-y divide-gray-100 overflow-hidden text-[12px]">
            {[
              { icon: Tag,   key: 'Asset', val: <span className="flex items-center gap-1.5 font-medium text-gray-800">{finding.asset.name}<AssetTypeTag type={finding.asset.type} /></span> },
              { icon: Clock, key: 'Time',  val: <span className="text-gray-600 tabular-nums">{finding.timestampFull}</span> },
              { icon: Globe, key: 'Env',   val: <span className="text-gray-600">{finding.environment}</span> },
            ].map(({ icon: Icon, key, val }) => (
              <div key={key} className="grid grid-cols-[68px_1fr] items-center px-3 py-2">
                <span className="flex items-center gap-1.5 text-gray-400 text-[11px]">
                  <Icon size={10} className="shrink-0" />{key}
                </span>
                <div>{val}</div>
              </div>
            ))}
          </div>
        </PanelSection>

        {/* ── Hypothesis (NEW — replaces/extends Root Cause) ─────────────── */}
        {finding.hypothesis ? (
          <PanelSection label="Hypothesis" icon={Brain}>
            <p className="text-[12px] text-gray-600 leading-relaxed">{finding.hypothesis}</p>
          </PanelSection>
        ) : finding.rootCause ? (
          <PanelSection label="Root Cause">
            <p className="text-[12px] text-gray-600 leading-relaxed">{finding.rootCause}</p>
          </PanelSection>
        ) : null}

        {/* ── Evidence (NEW) ────────────────────────────────────────────── */}
        {finding.evidence && finding.evidence.length > 0 && (
          <PanelSection label="Evidence" icon={Layers}>
            <div className="space-y-1.5">
              {finding.evidence.map((item, i) => (
                <div key={i} className="bg-gray-950 rounded-lg px-3.5 py-2.5 font-mono text-[11px] text-green-400 leading-relaxed whitespace-pre-wrap break-all">
                  {item}
                </div>
              ))}
            </div>
          </PanelSection>
        )}

        {/* Legacy context snapshot (shown when no structured evidence) */}
        {(!finding.evidence || finding.evidence.length === 0) && finding.contextSnippet && (
          <PanelSection label="Context Snapshot">
            <pre className="text-[11px] bg-gray-950 rounded-lg px-3.5 py-3 font-mono leading-relaxed whitespace-pre-wrap break-all text-green-400">
              {finding.contextSnippet}
            </pre>
          </PanelSection>
        )}

        {/* ── Correlated Findings (NEW) ──────────────────────────────────── */}
        {finding.correlated_findings && finding.correlated_findings.length > 0 && (
          <PanelSection label="Correlated Findings" icon={Network}>
            <div className="flex flex-wrap gap-1.5">
              {finding.correlated_findings.map((cf, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 rounded-md text-[11px] text-gray-600 font-medium">
                  <Layers size={9} className="text-gray-400 shrink-0" />
                  {typeof cf === 'string' ? cf : cf.id || JSON.stringify(cf)}
                </span>
              ))}
            </div>
          </PanelSection>
        )}

        {/* ── Network Investigation (shown for network-exposure findings) ── */}
        <NetworkInvestigationSection finding={finding} />

        {/* ── Policy Signals (NEW) ─────────────────────────────────────── */}
        {finding.policy_signals && finding.policy_signals.length > 0 && (
          <PanelSection label="Policy Signals" icon={Shield}>
            <div className="space-y-1">
              {finding.policy_signals.map((sig, i) => {
                const type   = sig?.type   || sig?.signal_type || 'signal'
                const policy = sig?.policy || sig?.policy_id   || (typeof sig === 'string' ? sig : JSON.stringify(sig))
                return (
                  <div key={i} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-orange-50/60 border border-orange-100">
                    <Shield size={9} className="text-orange-400 shrink-0" />
                    <span className="text-[11px] text-orange-700 font-medium">{type}</span>
                    <span className="text-[11px] text-orange-400">—</span>
                    <span className="text-[11px] text-orange-600 truncate">{policy}</span>
                  </div>
                )
              })}
            </div>
          </PanelSection>
        )}

        {/* ── Triggered Policies (existing) ─────────────────────────────── */}
        <PanelSection label="Triggered Policies">
          {finding.triggeredPolicies && finding.triggeredPolicies.length > 0
            ? <div className="flex flex-wrap gap-1.5">
                {finding.triggeredPolicies.map(p => (
                  <Badge key={p} variant="info" className="gap-1 text-[10px]">
                    <Shield size={9} />
                    {p}
                  </Badge>
                ))}
              </div>
            : <p className="text-[12px] text-orange-500 font-medium">No policies triggered</p>}
        </PanelSection>

        {/* ── Recommended Actions (NEW from API or legacy) ──────────────── */}
        {finding.recommended_actions && finding.recommended_actions.length > 0 && (
          <PanelSection label="Recommended Actions">
            <div className="space-y-1.5">
              {finding.recommended_actions.map((action, i) => {
                const label = typeof action === 'string' ? action : (action.label || action.action || JSON.stringify(action))
                return (
                  <button
                    key={i}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-[12px] font-medium text-left border border-gray-200 text-gray-600 bg-white hover:bg-gray-50 transition-colors group"
                  >
                    <ShieldAlert size={11} className="shrink-0 text-gray-400" />
                    <span className="flex-1">{label}</span>
                    <ChevronRight size={11} className="text-gray-300 group-hover:text-gray-400 transition-colors" />
                  </button>
                )
              })}
            </div>
          </PanelSection>
        )}

        {/* Legacy recommended actions (icon-rich, from mock era) */}
        {(!finding.recommended_actions || finding.recommended_actions.length === 0) &&
          finding.recommendedActions && finding.recommendedActions.length > 0 && (
          <PanelSection label="Recommended Actions">
            <div className="space-y-1.5">
              {finding.recommendedActions.map(({ label, icon: Icon, variant }, i) => (
                <button
                  key={label}
                  className={cn(
                    'w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-[12px] font-medium text-left',
                    'border transition-colors duration-150 group',
                    variant === 'destructive'
                      ? 'border-red-200 text-red-600 bg-red-50/70 hover:bg-red-50'
                      : 'border-gray-200 text-gray-600 bg-white hover:bg-gray-50',
                  )}
                >
                  <Icon size={12} className="shrink-0" />
                  <span className="flex-1">{label}</span>
                  <ChevronRight size={11} className="text-gray-300 group-hover:text-gray-400 transition-colors" />
                </button>
              ))}
            </div>
          </PanelSection>
        )}

        {/* ── Event Timeline (existing) ──────────────────────────────────── */}
        <PanelSection label="Event Timeline">
          <MiniTimeline events={finding.timeline} />
        </PanelSection>

        {/* ── Quick Links ───────────────────────────────────────────────────── */}
        <PanelSection label="Quick Links">
          <div className="space-y-0.5">
            {[
              {
                label:  'View in Inventory',
                icon:   Database,
                testId: 'quick-link-inventory',
                // Only filter by asset when we have a real name — otherwise just open Inventory
                href: finding.hasRealAsset
                  ? `/admin/inventory?asset=${encodeURIComponent(finding.asset.name)}`
                  : '/admin/inventory',
                disabled: !finding.asset?.name,
              },
              {
                label:  'Open Lineage Graph',
                icon:   GitBranch,
                testId: 'quick-link-lineage',
                // Pass asset context only when real; always pass finding_id for the banner
                href: finding.hasRealAsset
                  ? `/admin/lineage?asset=${encodeURIComponent(finding.asset.name)}&finding_id=${finding.id}`
                  : `/admin/lineage?finding_id=${finding.id}`,
                disabled: !finding.asset?.name,
              },
              {
                label:  'View Runtime Session',
                icon:   Play,
                testId: 'quick-link-runtime',
                // Use a real correlated session if available; otherwise just open Runtime
                href: finding.correlated_events?.length
                  ? `/admin/runtime?session_id=${encodeURIComponent(finding.correlated_events[0])}`
                  : '/admin/runtime',
                disabled: false,
              },
            ].map(({ label, icon: Icon, testId, href, disabled }) => (
              <button
                key={label}
                data-testid={testId}
                disabled={disabled}
                onClick={() => !disabled && navigate(href)}
                className={cn(
                  'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-colors',
                  disabled
                    ? 'text-gray-300 cursor-not-allowed'
                    : 'text-blue-600 hover:bg-blue-50/60',
                )}
              >
                <Icon size={11} className={cn('shrink-0', disabled ? 'text-gray-200' : 'text-blue-400')} />
                {label}
                <ArrowUpRight size={11} className={cn('ml-auto', disabled ? 'text-gray-200' : 'text-blue-300')} />
              </button>
            ))}
          </div>
        </PanelSection>

        {/* ── Investigation Actions (registry-driven, type-aware) ──────────── */}
        {getActionsForFinding(finding).length > 0 && (
          <PanelSection label="Investigation Actions" icon={Zap}>
            <ActionPanel finding={finding} />
          </PanelSection>
        )}

        {/* ── Case + Resolve — live at the bottom of the scroll body so there's no gap ── */}
        <div className="px-4 pt-2 pb-4 space-y-1.5 border-t border-gray-100">
          <LinkCaseWidget
            findingId={finding.id}
            currentCaseId={finding.case_id}
            onLink={onLinkCase}
          />
          {statusError && (
            <p className="text-[11px] text-red-500 text-center">{statusError}</p>
          )}
          {!isResolved && finding.status !== 'Investigating' && (
            <Button
              variant="outline"
              size="md"
              disabled={statusPending}
              onClick={() => handleMarkStatus('investigating')}
              className="w-full h-9 text-[12px] gap-2 justify-center"
            >
              {statusPending
                ? <Loader2 size={13} className="animate-spin" />
                : <Shield size={13} />}
              Investigate
            </Button>
          )}
          <Button
            size="md"
            disabled={isResolved || statusPending}
            onClick={() => !isResolved && handleMarkStatus('resolved')}
            className={cn(
              'w-full h-9 text-[12px] gap-2 justify-center',
              isResolved && 'bg-emerald-50 text-emerald-600 border border-emerald-200 pointer-events-none',
            )}
          >
            {statusPending
              ? <Loader2 size={13} className="animate-spin" />
              : <CheckCheck size={13} />}
            {isResolved ? 'Already Resolved' : 'Mark as Resolved'}
          </Button>
        </div>

      </div>
    </div>
  )
}

// ── Error banner ───────────────────────────────────────────────────────────────

function ErrorBanner({ message, onRetry }) {
  return (
    <div className="flex items-center gap-3 px-5 py-3 bg-red-50 border border-red-100 rounded-lg text-[12px]">
      <TriangleAlert size={14} className="text-red-400 shrink-0" />
      <p className="text-red-600 flex-1">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="text-red-500 font-semibold hover:text-red-700 whitespace-nowrap">
          Retry
        </button>
      )}
    </div>
  )
}

// ── Findings page ──────────────────────────────────────────────────────────────

export default function Alerts() {
  const { alertId }  = useParams()
  const navigate     = useNavigate()

  // ── Filter state (URL-synced) ──────────────────────────────────────────────
  const { values, setters } = useFilterParams({
    search:       '',
    severity:     'All Severity',
    status:       'All Status',
    timeRange:    'Last 24h',
    minRisk:      '',
    highRiskOnly: false,
  })
  const { search, severity, status, timeRange, minRisk, highRiskOnly } = values
  const { setSearch, setSeverity, setStatus, setTimeRange, setMinRisk, setHighRiskOnly } = setters

  // ── API filters (passed to hook) ───────────────────────────────────────────
  // Memoised so the object reference only changes when a filter value changes.
  // Without useMemo, timeRangeToFromTime() would call Date.now() on every render,
  // producing a new ISO string each time → new filterKey → infinite refetch loop.
  const apiFilters = useMemo(() => {
    function timeRangeToFromTime(range) {
      const hours = { 'Last 1h': 1, 'Last 24h': 24, 'Last 7d': 168, 'Last 30d': 720 }[range]
      if (!hours) return undefined
      return new Date(Date.now() - hours * 3_600_000).toISOString()
    }
    return {
      severity:      highRiskOnly ? 'high' : severity,
      status,
      min_risk_score: minRisk ? parseFloat(minRisk) : undefined,
      from_time:     timeRangeToFromTime(timeRange),
      sort_by:       'created_at',
      limit:         50,
      offset:        0,
    }
  }, [highRiskOnly, severity, status, minRisk, timeRange])

  const { findings, total, loading, error, refetch, markStatus, attachCase } = useFindings(apiFilters)

  // ── Client-side secondary filter (search, highRiskOnly) ───────────────────
  const filtered = findings.filter(f => {
    if (search) {
      const q = search.toLowerCase()
      if (!f.title.toLowerCase().includes(q) &&
          !f.asset.name.toLowerCase().includes(q) &&
          !f.type.toLowerCase().includes(q)) return false
    }
    if (highRiskOnly && f.severity !== 'Critical' && f.severity !== 'High') return false
    return true
  })

  // ── Selection (URL-driven) ─────────────────────────────────────────────────
  // Try the current page first; fall back to a single-item fetch if deep-linked
  const selected = filtered.find(f => f.id === alertId) ?? null
  const { finding: deepLinked } = useFinding(
    !loading && !selected && alertId ? alertId : null
  )
  const activeDetail = selected ?? deepLinked

  const handleSelect = (finding) => {
    if (finding?.id === alertId) {
      navigate('/admin/alerts', { replace: true })
    } else {
      navigate(`/admin/alerts/${finding.id}`, { replace: true })
    }
  }

  const openCount = filtered.filter(f => f.status === 'Open').length

  return (
    <PageContainer>

      <PageHeader
        title="Findings"
        subtitle="AI-powered threat findings from the hunt engine — investigate and respond"
        actions={
          <>
            <Button variant="outline" size="sm">
              <Download size={13} className="mr-1.5" />
              Export
            </Button>
            <Button size="sm">
              <Plus size={13} className="mr-1.5" />
              Create Rule
            </Button>
          </>
        }
      />

      {/* Summary strip */}
      <FindingsSummaryStrip findings={findings} total={total} loading={loading} />

      {/* Error banner */}
      {error && <ErrorBanner message={error} onRetry={refetch} />}

      {/* Main panel */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">

        {/* Filter bar */}
        <div className="px-5 py-2.5 border-b border-gray-100 bg-gray-50/30">
          <FindingsFilterBar
            search={search}           setSearch={setSearch}
            severity={severity}       setSeverity={setSeverity}
            status={status}           setStatus={setStatus}
            timeRange={timeRange}     setTimeRange={setTimeRange}
            minRisk={minRisk}         setMinRisk={setMinRisk}
            highRiskOnly={highRiskOnly} setHighRiskOnly={setHighRiskOnly}
          />
        </div>

        {/* Table + detail panel */}
        <div className="flex items-stretch divide-x divide-gray-100">

          <div className="flex-1 min-w-0 overflow-x-auto">
            <FindingsTable
              findings={filtered}
              selectedId={activeDetail?.id}
              onSelect={handleSelect}
              loading={loading}
            />
          </div>

          {activeDetail && (
            <FindingDetailPanel
              finding={activeDetail}
              onClose={() => navigate('/admin/alerts', { replace: true })}
              onMarkStatus={markStatus}
              onLinkCase={attachCase}
            />
          )}

        </div>

        {/* Footer */}
        <div className="px-5 py-2.5 border-t border-gray-100 flex items-center justify-between bg-gray-50/40">
          <span className="text-[11px] text-gray-400">
            {loading ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={10} className="animate-spin text-gray-400" />
                Loading findings…
              </span>
            ) : (
              <>
                {filtered.length} of {total} finding{total !== 1 ? 's' : ''}
                {openCount > 0 && (
                  <span className="ml-2 text-red-500 font-semibold">· {openCount} open</span>
                )}
              </>
            )}
          </span>
          <button
            onClick={refetch}
            className="text-[11px] font-semibold text-blue-600 hover:text-blue-700 transition-colors"
          >
            Refresh ↺
          </button>
        </div>

      </div>

    </PageContainer>
  )
}
