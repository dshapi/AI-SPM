import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Search, Pause, Play, Download,
  Cpu, Wrench,
  Shield, ShieldOff,
  MessageSquare, Zap, AlertTriangle, CheckCircle2,
  Clock,
  Terminal, Lock, ArrowUpRight,
  Bell, UserX, Key,
  Activity, AlertCircle, X,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { fetchAllSessions, fetchSessionEvents } from '../../api/simulationApi.js'
import { useSessionSocket } from '../../hooks/useSessionSocket.js'

// ── Design tokens ──────────────────────────────────────────────────────────────

const RISK_VARIANT   = { Critical: 'critical', High: 'high', Medium: 'medium', Low: 'low' }
const RISK_SCORE_BG  = { Critical: 'bg-red-500', High: 'bg-orange-500', Medium: 'bg-yellow-400', Low: 'bg-emerald-500' }
const RISK_SCORE_TXT = { Critical: 'text-white',  High: 'text-white',    Medium: 'text-gray-800', Low: 'text-white'     }
const RISK_STRIP     = { Critical: 'bg-red-500',  High: 'bg-orange-500', Medium: 'bg-yellow-400', Low: 'bg-emerald-500' }
const RISK_HEADER_BG = {
  Critical: 'bg-red-50/70 border-b-red-100',
  High:     'bg-orange-50/70 border-b-orange-100',
  Medium:   'bg-yellow-50/70 border-b-yellow-100',
  Low:      'bg-emerald-50/70 border-b-emerald-100',
}

const STATUS_COLOR = {
  Active:    { dot: 'bg-emerald-400 animate-pulse', text: 'text-emerald-600' },
  Blocked:   { dot: 'bg-red-500',                   text: 'text-red-600'     },
  Completed: { dot: 'bg-gray-300',                  text: 'text-gray-400'    },
}

// Event type config — left-border accent is the primary readability signal
const EVENT_CFG = {
  prompt:  { icon: MessageSquare, iconBg: 'bg-gray-100',    iconTxt: 'text-gray-500',    border: 'border-l-gray-300',    rowBg: '',                   label: 'Prompt',  badge: 'neutral'  },
  model:   { icon: Cpu,           iconBg: 'bg-violet-50',   iconTxt: 'text-violet-600',  border: 'border-l-violet-400',  rowBg: '',                   label: 'Model',   badge: 'info'     },
  tool:    { icon: Wrench,        iconBg: 'bg-blue-50',     iconTxt: 'text-blue-600',    border: 'border-l-blue-400',    rowBg: '',                   label: 'Tool',    badge: 'info'     },
  policy:  { icon: Shield,        iconBg: 'bg-amber-50',    iconTxt: 'text-amber-600',   border: 'border-l-amber-400',   rowBg: 'bg-amber-50/30',     label: 'Policy',  badge: 'medium'   },
  blocked: { icon: ShieldOff,     iconBg: 'bg-red-50',      iconTxt: 'text-red-600',     border: 'border-l-red-500',     rowBg: 'bg-red-50/40',       label: 'Blocked', badge: 'critical' },
  success: { icon: CheckCircle2,  iconBg: 'bg-emerald-50',  iconTxt: 'text-emerald-600', border: 'border-l-emerald-400', rowBg: '',                   label: 'Success', badge: 'success'  },
}

const DECISION_CFG = {
  allow:    { label: 'Allowed',   cls: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
  block:    { label: 'Blocked',   cls: 'text-red-700     bg-red-50     border-red-200'     },
  escalate: { label: 'Escalated', cls: 'text-amber-700   bg-amber-50   border-amber-200'   },
}

// ── Agent IDs to poll ─────────────────────────────────────────────────────────

const KNOWN_AGENTS = [
  'FinanceAssistant-v2', 'CustomerSupport-GPT', 'ThreatHunter-AI',
  'DataPipeline-Orchestrator', 'HR-Assistant-Pro',
]

// ── Adapter: backend session → UI session shape ───────────────────────────────

const RISK_TIER_MAP = {
  minimal:      'Low',
  limited:      'Medium',
  high:         'High',
  unacceptable: 'Critical',
}

const STATUS_MAP = {
  started:   'Active',
  blocked:   'Blocked',
  completed: 'Completed',
  failed:    'Completed',
}

function _relativeTime(isoString) {
  if (!isoString) return '—'
  const normalized = (typeof isoString === 'string' && !isoString.endsWith('Z') && !isoString.includes('+')) ? isoString + 'Z' : isoString
  const diffMs = Date.now() - new Date(normalized).getTime()
  const s = Math.floor(diffMs / 1000)
  if (s < 60)  return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60)  return `${m}m ago`
  return `${Math.floor(m / 60)}h ago`
}

function _adaptSession(s) {
  const riskTier = RISK_TIER_MAP[s.risk_tier] ?? 'Medium'
  const riskScore = Math.round((s.risk_score ?? 0) * 100)
  return {
    id:           s.session_id,
    agent:        s.agent_id,
    agentType:    'Agent',
    risk:         riskTier,
    riskScore,
    status:       STATUS_MAP[s.status] ?? 'Active',
    lastActivity: _relativeTime(s.created_at),
    eventsCount:  0,
    environment:  'Production',
    duration:     '—',
    currentState: STATUS_MAP[s.status] ?? s.status,
    lastDecision: {
      action: s.policy_decision ?? 'allow',
      policy: '—',
      reason: '—',
    },
    lastPrompt:   null,
    lastToolCall: null,
  }
}

// ── Adapter: WsEvent / REST event → EventRow shape ───────────────────────────

function _eventType(eventType, payload) {
  if (!eventType) return 'prompt'
  if (eventType.startsWith('prompt.'))   return 'prompt'
  if (eventType.startsWith('risk.'))     return 'model'
  if (eventType.startsWith('tool.'))     return 'tool'
  if (eventType === 'session.completed') return 'success'
  if (eventType === 'session.blocked')   return 'blocked'
  if (eventType.startsWith('session.'))  return 'success'
  if (eventType.startsWith('policy.')) {
    const dec = (payload?.decision ?? '').toLowerCase()
    return dec === 'block' ? 'blocked' : 'policy'
  }
  return 'prompt'
}

function _eventTitle(eventType) {
  const titles = {
    'prompt.received':   'Prompt received',
    'risk.calculated':   'Risk scored',
    'policy.decision':   'Policy evaluated',
    'policy.evaluated':  'Policy evaluated',
    'policy.enforced':   'Policy enforced',
    'tool.request':      'Tool call requested',
    'tool.observation':  'Tool call executed',
    'session.created':   'Session started',
    'session.completed': 'Session completed',
    'session.blocked':   'Session blocked',
    'final.response':    'Response generated',
    'memory.request':    'Memory read',
    'memory.result':     'Memory returned',
  }
  return titles[eventType] ?? eventType
}

function _eventDescription(event) {
  const p = event.payload ?? event
  if (p.summary)       return p.summary
  if (p.reason)        return p.reason
  if (p.decision)      return `Decision: ${p.decision}`
  if (p.tool_name)     return `Tool: ${p.tool_name}`
  if (p.score != null) return `Risk score: ${Math.round(p.score * 100)}`
  return event.event_type ?? '—'
}

function _formatTs(isoOrTs) {
  if (!isoOrTs) return '—'
  if (/^\d{2}:\d{2}:\d{2}$/.test(isoOrTs)) return isoOrTs
  // Server returns naive UTC datetimes without 'Z'; append it so JS parses as UTC
  const normalized = (typeof isoOrTs === 'string' && !isoOrTs.endsWith('Z') && !isoOrTs.includes('+')) ? isoOrTs + 'Z' : isoOrTs
  const d = new Date(normalized)
  if (isNaN(d)) return isoOrTs
  return d.toLocaleTimeString('en-US', { timeZone: 'Asia/Jerusalem', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

let _uid = 0
function _adaptEvent(raw, sessionId) {
  // Handles both WsEvent shape ({ event_type, source_service, timestamp, payload })
  // and REST events shape ({ event_type, summary, timestamp, payload }).
  // source_service is present in WsEvents; REST events may omit it → falls back to '—'.
  // Neither shape has agent_id — do not attempt raw.agent_id.
  const eventType = raw.event_type ?? raw.type
  const payload   = raw.payload ?? {}

  // User identity — present on prompt.received events (backfilled for older ones too)
  const userEmail = payload.user_email ?? null
  const userName  = payload.user_name  ?? payload.user_id ?? null

  return {
    id:          ++_uid,
    type:        _eventType(eventType, payload),
    session:     raw.session_id ?? sessionId,
    agent:       raw.source_service ?? '—',
    title:       _eventTitle(eventType),
    description: _eventDescription(raw),
    tool:        payload.tool_name ?? null,
    userEmail,
    userName,
    ts:          _formatTs(raw.timestamp),
  }
}

// ── Enrich selected session with derived fields from raw events ───────────────

function _enrichSession(session, rawEvents) {
  if (!session || rawEvents.length === 0) return session

  const lastPolicy = [...rawEvents].reverse().find(e =>
    (e.event_type ?? '').startsWith('policy.')
  )
  const lastPrompt = [...rawEvents].reverse().find(e =>
    (e.event_type ?? '').startsWith('prompt.')
  )
  const lastTool = [...rawEvents].reverse().find(e =>
    (e.event_type ?? '').startsWith('tool.')
  )
  const lastRisk = [...rawEvents].reverse().find(e =>
    (e.event_type ?? '').startsWith('risk.')
  )

  const riskScore = lastRisk?.payload?.score != null
    ? Math.round(lastRisk.payload.score * 100)
    : session.riskScore

  const riskTier = lastRisk?.payload?.tier
    ? (RISK_TIER_MAP[lastRisk.payload.tier] ?? session.risk)
    : session.risk

  const policyPayload = lastPolicy?.payload ?? {}
  const policyDec     = (policyPayload.decision ?? session.lastDecision.action).toLowerCase()

  return {
    ...session,
    eventsCount:  rawEvents.length,
    riskScore,
    risk:         riskTier,
    lastDecision: {
      action: policyDec,
      policy: policyPayload.policy_version ?? policyPayload.policy ?? session.lastDecision.policy,
      reason: policyPayload.reason ?? session.lastDecision.reason,
    },
    lastPrompt:   lastPrompt?.payload?.text ?? lastPrompt?.payload?.prompt ?? null,
    lastToolCall: lastTool
      ? `${lastTool.payload?.tool_name ?? ''}${lastTool.payload?.tool_args ? ': ' + JSON.stringify(lastTool.payload.tool_args) : ''}`
      : null,
  }
}

// ── KPI strip ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, accentClass, dim }) {
  return (
    <div className={cn(
      'bg-white rounded-xl border border-gray-200 border-l-[3px] px-4 py-3 flex items-center gap-3',
      accentClass,
    )}>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.08em] leading-none mb-1.5">{label}</p>
        <p className={cn('text-[22px] font-bold leading-none tabular-nums', dim ? 'text-gray-400' : 'text-gray-900')}>{value}</p>
        {sub && <p className="text-[10px] text-gray-400 mt-1 leading-none">{sub}</p>}
      </div>
    </div>
  )
}

// ── Session list ───────────────────────────────────────────────────────────────

function SessionList({ sessions, selectedId, onSelect, filter }) {
  const filtered = sessions.filter(s => {
    const q = filter.search.toLowerCase()
    if (q && !s.agent.toLowerCase().includes(q) && !s.id.toLowerCase().includes(q)) return false
    if (filter.risk   !== 'All' && s.risk   !== filter.risk)   return false
    if (filter.status !== 'All' && s.status !== filter.status) return false
    return true
  })

  if (filtered.length === 0) return (
    <p className="text-xs text-gray-400 text-center py-8">No sessions match filters</p>
  )

  return (
    <div className="flex flex-col divide-y divide-gray-100">
      {filtered.map(s => {
        const isSelected = s.id === selectedId
        const st = STATUS_COLOR[s.status]
        return (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              'w-full text-left px-3 py-2.5 transition-colors duration-100',
              'border-l-[3px]',
              isSelected
                ? 'bg-blue-50/70 border-l-blue-500'
                : 'bg-white border-l-transparent hover:bg-gray-50/80 hover:border-l-gray-300',
            )}
          >
            {/* Agent + score */}
            <div className="flex items-center justify-between gap-2 mb-0.5">
              <span className={cn(
                'text-[12px] font-semibold truncate leading-snug',
                isSelected ? 'text-blue-700' : 'text-gray-800',
              )}>
                {s.agent}
              </span>
              <span className={cn(
                'text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 tabular-nums leading-none',
                RISK_SCORE_BG[s.risk],
                RISK_SCORE_TXT[s.risk],
              )}>
                {s.riskScore}
              </span>
            </div>

            {/* Session ID */}
            <p className="text-[10px] text-gray-400 font-mono truncate leading-none mb-1.5">{s.id}</p>

            {/* Status + recency */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', st.dot)} />
                <span className={cn('text-[11px] font-medium', st.text)}>{s.status}</span>
              </div>
              <span className="text-[10px] text-gray-400 flex items-center gap-1 tabular-nums">
                <Clock size={9} strokeWidth={1.75} />
                {s.lastActivity}
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ── Event row ──────────────────────────────────────────────────────────────────

function EventRow({ event, isNew }) {
  const cfg  = EVENT_CFG[event.type] ?? EVENT_CFG.prompt
  const Icon = cfg.icon

  return (
    <div className={cn(
      'flex items-start gap-3 px-3 py-2 border-l-[3px] transition-colors duration-200',
      cfg.border,
      isNew ? 'bg-blue-50/50' : (cfg.rowBg || 'bg-white hover:bg-gray-50/60'),
    )}>
      {/* Type icon */}
      <div className={cn('w-6 h-6 rounded flex items-center justify-center shrink-0 mt-px', cfg.iconBg)}>
        <Icon size={12} className={cfg.iconTxt} strokeWidth={2} />
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-px">
          <span className="text-[12px] font-semibold text-gray-900 leading-snug truncate">{event.title}</span>
          <Badge variant={cfg.badge} className="text-[9px] py-0 px-1.5 shrink-0 leading-[1.7]">{cfg.label}</Badge>
        </div>
        <p className="text-[11px] text-gray-500 leading-snug line-clamp-1">{event.description}</p>
        {/* Meta row */}
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] text-gray-400 font-mono truncate">{event.agent}</span>
          {event.tool && (
            <span className="text-[10px] text-blue-500/80 font-mono truncate">{event.tool}</span>
          )}
          {(event.userName || event.userEmail) && (
            <span className="text-[10px] text-blue-500/80 font-mono truncate">
              User details : {[event.userName, event.userEmail].filter(Boolean).join(', ')}
            </span>
          )}
        </div>
      </div>

      {/* Timestamp — fixed width, always right-aligned */}
      <span className="w-14 shrink-0 text-right text-[10px] text-gray-400 font-mono tabular-nums mt-px">
        {event.ts}
      </span>
    </div>
  )
}

// ── Control / decision panel ───────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 leading-none">
      {children}
    </p>
  )
}

// ── Escalate confirm modal ─────────────────────────────────────────────────────

function EscalateConfirmModal({ open, onConfirm, onCancel, loading }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-[2px]"
        onClick={onCancel}
      />
      {/* Dialog */}
      <div className="relative z-10 bg-white rounded-xl shadow-xl border border-gray-200 w-[340px] p-5">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-9 h-9 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-center shrink-0">
            <AlertCircle size={16} className="text-amber-600" strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-gray-900">Escalate Session to Case</p>
            <p className="text-[12px] text-gray-500 mt-0.5 leading-relaxed">
              Are you sure you want to escalate this session for investigation?
            </p>
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          <Button
            variant="outline"
            size="sm"
            className="text-[12px] h-8 px-3"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            className="text-[12px] h-8 px-3 bg-amber-600 hover:bg-amber-700 text-white border-0"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? 'Escalating…' : 'Yes, Escalate'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── Toast ──────────────────────────────────────────────────────────────────────

function Toast({ message, variant = 'success', onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 4000)
    return () => clearTimeout(t)
  }, [onDismiss])

  const styles = variant === 'error'
    ? 'bg-red-600 border-red-700'
    : 'bg-emerald-600 border-emerald-700'

  return (
    <div className={cn(
      'fixed bottom-5 right-5 z-50 flex items-center gap-3 px-4 py-3',
      'rounded-xl border shadow-lg text-white text-[12px] font-medium',
      styles,
    )}>
      {variant === 'error'
        ? <AlertCircle size={14} strokeWidth={2} />
        : <CheckCircle2 size={14} strokeWidth={2} />}
      {message}
      <button onClick={onDismiss} className="ml-1 opacity-70 hover:opacity-100">
        <X size={13} />
      </button>
    </div>
  )
}

// ── ControlPanel ───────────────────────────────────────────────────────────────

function ControlPanel({ session }) {
  const [showConfirm, setShowConfirm]   = useState(false)
  const [escalating,  setEscalating]    = useState(false)
  const [toast,       setToast]         = useState(null)   // { message, variant }
  const navigate = useNavigate()

  const dismissToast = useCallback(() => setToast(null), [])

  async function handleEscalateConfirm() {
    setEscalating(true)
    try {
      // Resolve base URL — same logic as simulationApi.js: ignore absolute URLs (CORS).
      const base             = import.meta.env.VITE_API_URL || '/api'
      const _rawO            = import.meta.env.VITE_ORCHESTRATOR_URL || ''
      const orchestratorBase = (_rawO && !_rawO.startsWith('http')) ? _rawO : `${base}/v1`

      // Fetch a dev token the same way simulationApi does
      let token = null
      try {
        const r = await fetch(`${base}/dev-token`)
        if (r.ok) token = (await r.json()).token
      } catch { /* unauthenticated fallback */ }

      const headers = { 'Content-Type': 'application/json' }
      if (token) headers.Authorization = `Bearer ${token}`

      const res = await fetch(`${orchestratorBase}/cases`, {
        method:  'POST',
        headers,
        body: JSON.stringify({ session_id: session.id, reason: 'manual_escalation' }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail?.message ?? err?.error ?? `Request failed (${res.status})`)
      }

      const data = await res.json()
      setShowConfirm(false)
      setToast({ message: 'Case created — redirecting…', variant: 'success' })
      setTimeout(() => navigate(`/admin/cases?case_id=${data.case_id}`, { state: { escalatedCase: data } }), 800)
    } catch (err) {
      setShowConfirm(false)
      setToast({ message: err.message || 'Failed to create case', variant: 'error' })
    } finally {
      setEscalating(false)
    }
  }

  if (!session) return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      <div className="w-9 h-9 rounded-xl bg-gray-100 flex items-center justify-center mb-3">
        <Terminal size={16} className="text-gray-400" />
      </div>
      <p className="text-[13px] font-medium text-gray-500">No session selected</p>
      <p className="text-[11px] text-gray-400 mt-1">Select a session to view controls</p>
    </div>
  )

  const dec = DECISION_CFG[session.lastDecision.action] ?? DECISION_CFG.allow
  const st  = STATUS_COLOR[session.status]

  return (
    <div className="flex flex-col h-full">

      {/* ── Panel header — risk-tinted ── */}
      <div className={cn('relative px-4 pt-3.5 pb-3 border-b shrink-0', RISK_HEADER_BG[session.risk])}>
        {/* Top accent strip */}
        <div className={cn('absolute inset-x-0 top-0 h-[3px] rounded-t-xl', RISK_STRIP[session.risk])} />

        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-gray-900 truncate leading-snug">{session.agent}</p>
            <p className="text-[10px] text-gray-400 font-mono mt-0.5 truncate">{session.id}</p>
          </div>
          <Badge variant={RISK_VARIANT[session.risk]} className="shrink-0">{session.risk}</Badge>
        </div>

        {/* State row */}
        <div className="flex items-center gap-1.5 mb-1">
          <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', st.dot)} />
          <span className="text-[11px] text-gray-600 leading-none">{session.currentState}</span>
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-gray-400 flex items-center gap-1">
            <Clock size={9} strokeWidth={1.75} />{session.duration}
          </span>
          <span className="text-[10px] text-gray-400">{session.eventsCount} events</span>
          <span className="text-[10px] text-gray-400">{session.environment}</span>
        </div>
      </div>

      {/* ── Scrollable body ── */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100">

        {/* Last Decision */}
        <div className="px-4 py-3 space-y-2">
          <SectionLabel>Last Decision</SectionLabel>
          <div className={cn('rounded-lg border px-3 py-2 text-[11px] font-semibold', dec.cls)}>
            {dec.label} — {session.lastDecision.policy}
          </div>
          <p className="text-[11px] text-gray-500 leading-snug">{session.lastDecision.reason}</p>
        </div>

        {/* Last Prompt */}
        <div className="px-4 py-3 space-y-2">
          <SectionLabel>Last Prompt</SectionLabel>
          <div className="bg-gray-50 rounded-lg border border-gray-200 px-3 py-2">
            <p className="text-[11px] text-gray-700 font-mono leading-relaxed line-clamp-3 break-all">
              {session.lastPrompt}
            </p>
          </div>
        </div>

        {/* Last Tool Call */}
        {session.lastToolCall && (
          <div className="px-4 py-3 space-y-2">
            <SectionLabel>Last Tool Call</SectionLabel>
            <div className="bg-gray-900 rounded-lg px-3 py-2">
              <p className="text-[11px] text-emerald-400 font-mono leading-relaxed line-clamp-3 break-all">
                {session.lastToolCall}
              </p>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="px-4 py-3 space-y-2">
          <SectionLabel>Actions</SectionLabel>
          <div className="flex flex-col gap-1.5">
            <Button variant="destructive" size="sm"
              className="w-full justify-start gap-2 text-[12px] h-8">
              <Lock size={11} strokeWidth={2} /> Kill Session
            </Button>
            <Button variant="outline" size="sm"
              className="w-full justify-start gap-2 text-[12px] h-8 text-orange-600 border-orange-200 hover:bg-orange-50">
              <UserX size={11} strokeWidth={2} /> Block Agent
            </Button>
            <Button variant="outline" size="sm"
              className="w-full justify-start gap-2 text-[12px] h-8">
              <Key size={11} strokeWidth={2} /> Revoke Tool Access
            </Button>
            <Button variant="outline" size="sm"
              className="w-full justify-start gap-2 text-[12px] h-8 text-amber-700 border-amber-200 hover:bg-amber-50"
              onClick={() => setShowConfirm(true)}>
              <Bell size={11} strokeWidth={2} /> Escalate to Case
            </Button>
            <EscalateConfirmModal
              open={showConfirm}
              loading={escalating}
              onConfirm={handleEscalateConfirm}
              onCancel={() => setShowConfirm(false)}
            />
            {toast && (
              <Toast
                message={toast.message}
                variant={toast.variant}
                onDismiss={dismissToast}
              />
            )}
            <Button variant="outline" size="sm"
              className="w-full justify-start gap-2 text-[12px] h-8">
              <ArrowUpRight size={11} strokeWidth={2} /> Open Lineage
            </Button>
          </div>
        </div>

      </div>
    </div>
  )
}

// ── Panel chrome ───────────────────────────────────────────────────────────────

function Panel({ title, icon: Icon, right, children, className }) {
  return (
    <div className={cn(
      'bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden',
      className,
    )}>
      <div className="h-10 px-3 flex items-center justify-between border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2">
          {Icon && <Icon size={13} className="text-gray-400" strokeWidth={1.75} />}
          <span className="text-[12px] font-semibold text-gray-700">{title}</span>
        </div>
        {right && <div className="flex items-center gap-2">{right}</div>}
      </div>
      <div className="flex-1 overflow-hidden flex flex-col">{children}</div>
    </div>
  )
}

// ── Filter select ──────────────────────────────────────────────────────────────

function Sel({ value, onChange, options, className }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className={cn(
        'h-8 rounded-lg border border-gray-200 bg-white pl-2.5 pr-6 text-[12px] text-gray-700',
        'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 cursor-pointer',
        className,
      )}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

// ── Runtime page ───────────────────────────────────────────────────────────────

export default function Runtime() {
  const location = useLocation()
  const sessionIdFromUrl = new URLSearchParams(location.search).get('session_id')
  const filterFromUrl = new URLSearchParams(location.search).get('filter') // e.g. 'network'

  // ── UI state ───────────────────────────────────────────────────────────────
  const [paused,         setPaused]         = useState(false)
  const [newIds,         setNewIds]         = useState(new Set())
  const [suspiciousOnly, setSuspiciousOnly] = useState(false)
  const [sessionFilter,  setSessionFilter]  = useState({ search: '', risk: 'All', status: 'All' })
  const [streamType,     setStreamType]     = useState(filterFromUrl === 'network' ? 'tool' : 'All')
  const [networkBanner,  setNetworkBanner]  = useState(filterFromUrl === 'network')

  // ── Sessions list state ────────────────────────────────────────────────────
  const [sessions,        setSessions]        = useState([])
  const [selectedId,      setSelectedId]      = useState(null)
  const [sessionsLoading, setSessionsLoading] = useState(true)

  // ── Per-session event state ────────────────────────────────────────────────
  const [events,   setEvents]   = useState([])
  const [wsStatus, setWsStatus] = useState('idle')

  // ── WebSocket hook ─────────────────────────────────────────────────────────
  const { connectionStatus, liveEvents, connectWs, disconnectWs } = useSessionSocket()

  const rawEventsRef = useRef([])
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  // ── Load sessions list (poll every 10 s) ──────────────────────────────────
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await fetchAllSessions(KNOWN_AGENTS)
        if (!cancelled) {
          const adapted = data.map(_adaptSession)
          setSessions(adapted)
          setSessionsLoading(false)
          // Auto-select first session on initial load
          setSelectedId(prev => prev ?? adapted[0]?.id ?? null)
        }
      } catch (err) {
        console.error('[Runtime] fetchAllSessions error:', err)
        if (!cancelled) setSessionsLoading(false)
      }
    }
    load()
    const iv = setInterval(load, 10_000)
    return () => { cancelled = true; clearInterval(iv) }
  }, [])

  // ── Auto-select session from URL ?session_id= param (run once only) ────────
  const urlSelectDoneRef = useRef(false)
  useEffect(() => {
    if (!sessionIdFromUrl || sessions.length === 0) return
    if (urlSelectDoneRef.current) return          // already applied — don't override user clicks
    const match = sessions.find(s => s.id === sessionIdFromUrl)
    if (match) {
      setSelectedId(match.id)
      urlSelectDoneRef.current = true
    }
  }, [sessions, sessionIdFromUrl])

  // ── On session select: load history then open WS if active ────────────────
  useEffect(() => {
    if (!selectedId) return
    disconnectWs()
    setEvents([])
    rawEventsRef.current = []
    setWsStatus('idle')
    const session = sessions.find(s => s.id === selectedId)
    async function hydrate() {
      try {
        console.log('[Runtime] hydrate: fetching events for', selectedId)
        const data = await fetchSessionEvents(selectedId)
        console.log('[Runtime] hydrate: got data', data?.event_count, 'events', data?.events?.length)
        if (data?.events) {
          rawEventsRef.current = data.events
          setEvents(data.events.map(e => _adaptEvent(e, selectedId)))
          console.log('[Runtime] hydrate: setEvents called with', data.events.length, 'events')
        } else {
          console.warn('[Runtime] hydrate: data.events is falsy', data)
        }
      } catch (err) {
        console.error('[Runtime] fetchSessionEvents error:', err)
      }
      if (!session || session.status === 'Active') {
        connectWs(selectedId)
      }
    }
    hydrate()
    return () => disconnectWs()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // ── Merge live WS events into events[] ────────────────────────────────────
  // useSessionSocket already deduplicates WS events by event_type.
  // We deduplicate against REST history using adapted-event fields (type+ts)
  // to avoid showing the same pipeline step twice when REST and WS overlap.
  useEffect(() => {
    if (paused || liveEvents.length === 0) return
    const adapted = liveEvents.map(e => _adaptEvent(e, selectedId))
    setEvents(prev => {
      const seen = new Set(prev.map(e => `${e.type}:${e.ts}`))
      const fresh = adapted.filter(e => {
        const key = `${e.type}:${e.ts}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      rawEventsRef.current = [...rawEventsRef.current, ...liveEvents]
      if (fresh.length === 0) return prev
      const merged = [...prev, ...fresh].sort((a, b) => a.ts.localeCompare(b.ts))
      setNewIds(new Set(fresh.map(e => e.id)))
      setTimeout(() => setNewIds(new Set()), 1200)
      return merged.slice(-200)
    })
  }, [liveEvents, paused, selectedId])

  // ── Sync WS connection status ──────────────────────────────────────────────
  useEffect(() => {
    setWsStatus(connectionStatus)
  }, [connectionStatus])

  // ── Derived values ─────────────────────────────────────────────────────────
  const selectedRaw     = sessions.find(s => s.id === selectedId) ?? null
  const selectedSession = selectedRaw
    ? _enrichSession(selectedRaw, rawEventsRef.current)
    : null

  const activeSessions   = sessions.filter(s => s.status === 'Active').length
  const highRiskSessions = sessions.filter(s => s.risk === 'Critical' || s.risk === 'High').length
  const blockedCount     = events.filter(e => e.type === 'blocked').length
  const eventsPerSec     = wsStatus === 'connected' ? '~live' : '—'

  const filteredEvents = events.filter(e => {
    if (suspiciousOnly && e.type !== 'blocked' && e.type !== 'policy') return false
    if (streamType !== 'All' && e.type !== streamType) return false
    return true
  })

  const sessionCount = sessions.filter(s => {
    const q = sessionFilter.search.toLowerCase()
    if (q && !s.agent.toLowerCase().includes(q) && !s.id.toLowerCase().includes(q)) return false
    if (sessionFilter.risk   !== 'All' && s.risk   !== sessionFilter.risk)   return false
    if (sessionFilter.status !== 'All' && s.status !== sessionFilter.status) return false
    return true
  }).length

  return (
    <PageContainer>

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <PageHeader
        title="Runtime"
        subtitle="Monitor live AI execution, tool usage, and security decisions in real time"
        actions={
          <>
            <Button
              variant="outline" size="sm"
              onClick={() => setPaused(p => !p)}
              className={cn('gap-2', paused && 'border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100')}
            >
              {paused
                ? <><Play    size={13} strokeWidth={2} />Resume Stream</>
                : <><Pause   size={13} strokeWidth={2} />Pause Stream</>}
            </Button>
            <Button variant="outline" size="sm" className="gap-2">
              <Download size={13} strokeWidth={2} /> Export Events
            </Button>
          </>
        }
      />

      {/* ── KPI strip ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="Active Sessions"    value={sessionsLoading ? '…' : activeSessions}   sub={`${sessions.length} total`}                                      accentClass="border-l-blue-500"    />
        <KpiCard label="Events / sec"       value={eventsPerSec}                              sub={paused ? 'Paused' : wsStatus === 'connected' ? 'Live' : 'No session'} accentClass={wsStatus === 'connected' && !paused ? 'border-l-emerald-500' : 'border-l-amber-400'} dim={wsStatus !== 'connected'} />
        <KpiCard label="Blocked Actions"    value={blockedCount}                              sub="In current view"                                                  accentClass="border-l-red-500"     />
        <KpiCard label="High Risk Sessions" value={highRiskSessions}                          sub="Critical + High"                                                  accentClass="border-l-orange-500"  />
      </div>

      {/* ── Network filter banner ──────────────────────────────────────── */}
      {networkBanner && (
        <div
          data-testid="network-filter-banner"
          className="flex items-center gap-3 px-4 py-2 bg-orange-50 border border-orange-200
                     rounded-xl text-[12px] text-orange-700 font-medium"
        >
          <Activity size={13} className="text-orange-400 shrink-0" />
          <span className="flex-1">
            Filtered to <strong>network activity</strong> — showing tool-call events only
          </span>
          <button
            onClick={() => { setNetworkBanner(false); setStreamType('All') }}
            className="text-orange-400 hover:text-orange-600 transition-colors"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Filter bar ─────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 px-3 h-11 flex items-center gap-2.5">
        {/* Search */}
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search session or agent…"
            value={sessionFilter.search}
            onChange={e => setSessionFilter(f => ({ ...f, search: e.target.value }))}
            className="w-52 h-8 pl-8 pr-3 rounded-lg border border-gray-200 bg-gray-50 text-[12px] text-gray-700 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 focus:bg-white"
          />
        </div>

        <div className="w-px h-4 bg-gray-200 shrink-0" />

        <Sel value={sessionFilter.risk}   onChange={v => setSessionFilter(f => ({ ...f, risk: v }))}
          options={[{ value:'All',label:'All Risk'},{ value:'Critical',label:'Critical'},{ value:'High',label:'High'},{ value:'Medium',label:'Medium'},{ value:'Low',label:'Low'}]} />

        <Sel value={sessionFilter.status} onChange={v => setSessionFilter(f => ({ ...f, status: v }))}
          options={[{ value:'All',label:'All Status'},{ value:'Active',label:'Active'},{ value:'Blocked',label:'Blocked'},{ value:'Completed',label:'Completed'}]} />

        <div className="w-px h-4 bg-gray-200 shrink-0" />

        <Sel value={streamType} onChange={setStreamType}
          options={[{ value:'All',label:'All Events'},{ value:'prompt',label:'Prompts'},{ value:'model',label:'Model'},{ value:'tool',label:'Tool Calls'},{ value:'policy',label:'Policy'},{ value:'blocked',label:'Blocked'},{ value:'success',label:'Success'}]} />

        <button
          onClick={() => setSuspiciousOnly(p => !p)}
          className={cn(
            'flex items-center gap-1.5 h-8 px-2.5 rounded-lg border text-[12px] font-medium transition-colors shrink-0',
            suspiciousOnly
              ? 'bg-red-50 border-red-200 text-red-600'
              : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50',
          )}
        >
          <AlertTriangle size={11} strokeWidth={2} />
          Suspicious only
        </button>

        {/* Spacer + live indicator */}
        <div className="flex-1" />
        {wsStatus === 'connected' && !paused ? (
          <span className="flex items-center gap-1.5 text-[11px] text-emerald-600 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live
          </span>
        ) : paused ? (
          <span className="flex items-center gap-1.5 text-[11px] text-amber-600 font-medium">
            <Pause size={11} strokeWidth={2} /> Stream paused
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-[11px] text-gray-400 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-gray-300" /> {wsStatus === 'error' ? 'Disconnected' : 'Select session'}
          </span>
        )}
      </div>

      {/* ── 3-column main layout ────────────────────────────────────────────── */}
      <div className="grid grid-cols-12 gap-3" style={{ height: 'calc(100vh - 330px)', minHeight: 500 }}>

        {/* LEFT — Active Sessions (3) */}
        <Panel
          title="Sessions"
          icon={Activity}
          className="col-span-3"
          right={
            <span className="text-[11px] text-gray-400 tabular-nums">{sessionCount}</span>
          }
        >
          <div className="overflow-y-auto flex-1">
            <SessionList
              sessions={sessions}
              selectedId={selectedId}
              onSelect={setSelectedId}
              filter={sessionFilter}
            />
            {sessionsLoading && sessions.length === 0 && (
              <p className="text-xs text-gray-400 text-center py-8">Loading sessions…</p>
            )}
          </div>
        </Panel>

        {/* CENTER — Event Stream (6) */}
        <Panel
          title="Event Stream"
          icon={Zap}
          className="col-span-6"
          right={
            <span className="text-[11px] text-gray-400 tabular-nums">{filteredEvents.length} events</span>
          }
        >
          {filteredEvents.length === 0 ? (
            <div className="flex flex-col items-center justify-center flex-1 py-12">
              <Activity size={22} className="text-gray-300 mb-2" />
              <p className="text-[13px] text-gray-400">No events match current filters</p>
            </div>
          ) : (
            <div className="overflow-y-auto flex-1 divide-y divide-gray-100">
              {filteredEvents.map(e => (
                <EventRow key={e.id} event={e} isNew={newIds.has(e.id)} />
              ))}
            </div>
          )}
        </Panel>

        {/* RIGHT — Decision Panel (3) */}
        <div className="col-span-3 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
          <div className="h-10 px-3 flex items-center justify-between border-b border-gray-100 shrink-0">
            <div className="flex items-center gap-2">
              <Terminal size={13} className="text-gray-400" strokeWidth={1.75} />
              <span className="text-[12px] font-semibold text-gray-700">Control</span>
            </div>
            {selectedSession && (
              <Badge variant={RISK_VARIANT[selectedSession.risk]} className="text-[9px]">
                {selectedSession.risk}
              </Badge>
            )}
          </div>
          <div className="flex-1 overflow-hidden">
            <ControlPanel session={selectedSession} />
          </div>
        </div>

      </div>
    </PageContainer>
  )
}
