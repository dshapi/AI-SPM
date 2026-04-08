import { useState, useRef, useCallback } from 'react'
import Header from './components/Header.jsx'
import ChatView from './components/ChatView.jsx'
import ChatInput from './components/ChatInput.jsx'
import { sendMessageStream } from './api.js'

const MODELS = [
  { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku' },
  { id: 'claude-sonnet-4-6', label: 'Claude Sonnet' },
  { id: 'claude-opus-4-6', label: 'Claude Opus' },
]

let _sessionId = `session-${Date.now()}`

export default function App() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [model, setModel] = useState(MODELS[0].id)
  const [inChat, setInChat] = useState(false)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  const appendMessage = useCallback((role, text, streaming = false) => {
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), role, text, streaming }])
  }, [])

  const updateLastAssistant = useCallback((text, streaming = false) => {
    setMessages(prev => {
      const copy = [...prev]
      for (let i = copy.length - 1; i >= 0; i--) {
        if (copy[i].role === 'assistant') {
          copy[i] = { ...copy[i], text, streaming }
          return copy
        }
      }
      return copy
    })
  }, [])

  // Refs for the character-drip typer — survive re-renders without stale closures
  const charQueueRef  = useRef([])   // pending characters to drip
  const displayedRef  = useRef('')   // what's currently shown
  const badgesRef     = useRef([])   // tool badges received so far
  const timerRef      = useRef(null) // interval handle
  const streamDoneRef = useRef(false)// has the SSE stream finished?

  const buildDisplay = (text, streaming) => {
    const badgeLine = badgesRef.current.map(b => `\`${b}\``).join('  ')
    const body = badgeLine ? `${badgeLine}\n\n${text}` : text
    updateLastAssistant(body, streaming)
  }

  const startTyper = useCallback(() => {
    if (timerRef.current) return
    timerRef.current = setInterval(() => {
      if (charQueueRef.current.length === 0) {
        // Queue empty — if stream is done, finalize
        if (streamDoneRef.current) {
          clearInterval(timerRef.current)
          timerRef.current = null
          buildDisplay(displayedRef.current, false)
          setLoading(false)
        }
        return
      }
      // Drip one character at a time
      displayedRef.current += charQueueRef.current.shift()
      buildDisplay(displayedRef.current, true)
    }, 18) // ~55 chars/sec — feels like fast typing
  }, [updateLastAssistant])

  const handleSend = useCallback(async (text) => {
    if (!text.trim() || loading) return
    setError(null)
    if (!inChat) setInChat(true)

    // Reset typer state for new message
    charQueueRef.current  = []
    displayedRef.current  = ''
    badgesRef.current     = []
    streamDoneRef.current = false
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }

    appendMessage('user', text)
    setLoading(true)
    appendMessage('assistant', '', true)

    sendMessageStream(text, _sessionId, {
      onToken: (chunk) => {
        // Push each character into the queue — typer drips them one by one
        charQueueRef.current.push(...chunk.split(''))
        startTyper()
      },
      onBadge: (badge) => {
        badgesRef.current.push(badge)
        buildDisplay(displayedRef.current, true)
      },
      onDone: () => {
        streamDoneRef.current = true
        // If typer already drained the queue, finalize immediately
        if (charQueueRef.current.length === 0) {
          if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
          buildDisplay(displayedRef.current, false)
          setLoading(false)
        }
      },
      onError: (e) => {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
        updateLastAssistant(`⚠️ ${e.message}`, false)
        setError(e.message)
        setLoading(false)
      },
    })
  }, [loading, inChat, appendMessage, updateLastAssistant, startTyper])

  const handleNewChat = useCallback(() => {
    setMessages([])
    setInChat(false)
    setError(null)
    setLoading(false)
    _sessionId = `session-${Date.now()}`
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