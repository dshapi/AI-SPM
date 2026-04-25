// ui/src/admin/agents/AgentChatPanel.jsx
//
// Inline right-side panel for chatting with one agent. Sits in the
// same 300px slot as PreviewPanel + RegisterAgentPanel so the
// inventory layout doesn't shift — only the panel content swaps.
//
// Visual contract is identical to PreviewPanel:
//   - 300px fixed width (no overflow over the table)
//   - h-full so the parent flexbox owns vertical sizing (no h-screen
//     so the bottom composer can't get clipped by browser chrome)
//   - risk-tinted header, scrollable body, sticky composer footer

import { Loader2, MessageSquare, RefreshCw, Send, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { useAgentChat } from "./hooks/useAgentChat"


// Same risk-tint vocabulary as PreviewPanel uses (capitalised keys)
// PLUS lowercase keys for callers that pass the backend value directly.
const RISK_TINT = {
  Critical: "bg-red-50",
  High:     "bg-orange-50",
  Medium:   "bg-yellow-50",
  Low:      "bg-emerald-50",
  critical: "bg-red-50",
  high:     "bg-orange-50",
  medium:   "bg-yellow-50",
  low:      "bg-emerald-50",
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

  const riskBg = RISK_TINT[agent.risk] || "bg-gray-50"
  const canSend = !isStreaming && draft.trim().length > 0

  const onSubmit = (e) => {
    e.preventDefault()
    if (!canSend) return
    send(draft)
    setDraft("")
  }

  return (
    <div
      role="dialog" aria-modal="false" aria-label={`Chat with ${agent.name}`}
      // ``min-h-0`` lets the parent flex column actually constrain us
      // when the surrounding layout doesn't cap our height; ``max-h``
      // is a viewport-relative ceiling so the panel can never push the
      // composer below the fold even when the parent forgets to size
      // it. Combined with ``flex-1 min-h-0`` on the body below, the
      // message list scrolls and the composer stays pinned.
      className="w-[300px] shrink-0 flex flex-col h-full min-h-0 max-h-[calc(100vh-120px)] bg-white"
      data-testid="agent-chat-panel"
    >
      {/* Header — mirrors PreviewPanel exactly. */}
      <div className={`px-4 py-3.5 border-b border-gray-100 flex items-start justify-between gap-2 ${riskBg}`}>
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-wider text-gray-500 flex items-center gap-1">
            <MessageSquare size={11} aria-hidden /> Chat
          </div>
          <p className="text-[13px] font-semibold text-gray-900 leading-snug truncate mt-0.5">
            {agent.name}
          </p>
          <p className="text-[11px] text-gray-500 mt-0.5">
            {agent.runtime_state || "stopped"}
            {agent.runtime_state !== "running" && (
              <span className="ml-2 text-red-600">· paused</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-0.5 shrink-0 mt-0.5">
          <button
            type="button" onClick={reset}
            aria-label="New chat"
            className="w-6 h-6 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-black/5 transition-colors"
            title="Start a new session"
          >
            <RefreshCw size={12} />
          </button>
          <button
            type="button" onClick={onClose}
            aria-label="Close chat"
            className="w-6 h-6 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-black/5 transition-colors"
          >
            <X size={13} />
          </button>
        </div>
      </div>

      {/* Conversation body — scrollable. */}
      <div
        ref={bodyRef} data-testid="chat-body"
        className="flex-1 overflow-y-auto px-3 py-3 space-y-2 bg-gray-50"
      >
        {messages.length === 0 && (
          <p className="text-[12px] text-gray-500 italic">
            Type a message below to start the conversation.
          </p>
        )}
        {messages.map(m => <Bubble key={m.id} m={m} />)}
        {error && (
          <p className="text-[11px] text-red-600 mt-2" role="alert">
            ⚠ {error.message}
          </p>
        )}
      </div>

      {/* Composer — sticky bottom; bg-white so it stands out from
          the bg-gray-50 body. */}
      <form
        onSubmit={onSubmit}
        className="border-t border-gray-100 px-3 py-2 bg-white shrink-0"
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
              "flex-1 resize-none border border-gray-300 rounded-md px-2 py-1.5 " +
              "text-[12px] focus:outline-none focus:ring-2 focus:ring-blue-400 " +
              "disabled:bg-gray-50 disabled:text-gray-400"
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
                : "bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed")
            }
          >
            {isStreaming ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          </button>
        </div>
      </form>
    </div>
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
