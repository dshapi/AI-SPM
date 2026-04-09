import { NavLink } from 'react-router-dom'
import {
  Shield, TriangleAlert, Boxes, Database, Fingerprint,
  Activity, ScrollText, GitBranch, FlaskConical, ClipboardList,
  Workflow, TrendingUp, TrendingDown, Minus, ArrowRight,
  CheckCircle2, AlertCircle, Circle, Zap, Play, FileText,
  Settings, ChevronRight, Box,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { SectionCard }   from '../../components/display/SectionCard.jsx'

// ── Design tokens ─────────────────────────────────────────────────────────────

const SEV_CFG = {
  Critical: { dot: 'bg-red-500',    pill: 'text-red-700 bg-red-50 border-red-200',         bdr: 'border-l-red-500'    },
  High:     { dot: 'bg-orange-500', pill: 'text-orange-700 bg-orange-50 border-orange-200', bdr: 'border-l-orange-500' },
  Medium:   { dot: 'bg-yellow-400', pill: 'text-yellow-700 bg-yellow-50 border-yellow-200', bdr: 'border-l-yellow-400' },
  Low:      { dot: 'bg-blue-400',   pill: 'text-blue-700 bg-blue-50 border-blue-200',       bdr: 'border-l-blue-400'   },
}

const TILE_CFG = {
  Inventory:  { color: 'text-blue-600',    bg: 'bg-blue-50',    border: 'border-blue-200',    strip: 'bg-blue-500',    to: '/admin/inventory'  },
  Alerts:     { color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200',     strip: 'bg-red-500',     to: '/admin/alerts'     },
  Runtime:    { color: 'text-yellow-600',  bg: 'bg-yellow-50',  border: 'border-yellow-200',  strip: 'bg-yellow-400',  to: '/admin/runtime'    },
  Lineage:    { color: 'text-violet-600',  bg: 'bg-violet-50',  border: 'border-violet-200',  strip: 'bg-violet-500',  to: '/admin/lineage'    },
  Policies:   { color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200',  strip: 'bg-indigo-500',  to: '/admin/policies'   },
  Simulation: { color: 'text-pink-600',    bg: 'bg-pink-50',    border: 'border-pink-200',    strip: 'bg-pink-500',    to: '/admin/simulation' },
}

// ── Mock data ─────────────────────────────────────────────────────────────────

const THREATS = [
  { id: 't1', sev: 'Critical', title: 'Jailbreak pattern matched on mixtral-8x7b', agent: 'Agent-Core-7', time: '3m ago'  },
  { id: 't2', sev: 'High',     title: 'Prompt injection detected — gpt-4-turbo',  agent: 'Agent-Sales-2', time: '11m ago' },
  { id: 't3', sev: 'High',     title: 'Model gate block on unauthorized model',    agent: 'Agent-HR-1',    time: '34m ago' },
  { id: 't4', sev: 'Medium',   title: 'Output PII exposure — claude-sonnet-4-6',    agent: 'Agent-Legal-5', time: '1h ago'  },
  { id: 't5', sev: 'Medium',   title: 'Rate limit threshold exceeded',             agent: 'Agent-Ops-3',   time: '2h ago'  },
]

const RECOMMENDATIONS = [
  { id: 'r1', priority: 1, title: 'Enable MFA for all high-privilege agent identities',  domain: 'Identity & Trust',    impact: 'High'   },
  { id: 'r2', priority: 2, title: 'Apply output filtering policies to 3 unprotected agents', domain: 'Runtime Enforcement', impact: 'High'   },
  { id: 'r3', priority: 3, title: 'Run simulation coverage for Finance domain',           domain: 'Simulation Readiness', impact: 'Medium' },
  { id: 'r4', priority: 4, title: 'Classify 8 untagged data sources in knowledge base',  domain: 'Data & Knowledge',    impact: 'Medium' },
]

const ACTIVITY_BARS = [
  { label: 'Mon', events: 24, alerts: 6  },
  { label: 'Tue', events: 31, alerts: 8  },
  { label: 'Wed', events: 19, alerts: 3  },
  { label: 'Thu', events: 42, alerts: 12 },
  { label: 'Fri', events: 37, alerts: 9  },
  { label: 'Sat', events: 15, alerts: 2  },
  { label: 'Sun', events: 28, alerts: 7  },
]

const ACTIVITY_EVENTS = [
  { type: 'alert',  text: 'Critical alert — jailbreak on mixtral-8x7b',         time: '3m ago'  },
  { type: 'policy', text: 'Policy "Output PII Block" triggered 4 times',         time: '18m ago' },
  { type: 'drift',  text: 'Agent-Core-7 baseline drift detected',                time: '45m ago' },
  { type: 'alert',  text: 'Rate limit exceeded on Agent-Ops-3',                  time: '1h ago'  },
  { type: 'sim',    text: 'Simulation run completed — 94% pass rate',            time: '3h ago'  },
  { type: 'policy', text: 'New policy "Tool Scope Enforcement" activated',       time: '5h ago'  },
]

const COMMAND_TILES = [
  { label: 'Inventory',  icon: Boxes,       metric: '72 Agents',   sub: '18 models, 47 tools' },
  { label: 'Alerts',     icon: TriangleAlert, metric: '7 Critical', sub: '12 unresolved today' },
  { label: 'Runtime',    icon: Activity,    metric: '98.4% uptime', sub: '4 anomalies flagged'  },
  { label: 'Lineage',    icon: GitBranch,   metric: '312 paths',   sub: 'Across 6 domains'     },
  { label: 'Policies',   icon: ScrollText,  metric: '41 active',   sub: '3 violations today'   },
  { label: 'Simulation', icon: FlaskConical, metric: '94% pass',   sub: 'Last run 3h ago'      },
]

const SNAPSHOT_ITEMS = [
  { label: 'Agents',       value: '72',  color: 'text-blue-600',   bg: 'bg-blue-50',   border: 'border-blue-200'   },
  { label: 'Models',       value: '18',  color: 'text-violet-600', bg: 'bg-violet-50', border: 'border-violet-200' },
  { label: 'Tools',        value: '47',  color: 'text-emerald-600',bg: 'bg-emerald-50',border: 'border-emerald-200'},
  { label: 'Data Sources', value: '32',  color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200' },
]

const IMPACT_CFG = {
  High:   { pill: 'text-red-700 bg-red-50 border-red-200',         bdr: 'border-l-red-400'    },
  Medium: { pill: 'text-yellow-700 bg-yellow-50 border-yellow-200', bdr: 'border-l-yellow-400' },
  Low:    { pill: 'text-blue-700 bg-blue-50 border-blue-200',       bdr: 'border-l-blue-400'   },
}

const EVENT_TYPE_CFG = {
  alert:  { dot: 'bg-red-500',    color: 'text-red-500',     chip: 'text-red-700 bg-red-50 border-red-200'         },
  policy: { dot: 'bg-indigo-500', color: 'text-indigo-500',  chip: 'text-indigo-700 bg-indigo-50 border-indigo-200' },
  drift:  { dot: 'bg-yellow-400', color: 'text-yellow-600',  chip: 'text-yellow-700 bg-yellow-50 border-yellow-200' },
  sim:    { dot: 'bg-emerald-500',color: 'text-emerald-600', chip: 'text-emerald-700 bg-emerald-50 border-emerald-200'},
}

// ── MiniSpark ─────────────────────────────────────────────────────────────────

function MiniSpark({ data, colorClass }) {
  const max   = Math.max(...data)
  const min   = Math.min(...data)
  const range = max - min || 1
  const W = 52, H = 22
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * W,
    H - ((v - min) / range) * (H - 4) - 2,
  ])
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')
  const last = pts[pts.length - 1]
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
      <path d={d} fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
        className={colorClass} stroke="currentColor" />
      <circle cx={last[0]} cy={last[1]} r="2.5" className={colorClass} fill="currentColor" />
    </svg>
  )
}

// ── SVG Posture Gauge ─────────────────────────────────────────────────────────

function PostureGauge({ score = 83 }) {
  // Arc from 210° to 330° (240° sweep), score maps to fill portion
  const R     = 52
  const cx    = 72
  const cy    = 76
  const sweep = 240
  const start = 210
  const pct   = score / 100

  function polarToXY(deg, r) {
    const rad = (deg * Math.PI) / 180
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
  }

  function arcPath(startDeg, endDeg, r) {
    const [x1, y1] = polarToXY(startDeg, r)
    const [x2, y2] = polarToXY(endDeg, r)
    const large    = endDeg - startDeg > 180 ? 1 : 0
    return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`
  }

  const trackPath = arcPath(start, start + sweep, R)
  const fillDeg   = start + sweep * pct
  const fillPath  = arcPath(start, fillDeg, R)

  // Tier color
  const scoreColor = score >= 80 ? '#10b981' : score >= 60 ? '#f59e0b' : '#ef4444'
  const tierLabel  = score >= 80 ? 'Healthy' : score >= 60 ? 'Warning' : 'Critical'
  const tierPill   = score >= 80
    ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
    : score >= 60
    ? 'text-yellow-700 bg-yellow-50 border-yellow-200'
    : 'text-red-700 bg-red-50 border-red-200'

  // Tick marks at arc endpoints
  const [tx0, ty0] = polarToXY(start, R)
  const [tx1, ty1] = polarToXY(start + sweep, R)

  return (
    <div className="flex flex-col items-center justify-center h-full">
      <svg width="144" height="120" viewBox="0 0 144 120">
        {/* Track */}
        <path d={trackPath} fill="none" stroke="#f3f4f6" strokeWidth="12" strokeLinecap="round" />
        <path d={trackPath} fill="none" stroke="#e5e7eb" strokeWidth="10" strokeLinecap="round" />
        {/* Fill with glow */}
        <path d={fillPath} fill="none" stroke={scoreColor} strokeWidth="10" strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 6px ${scoreColor}66)` }} />
        {/* Endpoint ticks */}
        <circle cx={tx0} cy={ty0} r="4" fill="#e5e7eb" />
        <circle cx={tx1} cy={ty1} r="4" fill="#e5e7eb" />
        {/* Center score */}
        <text x={cx} y={cy - 7} textAnchor="middle"
          style={{ fill: scoreColor, fontSize: 30, fontWeight: 900, fontFamily: 'inherit', letterSpacing: '-0.5px' }}>
          {score}
        </text>
        <text x={cx} y={cy + 11} textAnchor="middle"
          style={{ fill: '#9ca3af', fontSize: 10, fontFamily: 'inherit' }}>
          /100
        </text>
        {/* "0" and "100" labels at arc endpoints */}
        <text x={tx0 - 4} y={ty0 + 14} textAnchor="middle"
          style={{ fill: '#d1d5db', fontSize: 8, fontFamily: 'inherit', fontWeight: 700 }}>0</text>
        <text x={tx1 + 4} y={ty1 + 14} textAnchor="middle"
          style={{ fill: '#d1d5db', fontSize: 8, fontFamily: 'inherit', fontWeight: 700 }}>100</text>
      </svg>
      <span className={cn('inline-flex items-center text-[10px] font-black px-2.5 py-1 rounded-full border tracking-[0.05em] -mt-3', tierPill)}>
        {tierLabel}
      </span>
    </div>
  )
}

// ── ExecKpiCard ───────────────────────────────────────────────────────────────

function ExecKpiCard({ label, value, sub, unit, color, bg, icon: Icon, stripClass, subUp, spark }) {
  const subColor = subUp === true ? 'text-emerald-600' : subUp === false ? 'text-red-500' : 'text-gray-400'
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden hover:border-gray-300 hover:shadow-md transition-all duration-150 flex flex-col min-h-[130px]">
      {/* Accent strip */}
      <div className={cn('h-[3px] w-full shrink-0', stripClass)} />
      <div className="px-5 py-4 flex-1 flex flex-col justify-between">
        {/* Label + icon row */}
        <div className="flex items-start justify-between gap-2">
          <p className="text-[10.5px] font-bold uppercase tracking-[0.09em] text-gray-400 leading-none mt-0.5">{label}</p>
          <div className={cn('w-9 h-9 rounded-2xl flex items-center justify-center border shrink-0 shadow-sm', bg, color.replace('text-', 'border-').replace('600', '200'))}>
            <Icon size={15} className={color} strokeWidth={2} />
          </div>
        </div>
        {/* Value + sparkline row + sub */}
        <div className="mt-2">
          <div className="flex items-end justify-between gap-2">
            <div className="flex items-end gap-1">
              <span className="text-[34px] font-black tabular-nums leading-none text-gray-900">{value}</span>
              {unit && <span className="text-[14px] text-gray-400 mb-1.5 font-semibold">{unit}</span>}
            </div>
            {spark && (
              <div className="mb-1.5 opacity-70">
                <MiniSpark data={spark} colorClass={color} />
              </div>
            )}
          </div>
          {sub && (
            <p className={cn('text-[11px] font-semibold mt-1.5 leading-snug', subColor)}>{sub}</p>
          )}
        </div>
      </div>
    </div>
  )
}

// ── SectionLabel ──────────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-[10.5px] font-black uppercase tracking-[0.1em] text-gray-400">{children}</span>
      <div className="flex-1 h-px bg-gray-100" />
    </div>
  )
}

// ── OverviewHero ──────────────────────────────────────────────────────────────

function OverviewHero() {
  return (
    <div className="relative border border-gray-200 rounded-2xl shadow-sm overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #ffffff 0%, #f0f5ff 60%, #eef2ff 100%)' }}>
      {/* Dot-grid texture overlay */}
      <div className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #c7d2fe 1px, transparent 1px)',
          backgroundSize: '22px 22px',
          opacity: 0.35,
        }} />
      {/* Gradient accent strip — 4px, wider spectrum */}
      <div className="relative h-1 w-full bg-gradient-to-r from-blue-600 via-indigo-500 to-violet-500" />

      <div className="relative px-8 py-8 flex items-center justify-between gap-10">
        {/* Left: branding + CTAs */}
        <div className="min-w-0 flex-1">
          {/* Eyebrow */}
          <div className="flex items-center gap-2.5 mb-3">
            <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-sm">
              <Shield size={13} className="text-white" strokeWidth={2.5} />
            </div>
            <span className="text-[10.5px] font-black uppercase tracking-[0.14em] text-indigo-500">Orbyx AI-SPM</span>
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[9px] font-black text-emerald-700 tracking-wide">LIVE</span>
            </div>
          </div>

          <h1 className="text-[30px] font-black text-gray-900 leading-[1.1] tracking-tight">
            Security Command Center
          </h1>
          <p className="text-[13.5px] text-gray-500 mt-2 leading-relaxed max-w-[520px]">
            Real-time AI security posture across every agent, model, and data source — inventory, runtime, policies, and threat response unified.
          </p>

          {/* CTA row */}
          <div className="flex items-center gap-2.5 mt-6">
            <NavLink to="/admin/simulation">
              <Button className="h-9 gap-2 text-[12.5px] font-bold bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white border-0 shadow-md shadow-blue-100 px-4">
                <Play size={12} strokeWidth={2.5} />
                Run Simulation
              </Button>
            </NavLink>
            <Button variant="outline" className="h-9 gap-2 text-[12.5px] font-semibold text-gray-600 border-gray-200 bg-white/80 hover:bg-white">
              <FileText size={12} strokeWidth={2} />
              Generate Report
            </Button>
            <NavLink to="/admin/settings">
              <Button variant="outline" className="h-9 w-9 p-0 border-gray-200 bg-white/80 hover:bg-white">
                <Settings size={14} className="text-gray-500" strokeWidth={1.75} />
              </Button>
            </NavLink>
            <span className="text-[10.5px] text-gray-400 ml-1">· Scanned 2 min ago</span>
          </div>
        </div>

        {/* Right: posture gauge — framed panel */}
        <div className="shrink-0 flex flex-col items-center bg-white/70 border border-white rounded-2xl px-7 py-5 shadow-sm backdrop-blur-sm">
          <p className="text-[9.5px] font-black uppercase tracking-[0.14em] text-gray-400 mb-0.5">Overall Posture</p>
          <PostureGauge score={83} />
          <div className="flex items-center gap-1.5 mt-1.5">
            <TrendingUp size={11} className="text-emerald-500" strokeWidth={2.5} />
            <span className="text-[11px] font-bold text-emerald-600">+2 pts</span>
            <span className="text-[10.5px] text-gray-400">vs last week</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── SnapshotStrip ─────────────────────────────────────────────────────────────

const SNAPSHOT_ITEMS_FULL = [
  { label: 'Agents',       value: '72',  sub: '+4 this week',  color: 'text-blue-600',    bg: 'bg-blue-500',    border: 'border-blue-200',    strip: 'bg-blue-500'    },
  { label: 'Models',       value: '18',  sub: '2 new versions', color: 'text-violet-600',  bg: 'bg-violet-500',  border: 'border-violet-200',  strip: 'bg-violet-500'  },
  { label: 'Tools',        value: '47',  sub: '6 unreviewed',  color: 'text-emerald-600', bg: 'bg-emerald-500', border: 'border-emerald-200', strip: 'bg-emerald-500' },
  { label: 'Data Sources', value: '32',  sub: '8 unclassified',color: 'text-orange-600',  bg: 'bg-orange-500',  border: 'border-orange-200',  strip: 'bg-orange-400'  },
]

function SnapshotStrip() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="grid grid-cols-4 divide-x divide-gray-100">
        {SNAPSHOT_ITEMS_FULL.map(item => (
          <div key={item.label} className="relative px-6 py-5 flex flex-col justify-between overflow-hidden">
            {/* Very subtle tinted bg wash */}
            <div className="absolute inset-0 opacity-[0.03] pointer-events-none"
              style={{ background: `var(--tw-color)` }} />
            {/* Label */}
            <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-gray-400 mb-2">{item.label}</p>
            {/* Number */}
            <p className={cn('text-[32px] font-black tabular-nums leading-none', item.color)}>{item.value}</p>
            {/* Sub */}
            <p className="text-[10.5px] text-gray-400 font-medium mt-1.5">{item.sub}</p>
            {/* Bottom color accent */}
            <div className={cn('absolute bottom-0 left-0 right-0 h-[2px]', item.strip)} />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── ThreatList ────────────────────────────────────────────────────────────────

function ThreatList() {
  return (
    <SectionCard
      title="Active Threats"
      subtitle="Real-time alert stream across all agents"
      action={
        <NavLink to="/admin/alerts" className="text-[12px] font-semibold text-blue-600 hover:text-blue-700 transition-colors flex items-center gap-1">
          View all <ArrowRight size={11} strokeWidth={2.5} />
        </NavLink>
      }
      contentClassName="p-0"
    >
      <div className="divide-y divide-gray-100">
        {THREATS.map(t => {
          const cfg = SEV_CFG[t.sev]
          return (
            <div key={t.id} className={cn('group/row flex items-center gap-3 px-4 py-3.5 border-l-[3px] hover:bg-gray-50 transition-colors cursor-pointer', cfg.bdr)}>
              {/* Severity pill — leads the row */}
              <span className={cn('inline-flex items-center text-[9px] font-black px-2 py-[3px] rounded-full border tracking-[0.05em] shrink-0', cfg.pill)}>
                {t.sev}
              </span>
              {/* Title + meta */}
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] font-semibold text-gray-800 leading-snug truncate">{t.title}</p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[10.5px] text-gray-400 font-medium">{t.agent}</span>
                  <span className="text-[10.5px] text-gray-300">·</span>
                  <span className="text-[10.5px] text-gray-400 tabular-nums">{t.time}</span>
                </div>
              </div>
              {/* Hover arrow */}
              <ArrowRight size={13} strokeWidth={2} className="text-gray-200 group-hover/row:text-blue-400 shrink-0 transition-colors" />
            </div>
          )
        })}
      </div>
    </SectionCard>
  )
}

// ── RecommendationList ────────────────────────────────────────────────────────

function RecommendationList() {
  return (
    <SectionCard
      title="Top Recommendations"
      subtitle="Prioritized actions to improve posture"
      contentClassName="p-4"
    >
      <div className="space-y-2.5">
        {RECOMMENDATIONS.map((rec, i) => {
          const imp = IMPACT_CFG[rec.impact] ?? IMPACT_CFG.Low
          return (
            <div key={rec.id} className={cn('flex items-start gap-3 px-3 py-2.5 bg-gray-50 border border-gray-100 border-l-[3px] rounded-lg hover:bg-gray-100/60 transition-colors cursor-pointer group', imp.bdr)}>
              {/* Priority badge */}
              <div className="w-6 h-6 rounded-full bg-white border border-gray-200 flex items-center justify-center shrink-0 mt-0.5 shadow-[0_1px_2px_rgba(0,0,0,0.06)]">
                <span className="text-[10px] font-black text-gray-500">{i + 1}</span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[12px] font-semibold text-gray-800 leading-snug">{rec.title}</p>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-[10px] text-gray-400 font-medium">{rec.domain}</span>
                  <span className={cn('inline-flex items-center text-[9px] font-black px-1.5 py-0.5 rounded border tracking-[0.04em]', imp.pill)}>{rec.impact}</span>
                </div>
              </div>
              <ChevronRight size={13} strokeWidth={2} className="text-gray-300 group-hover:text-gray-400 shrink-0 mt-1 transition-colors" />
            </div>
          )
        })}
      </div>
    </SectionCard>
  )
}

// ── ActivityPanel ─────────────────────────────────────────────────────────────

const EVENT_TYPE_LABEL = {
  alert:  'Alert',
  policy: 'Policy',
  drift:  'Drift',
  sim:    'Sim',
}

function ActivityPanel() {
  const maxEvents = Math.max(...ACTIVITY_BARS.map(b => b.events))
  const CHART_H = 72

  return (
    <SectionCard
      title="Activity & Events"
      subtitle="Platform activity — last 7 days"
      contentClassName="p-5"
    >
      {/* Mini bar chart — fixed stacking via absolute positioning */}
      <div className="mb-5">
        <SectionLabel>Weekly Event Volume</SectionLabel>
        <div className="flex items-end gap-1.5" style={{ height: CHART_H + 16 }}>
          {ACTIVITY_BARS.map(bar => {
            const totalH  = (bar.events / maxEvents) * CHART_H
            const alertH  = (bar.alerts / bar.events) * totalH
            const eventH  = totalH - alertH
            return (
              <div key={bar.label} className="flex-1 flex flex-col items-center justify-end gap-1">
                {/* Bar */}
                <div className="relative w-full rounded-sm overflow-hidden" style={{ height: totalH }}>
                  {/* Base: events (blue) */}
                  <div className="absolute bottom-0 left-0 right-0 bg-blue-100" style={{ height: eventH }} />
                  {/* Top: alerts (red) */}
                  <div className="absolute top-0 left-0 right-0 bg-red-400/80 rounded-t-sm" style={{ height: alertH }} />
                </div>
                {/* Day label */}
                <span className="text-[8px] text-gray-400 font-medium tabular-nums">{bar.label}</span>
              </div>
            )
          })}
        </div>
        {/* Legend */}
        <div className="flex items-center gap-4 mt-1.5">
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2 rounded-[2px] bg-blue-100" />
            <span className="text-[9.5px] text-gray-400 font-medium">Events</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2 rounded-[2px] bg-red-400/80" />
            <span className="text-[9.5px] text-gray-400 font-medium">Alerts</span>
          </div>
          <span className="text-[9.5px] text-gray-300 ml-auto">Mon–Sun</span>
        </div>
      </div>

      {/* Event feed — timeline track */}
      <SectionLabel>Recent Activity</SectionLabel>
      <div className="relative">
        {/* Vertical track */}
        <div className="absolute left-[5px] top-2 bottom-2 w-px bg-gray-100" />
        <div className="space-y-0">
          {ACTIVITY_EVENTS.map((ev, i) => {
            const cfg       = EVENT_TYPE_CFG[ev.type] ?? EVENT_TYPE_CFG.alert
            const typeLabel = EVENT_TYPE_LABEL[ev.type] ?? 'Event'
            return (
              <div key={i} className="relative flex items-start gap-2.5 pl-4 py-1.5 -mx-0.5 hover:bg-gray-50 rounded-lg px-2 transition-colors group/ev">
                {/* Timeline dot — pulse on first */}
                <div className={cn(
                  'absolute left-[1px] top-2.5 w-2.5 h-2.5 rounded-full border-2 border-white shrink-0',
                  cfg.dot,
                  i === 0 && 'ring-2 ring-offset-0',
                  i === 0 ? cfg.dot.replace('bg-', 'ring-') : '',
                )} />
                {/* Type chip */}
                <span className={cn(
                  'inline-flex items-center text-[8.5px] font-black px-1.5 py-[2px] rounded border tracking-[0.04em] shrink-0 mt-0.5',
                  cfg.chip,
                )}>
                  {typeLabel}
                </span>
                <p className="text-[11px] text-gray-600 leading-snug flex-1">{ev.text}</p>
                <span className="text-[9.5px] text-gray-400 tabular-nums shrink-0 mt-0.5 whitespace-nowrap">{ev.time}</span>
              </div>
            )
          })}
        </div>
      </div>
    </SectionCard>
  )
}

// ── CommandTiles ──────────────────────────────────────────────────────────────

function CommandTiles() {
  return (
    <div>
      {/* Section header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[10.5px] font-black uppercase tracking-[0.1em] text-gray-400">Launch</span>
          <div className="h-px w-12 bg-gray-100" />
        </div>
        <span className="text-[11px] text-gray-400">Navigate directly to any module</span>
      </div>
      <div className="grid grid-cols-6 gap-3">
        {COMMAND_TILES.map(tile => {
          const cfg  = TILE_CFG[tile.label] ?? {}
          const Icon = tile.icon
          return (
            /*
             * NavLink is a plain block — NO transitions, NO transforms, NO compositing layers.
             * Applying transition-all + hover:translate directly on a NavLink creates GPU
             * compositing layers that persist mid-flight when navigation fires on click,
             * causing the destination page to render invisible beneath the stale layer until
             * a mouse-movement forces a fresh composite frame.
             *
             * All hover animation is delegated to the inner div via group-hover:* so the
             * NavLink itself stays compositing-layer-free.
             */
            <NavLink
              key={tile.label}
              to={cfg.to ?? '/admin/overview'}
              className="group block rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              {/* Inner div owns ALL visual state — safe to animate here */}
              <div className={cn(
                'bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden',
                'group-hover:shadow-lg group-hover:-translate-y-1 transition-all duration-200',
                'flex flex-col h-full',
              )}>
                {/* Accent strip */}
                <div className={cn('h-[3px] w-full shrink-0', cfg.strip)} />

                <div className="px-4 pt-4 pb-3.5 flex flex-col flex-1 relative overflow-hidden">
                  {/* Hover tint wash — pure CSS, no JS handlers */}
                  <div className={cn(
                    'absolute inset-0 opacity-0 group-hover:opacity-[0.04] transition-opacity duration-200 pointer-events-none rounded-xl',
                    cfg.bg,
                  )} />

                  {/* Header: eyebrow label + icon */}
                  <div className="flex items-start justify-between mb-3">
                    <p className="text-[9.5px] font-black uppercase tracking-[0.12em] text-gray-400 mt-1">{tile.label}</p>
                    <div className={cn(
                      'w-8 h-8 rounded-xl flex items-center justify-center border shrink-0',
                      'shadow-sm group-hover:shadow-md group-hover:scale-105 transition-all duration-200',
                      cfg.bg, cfg.border,
                    )}>
                      <Icon size={14} className={cfg.color} strokeWidth={2} />
                    </div>
                  </div>

                  {/* Metric — hero number */}
                  <p className={cn('text-[22px] font-black tabular-nums leading-none', cfg.color)}>{tile.metric}</p>
                  {/* Sub */}
                  <p className="text-[10px] text-gray-400 mt-1 leading-snug flex-1">{tile.sub}</p>

                  {/* Footer: open link */}
                  <div className="flex items-center gap-1 mt-3 pt-2.5 border-t border-gray-100">
                    <span className={cn('text-[10.5px] font-bold', cfg.color.replace('600', '500'))}>Open</span>
                    <ArrowRight size={10} strokeWidth={2.5}
                      className={cn('shrink-0 -mt-px group-hover:translate-x-0.5 transition-transform duration-150', cfg.color.replace('600', '400'))} />
                  </div>
                </div>
              </div>
            </NavLink>
          )
        })}
      </div>
    </div>
  )
}

// ── Overview page ─────────────────────────────────────────────────────────────

export default function Overview() {
  return (
    <PageContainer>

      {/* Hero */}
      <OverviewHero />

      {/* KPI row — 4 exec cards */}
      <div className="grid grid-cols-4 gap-4">
        <ExecKpiCard
          label="Posture Score"
          value="83"
          unit="/100"
          sub="↑ +2 pts vs last week"
          subUp={true}
          color="text-emerald-600"
          bg="bg-emerald-50"
          icon={Shield}
          stripClass="bg-emerald-500"
          spark={[76, 78, 79, 80, 80, 81, 83]}
        />
        <ExecKpiCard
          label="Critical Alerts"
          value="7"
          sub="↑ 3 new in last hour"
          subUp={false}
          color="text-red-600"
          bg="bg-red-50"
          icon={TriangleAlert}
          stripClass="bg-red-500"
          spark={[3, 5, 2, 4, 6, 4, 7]}
        />
        <ExecKpiCard
          label="Policy Coverage"
          value="76"
          unit="%"
          sub="14 agents unprotected"
          subUp={false}
          color="text-blue-600"
          bg="bg-blue-50"
          icon={CheckCircle2}
          stripClass="bg-blue-500"
          spark={[82, 80, 79, 78, 77, 77, 76]}
        />
        <ExecKpiCard
          label="High Risk Agents"
          value="5"
          sub="Requires immediate review"
          subUp={false}
          color="text-orange-600"
          bg="bg-orange-50"
          icon={AlertCircle}
          stripClass="bg-orange-400"
          spark={[2, 2, 3, 3, 4, 4, 5]}
        />
      </div>

      {/* Snapshot strip */}
      <SnapshotStrip />

      {/* Operational grid — 2-col left + 1-col right */}
      <div className="grid grid-cols-12 gap-4">
        {/* Left column — stacked threat + recommendations */}
        <div className="col-span-7 flex flex-col gap-4">
          <ThreatList />
          <RecommendationList />
        </div>

        {/* Right column — activity panel */}
        <div className="col-span-5">
          <ActivityPanel />
        </div>
      </div>

      {/* Command tiles */}
      <CommandTiles />

    </PageContainer>
  )
}
