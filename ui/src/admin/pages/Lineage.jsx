import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  MessageSquare, Layers, FileText, Cpu, Wrench,
  Shield, CheckCircle2,
  Search, ChevronDown, Play, Download, RotateCcw,
  AlertTriangle, Clock, ChevronRight, Tag,
  Database, Globe, Terminal, Lock,
  AlertCircle, Info, Users, Zap,
  ArrowRight, Code2, FileSearch, GitBranch,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { useSimulationContext } from '../../context/SimulationContext.jsx'
import { lineageFromEvents, assignCoords, assignEdgePaths } from '../../lib/lineageFromEvents.js'

// ── Design tokens ──────────────────────────────────────────────────────────────

const NODE_CFG = {
  prompt:  { label: 'Prompt',    icon: MessageSquare, iconBg: 'bg-gray-100',    iconTxt: 'text-gray-500',    bg: 'bg-white',       border: 'border-gray-200',   accent: '#9ca3af', typeTxt: 'text-gray-500'    },
  context: { label: 'Context',   icon: Layers,        iconBg: 'bg-blue-50',     iconTxt: 'text-blue-600',    bg: 'bg-white',       border: 'border-blue-100',   accent: '#60a5fa', typeTxt: 'text-blue-500'    },
  rag:     { label: 'RAG Data',  icon: FileText,      iconBg: 'bg-cyan-50',     iconTxt: 'text-cyan-600',    bg: 'bg-white',       border: 'border-cyan-100',   accent: '#22d3ee', typeTxt: 'text-cyan-500'    },
  model:   { label: 'LLM Model', icon: Cpu,           iconBg: 'bg-violet-50',   iconTxt: 'text-violet-600',  bg: 'bg-white',       border: 'border-violet-100', accent: '#a78bfa', typeTxt: 'text-violet-500'  },
  tool:    { label: 'Tool Call', icon: Wrench,        iconBg: 'bg-indigo-50',   iconTxt: 'text-indigo-600',  bg: 'bg-white',       border: 'border-indigo-100', accent: '#818cf8', typeTxt: 'text-indigo-500'  },
  policy:  { label: 'Policy',    icon: Shield,        iconBg: 'bg-amber-50',    iconTxt: 'text-amber-600',   bg: 'bg-amber-50/30', border: 'border-amber-200',  accent: '#fbbf24', typeTxt: 'text-amber-600'   },
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
// Layout designed to fit the 8-col panel (~680px visible) with minimal scroll.
// 5 column positions: n1 | n2/n3 | n4 | n5/n6 | n7

const NW = 55   // node half-width  → node 110px wide
const NH = 28   // node half-height → node 56px tall
const CW = 790  // canvas width (≈680px visible + small scroll margin)
const CH = 300  // canvas height


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

function LineageGraph({ selectedId, onSelect, nodes, edges, nodeEdges }) {
  const [hoveredId, setHoveredId] = useState(null)

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

          {/* Column zone labels — positioned at each column centroid */}
          <text x="210" y="22" fontSize="9" fontWeight="700" fill="#d1d5db" letterSpacing="0.08em" textAnchor="middle" style={{ userSelect: 'none' }}>CONTEXT / RAG</text>
          <text x="380" y="22" fontSize="9" fontWeight="700" fill="#d1d5db" letterSpacing="0.08em" textAnchor="middle" style={{ userSelect: 'none' }}>MODEL</text>
          <text x="545" y="22" fontSize="9" fontWeight="700" fill="#d1d5db" letterSpacing="0.08em" textAnchor="middle" style={{ userSelect: 'none' }}>TOOLS &amp; POLICY</text>
          <text x="710" y="22" fontSize="9" fontWeight="700" fill="#d1d5db" letterSpacing="0.08em" textAnchor="middle" style={{ userSelect: 'none' }}>OUTPUT</text>

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
  const path = []
  if (nodeId && nodes && nodes.length > 0) {
    const selectedIdx = nodes.findIndex(n => n.id === nodeId)
    if (selectedIdx >= 0) {
      // Include all nodes up to and including the selected one
      for (let i = 0; i <= selectedIdx; i++) {
        path.push(nodes[i].label)
      }
    }
  }

  return (
    <div className="flex items-center gap-1 text-[10.5px] text-gray-400 flex-wrap">
      {path.map((label, i) => (
        <span key={`${label}-${i}`} className="flex items-center gap-1">
          {i > 0 && <ChevronRight size={10} strokeWidth={2} className="text-gray-300 shrink-0" />}
          <span className={cn('font-medium', i === path.length - 1 ? 'text-gray-700' : 'text-gray-400')}>
            {label}
          </span>
        </span>
      ))}
    </div>
  )
}

// ── Session selector ────────────────────────────────────────────────────────────

function SessionSelector({ selected, onSelect, open, setOpen }) {
  const riskVariant = selected.risk === 'High' || selected.risk === 'Critical' ? 'high'
    : selected.risk === 'Medium' ? 'medium' : 'low'

  return (
    <div className="bg-white rounded-xl border border-gray-200 px-3 py-2 flex items-center gap-2 min-w-0">

      {/* Search */}
      <div className="relative shrink-0">
        <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          placeholder="Search sessions…"
          className="w-44 h-7 pl-8 pr-3 rounded-lg border border-gray-200 bg-gray-50 text-[11.5px] text-gray-700 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
          readOnly
        />
      </div>

      <div className="w-px h-4 bg-gray-200 shrink-0" />

      {/* Session dropdown */}
      <div className="relative shrink-0">
        <button
          onClick={() => setOpen(p => !p)}
          className="flex items-center gap-1.5 h-7 px-2.5 rounded-lg border border-gray-200 bg-white text-[11px] text-gray-700 hover:bg-gray-50 transition-colors"
        >
          <span className="font-mono text-[10.5px] text-gray-500">{selected.id.slice(0, 20)}…</span>
          <ChevronDown size={10} strokeWidth={2} className="text-gray-400 shrink-0" />
        </button>
        {open && (
          <div className="absolute top-full left-0 mt-1 z-50 bg-white rounded-xl border border-gray-200 shadow-lg py-1 min-w-[360px]">
            {SESSIONS.map(s => (
              <button
                key={s.id}
                onClick={() => { onSelect(s); setOpen(false) }}
                className={cn(
                  'w-full text-left px-3 py-2 hover:bg-gray-50 transition-colors flex items-center gap-3',
                  s.id === selected.id && 'bg-blue-50/50',
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono text-gray-700">{s.id.slice(0, 24)}…</span>
                    {s.id === selected.id && (
                      <span className="text-[9px] font-bold bg-blue-100 text-blue-600 px-1.5 py-px rounded-full">CURRENT</span>
                    )}
                  </div>
                  <p className="text-[10px] text-gray-400 mt-0.5">{s.agent} · {s.at}</p>
                </div>
                <Badge variant={s.risk === 'High' ? 'high' : s.risk === 'Medium' ? 'medium' : 'low'}>{s.risk}</Badge>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Agent + time */}
      <div className="flex items-center gap-1.5 text-[11px] text-gray-500 min-w-0 overflow-hidden">
        <Users size={10} strokeWidth={2} className="shrink-0 text-gray-400" />
        <span className="truncate font-medium text-gray-700">{selected.agent}</span>
        <span className="text-gray-300 shrink-0">·</span>
        <Clock size={10} strokeWidth={2} className="shrink-0 text-gray-400" />
        <span className="shrink-0 text-gray-500">{selected.at}</span>
      </div>

      <div className="flex-1" />

      {/* Status badges — right-anchored, never clip */}
      <div className="flex items-center gap-1.5 shrink-0">
        <div className="w-px h-3.5 bg-gray-200" />
        <Badge variant={riskVariant}>{selected.risk} Risk</Badge>
        {selected.status === 'Flagged' && (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold bg-red-50 text-red-600 border border-red-200 px-2 py-0.5 rounded-md whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            Flagged
          </span>
        )}
      </div>
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

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Lineage({ simEvents: simEventsProp } = {}) {
  // Support both direct prop (for tests) and context (for live use)
  const { simEvents: simEventsCtx } = useSimulationContext()
  const simEvents = simEventsProp ?? simEventsCtx

  // Derive graph from events
  const { nodes: rawNodes, edges: rawEdges } = lineageFromEvents(simEvents)
  const positionedNodes = assignCoords(rawNodes)
  const nodeById        = new Map(positionedNodes.map(n => [n.id, n]))
  const positionedEdges = assignEdgePaths(rawEdges, nodeById)

  // Build dynamic nodeEdges map (replaces hardcoded NODE_EDGES)
  const nodeEdges = {}
  for (const e of positionedEdges) {
    ;(nodeEdges[e.from] = nodeEdges[e.from] || []).push(e.id)
    ;(nodeEdges[e.to]   = nodeEdges[e.to]   || []).push(e.id)
  }

  const [selectedId,    setSelectedId]    = useState(positionedNodes[0]?.id ?? null)
  const [sessionOpen,   setSessionOpen]   = useState(false)

  // ── Context banner from query params (set by ActionPanel navigation) ──────
  const location        = useLocation()
  const _params         = new URLSearchParams(location.search)
  const ctxAsset        = _params.get('asset')
  const ctxFindingId    = _params.get('finding_id')
  const [bannerVisible, setBannerVisible] = useState(!!(ctxAsset || ctxFindingId))

  const handleSelect = (id) => setSelectedId(id)

  const riskyCt    = positionedNodes.filter(n => n.flagged).length
  const flaggedEdge = positionedEdges.filter(e => e.type === 'sensitive').length

  // Empty state - but still allow showing the banner for context
  const isEmpty = positionedNodes.length === 0

  return (
    <PageContainer>
      {/* Close session dropdown on outside click */}
      {sessionOpen && (
        <div className="fixed inset-0 z-40" onClick={() => setSessionOpen(false)} />
      )}

      {/* ── Context banner (shown when navigated from ActionPanel) ── */}
      {bannerVisible && (ctxAsset || ctxFindingId) && (
        <div
          data-testid="lineage-context-banner"
          className="flex items-center gap-3 px-4 py-2.5 bg-blue-50 border border-blue-200
                     rounded-xl text-[12px] text-blue-700 font-medium"
        >
          <GitBranch size={13} className="text-blue-400 shrink-0" />
          <span className="flex-1">
            Viewing lineage context
            {ctxAsset     && <> for asset: <strong>{ctxAsset}</strong></>}
            {ctxFindingId && <> · Finding: <strong>{ctxFindingId}</strong></>}
          </span>
          <button
            data-testid="lineage-banner-dismiss"
            onClick={() => setBannerVisible(false)}
            className="text-blue-400 hover:text-blue-600 transition-colors"
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
            <Button variant="outline" size="sm" className="gap-1.5">
              <RotateCcw size={13} strokeWidth={2} /> Replay
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Download size={13} strokeWidth={2} /> Export Trace
            </Button>
            <Button variant="default" size="sm" className="gap-1.5">
              <Play size={13} strokeWidth={2} /> Run Simulation
            </Button>
          </>
        }
      />

      {isEmpty ? (
        <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
          No simulation data yet — run a simulation to populate the graph.
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
          <div className="h-10 px-4 flex items-center justify-between border-b border-gray-100 shrink-0">
            <div className="flex items-center gap-2">
              <ArrowRight size={13} className="text-gray-400" strokeWidth={1.75} />
              <span className="text-[12px] font-semibold text-gray-700">Context Flow Graph</span>
              <Breadcrumb nodeId={selectedId} nodes={positionedNodes} />
            </div>
            {/* Legend */}
            <div className="flex items-center gap-3 text-[10px] text-gray-400">
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
            <LineageGraph selectedId={selectedId} onSelect={handleSelect} nodes={positionedNodes} edges={positionedEdges} nodeEdges={nodeEdges} />
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
