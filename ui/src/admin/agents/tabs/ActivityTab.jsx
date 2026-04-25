// ui/src/admin/agents/tabs/ActivityTab.jsx
//
// Phase 4.5 — live tail of agent activity:
//   • chat turns (user / agent)
//   • AgentToolCall events emitted by spm-mcp on web_fetch
//   • AgentLLMCall events emitted by spm-llm-proxy per chat completion
//
// Backed by GET /api/spm/agents/{id}/activity which unifies
// agent_chat_messages with session_events filtered by agent_id, ordered
// newest-first. Polls every 5 s while the tab is visible; pauses while
// the tab is unmounted.

import {
  Activity,
  Bot,
  Hammer,
  Loader2,
  RefreshCw,
  Sparkles,
  User,
} from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { apiFetch } from "../../api/integrationsApi.js"


const POLL_MS = 5000


function fmtAge(ts) {
  if (!ts) return "—"
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const sec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000))
  if (sec < 60)  return `${sec}s ago`
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`
  return d.toLocaleDateString()
}


function Row({ r }) {
  // Colour + icon per kind so the timeline scans fast.
  let Icon, label, body
  if (r.kind === "chat" && r.role === "user") {
    Icon = User
    label = "User"
    body = r.text
  } else if (r.kind === "chat" && (r.role === "agent" || r.role === "assistant")) {
    Icon = Bot
    label = "Agent reply"
    body = r.text
  } else if (r.kind === "tool_call") {
    Icon = Hammer
    label = `Tool · ${r.tool || "unknown"}${r.ok === false ? " (failed)" : ""}`
    body = r.duration_ms != null
      ? `${r.duration_ms} ms`
      : ""
  } else if (r.kind === "llm_call") {
    Icon = Sparkles
    label = `LLM · ${r.model || "—"}${r.ok === false ? " (failed)" : ""}`
    const t = r.prompt_tokens != null && r.completion_tokens != null
      ? `${r.prompt_tokens} prompt + ${r.completion_tokens} completion tokens`
      : ""
    body = t
  } else {
    Icon = Activity
    label = r.kind || "event"
    body = r.text || ""
  }

  return (
    <li className="flex items-start gap-2 py-1.5 border-b border-slate-100 last:border-0">
      <Icon size={12} className="text-slate-500 mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-slate-700 truncate">
            {label}
          </span>
          <span className="text-[10.5px] text-slate-400 shrink-0">
            {fmtAge(r.ts)}
          </span>
        </div>
        {body && (
          <p className="text-[11.5px] text-slate-600 mt-0.5 leading-snug whitespace-pre-wrap break-words">
            {String(body).slice(0, 600)}
          </p>
        )}
      </div>
    </li>
  )
}


export default function ActivityTab({ agent }) {
  const [rows,    setRows]    = useState([])
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const tickRef = useRef(0)

  const refresh = useCallback(async () => {
    if (!agent?.id) return
    const my = ++tickRef.current
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch(
        `/agents/${encodeURIComponent(agent._backendId || agent.id)}/activity?limit=80`,
      )
      // Stale-tick guard — drop a slow response if a newer one started.
      if (my !== tickRef.current) return
      setRows(Array.isArray(data) ? data : [])
    } catch (e) {
      if (my !== tickRef.current) return
      setError(e)
    } finally {
      if (my === tickRef.current) setLoading(false)
    }
  }, [agent?.id, agent?._backendId])

  // Poll while the tab is mounted; pause on unmount.
  useEffect(() => {
    let cancelled = false
    refresh()
    const id = setInterval(() => { if (!cancelled) refresh() }, POLL_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [refresh])

  if (!agent) return null

  return (
    <div className="p-4 flex flex-col h-full min-h-0">
      <header className="flex items-center justify-between mb-2 shrink-0">
        <h3 className="text-[13px] font-semibold text-slate-900 flex items-center gap-2">
          <Activity size={14} className="text-slate-500" aria-hidden />
          Recent activity
          {loading && <Loader2 size={11} className="animate-spin text-slate-400" />}
        </h3>
        <button
          type="button"
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-slate-300 hover:bg-slate-50 text-[11px] disabled:opacity-50"
          aria-label="Refresh activity"
          onClick={refresh}
          disabled={loading}
          title="Refresh now (auto-polls every 5s)"
        >
          <RefreshCw size={11} aria-hidden /> Refresh
        </button>
      </header>

      {error && (
        <p className="text-[11px] text-rose-600 mb-2 shrink-0" role="alert">
          ⚠ {error.message || "Failed to load activity"}
        </p>
      )}

      {rows.length === 0 && !loading && !error ? (
        <p className="text-[12px] text-slate-500 italic">
          No activity yet. Send a message in the chat panel to populate.
        </p>
      ) : (
        <ul className="text-[12px] overflow-y-auto flex-1 min-h-0">
          {rows.map((r, i) => <Row key={`${r.ts}-${i}`} r={r} />)}
        </ul>
      )}
    </div>
  )
}
