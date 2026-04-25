// ui/src/admin/agents/AgentChatPanel.jsx
//
// Right-side drawer for chatting with one agent. Independent of the
// AgentDetailDrawer so an operator can keep both open at once.
//
// Visual style mirrors PreviewPanel + AgentDetailDrawer for
// consistency: risk-tinted header, scrollable body, sticky input
// composer at the bottom.

import { Loader2, MessageSquare, RefreshCw, Send, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { useAgentChat } from "./hooks/useAgentChat"


const RISK_TINT = {
  critical: "bg-rose-100   border-rose-300   text-rose-900",
  high:     "bg-rose-50    border-rose-200   text-rose-900",
  medium:   "bg-amber-50   border-amber-200  text-amber-900",
  low:      "bg-emerald-50 border-emerald-200 text-emerald-900",
}


/**
 * @param {object}   props
 * @param {boolean}  props.open
 * @param {object}   [props.agent]              — null when closed
 * @param {Function} [props.onClose]
 */
export default function AgentChatPanel({ open, agent, onClose }) {
  const { messages, send, reset, isStreaming, error } = useAgentChat(agent?.id)

  const [draft, setDraft] = useState("")
  const bodyRef = useRef(null)
  const inputRef = useRef(null)

  // Reset on agent switch — different agents shouldn't share history.
  useEffect(() => { reset() }, [agent?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll to the latest message whenever the list grows.
  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  // Focus the input on open.
  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus()
  }, [open, agent?.id])

  if (!open || !agent) return null

  const tint = RISK_TINT[agent.risk] || RISK_TINT.low
  const canSend = !isStreaming && draft.trim().length > 0

  const onSubmit = (e) => {
    e.preventDefault()
    if (!canSend) return
    send(draft)
    setDraft("")
  }

  return (
    <aside
      role="dialog" aria-modal="false" aria-label={`Chat with ${agent.name}`}
      className={
        "fixed top-0 right-0 z-40 h-screen w-[420px] max-w-[90vw] " +
        "bg-white border-l border-slate-200 shadow-2xl flex flex-col"
      }
      data-testid="agent-chat-panel"
    >
      <header className={`flex items-start justify-between p-4 border-b ${tint}`}>
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider opacity-70 flex items-center gap-1">
            <MessageSquare size={11} aria-hidden /> Chat
          </div>
          <h2 className="text-[15px] font-semibold mt-0.5">{agent.name}</h2>
          <div className="text-[11px] mt-1 opacity-80">
            {agent.runtime_state}
            {agent.runtime_state !== "running" && (
              <span className="ml-2 text-rose-700">· paused</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button" onClick={reset}
            aria-label="New chat"
            className="p-1 rounded hover:bg-black/10 text-current"
            title="Start a new session"
          >
            <RefreshCw size={14} />
          </button>
          <button
            type="button" onClick={onClose}
            aria-label="Close chat"
            className="p-1 rounded hover:bg-black/10 text-current"
          >
            <X size={16} />
          </button>
        </div>
      </header>

      {/* Conversation body */}
      <div
        ref={bodyRef} data-testid="chat-body"
        className="flex-1 overflow-y-auto p-3 space-y-2 bg-slate-50"
      >
        {messages.length === 0 && (
          <p className="text-[12px] text-slate-500 italic">
            Type a message below to start the conversation.
          </p>
        )}
        {messages.map(m => <Bubble key={m.id} m={m} />)}
        {error && (
          <p className="text-[11px] text-rose-700 mt-2" role="alert">
            ⚠ {error.message}
          </p>
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={onSubmit}
        className="border-t border-slate-200 p-2 bg-white"
      >
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                if (canSend) onSubmit(e)
              }
            }}
            placeholder={
              agent.runtime_state === "running"
                ? `Message ${agent.name}…`
                : `${agent.name} is ${agent.runtime_state}. Start it to chat.`
            }
            rows={2}
            disabled={agent.runtime_state !== "running"}
            className={
              "flex-1 resize-none border border-slate-300 rounded-md px-2 py-1.5 " +
              "text-[12px] focus:outline-none focus:ring-2 focus:ring-blue-400 " +
              "disabled:bg-slate-50 disabled:text-slate-500"
            }
          />
          <button
            type="submit"
            disabled={!canSend || agent.runtime_state !== "running"}
            aria-label="Send message"
            className={
              "px-2.5 py-1.5 rounded-md border " +
              (canSend && agent.runtime_state === "running"
                ? "bg-blue-600 hover:bg-blue-700 text-white border-blue-700"
                : "bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed")
            }
          >
            {isStreaming ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          </button>
        </div>
      </form>
    </aside>
  )
}


// ─── Single message bubble ─────────────────────────────────────────────────

function Bubble({ m }) {
  const mine = m.role === "user"
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={
          "max-w-[78%] rounded-lg px-3 py-1.5 text-[12px] whitespace-pre-wrap " +
          (mine
            ? "bg-blue-600 text-white"
            : "bg-white border border-slate-200 text-slate-800")
        }
        data-role={m.role}
      >
        {m.text}
        {m.streaming && (
          <span className="ml-1 inline-block w-1.5 h-3 bg-current opacity-60 animate-pulse align-middle" />
        )}
      </div>
    </div>
  )
}
