import { useState, useEffect } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  MessageSquare, Layers, FileText, Cpu, Wrench,
  Shield, CheckCircle2,
  Play, Download,
  AlertTriangle, Clock, ChevronRight, Tag,
  Database, Globe, Terminal, Lock,
  AlertCircle, Zap,
  ArrowRight, Code2, FileSearch, GitBranch,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { useSimulationContext } from '../../context/SimulationContext.jsx'
import { lineageFromEvents, assignCoords, assignEdgePaths, graphDimensions } from '../../lib/lineageFromEvents.js'
import { normalizeEvent } from '../../lib/eventSchema.js'
import { listSessions, fetchSessionEvents } from '../../api.js'
import { useFinding } from '../../hooks/useFindings.js'

// ── replayPromptFromFinding ─────────────────────────────────────────────────
// Resolve a usable REPLAY prompt from a Finding. Used when navigation lands
// on Lineage with ?finding_id=… — Run Simulation then re-runs the hunter's
// actual hypothesis (not a synthesised evidence join). Returns null when no
// replayable text exists so we can disable the Run button.
function replayPromptFromFinding(finding) {
  if (!finding) return null
  const h = finding.hypothesis
  if (typeof h === 'string' && h.trim()) return h.trim()
  const p = finding.prompt
  if (typeof p === 'string' && p.trim()) return p.trim()
  const t = finding.title
  if (typeof t === 'string' && t.trim()) return t.trim()
  return null
}

// ── Design tokens ──────────────────────────────────────────────────────────────

const NODE_CFG = {
  prompt:  { label: 'Prompt',    icon: MessageSquare, iconBg: 'bg-gray-100',    iconTxt: 'text-gray-500',    bg: 'bg-white',       border: 'border-gray-200',   accent: '#9ca3af', typeTxt: 'text-gray-500'    },
  context: { label: 'Context',   icon: Layers,        iconBg: 'bg-blue-50',     iconTxt: 'text-blue-600',    bg: 'bg-white',       border: 'border-blue-100',   accent: '#60a5fa', typeTxt: 'text-blue-500'    },
  rag:     { label: 'RAG Data',  icon: FileText,      iconBg: 'bg-cyan-50',     iconTxt: 'text-cyan-600',    bg: 'bg-white',       border: 'border-cyan-100',   accent: '#22d3ee', typeTxt: 'text-cyan-500'    },
  model:   { label: 'LLM Model', icon: Cpu,           iconBg: 'bg-violet-50',   iconTxt: 'text-violet-600',  bg: 'bg-white',       border: 'border-violet-100', accent: '#a78bfa', typeTxt: 'text-violet-500'  },
  tool:    { label: 'Tool Call', icon: Wrench,        iconBg: 'bg-indigo-50',   iconTxt: 'text-indigo-600',  bg: 'bg-white',       border: 'border-indigo-100', accent: '#818cf8', typeTxt: 'text-indigo-500'  },
  policy:  { label: 'Policy',    icon: Shield,        iconBg: 'bg-amber-50',    iconTxt: 'text-amber-600',   bg: 'bg-amber-50/30', border: 'border-amber-200',  accent: '#fbbf24', typeTxt: 'text-amber-600'   },
  llm:     { label: 'LLM Call',  icon: Zap,           iconBg: 'bg-fuchsia-50',  iconTxt: 'text-fuchsia-600', bg: 'bg-white',       border: 'border-fuchsia-100',accent: '#e879f9', typeTxt: 'text-fuchsia-500' },
  output:  { label: 'Output',    icon: CheckCircle2,  iconBg: 'bg-emerald-50',  iconTxt: 'text-emerald-600', bg: 'bg-white',       border: 'border-emerald-100',accent: '#34d399', typeTxt: 'text-emerald-500' },
}

const RISK_VARIANT = { Critical: 'critical', High: 'high', Medium: 'medium', Low: 'low' }

const EDGE_CFG = {
  data:      { stroke: '#d1d5db', strokeHi: '#9ca3af', dash: null,       marker: 'm-data',      label: 'data flow'          },
  sensitive: { stroke: '#fca5a5', strokeHi: '#f87171', dash: '5,3',      marker: 'm-sensitive', label: 'sensitive data'     },
  tool:      { stroke: '#a5b4fc', strokeHi: '#818cf8', dash: null,       marker: 'm-tool',      label: 'tool invocation'    },
  policy:    { stroke: '#fcd34d', strokeHi: '#f59e0b', dash: null,       marker: 'm-policy',    label: 'policy evaluation'  },
  output:    { stroke: '#6ee7b7', strokeHi: '#34d399', dash: null,       marker: 'm-output',    label: 'gated output'       },
}

// ── Graph dimensions ───────────────────────────────────────────────────────────
// Node sizing is fixed; canvas size is derived dynamically from how many tool
// nodes need to be rendered (see graphDimensions() in lineageFromEvents.js).
// This keeps the canonical 5-step graph compact (790×300) while letting
// 6-tool fan-outs (e.g. the threat-hunting agent) wrap into a second column
// with a wider/taller canvas — no overflow, no overlap with the policy node.

const NW = 55   // node half-width  → node 110px wide
const NH = 28   // node half-height → node 56px tall


// ── LineageGraph ───────────────────────────────────────────────────────────────

function RiskDot({ level }) {
  const cls = level === 'Critical' ? 'bg-red-500' : level === 'High' ? 'bg-orange-400' : level === 'Medium' ? 'bg-yellow-400' : 'bg-gray-300'
  return <span className={cn('inline-block w-1.5 h-1.5 rounded-full shrink-0', cls)} />
}

function GraphNode({ node, selected, hovered, dimmed, onSelect, onHover, onLeave }) {
  const cfg  = NODE_CFG[node.type] ?? NODE_CFG.prompt
  const Icon = cfg.icon
  const isRisky = node.risk === 'Critical' || node.risk === 'High'
  // For flagged/risky nodes the left accent uses the risk color; otherwise the type accent
  const accentColor = node.risk === 'Critical' ? '#ef4444'
                    : node.risk === 'High'     ? '#f97316'
                    : cfg.accent

  return (
    <div
      onClick={() => onSelect(node.id)}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={onLeave}
      style={{
        position: 'absolute',
        left: node.cx - NW,
        top:  node.cy - NH,
        width:  NW * 2,
        height: NH * 2,
        zIndex: selected ? 10 : hovered ? 8 : 1,
        borderLeftColor: selected ? '#3b82f6' : accentColor,
        borderLeftWidth: 3,
      }}
      className={cn(
        'rounded-xl border cursor-pointer transition-all duration-150 select-none overflow-hidden',
        cfg.bg, cfg.border,
        selected  && 'ring-2 ring-offset-1 ring-blue-500 shadow-lg',
        !selected && hovered  && 'shadow-md',
        !selected && !hovered && isRisky && 'ring-1 ring-offset-0 ring-red-200',
        dimmed && 'opacity-25',
      )}
    >
      <div className="flex items-center gap-2 px-2.5 h-full">
        {/* Icon */}
        <div className={cn(
          'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border',
          selected ? 'bg-blue-50 border-blue-200' : cn(cfg.iconBg, 'border-transparent'),
        )}>
          <Icon size={14} className={selected ? 'text-blue-600' : cfg.iconTxt} strokeWidth={selected ? 2 : 1.75} />
        </div>

        {/* Labels */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1 mb-[2px]">
            <span className={cn(
              'text-[9.5px] font-bold uppercase tracking-[0.07em] leading-none',
              selected ? 'text-blue-600' : cfg.typeTxt,
            )}>
              {cfg.label}
            </span>
            {node.flagged && (
              <span className="shrink-0 w-3 h-3 rounded-full bg-red-100 border border-red-200 flex items-center justify-center">
                <AlertTriangle size={7} className="text-red-500" strokeWidth={2.5} />
              </span>
            )}
          </div>
          <p className={cn(
            'text-[11.5px] font-semibold leading-none truncate',
            selected ? 'text-blue-700' : 'text-gray-900',
          )}>
            {node.label}
          </p>
          <p className="text-[9.5px] text-gray-400 leading-none mt-[2px] truncate">{node.sub}</p>
        </div>

        {/* Risk dot */}
        <div className="shrink-0 self-start mt-1.5">
          <RiskDot level={node.risk} />
        </div>
      </div>
    </div>
  )
}

function LineageGraph({ selectedId, onSelect, nodes, edges, nodeEdges, cw, ch }) {
  const [hoveredId, setHoveredId] = useState(null)
  const CW = cw
  const CH = ch

  // Hover → dim non-connected nodes (investigation mode)
  // Selection → highlight edges only; never dim the whole graph
  const hoverEdges    = hoveredId  ? (nodeEdges[hoveredId]  ?? []) : []
  const selectedEdges = selectedId ? (nodeEdges[selectedId] ?? []) : []
  // Which edges to highlight: hover takes precedence over selection
  const activeEdges   = hoveredId ? hoverEdges : selectedEdges

  // A node is dimmed only while hovering, never just from a click
  const isDimmed = (node) => {
    if (!hoveredId) return false
    if (node.id === hoveredId) return false
    return !hoverEdges.some(eid => {
      const e = edges.find(x => x.id === eid)
      return e && (e.from === node.id || e.to === node.id)
    })
  }

  return (
    <div className="relative overflow-x-auto">
      <div style={{ width: CW, height: CH, position: 'relative' }}>

        {/* ── SVG edge layer (behind nodes) ── */}
        <svg
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
          width={CW}
          height={CH}
          viewBox={`0 0 ${CW} ${CH}`}
        >
          <defs>
            {/* Dot-grid background pattern */}
            <pattern id="dot-grid" x="0" y="0" width="20" height="20" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="0.9" fill="#e5e7eb" />
            </pattern>

            {/* Arrowhead markers */}
            {[
              { id: 'm-data',      fill: '#9ca3af' },
              { id: 'm-sensitive', fill: '#f87171' },
              { id: 'm-tool',      fill: '#818cf8' },
              { id: 'm-policy',    fill: '#f59e0b' },
              { id: 'm-output',    fill: '#34d399' },
            ].map(m => (
              <marker key={m.id} id={m.id} markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
                <path d="M0,0 L7,2.5 L0,5 Z" fill={m.fill} />
              </marker>
            ))}
          </defs>

          {/* Dot-grid fill */}
          <rect width={CW} height={CH} fill="url(#dot-grid)" />

          {/* Column zone labels — positioned dynamically over each present
              node column so they line up regardless of which event types
              actually fired. Computed by the parent and passed in via `cols`. */}
          {(nodes ?? []).reduce((acc, n) => {
            // One label per column position; first node we see at a given cx wins.
            if (!acc.seen.has(n.cx) && n.type !== 'tool') {
              acc.seen.add(n.cx)
              const cfg = NODE_CFG[n.type]
              if (cfg) acc.labels.push(
                <text
                  key={`zone-${n.cx}`}
                  x={n.cx}
                  y={22}
                  fontSize="9"
                  fontWeight="700"
                  fill="#d1d5db"
                  letterSpacing="0.08em"
                  textAnchor="middle"
                  style={{ userSelect: 'none' }}
                >
                  {cfg.label.toUpperCase()}
                </text>
              )
            }
            return acc
          }, { seen: new Set(), labels: [] }).labels}

          {edges.map(edge => {
            const cfg         = EDGE_CFG[edge.type] ?? EDGE_CFG.data
            const inActive    = activeEdges.includes(edge.id)
            const hasActive   = activeEdges.length > 0
            return (
              <g key={edge.id}>
                <path
                  d={edge.path}
                  fill="none"
                  stroke={inActive ? cfg.strokeHi : cfg.stroke}
                  strokeWidth={inActive ? 2.5 : 1.5}
                  strokeDasharray={cfg.dash ?? undefined}
                  markerEnd={`url(#${cfg.marker})`}
                  opacity={hasActive ? (inActive ? 1 : 0.22) : 0.7}
                  style={{ transition: 'opacity 0.15s ease, stroke-width 0.12s ease' }}
                />
              </g>
            )
          })}
        </svg>

        {/* ── HTML node layer ── */}
        {nodes.map(node => (
          <GraphNode
            key={node.id}
            node={node}
            selected={node.id === selectedId}
            hovered={node.id === hoveredId}
            dimmed={isDimmed(node)}
            onSelect={onSelect}
            onHover={id => setHoveredId(id)}
            onLeave={() => setHoveredId(null)}
          />
        ))}
      </div>
    </div>
  )
}

// ── Node detail panel ──────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 leading-none">{children}</p>
}

function Flag({ label }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold bg-red-50 text-red-600 border border-red-200 px-1.5 py-0.5 rounded-md">
      <AlertTriangle size={9} strokeWidth={2.5} />{label.replace(/_/g, ' ')}
    </span>
  )
}

function NodeDetailPanel({ nodeId, nodes }) {
  const node   = nodes && nodeId ? nodes.find(n => n.id === nodeId) : null
  const cfg    = node ? (NODE_CFG[node.type] ?? NODE_CFG.prompt) : null
  const Icon   = cfg?.icon

  if (!node) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center mb-3">
          <FileSearch size={18} className="text-gray-400" />
        </div>
        <p className="text-[13px] font-medium text-gray-500">No node selected</p>
        <p className="text-[11px] text-gray-400 mt-1">Click any node in the graph to inspect its details</p>
      </div>
    )
  }

  const riskVariant = RISK_VARIANT[node.risk] ?? 'neutral'

  return (
    <div className="flex flex-col h-full">

      {/* Header accent strip */}
      <div className="h-[3px] shrink-0 rounded-t-xl" style={{ background: cfg.accent }} />

      {/* Identity row */}
      <div className="px-4 py-3 border-b border-gray-100 shrink-0">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5 min-w-0">
            <div className={cn('w-8 h-8 rounded-xl flex items-center justify-center shrink-0 border', cfg.iconBg, 'border-transparent')}>
              <Icon size={15} className={cfg.iconTxt} strokeWidth={1.75} />
            </div>
            <div className="min-w-0">
              <p className={cn('text-[9.5px] font-bold uppercase tracking-[0.07em] leading-none mb-1', cfg.typeTxt)}>
                {cfg.label}
              </p>
              <h3 className="text-[14px] font-bold text-gray-900 leading-none">{node.label}</h3>
              <p className="text-[10px] text-gray-400 mt-0.5 truncate">{node.sub}</p>
            </div>
          </div>
          <div className="shrink-0 flex flex-col items-end gap-1">
            <Badge variant={riskVariant}>{node.risk}</Badge>
            {node.flagged && <Badge variant="critical">Flagged</Badge>}
          </div>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
        <div className="px-4 py-3">
          <SectionLabel>Node Information</SectionLabel>
          <div className="mt-2 text-[11px] text-gray-600 leading-relaxed">
            <p>This node represents a {cfg.label.toLowerCase()} in the data lineage.</p>
            {node.sub && <p className="mt-2 text-gray-500">{node.sub}</p>}
          </div>
        </div>


      </div>
    </div>
  )
}

// ── TraceTimeline ──────────────────────────────────────────────────────────────

const STEP_CFG = {
  ok:       { dot: 'bg-emerald-400 border-emerald-400', icon: CheckCircle2, txt: 'text-emerald-600', line: 'bg-emerald-200' },
  warn:     { dot: 'bg-amber-400 border-amber-400',     icon: AlertTriangle,txt: 'text-amber-600',   line: 'bg-amber-200'   },
  critical: { dot: 'bg-red-500 border-red-500',         icon: AlertTriangle,txt: 'text-red-600',     line: 'bg-red-300'     },
}

function TraceTimeline({ selectedId, onSelect, nodes }) {
  // Build timeline from nodes
  const timeline = nodes.map((n, i) => ({
    id: n.id,
    step: i + 1,
    label: n.label,
    ts: '00:00:00.000',
    dur: 'N/A',
    gapMs: 0,
    status: 'ok',
  }))

  if (timeline.length === 0) {
    return null
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="h-10 px-4 flex items-center justify-between border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2">
          <Clock size={13} className="text-gray-400" strokeWidth={1.75} />
          <span className="text-[12px] font-semibold text-gray-700">Trace Timeline</span>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-gray-400">
          <span>{timeline.length} events</span>
        </div>
      </div>

      {/* Steps */}
      <div className="px-5 py-4 overflow-x-auto">
        <div className="flex items-start gap-0 min-w-max">
          {timeline.map((step, idx) => {
            const scfg     = STEP_CFG[step.status] ?? STEP_CFG.ok
            const isSelected = step.id === selectedId
            const isLast = idx === timeline.length - 1
            const cw = 60  // Fixed connector width

            return (
              <div key={step.id} className="flex items-start">
                {/* Step block */}
                <button
                  onClick={() => onSelect(step.id)}
                  className={cn(
                    'flex flex-col items-center w-[108px] px-1 pt-1.5 pb-2 rounded-lg transition-all duration-100 group',
                    isSelected
                      ? 'bg-blue-50 ring-1 ring-blue-200'
                      : 'hover:bg-gray-50',
                  )}
                >
                  {/* Dot + step number */}
                  <div className={cn(
                    'w-7 h-7 rounded-full border-2 flex items-center justify-center mb-2 transition-all shadow-sm',
                    isSelected ? 'bg-blue-600 border-blue-600 shadow-blue-200' : cn(scfg.dot, 'group-hover:scale-105'),
                  )}>
                    <span className="text-[10px] font-bold text-white leading-none">{step.step}</span>
                  </div>

                  {/* Label */}
                  <p className={cn(
                    'text-[10.5px] font-semibold text-center leading-tight mb-1.5 px-0.5',
                    isSelected ? 'text-blue-700' : 'text-gray-700',
                  )}>
                    {step.label}
                  </p>

                  {/* Timestamp sub-ms portion */}
                  <p className="text-[9px] text-gray-400 font-mono leading-none tabular-nums">
                    {step.ts.includes('.') ? '.' + step.ts.split('.')[1] : ''}
                  </p>

                  {/* Duration */}
                  <p className={cn(
                    'text-[9.5px] font-semibold mt-0.5 tabular-nums',
                    step.status === 'critical' ? 'text-red-500'
                      : step.status === 'warn' ? 'text-amber-500'
                      : isSelected ? 'text-blue-500'
                      : 'text-gray-400',
                  )}>
                    {step.dur}
                  </p>
                </button>

                {/* Proportional connector line */}
                {!isLast && (
                  <div
                    className="flex items-center self-start mt-[25px]"
                    style={{ width: cw }}
                  >
                    <div
                      className={cn('h-[2px] flex-1 rounded-full',
                        step.status === 'critical' ? 'bg-red-300'
                          : step.status === 'warn'  ? 'bg-amber-200'
                          : 'bg-gray-200',
                      )}
                    />
                    <ArrowRight
                      size={8}
                      className={cn('shrink-0 -ml-0.5',
                        step.status === 'critical' ? 'text-red-400'
                          : step.status === 'warn'  ? 'text-amber-300'
                          : 'text-gray-300',
                      )}
                      strokeWidth={2}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────────

function Breadcrumb({ nodeId, nodes }) {
  // Build a simple breadcrumb path from root to the selected node
  // by traversing the first edge connected to the node
  const full = []
  if (nodeId && nodes && nodes.length > 0) {
    const selectedIdx = nodes.findIndex(n => n.id === nodeId)
    if (selectedIdx >= 0) {
      // Include all nodes up to and including the selected one
      for (let i = 0; i <= selectedIdx; i++) {
        full.push(nodes[i].label)
      }
    }
  }

  // Collapse long paths (e.g. threat-hunter's 6-tool fan-out) into
  // "first … last-3" so the panel header stays on one line.
  const MAX = 4
  const path = full.length > MAX
    ? [full[0], '…', ...full.slice(-3)]
    : full

  return (
    <div className="flex items-center gap-1 text-[10.5px] text-gray-400 min-w-0 overflow-hidden whitespace-nowrap">
      {path.map((label, i) => (
        <span key={`${label}-${i}`} className="flex items-center gap-1 shrink-0">
          {i > 0 && <ChevronRight size={10} strokeWidth={2} className="text-gray-300 shrink-0" />}
          <span className={cn(
            'font-medium truncate max-w-[120px]',
            label === '…' ? 'text-gray-300' :
            i === path.length - 1 ? 'text-gray-700' : 'text-gray-400',
          )}>
            {label}
          </span>
        </span>
      ))}
    </div>
  )
}

// ── KPI strip ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, accentClass }) {
  return (
    <div className={cn('bg-white rounded-xl border border-gray-200 border-l-[3px] px-4 py-3 flex items-center gap-3', accentClass)}>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.08em] leading-none mb-1.5">{label}</p>
        <p className="text-[22px] font-bold text-gray-900 leading-none tabular-nums">{value}</p>
        {sub && <p className="text-[10px] text-gray-400 mt-1 leading-none">{sub}</p>}
      </div>
    </div>
  )
}

// ── Session picker ────────────────────────────────────────────────────────────

function _formatSessionLabel(s) {
  const sid = s.session_id || ''
  const shortSid = sid.length > 16 ? `${sid.slice(0, 6)}…${sid.slice(-6)}` : sid
  const promptPreview = typeof s.prompt === 'string' && s.prompt.length > 0
    ? ` — ${s.prompt.slice(0, 36)}${s.prompt.length > 36 ? '…' : ''}`
    : ''
  return `${shortSid}${promptPreview}`
}

function LineageSessionPicker({ sessions, value, loading, onChange }) {
  const list     = Array.isArray(sessions) ? sessions : []
  const isEmpty  = list.length === 0
  // Always render the picker so the control is discoverable even before the
  // first /sessions fetch resolves (or when the backend has no recorded
  // sessions yet). The dropdown is disabled in that case and shows a hint.
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px] font-medium text-gray-500">Session:</span>
      <select
        value={value || ''}
        onChange={e => onChange(e.target.value)}
        disabled={loading || isEmpty}
        title={isEmpty ? 'No recorded sessions yet — run a simulation to populate' : undefined}
        className={cn(
          'text-[12px] border border-gray-200 rounded-lg px-2 py-1',
          'bg-white text-gray-700 min-w-[180px] max-w-[340px]',
          'focus:outline-none focus:ring-1 focus:ring-blue-400',
          (loading || isEmpty) && 'opacity-60 cursor-not-allowed',
        )}
      >
        {isEmpty ? (
          <option value="">No recent sessions</option>
        ) : (
          <>
            <option value="">Live (current)</option>
            {list.map(s => (
              <option key={s.session_id} value={s.session_id}>
                {_formatSessionLabel(s)}
              </option>
            ))}
          </>
        )}
      </select>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Lineage({ simEvents: simEventsProp } = {}) {
  // Support both direct prop (for tests) and context (for live use)
  const { simEvents: simEventsCtx, startSimulation } = useSimulationContext()

  // ── Entry points & traceability ──────────────────────────────────────────
  // The Lineage page can be reached MANY ways — every action in the system
  // should land here with a renderable graph. Since session lineage events
  // are now persisted in Postgres (orchestrator session_events table) and
  // the api service transparently falls back to that store when its in-memory
  // LRU evicts a session, we have a single source of truth: the backfill
  // endpoint. No more synthetic reconstruction from finding evidence.
  //
  // Resolution chain (in priority):
  //   1. simEventsProp  (explicit test prop)
  //   2. backfillEvents (HTTP /sessions/{id}/events — unions in-memory log +
  //                      persistent session_events)
  //   3. simEventsCtx   (live WebSocket stream for current chat)
  //
  // Entry routes:
  //   /admin/lineage                                  → live
  //   /admin/lineage/:sessionId                       → backfill
  //   /admin/lineage?finding_id=…                     → finding-linked replay
  //                                                     (hypothesis used as
  //                                                     Run Simulation prompt)
  //   /admin/lineage/:sessionId?finding_id=…          → backfill + finding ctx
  const { sessionId: routeSessionId } = useParams()
  const navigate = useNavigate()
  const location        = useLocation()
  const _params         = new URLSearchParams(location.search)
  const ctxAsset        = _params.get('asset')
  const ctxFindingId    = _params.get('finding_id')
  const [sessions, setSessions]           = useState([])
  const [pickedSession, setPickedSession] = useState(routeSessionId || '')
  const [backfillEvents, setBackfillEvents] = useState(null)
  const [backfillLoading, setBackfillLoading] = useState(false)

  // Fetch the list of recent sessions on mount. Re-fetched when simEvents gets
  // non-empty (a fresh session completed) so the dropdown stays current.
  useEffect(() => {
    let cancelled = false
    listSessions().then(list => {
      if (!cancelled) setSessions(list)
    })
    return () => { cancelled = true }
  }, [simEventsCtx.length])

  // If the URL contains a :sessionId, treat it as the picked session.
  useEffect(() => {
    if (routeSessionId && routeSessionId !== pickedSession) {
      setPickedSession(routeSessionId)
    }
  }, [routeSessionId, pickedSession])

  // When a session is picked, fetch its events from the backend and normalise
  // them into SimulationEvent shape for lineageFromEvents(). We keep the
  // backfilled events in LOCAL state (not shared context) so switching back to
  // "Live" cleanly restores the current session without leftover history.
  useEffect(() => {
    if (!pickedSession) { setBackfillEvents(null); return }
    let cancelled = false
    setBackfillLoading(true)
    fetchSessionEvents(pickedSession).then(raw => {
      if (cancelled) return
      const normalised = raw.map(normalizeEvent)
      setBackfillEvents(normalised)
      setBackfillLoading(false)
    })
    return () => { cancelled = true }
  }, [pickedSession])

  // Finding context (if arrived with ?finding_id=…) — used ONLY to seed the
  // Run Simulation prompt with the hunter's actual hypothesis. The graph
  // itself is rendered from persisted session events (never synthesised).
  const { finding: ctxFinding } = useFinding(ctxFindingId)
  const hasBackfillEvents = Array.isArray(backfillEvents) && backfillEvents.length > 0

  // Resolution order: test prop → backfill (when non-empty) → empty backfill
  // (drives the "no events" message) → live context.
  const simEvents =
    simEventsProp
    ?? (hasBackfillEvents ? backfillEvents : null)
    ?? backfillEvents
    ?? simEventsCtx

  const handleSessionChange = (sid) => {
    setPickedSession(sid)
    // Keep the URL in sync so the selection survives reload / is shareable.
    if (sid) {
      navigate(`/admin/lineage/${encodeURIComponent(sid)}`, { replace: true })
    } else {
      navigate('/admin/lineage', { replace: true })
    }
  }

  // ── Run Simulation → replay current session ─────────────────────────────────
  // Re-executes the same investigation that produced the currently-viewed
  // lineage, kicking off a fresh live run. We stay on the Lineage page and let
  // the new session's events stream in through the shared context (clearing
  // pickedSession so the graph switches from backfilled → live).
  //
  // All findings in this system come from the threat-hunting agent, so when
  // a finding is in context, the replay prompt IS the finding's hypothesis —
  // the actual question the hunter asked — never the evidence-joined
  // contextSnippet.
  //
  // Prompt resolution order (highest priority first):
  //   1. finding hypothesis/prompt/title — when a finding is in context
  //      (Alerts → Lineage entry), use the real replayable query.
  //   2. sessions[] summary row matching pickedSession (fast path — already
  //      surfaced by the backend's list_sessions() summary).
  //   3. normalised simEvents (`session.started` event's details.prompt).
  const _findReplayPrompt = () => {
    // 1. Prefer the finding's own prompt when a finding is in context.
    if (ctxFinding) {
      const p = replayPromptFromFinding(ctxFinding)
      if (p) return p
    }
    // 2. Backend session summary row
    if (pickedSession) {
      const row = sessions.find(s => s.session_id === pickedSession)
      if (row && typeof row.prompt === 'string' && row.prompt.trim()) {
        return row.prompt.trim()
      }
    }
    // 3. session.started event in whatever event list we're rendering
    for (const ev of simEvents || []) {
      if (ev?.event_type === 'session.started') {
        const p = ev.details?.prompt
        if (typeof p === 'string' && p.trim()) return p.trim()
      }
    }
    return null
  }

  const replayPrompt = _findReplayPrompt()
  const canReplay    = typeof replayPrompt === 'string' && replayPrompt.trim().length > 0

  const handleRunSimulation = () => {
    if (!canReplay) return
    // Switch the GRAPH source to the LIVE context so new events stream in,
    // but DON'T reset the session selector — the user wants to see which
    // session is being replayed. Clearing backfillEvents (without clearing
    // pickedSession or navigating away) makes the resolution chain
    // `backfill ?? simEventsCtx` fall through to the live stream.
    setBackfillEvents(null)

    startSimulation({
      attackType:  'exfiltration',
      prompt:      replayPrompt,
      execMode:    'live',
      customMode:  'single',
      garakConfig: null,
    })
  }

  // Export whatever events are currently being rendered as a JSON file the
  // user can attach to bug reports / postmortems.
  const handleExportTrace = () => {
    if (!simEvents || simEvents.length === 0) return
    try {
      const blob = new Blob([JSON.stringify(simEvents, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const sid = pickedSession || 'live'
      const safe = String(sid).replace(/[^A-Za-z0-9._-]/g, '_')
      a.download = `lineage-${safe}-${Date.now()}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('[Lineage] Export failed:', err)
    }
  }

  // Derive graph from events
  const { nodes: rawNodes, edges: rawEdges } = lineageFromEvents(simEvents)
  const positionedNodes = assignCoords(rawNodes)
  const nodeById        = new Map(positionedNodes.map(n => [n.id, n]))
  const positionedEdges = assignEdgePaths(rawEdges, nodeById)

  // Compute the canvas size from actually-present node types (and tool count).
  // Passing nodes[] uses graphDimensions' overload that auto-derives both
  // toolCount and presentTypes — so the canvas only sizes for the columns we
  // actually render, eliminating the empty left gutter when upstream nodes
  // (prompt / context / model) are missing.
  const { cw: CW, ch: CH } = graphDimensions(positionedNodes)

  // Build dynamic nodeEdges map (replaces hardcoded NODE_EDGES)
  const nodeEdges = {}
  for (const e of positionedEdges) {
    ;(nodeEdges[e.from] = nodeEdges[e.from] || []).push(e.id)
    ;(nodeEdges[e.to]   = nodeEdges[e.to]   || []).push(e.id)
  }

  const [selectedId,    setSelectedId]    = useState(positionedNodes[0]?.id ?? null)

  // ── Context banner from query params (set by ActionPanel navigation) ──────
  // Shown when navigation landed here with asset / finding context so the
  // user sees *why* this graph is on screen. With persistent session_events
  // the graph is ALWAYS the real recorded run, never synthesised — so the
  // banner only surfaces navigation context, never a "reconstructed" warning.
  const [bannerDismissed, setBannerDismissed] = useState(false)
  const bannerVisible = !bannerDismissed && (!!ctxAsset || !!ctxFindingId)
  const bannerFindingId = ctxFindingId || null

  const handleSelect = (id) => setSelectedId(id)

  const riskyCt    = positionedNodes.filter(n => n.flagged).length
  const flaggedEdge = positionedEdges.filter(e => e.type === 'sensitive').length

  // Empty state - but still allow showing the banner for context
  const isEmpty = positionedNodes.length === 0

  return (
    <PageContainer>

      {/* ── Context banner (shown when navigated from ActionPanel with
            asset / finding context) ── */}
      {bannerVisible && (
        <div
          data-testid="lineage-context-banner"
          className="flex items-center gap-3 px-4 py-2.5 border rounded-xl text-[12px] font-medium bg-blue-50 border-blue-200 text-blue-700"
        >
          <GitBranch size={13} className="text-blue-400 shrink-0" />
          <span className="flex-1">
            <>Viewing lineage context</>
            {ctxAsset        && <> · asset: <strong>{ctxAsset}</strong></>}
            {bannerFindingId && <> · Finding: <strong>{bannerFindingId}</strong></>}
          </span>
          <button
            data-testid="lineage-banner-dismiss"
            onClick={() => setBannerDismissed(true)}
            className="transition-colors text-blue-400 hover:text-blue-600"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Header ── */}
      <PageHeader
        title="Lineage"
        subtitle="Trace context flow and understand how AI decisions are formed"
        actions={
          <>
            <LineageSessionPicker
              sessions={sessions}
              value={pickedSession}
              loading={backfillLoading}
              onChange={handleSessionChange}
            />
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={handleExportTrace}
              disabled={simEvents.length === 0}
              title={
                simEvents.length === 0
                  ? 'No events to export'
                  : 'Download the event stream as JSON'
              }
            >
              <Download size={13} strokeWidth={2} /> Export Trace
            </Button>
            <Button
              variant="default"
              size="sm"
              className="gap-1.5"
              onClick={handleRunSimulation}
              disabled={!canReplay}
              title={
                canReplay
                  ? 'Replay this session — re-runs the same prompt through the live pipeline'
                  : 'Pick a session (or load one with events) to replay its prompt'
              }
            >
              <Play size={13} strokeWidth={2} /> Run Simulation
            </Button>
          </>
        }
      />

      {isEmpty ? (
        <div className="flex flex-col items-center justify-center h-64 text-gray-500 text-sm gap-2">
          {backfillLoading ? (
            <span className="text-gray-400">Loading session events…</span>
          ) : pickedSession ? (
            <>
              <span className="text-gray-500">
                No events recorded for this session.
              </span>
              <span className="text-[11px] text-gray-400">
                Session id: <code className="font-mono">{pickedSession}</code>
              </span>
              <span className="text-[11px] text-gray-400">
                If this session ran but events were never persisted, the
                orchestrator's session_events store was likely unreachable
                at the time.
              </span>
            </>
          ) : sessions.length > 0 ? (
            <>
              <span>No live simulation — pick a recent session above to inspect it.</span>
              <span className="text-[11px] text-gray-400">
                {sessions.length} recent session{sessions.length === 1 ? '' : 's'} available.
              </span>
            </>
          ) : (
            <span className="text-gray-400">
              No simulation data yet — run a simulation to populate the graph.
            </span>
          )}
        </div>
      ) : (
        <>
          {/* ── KPI strip ── */}
          <div className="grid grid-cols-4 gap-3">
            <KpiCard label="Trace Nodes"       value={positionedNodes.length}     sub="In this session"         accentClass="border-l-blue-500"    />
            <KpiCard label="Flagged Nodes"     value={riskyCt}          sub="Risk flags raised"        accentClass="border-l-red-500"     />
            <KpiCard label="Sensitive Flows"   value={flaggedEdge}       sub="PII / sensitive data"    accentClass="border-l-amber-500"   />
            <KpiCard label="Policies Triggered" value={positionedEdges.filter(e => e.type === 'policy').length}  sub="policy evaluation"           accentClass="border-l-orange-500"  />
          </div>

          {/* ── Main layout ── */}
      <div
        className="grid grid-cols-12 gap-3"
        style={{ height: 'calc(100vh - 380px)', minHeight: 520 }}
      >
        {/* LEFT/CENTER — graph panel (8 cols) */}
        <div className="col-span-8 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
          {/* Panel header */}
          <div className="h-10 px-4 flex items-center justify-between gap-3 border-b border-gray-100 shrink-0">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <ArrowRight size={13} className="text-gray-400 shrink-0" strokeWidth={1.75} />
              <span className="text-[12px] font-semibold text-gray-700 whitespace-nowrap shrink-0">Context Flow Graph</span>
              <Breadcrumb nodeId={selectedId} nodes={positionedNodes} />
            </div>
            {/* Legend */}
            <div className="flex items-center gap-3 text-[10px] text-gray-400 shrink-0">
              {[
                { label: 'data flow',   color: '#d1d5db', dash: false },
                { label: 'sensitive',   color: '#fca5a5', dash: true  },
                { label: 'tool call',   color: '#a5b4fc', dash: false },
                { label: 'policy',      color: '#fcd34d', dash: false },
              ].map(({ label, color, dash }) => (
                <span key={label} className="flex items-center gap-1">
                  <svg width="18" height="4">
                    <line x1="0" y1="2" x2="18" y2="2" stroke={color} strokeWidth="2" strokeDasharray={dash ? '4,2' : undefined} />
                  </svg>
                  {label}
                </span>
              ))}
            </div>
          </div>

          {/* Graph area */}
          <div className="flex-1 overflow-auto p-4">
            <LineageGraph selectedId={selectedId} onSelect={handleSelect} nodes={positionedNodes} edges={positionedEdges} nodeEdges={nodeEdges} cw={CW} ch={CH} />
          </div>

          {/* Graph footer — edge type + node selection stats */}
          <div className="px-4 py-2 border-t border-gray-100 bg-gray-50/50 shrink-0 flex items-center gap-3">
            <div className="flex items-center gap-3 text-[10px] text-gray-400">
              {positionedNodes.map(n => {
                const ncfg = NODE_CFG[n.type] ?? NODE_CFG.prompt
                return (
                  <button
                    key={n.id}
                    onClick={() => handleSelect(n.id)}
                    className={cn(
                      'flex items-center gap-1 transition-colors',
                      n.id === selectedId ? 'text-blue-600 font-semibold' : 'hover:text-gray-600',
                    )}
                  >
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ background: ncfg.accent }}
                    />
                    {n.label}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        {/* RIGHT — node detail panel (4 cols) */}
        <div className="col-span-4 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
          <NodeDetailPanel nodeId={selectedId} nodes={positionedNodes} />
        </div>
      </div>

          {/* ── Timeline ── */}
          <TraceTimeline selectedId={selectedId} onSelect={handleSelect} nodes={positionedNodes} />
        </>
      )}

    </PageContainer>
  )
}
