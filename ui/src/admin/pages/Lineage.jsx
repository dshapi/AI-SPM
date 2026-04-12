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

// ── Graph nodes ────────────────────────────────────────────────────────────────
// Port reference (half-widths/heights):
//   right=(cx+NW,cy)  left=(cx-NW,cy)  top=(cx,cy-NH)  bottom=(cx,cy+NH)

const NODES = [
  { id: 'n1', type: 'prompt',  label: 'User Prompt',       sub: '"Summarize Q1 financials…"',   cx: 65,  cy: 150, risk: 'Low',      flagged: false },
  { id: 'n2', type: 'context', label: 'Session Context',   sub: '3 turns · 2.1 KB',             cx: 210, cy: 78,  risk: 'Low',      flagged: false },
  { id: 'n3', type: 'rag',     label: 'RAG Document',      sub: 'customer_financials_2024.pdf',  cx: 210, cy: 222, risk: 'High',     flagged: true  },
  { id: 'n4', type: 'model',   label: 'LLM Processing',    sub: 'gpt-4o · 1,247 tokens',        cx: 380, cy: 150, risk: 'Medium',   flagged: false },
  { id: 'n5', type: 'tool',    label: 'SQL Query',         sub: 'fin_records · 50 rows',        cx: 520, cy: 72,  risk: 'Medium',   flagged: false },
  { id: 'n6', type: 'policy',  label: 'PII Policy',        sub: 'pii-detect-v2 · TRIGGERED',   cx: 570, cy: 228, risk: 'Critical', flagged: true  },
  { id: 'n7', type: 'output',  label: 'Output',            sub: 'Redacted · 312 tokens',        cx: 710, cy: 150, risk: 'Low',      flagged: false },
]

// ── Graph edges ─────────────────────────────────────────────────────────────────
// Port coords:
//   n1R=(120,150)  n2L=(155,78)  n2R=(265,78)  n3L=(155,222)  n3R=(265,222)
//   n4L=(325,150)  n4R=(435,150)
//   n5Bo=(520,100) n5L=(465,72)
//   n6T=(570,200)  n6L=(515,228) n6R=(625,228)
//   n7L=(655,150)

const EDGES = [
  { id: 'e1', from: 'n1', to: 'n2', type: 'data',      label: 'data',        path: 'M 120 150 C 138 150, 138 78,  155 78'   },
  { id: 'e2', from: 'n1', to: 'n3', type: 'sensitive',  label: 'retrieval',   path: 'M 120 150 C 138 150, 138 222, 155 222'  },
  { id: 'e3', from: 'n2', to: 'n4', type: 'data',       label: 'context',     path: 'M 265 78  C 295 78,  295 150, 325 150'  },
  { id: 'e4', from: 'n3', to: 'n4', type: 'sensitive',  label: 'rag content', path: 'M 265 222 C 295 222, 295 150, 325 150'  },
  { id: 'e5', from: 'n4', to: 'n5', type: 'tool',       label: 'tool call',   path: 'M 435 150 C 478 150, 520 124, 520 100'  },
  { id: 'e6', from: 'n4', to: 'n6', type: 'policy',     label: 'policy eval', path: 'M 435 150 C 475 150, 475 228, 515 228'  },
  { id: 'e7', from: 'n5', to: 'n6', type: 'policy',     label: 'pii scan',    path: 'M 520 100 C 520 152, 570 152, 570 200'  },
  { id: 'e8', from: 'n3', to: 'n6', type: 'sensitive',  label: 'direct scan', path: 'M 265 222 C 390 246, 390 246, 515 228'  },
  { id: 'e9', from: 'n6', to: 'n7', type: 'output',     label: 'gated',       path: 'M 625 228 C 640 228, 640 150, 655 150'  },
]

// Edges connected to each node (for highlight logic)
const NODE_EDGES = {
  n1: ['e1','e2'],
  n2: ['e1','e3'],
  n3: ['e2','e4','e8'],
  n4: ['e3','e4','e5','e6'],
  n5: ['e5','e7'],
  n6: ['e6','e7','e8','e9'],
  n7: ['e9'],
}

// Breadcrumb path to each node
const NODE_PATH = {
  n1: ['Prompt'],
  n2: ['Prompt','Context'],
  n3: ['Prompt','RAG Doc'],
  n4: ['Prompt','Context','LLM'],
  n5: ['Prompt','Context','LLM','SQL Tool'],
  n6: ['Prompt','RAG Doc','PII Policy'],
  n7: ['Prompt','RAG Doc','PII Policy','Output'],
}

// ── Mock sessions ──────────────────────────────────────────────────────────────

const SESSIONS = [
  { id: 'sess_01HZ4bQxk1M7tR9pN2', agent: 'FinanceAssistant-v2',        risk: 'High',   status: 'Flagged',   at: '09:14 UTC', active: true  },
  { id: 'sess_01HZ3aKxj0L6qQ8mM1', agent: 'CustomerSupport-GPT',        risk: 'Low',    status: 'Completed', at: '09:02 UTC', active: false },
  { id: 'sess_01HZ2yIwi9K5pP7lL0', agent: 'ThreatHunter-AI',            risk: 'Medium', status: 'Completed', at: '08:51 UTC', active: false },
  { id: 'sess_01HZ1xHvh8J4oO6kK9', agent: 'DataPipeline-Orchestrator',  risk: 'Low',    status: 'Completed', at: '08:30 UTC', active: false },
]

// ── Timeline steps ─────────────────────────────────────────────────────────────

const TIMELINE = [
  { id: 'n1', step: 1, label: 'Prompt received',       ts: '09:14:03.002', dur: '< 1ms',   gapMs: 1,    status: 'ok'       },
  { id: 'n2', step: 2, label: 'Context retrieved',      ts: '09:14:03.008', dur: '6ms',     gapMs: 6,    status: 'ok'       },
  { id: 'n3', step: 3, label: 'RAG documents fetched',  ts: '09:14:03.014', dur: '48ms',    gapMs: 48,   status: 'warn'     },
  { id: 'n4', step: 4, label: 'Model invoked',          ts: '09:14:03.062', dur: '2,310ms', gapMs: 2310, status: 'ok'       },
  { id: 'n5', step: 5, label: 'SQL tool called',        ts: '09:14:05.372', dur: '180ms',   gapMs: 180,  status: 'ok'       },
  { id: 'n6', step: 6, label: 'Policy triggered',       ts: '09:14:05.552', dur: '12ms',    gapMs: 12,   status: 'critical' },
  { id: 'n7', step: 7, label: 'Output generated',       ts: '09:14:05.564', dur: '< 1ms',   gapMs: 0,    status: 'ok'       },
]

// Log-scale connector width: min 20px, max 72px, proportional to step duration
const TL_MAX_MS = Math.max(...TIMELINE.map(s => s.gapMs))
const connectorWidth = ms => ms <= 0 ? 0
  : Math.round(20 + 52 * (Math.log(ms + 1) / Math.log(TL_MAX_MS + 1)))

// ── Node detail data ───────────────────────────────────────────────────────────

const NODE_DETAIL = {
  n1: {
    ts: '09:14:03.002 UTC', dur: '< 1ms', type: 'user_message',
    agent: 'FinanceAssistant-v2', session: 'sess_01HZ4bQxk1',
    user: 'j.smith@acme.corp',
    content: { kind: 'prompt', text: '"Summarize the Q1 2024 customer financial data for the top 50 accounts and highlight any anomalies."', tokens: 23 },
    risk: { score: 12, level: 'Low', flags: [] },
    related: { alerts: 0, policies: ['prompt-guard-v3'], actions: [] },
  },
  n2: {
    ts: '09:14:03.008 UTC', dur: '6ms', type: 'context_retrieval',
    agent: 'FinanceAssistant-v2', session: 'sess_01HZ4bQxk1',
    user: 'system',
    content: { kind: 'context', turns: 3, size: '2.1 KB', summary: 'Prior turn: user requested monthly breakdown. Agent returned chart data. No anomalies flagged in session history.' },
    risk: { score: 8, level: 'Low', flags: [] },
    related: { alerts: 0, policies: [], actions: [] },
  },
  n3: {
    ts: '09:14:03.014 UTC', dur: '48ms', type: 'rag_retrieval',
    agent: 'FinanceAssistant-v2', session: 'sess_01HZ4bQxk1',
    user: 'retriever',
    content: { kind: 'rag', document: 'customer_financials_2024.pdf', excerpt: '…ACME Corp — Q1 Revenue: $4.2M. SSN: 123-45-6789. Account #: 847362910. Balance: $1,248,300. Credit rating: AA…', chunks: 3, tokens: 412, similarity: 0.94 },
    risk: { score: 78, level: 'High', flags: ['pii_detected', 'financial_data', 'ssn_pattern'] },
    related: { alerts: 2, policies: ['pii-detect-v2', 'data-access-v1'], actions: ['flag_for_review'] },
  },
  n4: {
    ts: '09:14:03.062 UTC', dur: '2,310ms', type: 'model_invocation',
    agent: 'FinanceAssistant-v2', session: 'sess_01HZ4bQxk1',
    user: 'gpt-4o',
    content: { kind: 'model', model: 'gpt-4o-2024-11-20', temperature: 0.3, promptTokens: 1247, completionTokens: 892, totalTokens: 2139 },
    risk: { score: 35, level: 'Medium', flags: ['large_context'] },
    related: { alerts: 0, policies: ['token-budget-v1'], actions: [] },
  },
  n5: {
    ts: '09:14:05.372 UTC', dur: '180ms', type: 'tool_call',
    agent: 'FinanceAssistant-v2', session: 'sess_01HZ4bQxk1',
    user: 'SQL-Query-Runner',
    content: { kind: 'tool', tool: 'SQL-Query-Runner', query: "SELECT account_id, name, ssn, balance, q1_revenue\nFROM customer_records\nWHERE tier = 'enterprise'\nORDER BY balance DESC\nLIMIT 50", rows: 50, bytes: '24.6 KB' },
    risk: { score: 62, level: 'High', flags: ['unrestricted_select', 'pii_in_result', 'ssn_exposed'] },
    related: { alerts: 1, policies: ['tool-scope-v2'], actions: [] },
  },
  n6: {
    ts: '09:14:05.552 UTC', dur: '12ms', type: 'policy_evaluation',
    agent: 'FinanceAssistant-v2', session: 'sess_01HZ4bQxk1',
    user: 'pii-detect-v2',
    content: { kind: 'policy', policy: 'pii-detect-v2', triggered: true, action: 'redact_and_flag', findings: ['SSN pattern matched (regex: \\d{3}-\\d{2}-\\d{4})', 'Account numbers detected (9-digit)', 'Financial PII threshold exceeded (score 0.91 > 0.85)'], redacted: 4 },
    risk: { score: 91, level: 'Critical', flags: ['policy_triggered', 'pii_redacted', 'alert_generated', 'audit_logged'] },
    related: { alerts: 2, policies: ['pii-detect-v2'], actions: ['redact', 'alert', 'audit_log'] },
  },
  n7: {
    ts: '09:14:05.564 UTC', dur: '< 1ms', type: 'response_generated',
    agent: 'FinanceAssistant-v2', session: 'sess_01HZ4bQxk1',
    user: 'output',
    content: { kind: 'output', text: 'Here is the Q1 2024 summary for the top 50 enterprise accounts:\n\nTotal portfolio value: $[REDACTED]\nAccounts reviewed: 50\nAnomalies detected: 3\n\nAccount details have been redacted per data protection policy pii-detect-v2. Contact your data administrator for full access.', redactions: 4, tokens: 312 },
    risk: { score: 18, level: 'Low', flags: ['data_redacted'] },
    related: { alerts: 0, policies: ['pii-detect-v2', 'output-validation-v1'], actions: [] },
  },
}

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

function LineageGraph({ selectedId, onSelect }) {
  const [hoveredId, setHoveredId] = useState(null)

  // Hover → dim non-connected nodes (investigation mode)
  // Selection → highlight edges only; never dim the whole graph
  const hoverEdges    = hoveredId  ? (NODE_EDGES[hoveredId]  ?? []) : []
  const selectedEdges = selectedId ? (NODE_EDGES[selectedId] ?? []) : []
  // Which edges to highlight: hover takes precedence over selection
  const activeEdges   = hoveredId ? hoverEdges : selectedEdges

  // A node is dimmed only while hovering, never just from a click
  const isDimmed = (node) => {
    if (!hoveredId) return false
    if (node.id === hoveredId) return false
    return !hoverEdges.some(eid => {
      const e = EDGES.find(x => x.id === eid)
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

          {EDGES.map(edge => {
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
        {NODES.map(node => (
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

function NodeDetailPanel({ nodeId }) {
  const node   = NODES.find(n => n.id === nodeId)
  const detail = nodeId ? NODE_DETAIL[nodeId] : null
  const cfg    = node ? (NODE_CFG[node.type] ?? NODE_CFG.prompt) : null
  const Icon   = cfg?.icon

  if (!node || !detail) {
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

        {/* Event metadata */}
        <div className="px-4 py-3">
          <SectionLabel>Event</SectionLabel>
          <div className="mt-2 divide-y divide-gray-50 border border-gray-100 rounded-lg overflow-hidden">
            {[
              { k: 'Type',      v: detail.type.replace(/_/g, ' '), mono: false },
              { k: 'Timestamp', v: detail.ts,                       mono: true  },
              { k: 'Duration',  v: detail.dur,                      mono: true  },
              { k: 'Agent',     v: detail.agent,                    mono: false },
              { k: 'Session',   v: detail.session.slice(0, 18) + '…', mono: true },
            ].map(({ k, v, mono }) => (
              <div key={k} className="flex items-center justify-between px-2.5 py-1.5 bg-white">
                <span className="text-[9.5px] font-bold uppercase tracking-wide text-gray-400 shrink-0 w-16">{k}</span>
                <span className={cn(
                  'text-[11px] text-gray-800 font-medium truncate ml-2 text-right',
                  mono && 'font-mono',
                )}>{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Content / data section — varies by type */}
        <div className="px-4 py-3">
          {detail.content.kind === 'prompt' && (
            <>
              <SectionLabel>Prompt Content</SectionLabel>
              <div className="mt-2 bg-gray-50 rounded-lg border border-gray-100 px-3 py-2.5">
                <p className="text-[12px] text-gray-700 leading-relaxed italic">{detail.content.text}</p>
                <p className="text-[10px] text-gray-400 mt-1.5 tabular-nums">{detail.content.tokens} tokens</p>
              </div>
            </>
          )}

          {detail.content.kind === 'context' && (
            <>
              <SectionLabel>Session Context</SectionLabel>
              <div className="mt-2 space-y-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-gray-500">Prior turns</span>
                  <span className="font-medium text-gray-800 tabular-nums">{detail.content.turns}</span>
                </div>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-gray-500">Context size</span>
                  <span className="font-medium text-gray-800">{detail.content.size}</span>
                </div>
                <div className="bg-gray-50 rounded-lg border border-gray-100 px-3 py-2 mt-2">
                  <p className="text-[11px] text-gray-600 leading-relaxed">{detail.content.summary}</p>
                </div>
              </div>
            </>
          )}

          {detail.content.kind === 'rag' && (
            <>
              <SectionLabel>Retrieved Document</SectionLabel>
              <div className="mt-2 space-y-2">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-gray-700">
                  <FileText size={11} className="text-cyan-500 shrink-0" strokeWidth={1.75} />
                  {detail.content.document}
                </div>
                <div className="flex items-center gap-4 text-[10px] text-gray-400">
                  <span>{detail.content.chunks} chunks</span>
                  <span>{detail.content.tokens} tokens</span>
                  <span>sim {detail.content.similarity}</span>
                </div>
                <div className="bg-gray-950 rounded-lg border border-gray-800 px-3 py-2.5">
                  <p className="text-[11px] font-mono text-gray-300 leading-relaxed break-all">
                    {detail.content.excerpt.split(/(\[\w+\]|\d{3}-\d{2}-\d{4}|\d{9}|\$[\d,]+)/).map((part, i) =>
                      /\d{3}-\d{2}-\d{4}|\d{9}|\$[\d,]+/.test(part)
                        ? <span key={i} className="bg-red-900/60 text-red-300 rounded px-0.5">{part}</span>
                        : <span key={i}>{part}</span>
                    )}
                  </p>
                </div>
              </div>
            </>
          )}

          {detail.content.kind === 'model' && (
            <>
              <SectionLabel>Model Invocation</SectionLabel>
              <div className="mt-2 space-y-1.5">
                {[
                  { k: 'Model', v: detail.content.model },
                  { k: 'Temperature', v: String(detail.content.temperature) },
                  { k: 'Prompt tokens', v: detail.content.promptTokens.toLocaleString() },
                  { k: 'Completion tokens', v: detail.content.completionTokens.toLocaleString() },
                  { k: 'Total tokens', v: detail.content.totalTokens.toLocaleString() },
                ].map(({ k, v }) => (
                  <div key={k} className="flex items-center justify-between text-[11px]">
                    <span className="text-gray-500">{k}</span>
                    <span className="font-medium text-gray-800 font-mono">{v}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {detail.content.kind === 'tool' && (
            <>
              <SectionLabel>Tool Call</SectionLabel>
              <div className="mt-2 space-y-2">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-gray-700">
                  <Wrench size={11} className="text-indigo-500 shrink-0" strokeWidth={1.75} />
                  {detail.content.tool}
                </div>
                <div className="flex items-center gap-4 text-[10px] text-gray-400">
                  <span>{detail.content.rows} rows</span>
                  <span>{detail.content.bytes}</span>
                </div>
                <div className="bg-gray-950 rounded-lg border border-gray-800 px-3 py-2.5">
                  <pre className="text-[11px] font-mono text-indigo-300 leading-relaxed whitespace-pre-wrap break-all">{detail.content.query}</pre>
                </div>
              </div>
            </>
          )}

          {detail.content.kind === 'policy' && (
            <>
              <SectionLabel>Policy Evaluation</SectionLabel>
              <div className="mt-2 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-[11px] font-medium text-gray-700">
                    <Shield size={11} className="text-amber-500 shrink-0" strokeWidth={1.75} />
                    {detail.content.policy}
                  </div>
                  <span className="text-[10px] font-bold bg-red-50 text-red-600 border border-red-200 px-1.5 py-0.5 rounded-md">
                    TRIGGERED
                  </span>
                </div>
                <div className="text-[11px] text-gray-500">
                  Action: <span className="font-semibold text-amber-700">{detail.content.action.replace(/_/g,' ')}</span>
                  <span className="ml-2 text-gray-400">· {detail.content.redacted} fields redacted</span>
                </div>
                <div className="space-y-1">
                  {detail.content.findings.map((f, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-[10.5px] text-gray-600 bg-amber-50/60 rounded-md px-2.5 py-1.5 border border-amber-100">
                      <AlertTriangle size={9} className="text-amber-500 shrink-0 mt-0.5" strokeWidth={2} />
                      <span>{f}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {detail.content.kind === 'output' && (
            <>
              <SectionLabel>Response</SectionLabel>
              <div className="mt-2 space-y-1.5">
                <div className="flex items-center gap-4 text-[10px] text-gray-400">
                  <span>{detail.content.tokens} tokens</span>
                  <span className="text-red-500 font-medium">{detail.content.redactions} redactions</span>
                </div>
                <div className="bg-gray-50 rounded-lg border border-gray-100 px-3 py-2.5">
                  <pre className="text-[11px] text-gray-700 leading-relaxed whitespace-pre-wrap font-sans break-words">
                    {detail.content.text.split('[REDACTED]').map((part, i, arr) => (
                      <span key={i}>
                        {part}
                        {i < arr.length - 1 && (
                          <span className="inline-flex items-center bg-red-100 text-red-600 border border-red-200 rounded px-1 text-[9px] font-bold mx-0.5">
                            [REDACTED]
                          </span>
                        )}
                      </span>
                    ))}
                  </pre>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Risk analysis */}
        <div className="px-4 py-3">
          <SectionLabel>Risk Analysis</SectionLabel>
          <div className="mt-2 space-y-2.5">
            {/* Score bar */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-gray-500">Risk score</span>
                <span className={cn(
                  'text-[12px] font-bold tabular-nums',
                  detail.risk.score >= 80 ? 'text-red-600' : detail.risk.score >= 50 ? 'text-orange-500' : detail.risk.score >= 25 ? 'text-yellow-600' : 'text-emerald-600',
                )}>
                  {detail.risk.score}
                </span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all duration-500',
                    detail.risk.score >= 80 ? 'bg-red-500' : detail.risk.score >= 50 ? 'bg-orange-400' : detail.risk.score >= 25 ? 'bg-yellow-400' : 'bg-emerald-400',
                  )}
                  style={{ width: `${detail.risk.score}%` }}
                />
              </div>
            </div>

            {/* Flags */}
            {detail.risk.flags.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {detail.risk.flags.map(f => <Flag key={f} label={f} />)}
              </div>
            ) : (
              <p className="text-[11px] text-gray-400 italic">No risk flags detected</p>
            )}
          </div>
        </div>

        {/* Related elements */}
        <div className="px-4 py-3">
          <SectionLabel>Related</SectionLabel>
          <div className="mt-2 space-y-1.5">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-gray-500 flex items-center gap-1.5"><AlertCircle size={10} strokeWidth={2} /> Linked alerts</span>
              <span className={cn('font-semibold tabular-nums', detail.related.alerts > 0 ? 'text-red-600' : 'text-gray-400')}>
                {detail.related.alerts}
              </span>
            </div>
            {detail.related.policies.length > 0 && (
              <div className="text-[11px]">
                <span className="text-gray-500 flex items-center gap-1.5 mb-1.5">
                  <Shield size={10} strokeWidth={2} /> Policies evaluated
                </span>
                <div className="flex flex-wrap gap-1">
                  {detail.related.policies.map(p => (
                    <span key={p} className="inline-flex items-center gap-1 text-[10px] bg-gray-100 text-gray-600 border border-gray-200 rounded-md px-1.5 py-0.5 font-medium">
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {detail.related.actions.length > 0 && (
              <div className="text-[11px]">
                <span className="text-gray-500 flex items-center gap-1.5 mb-1.5">
                  <Zap size={10} strokeWidth={2} /> Actions taken
                </span>
                <div className="flex flex-wrap gap-1">
                  {detail.related.actions.map(a => (
                    <span key={a} className="inline-flex items-center gap-1 text-[10px] bg-amber-50 text-amber-700 border border-amber-200 rounded-md px-1.5 py-0.5 font-medium">
                      {a.replace(/_/g,' ')}
                    </span>
                  ))}
                </div>
              </div>
            )}
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

function TraceTimeline({ selectedId, onSelect }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="h-10 px-4 flex items-center justify-between border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2">
          <Clock size={13} className="text-gray-400" strokeWidth={1.75} />
          <span className="text-[12px] font-semibold text-gray-700">Trace Timeline</span>
          <span className="text-[10px] text-gray-400 font-mono ml-1">09:14:03.002 – 09:14:05.564 UTC</span>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-gray-400">
          <span className="font-mono tabular-nums font-medium text-gray-600">2,562ms total</span>
          <span className="text-gray-200">·</span>
          <span>7 events</span>
          <span className="text-gray-200">·</span>
          <span className="text-[9.5px] italic text-gray-400">connector width ∝ log(duration)</span>
        </div>
      </div>

      {/* Steps */}
      <div className="px-5 py-4 overflow-x-auto">
        <div className="flex items-start gap-0 min-w-max">
          {TIMELINE.map((step, idx) => {
            const scfg     = STEP_CFG[step.status] ?? STEP_CFG.ok
            const isSelected = step.id === selectedId
            const isLast = idx === TIMELINE.length - 1
            const cw = connectorWidth(step.gapMs)

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

function Breadcrumb({ nodeId }) {
  const path = NODE_PATH[nodeId] ?? []
  return (
    <div className="flex items-center gap-1 text-[10.5px] text-gray-400 flex-wrap">
      {path.map((label, i) => (
        <span key={label} className="flex items-center gap-1">
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

export default function Lineage() {
  const [selectedId,    setSelectedId]    = useState('n1')
  const [sessionOpen,   setSessionOpen]   = useState(false)
  const [activeSession, setActiveSession] = useState(SESSIONS[0])

  // ── Context banner from query params (set by ActionPanel navigation) ──────
  const location        = useLocation()
  const _params         = new URLSearchParams(location.search)
  const ctxAsset        = _params.get('asset')
  const ctxFindingId    = _params.get('finding_id')
  const [bannerVisible, setBannerVisible] = useState(!!(ctxAsset || ctxFindingId))

  const handleSelect = (id) => setSelectedId(id)

  const riskyCt    = NODES.filter(n => n.flagged).length
  const flaggedEdge = EDGES.filter(e => e.type === 'sensitive').length

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

      {/* ── KPI strip ── */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="Trace Nodes"       value={NODES.length}     sub="In this session"         accentClass="border-l-blue-500"    />
        <KpiCard label="Flagged Nodes"     value={riskyCt}          sub="Risk flags raised"        accentClass="border-l-red-500"     />
        <KpiCard label="Sensitive Flows"   value={flaggedEdge}       sub="PII / sensitive data"    accentClass="border-l-amber-500"   />
        <KpiCard label="Policies Triggered" value={1}               sub="pii-detect-v2"           accentClass="border-l-orange-500"  />
      </div>

      {/* ── Session selector ── */}
      <SessionSelector
        selected={activeSession}
        onSelect={setActiveSession}
        open={sessionOpen}
        setOpen={setSessionOpen}
      />

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
              <Breadcrumb nodeId={selectedId} />
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
            <LineageGraph selectedId={selectedId} onSelect={handleSelect} />
          </div>

          {/* Graph footer — edge type + node selection stats */}
          <div className="px-4 py-2 border-t border-gray-100 bg-gray-50/50 shrink-0 flex items-center gap-3">
            <div className="flex items-center gap-3 text-[10px] text-gray-400">
              {NODES.map(n => {
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
          <NodeDetailPanel nodeId={selectedId} />
        </div>
      </div>

      {/* ── Timeline ── */}
      <TraceTimeline selectedId={selectedId} onSelect={handleSelect} />

    </PageContainer>
  )
}
