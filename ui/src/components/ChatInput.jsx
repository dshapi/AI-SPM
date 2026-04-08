import { useState, useEffect } from 'react'

export default function ChatInput({ onSend, loading, model, models, onModelChange, inputRef }) {
  const [value, setValue] = useState('')

  // Keep focus on input after each message
  useEffect(() => {
    if (!loading) inputRef.current?.focus()
  }, [loading])

  const submit = () => {
    if (!value.trim() || loading) return
    onSend(value)
    setValue('')
    // Reset height
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
    }
  }

  return (
    <div style={{
      borderTop: '1px solid var(--border)',
      background: 'rgba(255,255,255,0.95)',
      backdropFilter: 'blur(12px)',
      padding: '12px 20px 16px',
    }}>
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        {/* Main input pill */}
        <div style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 8,
          background: 'var(--bg-2)',
          border: '1.5px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          padding: '8px 10px',
          boxShadow: 'var(--shadow-sm)',
          transition: 'border-color var(--transition)',
        }}>
          {/* + button */}
          <button
            title="Attach file (coming soon)"
            style={{
              width: 32, height: 32, flexShrink: 0,
              borderRadius: '50%',
              background: 'var(--bg-3)',
              color: 'var(--text-2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 18,
              transition: 'background var(--transition)',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--border)'}
            onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-3)'}
          >
            +
          </button>

          {/* Globe button */}
          <button
            title="Web context (coming soon)"
            style={{
              width: 32, height: 32, flexShrink: 0,
              borderRadius: '50%',
              background: 'var(--bg-3)',
              color: 'var(--text-3)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14,
              transition: 'background var(--transition)',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--border)'}
            onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-3)'}
          >
            🌐
          </button>

          {/* Text area */}
          <textarea
            ref={inputRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() }
            }}
            onInput={e => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 180) + 'px'
            }}
            placeholder="Ask anything..."
            disabled={loading}
            rows={1}
            style={{
              flex: 1,
              border: 'none',
              outline: 'none',
              resize: 'none',
              fontSize: '14.5px',
              lineHeight: 1.6,
              color: 'var(--text)',
              background: 'transparent',
              maxHeight: 180,
              overflowY: 'auto',
              padding: '4px 0',
              opacity: loading ? 0.5 : 1,
            }}
          />

          {/* Model selector */}
          <div style={{
            display: 'flex', alignItems: 'center',
            background: 'var(--bg-3)',
            borderRadius: 8, padding: '3px 8px',
            flexShrink: 0,
          }}>
            <select
              value={model}
              onChange={e => onModelChange(e.target.value)}
              style={{
                border: 'none', background: 'transparent',
                fontSize: 12, color: 'var(--text-2)',
                cursor: 'pointer', outline: 'none',
                fontWeight: 500,
              }}
            >
              {models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>

          {/* Send button */}
          <button
            onClick={submit}
            disabled={!value.trim() || loading}
            style={{
              width: 34, height: 34, flexShrink: 0,
              borderRadius: '50%',
              background: value.trim() && !loading ? 'var(--accent)' : 'var(--bg-3)',
              color: value.trim() && !loading ? '#fff' : 'var(--text-3)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16,
              transition: 'background var(--transition), color var(--transition)',
            }}
          >
            {loading ? <Spinner /> : '↑'}
          </button>
        </div>

        {/* Footer hint */}
        <p style={{
          textAlign: 'center',
          fontSize: 11.5,
          color: 'var(--text-3)',
          marginTop: 8,
        }}>
          All messages are screened by the Orbyx security layer before processing.
        </p>
      </div>
    </div>
  )
}

function Spinner() {
  return (
    <div style={{
      width: 14, height: 14,
      border: '2px solid rgba(148,163,184,0.3)',
      borderTopColor: 'var(--text-3)',
      borderRadius: '50%',
      animation: 'spin 0.7s linear infinite',
    }} />
  )
}
