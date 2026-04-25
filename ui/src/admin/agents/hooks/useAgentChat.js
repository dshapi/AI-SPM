// ui/src/admin/agents/hooks/useAgentChat.js
//
// Hook backing the AgentChatPanel. Manages:
//   - the in-memory message list (user + agent turns)
//   - the SSE stream for the in-flight agent reply
//   - one stable session_id per panel mount (reset() bumps it)
//
// Wire format mirrors ui/src/api.js::sendMessageStream — POST to
// /api/spm/agents/{id}/chat with {message, session_id}, server
// responds with text/event-stream chunks shaped:
//
//   data: {"type":"token", "text":"hi"}\n
//   data: {"type":"token", "text":" there"}\n
//   data: {"type":"done",  "text":"hi there"}\n
//
// V1 backend emits one big `done` chunk (no streaming yet); V1.5 will
// stream tokens. Either path works without UI changes.

import { useCallback, useRef, useState } from "react"


function _newSessionId() {
  // crypto.randomUUID is available in Node 19+ and all browsers we
  // ship to. Fallback to a low-entropy id only for ancient envs.
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return "sess-" + Math.random().toString(36).slice(2, 11)
}


/**
 * Each ChatTurn is one displayable bubble:
 *   { id, role: "user" | "agent", text, ts: ISOString, streaming?: boolean }
 */

async function _getDevToken() {
  try {
    const r = await fetch("/api/dev-token")
    if (!r.ok) return null
    const d = await r.json()
    return d.token || null
  } catch { return null }
}


/**
 * @param {string} agentId
 * @returns {{
 *   messages: Array,
 *   send:     (text:string) => Promise<void>,
 *   reset:    () => void,
 *   isStreaming: boolean,
 *   error:    Error|null,
 * }}
 */
export function useAgentChat(agentId) {
  const [messages,    setMessages]    = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error,       setError]       = useState(null)

  // Session id is held in a ref so it survives re-renders without
  // tripping the message-list dependency in useMemo elsewhere.
  const sessionIdRef = useRef(_newSessionId())
  const abortRef     = useRef(null)

  const reset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    sessionIdRef.current = _newSessionId()
    setMessages([])
    setError(null)
    setIsStreaming(false)
  }, [])

  const send = useCallback(async (text) => {
    const trimmed = (text || "").trim()
    if (!trimmed || !agentId) return

    const now = new Date().toISOString()
    const userTurn = {
      id: _newSessionId(), role: "user", text: trimmed, ts: now,
    }
    const replyTurn = {
      id: _newSessionId(), role: "agent", text: "", ts: now,
      streaming: true,
    }
    setMessages(prev => [...prev, userTurn, replyTurn])
    setIsStreaming(true)
    setError(null)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = await _getDevToken()
      const res = await fetch(`/api/spm/agents/${encodeURIComponent(agentId)}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept":       "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message:    trimmed,
          session_id: sessionIdRef.current,
        }),
        signal: controller.signal,
      })

      if (!res.ok) {
        const body = await res.text().catch(() => "")
        throw new Error(`Chat failed (${res.status}): ${body || res.statusText}`)
      }

      // Stream parser — mirrors ui/src/api.js::sendMessageStream.
      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      // Coalesce token appends into a single setMessages per animation
      // frame to avoid render thrash on long replies. The buffer of
      // pending text lives in a closure variable; the rAF callback
      // flushes it.
      let pendingText = ""
      let rafId = null
      const flushPending = () => {
        rafId = null
        if (!pendingText) return
        const chunk = pendingText
        pendingText = ""
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (!last || last.role !== "agent" || !last.streaming) return prev
          const updated = { ...last, text: last.text + chunk }
          return [...prev.slice(0, -1), updated]
        })
      }
      const queueAppend = (chunk) => {
        pendingText += chunk
        if (rafId == null) {
          rafId = (typeof requestAnimationFrame !== "undefined"
                    ? requestAnimationFrame : (cb) => setTimeout(cb, 16))(flushPending)
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Each SSE record is `data: <json>\n` — split on \n, keep the
        // trailing partial in the buffer.
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""
        for (const raw of lines) {
          const line = raw.trim()
          if (!line.startsWith("data:")) continue
          let evt
          try { evt = JSON.parse(line.slice(5).trim()) } catch { continue }

          if (evt.type === "token" && typeof evt.text === "string") {
            queueAppend(evt.text)
          } else if (evt.type === "done") {
            // Flush any pending tokens, then mark the streaming turn
            // complete and replace its text with the canonical full
            // message if `done` carried one.
            flushPending()
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (!last || last.role !== "agent" || !last.streaming) return prev
              const finalText = (typeof evt.text === "string" && evt.text)
                ? evt.text
                : last.text
              const updated = { ...last, text: finalText, streaming: false }
              return [...prev.slice(0, -1), updated]
            })
          } else if (evt.type === "error") {
            throw new Error(evt.text || "Agent reported error")
          }
        }
      }
      // Flush any tokens that arrived after the last newline.
      flushPending()
    } catch (e) {
      if (controller.signal.aborted) return
      setError(e)
      // Mark the in-flight turn as not-streaming so the UI doesn't
      // show a forever-spinner.
      setMessages(prev => {
        const last = prev[prev.length - 1]
        if (!last || last.role !== "agent" || !last.streaming) return prev
        return [...prev.slice(0, -1),
                 { ...last, text: last.text + ` (error: ${e.message})`, streaming: false }]
      })
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setIsStreaming(false)
    }
  }, [agentId])

  return { messages, send, reset, isStreaming, error }
}
