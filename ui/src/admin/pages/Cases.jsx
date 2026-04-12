import { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Search, Download, Plus, BookMarked,
  ChevronDown, X, Clock, User, Shield,
  ShieldAlert, FileWarning, MessageSquare,
  Briefcase, ClipboardList, Link2,
  ArrowUpRight, CheckCircle2, AlertTriangle,
  XCircle, Tag, Filter, Bot, Cpu, Wrench,
  Database, Activity, GitBranch, FlaskConical,
  Network, MoreHorizontal, Send, Paperclip,
  ChevronRight, Eye, Zap, RotateCcw,
  TriangleAlert, CircleDot, Layers, Lock,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'

// ── Design tokens ──────────────────────────────────────────────────────────────

const SEV_VARIANT  = { Critical: 'critical', High: 'high', Medium: 'medium', Low: 'low' }
const SEV_DOT      = { Critical: 'bg-red-500', High: 'bg-orange-500', Medium: 'bg-yellow-400', Low: 'bg-emerald-500' }
const SEV_ROW_BDR  = { Critical: 'border-l-red-500', High: 'border-l-orange-500', Medium: 'border-l-yellow-400', Low: 'border-l-emerald-400' }
const SEV_HDR_BG   = {
  Critical: 'bg-red-50/60 border-b-red-100',
  High:     'bg-orange-50/60 border-b-orange-100',
  Medium:   'bg-yellow-50/60 border-b-yellow-100',
  Low:      'bg-emerald-50/60 border-b-emerald-100',
}
const SEV_STRIP    = { Critical: 'bg-red-500', High: 'bg-orange-500', Medium: 'bg-yellow-400', Low: 'bg-emerald-500' }

const STATUS_VARIANT = {
  Open:             'critical',
  Investigating:    'info',
  Escalated:        'high',
  'Awaiting Review':'medium',
  Resolved:         'success',
}
const STATUS_DOT = {
  Open:             'bg-red-400',
  Investigating:    'bg-blue-400',
  Escalated:        'bg-orange-400',
  'Awaiting Review':'bg-yellow-400',
  Resolved:         'bg-emerald-400',
}

const PRIORITY_VARIANT = { P1: 'critical', P2: 'high', P3: 'medium', P4: 'low' }

const TL_TYPE_CFG = {
  created:    { dot: 'bg-blue-400',    icon: Plus,          label: 'Created'    },
  assigned:   { dot: 'bg-violet-400',  icon: User,          label: 'Assigned'   },
  alert:      { dot: 'bg-red-500',     icon: TriangleAlert, label: 'Alert'      },
  policy:     { dot: 'bg-orange-400',  icon: Shield,        label: 'Policy'     },
  escalated:  { dot: 'bg-orange-500',  icon: ShieldAlert,   label: 'Escalated'  },
  comment:    { dot: 'bg-gray-400',    icon: MessageSquare, label: 'Note'       },
  status:     { dot: 'bg-blue-400',    icon: CircleDot,     label: 'Status'     },
  resolved:   { dot: 'bg-emerald-500', icon: CheckCircle2,  label: 'Resolved'   },
  evidence:   { dot: 'bg-purple-400',  icon: FileWarning,   label: 'Evidence'   },
}

// ── Adapter: backend CaseResponse → display shape ─────────────────────────────

function adaptApiCase(c) {
  const score  = typeof c.risk_score === 'number' ? c.risk_score : 0.5
  const sev    = score >= 0.85 ? 'Critical' : score >= 0.65 ? 'High' : score >= 0.4 ? 'Medium' : 'Low'
  const statusMap = { open: 'Open', investigating: 'Investigating', escalated: 'Escalated', resolved: 'Resolved' }
  const status    = statusMap[(c.status ?? '').toLowerCase()] ?? 'Open'
  const pct       = (score * 100).toFixed(0)
  const _fmt = (iso) => {
    try {
      // Server returns naive UTC datetimes without 'Z'; append it so JS parses as UTC
      const normalized = (typeof iso === 'string' && !iso.endsWith('Z') && !iso.includes('+')) ? iso + 'Z' : iso
      const d = new Date(normalized)
      return d.toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jerusalem', hour12: false,
      })
    } catch (_) { return 'Unknown' }
  }
  const createdAt = c.created_at ? _fmt(c.created_at) : 'Just now'
  const updatedAt = c.updated_at ? _fmt(c.updated_at) : createdAt

  const rawSummary = c.summary || ''
  const title = rawSummary.startsWith('Threat finding raised by the Threat-hunter agent')
    ? 'Threat finding raised by the Threat-hunter agent'
    : rawSummary || `Escalated session ${c.session_id}`

  return {
    id: c.case_id,
    title,
    severity: sev,
    status,
    priority: score >= 0.85 ? 'P1' : score >= 0.55 ? 'P2' : 'P3',
    owner: null,
    ownerDisplay: null,
    environment: 'Production',
    createdAt,
    updatedAt,
    linkedAlerts: 0,
    linkedSessions: 1,
    tags: [c.reason ?? 'escalation'].filter(Boolean),
    description: c.summary || `Session ${c.session_id} was escalated for review. Risk score: ${pct}%. Policy decision: ${c.decision ?? 'N/A'}.`,
    affectedAssets: [{ name: c.session_id, type: 'Session' }],
    linkedAlertList: [],
    evidence: [
      { type: 'session', label: 'Session ID',  value: c.session_id,                ts: createdAt },
      { type: 'policy',  label: 'Risk Score',  value: `${pct}% (${sev})`,          ts: createdAt },
      { type: 'policy',  label: 'Decision',    value: c.decision ?? 'N/A',         ts: createdAt },
      { type: 'prompt',  label: 'Reason',      value: c.reason ?? 'manual_escalation', ts: createdAt },
    ],
    timeline: [
      { type: 'created', ts: createdAt, text: `Case escalated — ${c.reason ?? 'manual escalation'}` },
      { type: 'status',  ts: createdAt, text: `Risk ${sev} (${pct}%) · Decision: ${c.decision ?? 'N/A'}` },
    ],
    notes: [],
    linkedEntities: { agents: [c.session_id], models: [], tools: [], data: [] },
    recommendedActions: [
      { icon: Eye,    label: 'Inspect Session',  desc: 'View session events in Runtime monitor', route: 'runtime'  },
      { icon: Shield, label: 'Review Policy',    desc: 'Check triggered policy and thresholds',   route: 'policies' },
    ],
  }
}

// ── Filter config ──────────────────────────────────────────────────────────────

const STATUSES    = ['All Status', 'Open', 'Investigating', 'Escalated', 'Awaiting Review', 'Resolved']
const SEVERITIES  = ['All Severity', 'Critical', 'High', 'Medium', 'Low']
const PRIORITIES  = ['All Priority', 'P1', 'P2', 'P3', 'P4']
const OWNERS      = ['All Owners', 'sarah.chen', 'mike.torres', 'alex.kim', 'lisa.wong']
const OWNER_LABEL = { 'sarah.chen': 'Sarah Chen', 'mike.torres': 'Mike Torres', 'alex.kim': 'Alex Kim', 'lisa.wong': 'Lisa Wong' }
const TIME_RANGES = ['Last 24h', 'Last 7d', 'Last 30d', 'All Time']

// ── Small shared primitives ────────────────────────────────────────────────────

function FilterSelect({ value, onChange, options }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className={cn(
          'h-8 pl-3 pr-8 rounded-lg border border-gray-200 bg-white',
          'text-[12px] text-gray-700 font-medium appearance-none cursor-pointer',
          'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1',
          'hover:border-gray-300 transition-colors',
        )}
      >
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
      <ChevronDown size={11} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
    </div>
  )
}

function Toggle({ checked, onChange, label }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative w-8 h-[18px] rounded-full transition-colors duration-200 shrink-0',
          checked ? 'bg-blue-600' : 'bg-gray-200',
        )}
      >
        <span className={cn(
          'absolute top-0.5 left-0.5 w-3.5 h-3.5 rounded-full bg-white shadow-sm transition-transform duration-200',
          checked ? 'translate-x-[14px]' : 'translate-x-0',
        )} />
      </button>
      <span className="text-[12px] font-medium text-gray-600 whitespace-nowrap">{label}</span>
    </label>
  )
}

function OwnerAvatar({ name, size = 'sm' }) {
  if (!name) return (
    <div className={cn(
      'rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-400',
      size === 'sm' ? 'w-6 h-6' : 'w-7 h-7',
    )}>
      <User size={size === 'sm' ? 11 : 13} strokeWidth={1.75} />
    </div>
  )
  const initials = name.split('.').map(p => p[0].toUpperCase()).join('')
  const colors   = ['bg-blue-100 text-blue-700', 'bg-violet-100 text-violet-700', 'bg-emerald-100 text-emerald-700', 'bg-amber-100 text-amber-700']
  const color    = colors[name.charCodeAt(0) % colors.length]
  return (
    <div className={cn('rounded-full flex items-center justify-center font-bold border border-white ring-1 ring-gray-200', color,
      size === 'sm' ? 'w-6 h-6 text-[8px]' : 'w-7 h-7 text-[9px]',
    )}>
      {initials}
    </div>
  )
}

function PriorityPip({ priority }) {
  const cfg = {
    P1: 'bg-red-500     text-white',
    P2: 'bg-orange-400  text-white',
    P3: 'bg-yellow-400  text-gray-800',
    P4: 'bg-gray-300    text-gray-600',
  }
  return (
    <span className={cn('inline-flex items-center justify-center w-6 h-6 rounded-md text-[9px] font-black shrink-0', cfg[priority] ?? cfg.P4)}>
      {priority}
    </span>
  )
}

function EntityChip({ label, type }) {
  const cfg = {
    Agent: { bg: 'bg-violet-50 border-violet-200 text-violet-700', icon: Bot    },
    Model: { bg: 'bg-blue-50   border-blue-200   text-blue-700',   icon: Cpu    },
    Tool:  { bg: 'bg-amber-50  border-amber-200  text-amber-700',  icon: Wrench },
    Data:  { bg: 'bg-cyan-50   border-cyan-200   text-cyan-700',   icon: Database },
  }
  const { bg, icon: Icon } = cfg[type] ?? { bg: 'bg-gray-50 border-gray-200 text-gray-600', icon: Layers }
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] font-semibold', bg)}>
      <Icon size={9} strokeWidth={2} />
      {label}
    </span>
  )
}

// ── Summary strip ──────────────────────────────────────────────────────────────

function CasesSummaryStrip({ cases }) {
  const open        = cases.filter(c => c.status === 'Open').length
  const investing   = cases.filter(c => c.status === 'Investigating').length
  const escalated   = cases.filter(c => c.status === 'Escalated').length
  const resolved    = cases.filter(c => c.status === 'Resolved').length

  const items = [
    { label: 'Open Cases',      value: open,      icon: Briefcase,    iconColor: 'text-red-500',     iconBg: 'bg-red-50',     accent: 'border-l-red-400'     },
    { label: 'Investigating',   value: investing, icon: ClipboardList, iconColor: 'text-blue-500',   iconBg: 'bg-blue-50',    accent: 'border-l-blue-400'    },
    { label: 'Escalated',       value: escalated, icon: ShieldAlert,  iconColor: 'text-orange-500',  iconBg: 'bg-orange-50',  accent: 'border-l-orange-400'  },
    { label: 'Resolved (7d)',   value: resolved,  icon: CheckCircle2, iconColor: 'text-emerald-600', iconBg: 'bg-emerald-50', accent: 'border-l-emerald-400' },
  ]

  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map(({ label, value, icon: Icon, iconColor, iconBg, accent }) => (
        <div key={label} className={cn(
          'bg-white rounded-xl border border-gray-200 border-l-[3px] px-4 py-3 flex items-center gap-3 shadow-sm',
          accent,
        )}>
          <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0', iconBg)}>
            <Icon size={15} className={iconColor} strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <p className="text-[22px] font-bold tabular-nums text-gray-900 leading-none">{value}</p>
            <p className="text-[11px] text-gray-500 mt-0.5 leading-none">{label}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Cases table ────────────────────────────────────────────────────────────────

function CasesTable({ cases, selectedId, onSelect, rowRefs }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse min-w-[720px]">
        <thead>
          <tr className="bg-gray-50/70 border-b border-gray-100">
            {['Case ID', 'Title', 'Pri', 'Severity', 'Status', 'Owner', 'Alerts', 'Created'].map(h => (
              <th key={h} className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-[0.08em] px-4 py-2 whitespace-nowrap first:pl-5">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cases.map((c, idx) => {
            const selected = c.id === selectedId
            return (
              <tr
                key={c.id}
                ref={el => { if (rowRefs) rowRefs.current[c.id] = el }}
                onClick={() => onSelect(c.id)}
                className={cn(
                  'group border-l-[3px] cursor-pointer transition-colors duration-100',
                  idx !== cases.length - 1 && 'border-b border-gray-50',
                  SEV_ROW_BDR[c.severity],
                  selected
                    ? 'bg-blue-50/70 hover:bg-blue-50/80'
                    : 'hover:bg-gray-50',
                )}
              >
                {/* Case ID */}
                <td className="pl-5 pr-3 py-3.5 whitespace-nowrap">
                  <span className={cn(
                    'text-[11px] font-mono font-bold',
                    selected ? 'text-blue-700' : 'text-blue-600',
                  )}>
                    {c.id}
                  </span>
                </td>
                {/* Title */}
                <td className="px-3 py-3.5 max-w-[240px]">
                  <p className="text-[12.5px] font-semibold text-gray-800 truncate leading-snug">{c.title}</p>
                  {c.tags.length > 0 && (
                    <div className="flex items-center gap-1 mt-1.5">
                      {c.tags.slice(0, 2).map(t => (
                        <span key={t} className="text-[9px] font-semibold bg-gray-100 text-gray-500 px-1.5 py-px rounded border border-gray-200">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                {/* Priority */}
                <td className="px-3 py-3.5">
                  <PriorityPip priority={c.priority} />
                </td>
                {/* Severity */}
                <td className="px-3 py-3.5 whitespace-nowrap">
                  <Badge variant={SEV_VARIANT[c.severity]}>{c.severity}</Badge>
                </td>
                {/* Status */}
                <td className="px-3 py-3.5 whitespace-nowrap">
                  <div className="flex items-center gap-1.5">
                    <span className={cn('w-1.5 h-1.5 rounded-full shrink-0 ring-2 ring-white', STATUS_DOT[c.status] ?? 'bg-gray-400')} />
                    <span className={cn(
                      'text-[11px] font-semibold',
                      c.status === 'Open'          ? 'text-red-600'
                      : c.status === 'Escalated'   ? 'text-orange-600'
                      : c.status === 'Investigating'? 'text-blue-600'
                      : c.status === 'Awaiting Review' ? 'text-yellow-700'
                      : 'text-emerald-700',
                    )}>
                      {c.status}
                    </span>
                  </div>
                </td>
                {/* Owner */}
                <td className="px-3 py-3.5 whitespace-nowrap">
                  <div className="flex items-center gap-1.5">
                    <OwnerAvatar name={c.owner} />
                    {c.ownerDisplay
                      ? <span className="text-[11.5px] text-gray-700 font-medium">{c.ownerDisplay}</span>
                      : <span className="text-[11px] text-gray-400 font-medium italic">Unassigned</span>
                    }
                  </div>
                </td>
                {/* Linked Alerts */}
                <td className="px-3 py-3.5">
                  {c.linkedAlerts > 0 ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded-md">
                      <FileWarning size={10} strokeWidth={2} />
                      {c.linkedAlerts}
                    </span>
                  ) : (
                    <span className="text-[11px] text-gray-300 font-medium">—</span>
                  )}
                </td>
                {/* Updated */}
                <td className="px-3 pr-5 py-3.5 whitespace-nowrap">
                  <span className="text-[11px] text-gray-400 font-medium">{c.updatedAt}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {cases.length === 0 && (
        <div className="text-center py-14">
          <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center mx-auto mb-3">
            <Briefcase size={18} className="text-gray-400" strokeWidth={1.5} />
          </div>
          <p className="text-[13px] font-semibold text-gray-500">No cases match your filters</p>
          <p className="text-[11.5px] text-gray-400 mt-1">Try adjusting the search or filter options</p>
        </div>
      )}
    </div>
  )
}

// ── Case detail panel ──────────────────────────────────────────────────────────

const PANEL_TABS = ['Overview', 'Linked Alerts', 'Evidence', 'Timeline', 'Notes', 'Actions']

const EVIDENCE_ICON = {
  session:  { icon: Activity,      color: 'text-blue-500',   bg: 'bg-blue-50'   },
  prompt:   { icon: MessageSquare, color: 'text-violet-500', bg: 'bg-violet-50' },
  policy:   { icon: Shield,        color: 'text-orange-500', bg: 'bg-orange-50' },
  tool:     { icon: Wrench,        color: 'text-amber-500',  bg: 'bg-amber-50'  },
  artifact: { icon: Paperclip,     color: 'text-gray-500',   bg: 'bg-gray-100'  },
}

function mapCategoryToPolicy(categories) {
  if (!categories || categories.length === 0) return 'Prompt-Guard'
  if (categories.some(c => c.startsWith('S'))) return 'Prompt-Guard'
  return 'Prompt-Guard'
}

function CaseDetailPanel({ caseData, onClose }) {
  const navigate    = useNavigate()
  const [activeTab, setActiveTab] = useState('Overview')
  const [noteText,  setNoteText]  = useState('')
  const [notes,     setNotes]     = useState(caseData.notes)

  useEffect(() => {
    setActiveTab('Overview')
    setNotes(caseData.notes)
    setNoteText('')
  }, [caseData.id])

  const submitNote = () => {
    if (!noteText.trim()) return
    setNotes(prev => [...prev, {
      id: Date.now(),
      author: 'You',
      initials: 'YO',
      ts: 'Just now',
      text: noteText.trim(),
    }])
    setNoteText('')
  }

  const stripColor = SEV_STRIP[caseData.severity]

  return (
    <div className="flex flex-col h-full overflow-hidden bg-white">
      {/* Severity accent strip — 3px, full width */}
      <div className={cn('h-[3px] w-full shrink-0', stripColor)} />

      {/* Panel header */}
      <div className={cn('px-5 pt-4 pb-3.5 border-b shrink-0', SEV_HDR_BG[caseData.severity])}>

        {/* Row 1: case ID + badges + close */}
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-mono font-bold text-gray-400 tracking-wide">{caseData.id}</span>
            <span className="text-gray-300">·</span>
            <PriorityPip priority={caseData.priority} />
            <Badge variant={SEV_VARIANT[caseData.severity]}>{caseData.severity}</Badge>
            <Badge variant={STATUS_VARIANT[caseData.status] ?? 'neutral'}>{caseData.status}</Badge>
          </div>
          <button
            onClick={onClose}
            className="w-6 h-6 rounded-md flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-black/5 transition-colors shrink-0"
          >
            <X size={13} strokeWidth={2.5} />
          </button>
        </div>

        {/* Row 2: title */}
        <h2 className="text-[14.5px] font-bold text-gray-900 leading-snug mb-2.5">{caseData.title}</h2>

        {/* Row 3: owner + updated secondary meta */}
        <div className="flex items-center gap-3 mb-3.5 text-[11px] text-gray-500">
          <div className="flex items-center gap-1.5">
            <OwnerAvatar name={caseData.owner} size="sm" />
            {caseData.ownerDisplay
              ? <span className="font-medium text-gray-700">{caseData.ownerDisplay}</span>
              : <span className="italic text-gray-400">Unassigned</span>}
          </div>
          <span className="text-gray-300">·</span>
          <div className="flex items-center gap-1 text-gray-400">
            <Clock size={10} strokeWidth={2} />
            <span>Created {caseData.createdAt}</span>
          </div>
          <span className="text-gray-300">·</span>
          <span className="text-gray-400">{caseData.environment}</span>
        </div>

        {/* Row 4: action buttons — two groups */}
        <div className="flex items-center gap-2">
          {/* Secondary group */}
          <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white p-0.5 shadow-sm">
            <button className="flex items-center gap-1.5 h-6 px-2.5 rounded-md text-[11px] font-semibold text-gray-600 hover:bg-gray-100 hover:text-gray-800 transition-colors">
              <User size={11} strokeWidth={2} /> Assign
            </button>
            <div className="w-px h-4 bg-gray-200" />
            <button className="flex items-center gap-1.5 h-6 px-2.5 rounded-md text-[11px] font-semibold text-gray-600 hover:bg-gray-100 hover:text-gray-800 transition-colors">
              <CircleDot size={11} strokeWidth={2} /> Status
            </button>
          </div>

          {/* Escalate */}
          <button className="flex items-center gap-1.5 h-7 px-2.5 rounded-lg border border-orange-200 bg-orange-50 text-[11px] font-semibold text-orange-700 hover:bg-orange-100 hover:border-orange-300 transition-colors shadow-sm">
            <ShieldAlert size={11} strokeWidth={2} /> Escalate
          </button>

          {/* Resolve — primary CTA */}
          <button className="ml-auto flex items-center gap-1.5 h-7 px-3 rounded-lg bg-emerald-600 text-[11px] font-bold text-white hover:bg-emerald-700 transition-colors shadow-sm">
            <CheckCircle2 size={11} strokeWidth={2.5} /> Resolve
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center border-b border-gray-100 px-5 shrink-0 overflow-x-auto">
        {PANEL_TABS.map(tab => (
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
            {tab === 'Notes' && notes.length > 0 && (
              <span className="ml-1.5 text-[9px] bg-gray-100 text-gray-500 rounded-full px-1.5 py-px font-bold">{notes.length}</span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">

        {/* ── Overview ── */}
        {activeTab === 'Overview' && (
          <div className="divide-y divide-gray-50">

            {/* Description */}
            <div className="px-5 py-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 mb-2">Summary</p>
              <p className="text-[12px] text-gray-600 leading-relaxed">{caseData.description}</p>
            </div>

            {/* Evidence counters — horizontal bar */}
            <div className="px-5 py-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 mb-3">Evidence at a Glance</p>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Linked Alerts', value: caseData.linkedAlerts,  icon: FileWarning, bar: 'bg-red-400',    accent: 'border-l-red-400'    },
                  { label: 'Sessions',      value: caseData.linkedSessions, icon: Activity,    bar: 'bg-blue-400',   accent: 'border-l-blue-400'   },
                  { label: 'Policies Hit',  value: caseData.evidence.filter(e => e.type === 'policy').length, icon: Shield, bar: 'bg-orange-400', accent: 'border-l-orange-400' },
                ].map(({ label, value, icon: Icon, bar, accent }) => (
                  <div key={label} className={cn('bg-white border border-gray-200 border-l-[3px] rounded-lg px-3 py-2.5', accent)}>
                    <p className="text-[20px] font-black tabular-nums text-gray-900 leading-none">{value}</p>
                    <p className="text-[10px] font-semibold text-gray-500 mt-1">{label}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Case metadata */}
            <div className="px-5 py-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 mb-2.5">Case Details</p>
              <div className="space-y-0 rounded-xl border border-gray-100 overflow-hidden divide-y divide-gray-50">
                {[
                  { label: 'Created',     value: caseData.createdAt,              icon: Clock     },
                  { label: 'Owner',       value: caseData.ownerDisplay ?? '—',    icon: User      },
                  { label: 'Environment', value: caseData.environment,            icon: Network   },
                ].map(({ label, value, icon: Icon }) => (
                  <div key={label} className="flex items-center justify-between px-3 py-2 bg-gray-50/50">
                    <div className="flex items-center gap-2 text-[11px] text-gray-400 font-medium w-24 shrink-0">
                      <Icon size={10} strokeWidth={2} />
                      {label}
                    </div>
                    <span className="text-[11.5px] text-gray-800 font-semibold text-right">{value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Affected assets + entities */}
            <div className="px-5 py-4 space-y-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 mb-2">Affected Assets</p>
                <div className="flex flex-wrap gap-1.5">
                  {caseData.affectedAssets.map(a => (
                    <EntityChip key={a.name} label={a.name} type={a.type} />
                  ))}
                </div>
              </div>
              {(caseData.linkedEntities.agents.length + caseData.linkedEntities.models.length +
                caseData.linkedEntities.tools.length  + caseData.linkedEntities.data.length) > 0 && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 mb-2">Linked Entities</p>
                  <div className="flex flex-wrap gap-1.5">
                    {caseData.linkedEntities.agents.map(n => <EntityChip key={n} label={n} type="Agent" />)}
                    {caseData.linkedEntities.models.map(n => <EntityChip key={n} label={n} type="Model" />)}
                    {caseData.linkedEntities.tools.map(n  => <EntityChip key={n} label={n} type="Tool"  />)}
                    {caseData.linkedEntities.data.map(n   => <EntityChip key={n} label={n} type="Data"  />)}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Linked Alerts ── */}
        {activeTab === 'Linked Alerts' && (
          <div className="px-5 py-4">
            <div className="flex items-center justify-between mb-3.5">
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400">Linked Alerts</p>
              <span className="text-[10px] text-gray-400 font-medium">{caseData.linkedAlertList.length} alert{caseData.linkedAlertList.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="space-y-2">
              {caseData.linkedAlertList.map(a => {
                const bdrColor = a.severity === 'Critical' ? 'border-l-red-500'
                  : a.severity === 'High' ? 'border-l-orange-400'
                  : 'border-l-yellow-400'
                const bgColor = a.severity === 'Critical' ? 'bg-red-50/30'
                  : a.severity === 'High' ? 'bg-orange-50/30'
                  : 'bg-yellow-50/30'
                return (
                  <div key={a.id} className={cn(
                    'rounded-xl border border-gray-200 border-l-[3px] p-3.5 flex items-start gap-3',
                    bdrColor, bgColor,
                  )}>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-[10px] font-mono font-bold text-gray-400">{a.id}</span>
                        <Badge variant={SEV_VARIANT[a.severity]}>{a.severity}</Badge>
                        <Badge variant={STATUS_VARIANT[a.status] ?? 'neutral'}>{a.status}</Badge>
                      </div>
                      <p className="text-[12.5px] font-semibold text-gray-800 leading-snug mb-1.5">{a.title}</p>
                      <div className="flex items-center gap-1 text-[10px] text-gray-400">
                        <Clock size={9} strokeWidth={2} />
                        {a.ts}
                      </div>
                    </div>
                    <button className="flex items-center gap-1 h-7 px-2.5 rounded-lg border border-gray-200 bg-white text-[10.5px] font-semibold text-gray-600 hover:text-blue-600 hover:border-blue-200 hover:bg-blue-50 transition-colors shrink-0">
                      View <ArrowUpRight size={10} strokeWidth={2.5} />
                    </button>
                  </div>
                )
              })}
              {caseData.linkedAlertList.length === 0 && (
                <div className="text-center py-10 text-[12px] text-gray-400">No linked alerts for this case.</div>
              )}
            </div>
          </div>
        )}

        {/* ── Evidence ── */}
        {activeTab === 'Evidence' && (() => {
          const BORDER = {
            session:  'border-l-blue-400',
            prompt:   'border-l-violet-400',
            policy:   'border-l-orange-400',
            tool:     'border-l-amber-400',
            artifact: 'border-l-gray-300',
          }
          return (
            <div className="px-5 py-4">
              <div className="flex items-center justify-between mb-3.5">
                <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400">Collected Evidence</p>
                <span className="text-[10px] text-gray-400 font-medium">{caseData.evidence.length} items</span>
              </div>
              <div className="space-y-2.5">
                {caseData.evidence.map((e, i) => {
                  const ecfg   = EVIDENCE_ICON[e.type] ?? EVIDENCE_ICON.artifact
                  const Icon   = ecfg.icon
                  const border = BORDER[e.type] ?? BORDER.artifact
                  const isTech = e.type === 'session' || e.type === 'prompt' || e.type === 'tool'
                  return (
                    <div key={i} className={cn(
                      'bg-white rounded-xl border border-gray-200 border-l-[3px] overflow-hidden',
                      border,
                    )}>
                      {/* Header row */}
                      <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
                        <div className="flex items-center gap-2">
                          <div className={cn('w-6 h-6 rounded-md flex items-center justify-center shrink-0', ecfg.bg)}>
                            <Icon size={11} className={ecfg.color} strokeWidth={2} />
                          </div>
                          <span className="text-[11px] font-bold text-gray-700">{e.label}</span>
                        </div>
                        <span className="text-[9.5px] text-gray-400 font-mono">{e.ts}</span>
                      </div>
                      {/* Value */}
                      <div className={cn('mx-3.5 mb-3 rounded-lg px-2.5 py-2 break-all',
                        isTech
                          ? 'bg-gray-900 border border-gray-800'
                          : 'bg-gray-50 border border-gray-100',
                      )}>
                        <p className={cn('text-[11px] leading-relaxed',
                          isTech ? 'font-mono text-gray-200' : 'text-gray-700',
                        )}>
                          {e.value}
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="mt-3">
                <Button variant="outline" size="sm" className="gap-1.5 text-[11px] h-8">
                  <Paperclip size={11} strokeWidth={2} /> Attach Artifact
                </Button>
              </div>
            </div>
          )
        })()}

        {/* ── Timeline ── */}
        {activeTab === 'Timeline' && (
          <div className="px-5 py-4">
            <div className="flex items-center justify-between mb-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400">Activity Log</p>
              <span className="text-[10px] text-gray-400 font-medium">{caseData.timeline.length} events</span>
            </div>
            <div>
              {caseData.timeline.map((event, idx) => {
                const tcfg   = TL_TYPE_CFG[event.type] ?? TL_TYPE_CFG.status
                const Icon   = tcfg.icon
                const isLast = idx === caseData.timeline.length - 1

                // Per-type label color
                const labelColor =
                  event.type === 'alert' || event.type === 'escalated' ? 'text-red-600'
                  : event.type === 'policy'   ? 'text-orange-600'
                  : event.type === 'resolved' ? 'text-emerald-700'
                  : event.type === 'assigned' ? 'text-violet-600'
                  : event.type === 'evidence' ? 'text-purple-600'
                  : 'text-blue-600'

                return (
                  <div key={idx} className="flex gap-3">
                    {/* Dot + connector */}
                    <div className="flex flex-col items-center shrink-0">
                      <div className={cn(
                        'w-7 h-7 rounded-full flex items-center justify-center shrink-0 ring-2 ring-[#f6f7fb]',
                        tcfg.dot,
                      )}>
                        <Icon size={12} className="text-white" strokeWidth={2} />
                      </div>
                      {!isLast && (
                        <div className="w-px flex-1 mt-1.5 mb-1.5 border-l border-dashed border-gray-200" />
                      )}
                    </div>

                    {/* Card */}
                    <div className={cn('flex-1 min-w-0 rounded-xl border border-gray-150 bg-white px-3 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]', isLast ? 'mb-0' : 'mb-2.5')}>
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className={cn('text-[9.5px] font-bold uppercase tracking-wider', labelColor)}>
                          {tcfg.label}
                        </span>
                        <span className="text-[9.5px] text-gray-400 font-mono shrink-0">{event.ts}</span>
                      </div>
                      <p className="text-[12px] text-gray-700 leading-snug">{event.text}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── Notes ── */}
        {activeTab === 'Notes' && (
          <div className="flex flex-col h-full">
            {/* Compose bar */}
            <div className="border-b border-gray-100 bg-gray-50/60 px-5 py-3 shrink-0">
              <div className="flex items-end gap-2.5">
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-[9px] font-bold shrink-0 shadow-sm ring-2 ring-white">
                  YO
                </div>
                <div className="flex-1 min-w-0 bg-white border border-gray-200 rounded-2xl px-3.5 py-2.5 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-300 transition shadow-sm">
                  <textarea
                    value={noteText}
                    onChange={e => setNoteText(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitNote() }}
                    placeholder="Add an analyst note…"
                    rows={2}
                    className="w-full bg-transparent text-[12px] text-gray-700 resize-none focus:outline-none placeholder:text-gray-400 leading-relaxed"
                  />
                  <div className="flex items-center justify-between mt-1.5">
                    <span className="text-[9.5px] text-gray-400">⌘↵ to send</span>
                    <button
                      onClick={submitNote}
                      disabled={!noteText.trim()}
                      className={cn(
                        'flex items-center gap-1.5 h-6 px-2.5 rounded-lg text-[10.5px] font-bold transition-colors',
                        noteText.trim()
                          ? 'bg-blue-600 text-white hover:bg-blue-700'
                          : 'bg-gray-100 text-gray-400 cursor-not-allowed',
                      )}
                    >
                      <Send size={10} strokeWidth={2.5} /> Send
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Notes list */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {notes.length === 0 && (
                <div className="text-center py-10">
                  <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center mx-auto mb-3">
                    <MessageSquare size={16} className="text-gray-400" strokeWidth={1.75} />
                  </div>
                  <p className="text-[12.5px] font-semibold text-gray-500">No notes yet</p>
                  <p className="text-[11px] text-gray-400 mt-1">Add the first analyst comment above.</p>
                </div>
              )}
              {notes.map((note, idx) => {
                const isOwn = note.author === 'You'
                const avatarColors = [
                  'bg-blue-100 text-blue-700',
                  'bg-violet-100 text-violet-700',
                  'bg-emerald-100 text-emerald-700',
                  'bg-amber-100 text-amber-700',
                ]
                const avatarColor = isOwn
                  ? 'bg-blue-600 text-white'
                  : avatarColors[idx % avatarColors.length]
                return (
                  <div key={note.id} className="flex gap-3">
                    {/* Avatar */}
                    <div className={cn(
                      'w-8 h-8 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0 ring-2 ring-white shadow-sm',
                      avatarColor,
                    )}>
                      {note.initials}
                    </div>
                    {/* Bubble */}
                    <div className="flex-1 min-w-0">
                      {/* Author line */}
                      <div className="flex items-baseline gap-2 mb-1.5">
                        <span className="text-[12px] font-bold text-gray-800">{note.author}</span>
                        <span className="text-gray-300 text-[10px]">·</span>
                        <span className="text-[10px] text-gray-400 font-mono">{note.ts}</span>
                      </div>
                      {/* Message */}
                      <div className={cn(
                        'rounded-2xl rounded-tl-md px-4 py-3 border',
                        isOwn
                          ? 'bg-blue-600 border-blue-700 text-white'
                          : 'bg-white border-gray-200 text-gray-700',
                      )}>
                        <p className={cn('text-[12px] leading-relaxed', isOwn ? 'text-white' : 'text-gray-700')}>
                          {note.text}
                        </p>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── Actions ── */}
        {activeTab === 'Actions' && (
          <div className="px-5 py-4">
            <div className="flex items-center justify-between mb-3.5">
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400">Recommended Actions</p>
              <span className="text-[10px] text-gray-400 font-medium">{caseData.recommendedActions.length} action{caseData.recommendedActions.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="space-y-2">
              {caseData.recommendedActions.map((action, i) => {
                const Icon = action.icon
                const handleActionClick = () => {
                  if (action.route === 'runtime') {
                    const sessionId = caseData.linkedEntities.agents[0] ?? caseData.affectedAssets[0]?.name
                    if (sessionId) navigate(`/admin/runtime?session_id=${sessionId}`)
                  } else if (action.route === 'policies') {
                    const policyName = mapCategoryToPolicy(caseData.categories)
                    navigate(`/admin/policies?policy=${encodeURIComponent(policyName)}`)
                  }
                }
                return (
                  <div key={i} onClick={handleActionClick} className="group bg-white rounded-xl border border-gray-200 p-3.5 flex items-center gap-3.5 hover:border-blue-200 hover:shadow-[0_0_0_3px_rgba(59,130,246,0.08)] transition-all cursor-pointer">
                    <div className="w-9 h-9 rounded-xl bg-gray-100 flex items-center justify-center shrink-0 group-hover:bg-blue-100 transition-colors">
                      <Icon size={15} className="text-gray-500 group-hover:text-blue-600 transition-colors" strokeWidth={1.75} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[12.5px] font-semibold text-gray-800 group-hover:text-blue-700 transition-colors">{action.label}</p>
                      <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">{action.desc}</p>
                    </div>
                    <div className="flex items-center gap-1 text-[11px] font-semibold text-gray-400 group-hover:text-blue-600 transition-all group-hover:translate-x-0.5">
                      <span>Open</span>
                      <ArrowUpRight size={12} strokeWidth={2.5} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Cases() {
  const location   = useLocation()
  const rowRefs    = useRef({})

  const [cases,        setCases]        = useState([])
  const [loading,      setLoading]      = useState(true)
  const [selectedId,   setSelectedId]   = useState(null)
  const [search,       setSearch]       = useState('')
  const [statusFilter, setStatusFilter] = useState('All Status')
  const [sevFilter,    setSevFilter]    = useState('All Severity')
  const [prioFilter,   setPrioFilter]   = useState('All Priority')
  const [ownerFilter,  setOwnerFilter]  = useState('All Owners')
  const [timeRange,    setTimeRange]    = useState('Last 7d')
  const [unassigned,   setUnassigned]   = useState(false)

  // Fetch all cases from the DB-backed API.
  // Uses relative paths so requests go through the nginx proxy (same pattern as Runtime.jsx).
  // Retries on startup failure (handles orchestrator warm-up race condition),
  // then polls every 30 s so new cases appear automatically.
  useEffect(() => {
    let cancelled = false

    const apiBase  = import.meta.env.VITE_API_URL || '/api'
    const orchBase = (() => {
      const raw = import.meta.env.VITE_ORCHESTRATOR_URL || ''
      return (raw && !raw.startsWith('http')) ? raw : `${apiBase}/v1`
    })()

    async function fetchCases() {
      try {
        const tokenRes = await fetch(`${apiBase}/dev-token`)
        if (!tokenRes.ok) {
          console.warn('[Cases] dev-token fetch failed:', tokenRes.status)
          return false
        }
        const tokenData = await tokenRes.json()
        const token = tokenData.token || tokenData.access_token
        if (!token) {
          console.warn('[Cases] dev-token response missing token field:', Object.keys(tokenData))
          return false
        }

        const res = await fetch(`${orchBase}/cases`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) {
          console.warn('[Cases] GET /cases failed:', res.status, await res.text().catch(() => ''))
          return false
        }
        const data = await res.json()
        const apiCases = data.cases
        console.log('[Cases] fetched', apiCases?.length, 'cases')
        if (Array.isArray(apiCases) && !cancelled) {
          setCases(apiCases.map(adaptApiCase))
        }
        return true
      } catch (err) {
        console.warn('[Cases] fetchCases error:', err)
        return false
      }
    }

    // Initial load with retry (up to 3 attempts, 2 s apart) so a slow
    // orchestrator startup doesn't leave the page permanently empty.
    async function initialLoad() {
      for (let attempt = 0; attempt < 3; attempt++) {
        if (cancelled) return
        if (attempt > 0) await new Promise(r => setTimeout(r, 2000))
        if (cancelled) return
        const ok = await fetchCases()
        if (ok) break
      }
      if (!cancelled) setLoading(false)
    }

    initialLoad()

    // Poll every 30 s for live updates (silently — no loading spinner).
    const interval = setInterval(() => { fetchCases() }, 30_000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  // Auto-select case from ?case_id=<id> query param (e.g. after escalation from Runtime)
  const urlCaseId = new URLSearchParams(location.search).get('case_id')

  // Effect 1: if the case isn't in the API response (race condition), inject it from router state
  useEffect(() => {
    if (!urlCaseId) return
    setCases(prev => {
      if (prev.find(c => c.id === urlCaseId)) return prev
      const apiCase = location.state?.escalatedCase
      if (!apiCase) return prev
      return [adaptApiCase(apiCase), ...prev]
    })
  }, [urlCaseId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Effect 2: select + scroll AFTER loading is done so the table rows exist in the DOM
  useEffect(() => {
    if (!urlCaseId || loading) return
    setSelectedId(urlCaseId)
    requestAnimationFrame(() => {
      rowRefs.current[urlCaseId]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }, [urlCaseId, loading])

  const selectedCase = cases.find(c => c.id === selectedId) ?? null

  const filtered = cases.filter(c => {
    if (search       && !c.title.toLowerCase().includes(search.toLowerCase()) && !c.id.toLowerCase().includes(search.toLowerCase())) return false
    if (statusFilter !== 'All Status'   && c.status   !== statusFilter) return false
    if (sevFilter    !== 'All Severity' && c.severity  !== sevFilter)    return false
    if (prioFilter   !== 'All Priority' && c.priority  !== prioFilter)   return false
    if (ownerFilter  !== 'All Owners'   && c.owner     !== ownerFilter)  return false
    if (unassigned   && c.owner !== null)                                 return false
    return true
  })

  const handleSelect = (id) => {
    setSelectedId(prev => prev === id ? null : id)
  }

  const panelOpen = selectedCase !== null

  return (
    <PageContainer>
      {/* Header */}
      <PageHeader
        title="Cases"
        subtitle="Track investigations, coordinate response, and manage AI security incidents"
        actions={
          <>
            <Button variant="outline" size="sm" className="gap-1.5">
              <BookMarked size={13} strokeWidth={2} /> Saved Views
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Download size={13} strokeWidth={2} /> Export
            </Button>
            <Button variant="default" size="sm" className="gap-1.5">
              <Plus size={13} strokeWidth={2} /> Create Case
            </Button>
          </>
        }
      />

      {/* Summary strip */}
      <CasesSummaryStrip cases={cases} />

      {/* Filter bar */}
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex items-center gap-3 flex-wrap shadow-sm">
        {/* Search */}
        <div className="relative flex-1 min-w-[180px] max-w-[280px]">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" strokeWidth={2} />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search cases or IDs…"
            className={cn(
              'w-full h-8 pl-8 pr-3 rounded-lg border border-gray-200 bg-gray-50',
              'text-[12px] text-gray-700 placeholder:text-gray-400',
              'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 focus:bg-white',
              'hover:border-gray-300 transition-colors',
            )}
          />
        </div>

        <div className="w-px h-5 bg-gray-200 shrink-0" />

        {/* Dropdowns */}
        <FilterSelect value={statusFilter} onChange={setStatusFilter} options={STATUSES}   />
        <FilterSelect value={sevFilter}    onChange={setSevFilter}    options={SEVERITIES}  />
        <FilterSelect value={prioFilter}   onChange={setPrioFilter}   options={PRIORITIES}  />
        <FilterSelect value={ownerFilter}  onChange={setOwnerFilter}  options={OWNERS}      />
        <FilterSelect value={timeRange}    onChange={setTimeRange}    options={TIME_RANGES} />

        <div className="w-px h-5 bg-gray-200 shrink-0" />

        {/* Unassigned toggle */}
        <Toggle checked={unassigned} onChange={setUnassigned} label="Unassigned only" />

        {/* Results count */}
        <div className="ml-auto shrink-0 text-[11px] text-gray-400 font-medium">
          {filtered.length} case{filtered.length !== 1 ? 's' : ''}
        </div>
      </div>

      {/* Main layout — table + optional detail panel */}
      <div
        className={cn('grid gap-4 transition-all duration-300')}
        style={{
          gridTemplateColumns: panelOpen ? '1fr 420px' : '1fr',
          minHeight: 480,
        }}
      >
        {/* LEFT — Cases table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
          {/* Table header row */}
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Briefcase size={13} className="text-gray-400" strokeWidth={1.75} />
              <span className="text-[12px] font-semibold text-gray-700">Cases</span>
              <span className="text-[10.5px] text-gray-400 bg-gray-100 rounded-full px-2 py-px font-bold">{filtered.length}</span>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" className="h-7 text-[11px] px-2.5 gap-1.5">
                <Filter size={11} strokeWidth={2} /> Sort
              </Button>
              <Button variant="ghost" size="sm" className="h-7 text-[11px] px-2.5 gap-1.5">
                <MoreHorizontal size={11} strokeWidth={2} />
              </Button>
            </div>
          </div>
          {loading
            ? (
              <div className="flex items-center justify-center py-20 gap-2 text-gray-400">
                <Activity size={14} className="animate-spin" strokeWidth={2} />
                <span className="text-[12px]">Loading cases…</span>
              </div>
            )
            : <CasesTable cases={filtered} selectedId={selectedId} onSelect={handleSelect} rowRefs={rowRefs} />
          }
        </div>

        {/* RIGHT — Detail panel */}
        {panelOpen && selectedCase && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm"
            style={{ minHeight: 480 }}>
            <CaseDetailPanel
              caseData={selectedCase}
              onClose={() => setSelectedId(null)}
            />
          </div>
        )}
      </div>
    </PageContainer>
  )
}
