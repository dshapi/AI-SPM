import { useState, useRef, useCallback, useEffect } from 'react'
import Header from './components/Header.jsx'
import ChatView from './components/ChatView.jsx'
import ChatInput from './components/ChatInput.jsx'
import { sendMessageStream } from './api.js'
import { useSimulationContext } from './context/SimulationContext.jsx'

const MODELS = [
  { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku' },
  { id: 'claude-sonnet-4-6', label: 'Claude Sonnet' },
  { id: 'claude-opus-4-6', label: 'Claude Opus' },
]

function _freshSessionId() {
  return `session-${Date.now()}`
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [model, setModel] = useState(MODELS[0].id)
  const [inChat, setInChat] = useState(false)
  const [error, setError] = useState(null)
  const [sessionId, setSessionId] = useState(_freshSessionId)
  const inputRef = useRef(null)

  // ── Wire chat session events into the shared SimulationContext ──
  // The backend emits platform session events (session.started, policy.*,
  // output.generated, etc.) to /ws/sessions/{sessionId}.  By subscribing
  // whenever the chat's sessionId changes, those events flow into the same
  // simEvents array that Lineage / Alerts read from — so a live chat at /
  // populates the Lineage graph at /admin/lineage without a reload.
  //
  // IMPORTANT — no cleanup that calls unsubscribeFromSession():
  // stopStream() inside the context resets simEvents to []. If we invoked
  // it on unmount, simply navigating from / (chat) to /admin/lineage would
  // wipe the event stream the chat just produced — exactly what we want to
  // display.  Swapping sessions is still safe: the next
  // subscribeToSession(newSessionId) internally tears down the prior socket
  // via connectWs → _closeSocket, so there's no leak.
  //
  // subscribeToSession is a no-op stub on the context default value, so this
  // safely degrades if the provider isn't mounted (e.g. test renders).
  const { subscribeToSession } = useSimulationContext()
  useEffect(() => {
    if (!sessionId || typeof subscribeToSession !== 'function') return
    subscribeToSession(sessionId)
  }, [sessionId, subscribeToSession])

  const appendMessage = useCallback((role, text, streaming = false) => {
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), role, text, streaming }])
  }, [])

  const updateLastAssistant = useCallback((text, streaming = false, blockDetail = null) => {
    setMessages(prev => {
      const copy = [...prev]
      for (let i = copy.length - 1; i >= 0; i--) {
        if (copy[i].role === 'assistant') {
          copy[i] = { ...copy[i], text, streaming, blockDetail }
          return copy
        }
      }
      return copy
    })
  }, [])

  // Refs for the streaming display — survive re-renders without stale closures.
  // We used to character-drip via setInterval, but each tick triggered a full
  // ReactMarkdown re-render (~100-300ms), so the typer ran far slower than its
  // 18ms schedule and long replies took a minute to trickle out.  The natural
  // token stream already gives a typing feel, so we render each token directly
  // via rAF-coalesced updates instead.
  const displayedRef  = useRef('')   // full text shown so far
  const badgesRef     = useRef([])   // tool badges received so far
  const rafRef        = useRef(null) // pending animation-frame handle
  const pendingRef    = useRef(false)// a render is queued

  const buildDisplay = (text, streaming) => {
    const badgeLine = badgesRef.current.map(b => `\`${b}\``).join('  ')
    const body = badgeLine ? `${badgeLine}\n\n${text}` : text
    updateLastAssistant(body, streaming)
  }

  // Coalesce bursts of tokens into a single render per animation frame.
  // Without this, a fast LLM can fire tokens faster than React can reconcile,
  // producing jank even on the happy path.
  const scheduleRender = useCallback((streaming) => {
    if (pendingRef.current) return
    pendingRef.current = true
    rafRef.current = requestAnimationFrame(() => {
      pendingRef.current = false
      rafRef.current = null
      buildDisplay(displayedRef.current, streaming)
    })
  }, [updateLastAssistant])

  const flushRender = useCallback((streaming) => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    pendingRef.current = false
    buildDisplay(displayedRef.current, streaming)
  }, [updateLastAssistant])

  const handleSend = useCallback(async (text) => {
    if (!text.trim() || loading) return
    setError(null)
    if (!inChat) setInChat(true)

    // Reset streaming state for new message
    displayedRef.current = ''
    badgesRef.current    = []
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    pendingRef.current = false

    appendMessage('user', text)
    setLoading(true)
    appendMessage('assistant', '', true)

    sendMessageStream(text, sessionId, {
      onToken: (chunk) => {
        // Append the token directly and coalesce renders via rAF.
        displayedRef.current += chunk
        scheduleRender(true)
      },
      onBadge: (badge) => {
        badgesRef.current.push(badge)
        scheduleRender(true)
      },
      onDone: () => {
        flushRender(false)
        setLoading(false)
      },
      onError: (e) => {
        if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
        pendingRef.current = false
        updateLastAssistant(`⚠️ ${e.message}`, false, e.blockDetail || null)
        setError(e.message)
        setLoading(false)
      },
    })
  }, [loading, inChat, sessionId, appendMessage, updateLastAssistant, scheduleRender, flushRender])

  const handleNewChat = useCallback(() => {
    setMessages([])
    setInChat(false)
    setError(null)
    setLoading(false)
    // Generating a fresh sessionId triggers the subscribeToSession effect,
    // which closes the previous WS and opens a new one for the new session.
    setSessionId(_freshSessionId())
    setTimeout(() => inputRef.current?.focus(), 100)
  }, [])

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#ffffff' }}>
      {inChat && (
        <Header
          model={model}
          models={MODELS}
          onModelChange={setModel}
          onNewChat={handleNewChat}
        />
      )}

      <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        {inChat ? (
          <ChatView messages={messages} loading={loading} />
        ) : (
          <Landing
            onSend={handleSend}
            model={model}
            models={MODELS}
            onModelChange={setModel}
            inputRef={inputRef}
          />
        )}
      </div>

      {inChat && (
        <ChatInput
          onSend={handleSend}
          loading={loading}
          model={model}
          models={MODELS}
          onModelChange={setModel}
          inputRef={inputRef}
        />
      )}
    </div>
  )
}

// ── Landing ─────────────────────────────────────────────────────────────

function Landing({ onSend, model, models, onModelChange, inputRef }) {
  const [value, setValue] = useState('')
  const [devOpen, setDevOpen] = useState(false)

  const submit = () => {
    if (value.trim()) {
      onSend(value)
      setValue('')
    }
  }

  return (
    <div style={{
      height: '100%',
      position: 'relative',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '40px',
      padding: '0 20px',
    }}>

      <LogoMark />

      <div style={{ textAlign: 'center' }}>
        <h1 style={{
          fontSize: '3rem',
          fontWeight: 700,
          letterSpacing: '-0.04em',
          margin: 0,
          color: '#0f172a',
        }}>
          Orbyx
        </h1>

        <p style={{
          color: '#64748b',
          fontSize: '1.05rem',
          marginTop: 6,
        }}>
          AI Security Posture Management
        </p>
      </div>

      <div style={{ width: '100%', maxWidth: 640 }}>
        <div style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 10,
          background: '#ffffff',
          border: '1.5px solid #e5e7eb',
          borderRadius: 30,
          padding: '14px 16px',
          boxShadow: '0 10px 35px rgba(0,0,0,0.06)',
        }}>

          <textarea
            ref={inputRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder="Ask anything..."
            rows={1}
            style={{
              flex: 1,
              border: 'none',
              outline: 'none',
              resize: 'none',
              fontSize: '16px',
              lineHeight: '1.6',
              color: '#111827',
              background: 'transparent',
              maxHeight: 180,
              overflowY: 'auto',
            }}
            onInput={e => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 180) + 'px'
            }}
          />

          <button
            onClick={submit}
            disabled={!value.trim()}
            style={{
              width: 38,
              height: 38,
              borderRadius: '50%',
              background: value.trim()
                ? 'linear-gradient(135deg, #2563EB, #06B6D4)'
                : '#e5e7eb',
              color: value.trim() ? '#fff' : '#9ca3af',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s ease',
              fontSize: 16,
            }}
          >
            ↑
          </button>

        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 13, color: '#9ca3af' }}>Model:</span>
        <select
          value={model}
          onChange={e => onModelChange(e.target.value)}
          style={{
            border: 'none',
            background: 'transparent',
            fontSize: 13,
            color: '#374151',
            cursor: 'pointer',
            outline: 'none',
          }}
        >
          {models.map(m => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
      </div>

      {/* Dev Console */}
      <div style={{
        position: 'absolute',
        bottom: 20,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 8,
      }}>
        <button
          onClick={() => setDevOpen(!devOpen)}
          style={{
            fontSize: 12,
            color: '#9ca3af',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          Dev Tools {devOpen ? '▴' : '▾'}
        </button>

        {devOpen && (
          <div style={{
            display: 'flex',
            gap: 16,
            fontSize: 13,
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: 12,
            padding: '8px 14px',
            boxShadow: '0 10px 30px rgba(0,0,0,0.08)',
          }}>
            <a href="http://localhost:3000/" target="_blank" style={{ color: '#2563eb', textDecoration: 'none' }}>
              Grafana
            </a>
            <a href="http://localhost:9090/" target="_blank" style={{ color: '#2563eb', textDecoration: 'none' }}>
              Prometheus
            </a>
          </div>
        )}
      </div>

    </div>
  )
}

// ── Logo ─────────────────────────────────────────────────────────────

function LogoMark() {
  return (
    <div style={{
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: 12,
    }}>

      {/* Strong glow */}
      <div style={{
        position: 'absolute',
        width: 320,
        height: 320,
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(37,99,235,0.35) 0%, rgba(6,182,212,0.22) 40%, transparent 75%)',
        filter: 'blur(55px)',
      }} />

      {/* Logo */}
      <img
        src="/logo.png"
        alt="Orbyx"
        style={{
          width: 220,   // 👈 MUCH bigger
          height: 220,
          objectFit: 'contain',
          position: 'relative',
          zIndex: 2,
          filter: 'drop-shadow(0 25px 60px rgba(37,99,235,0.45))',
        }}
      />

    </div>
  )
}