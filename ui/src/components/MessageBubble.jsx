import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Split tool badges from response body
// Badges are lines like `🔍 Searched: "..."` at the top of the message
function parseToolBadges(text) {
  if (!text) return { badges: [], body: text }
  const lines = text.split('\n')
  const badges = []
  let i = 0
  // Collect leading backtick-wrapped badge lines
  while (i < lines.length) {
    const match = lines[i].match(/`(🔍[^`]+|🌐[^`]+)`/g)
    if (match) {
      match.forEach(m => badges.push(m.replace(/`/g, '').trim()))
      i++
    } else if (lines[i].trim() === '') {
      i++
      if (badges.length > 0) break  // blank line after badges = separator
    } else {
      break
    }
  }
  const body = lines.slice(i).join('\n').trimStart()
  return { badges, body: body || text }
}

const REASON_LABELS = {
  lexical_block:       'Lexical scanner',
  guard_model_block:   'Guard model',
  policy_block:        'OPA policy',
  policy_unavailable:  'Policy unavailable',
  guard_unavailable:   'Guard unavailable',
  obfuscation_block:   'Obfuscation detected',
}

function BlockCard({ detail }) {
  const reason = REASON_LABELS[detail.reason] || detail.reason || 'Security policy'
  const fullText = detail.explanation || 'This request was blocked by the security policy.'

  // Stream the explanation in character-by-character, just like a normal response
  const [visibleText, setVisibleText] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    setVisibleText('')
    setDone(false)
    let i = 0
    const id = setInterval(() => {
      i++
      setVisibleText(fullText.slice(0, i))
      if (i >= fullText.length) {
        clearInterval(id)
        setDone(true)
      }
    }, 12) // ~83 chars/sec — matches a fast token stream
    return () => clearInterval(id)
  }, [fullText])

  return (
    <div style={{
      borderLeft: '3px solid #ef4444',
      background: 'rgba(239,68,68,0.05)',
      borderRadius: '0 10px 10px 0',
      padding: '12px 14px',
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
    }}>
      {/* Header — always visible immediately */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16 }}>🛡️</span>
        <span style={{ fontWeight: 700, fontSize: 14, color: '#dc2626' }}>Request Blocked</span>
      </div>

      {/* Explanation — streams in with blinking cursor */}
      <div style={{ fontSize: 13.5, color: '#374151', lineHeight: 1.6 }} className="block-explanation">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{visibleText}</ReactMarkdown>
        {!done && <span style={{ animation: 'blink 1s infinite', marginLeft: 1 }}>▌</span>}
      </div>

      {/* Tags — fade in only after text finishes streaming */}
      {done && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2, animation: 'fadeIn 0.35s ease' }}>
          <Tag label="Trigger" value={reason} color="#dc2626" />
          {detail.matched_rule && (
            <Tag label="Rule" value={detail.matched_rule} color="#7c3aed" />
          )}
          {detail.categories && detail.categories.length > 0 && (
            <Tag label="Categories" value={detail.categories.join(', ')} color="#d97706" />
          )}
          {detail.correlation_id && (
            <Tag label="ID" value={detail.correlation_id.slice(0, 8)} color="#6b7280" />
          )}
        </div>
      )}
    </div>
  )
}

function Tag({ label, value, color }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: `${color}12`,
      border: `1px solid ${color}30`,
      borderRadius: 20,
      padding: '2px 10px',
      fontSize: 12,
      color,
      fontWeight: 500,
    }}>
      <span style={{ opacity: 0.6 }}>{label}:</span> {value}
    </span>
  )
}

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'flex-end',
        marginBottom: 4,
        animation: 'fadeIn 0.25s ease',
      }}>
        <div style={{
          maxWidth: '72%',
          background: 'var(--user-bg)',
          color: 'var(--text)',
          borderRadius: '18px 18px 4px 18px',
          padding: '10px 14px',
          fontSize: 14.5,
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}>
          {message.text}
        </div>
      </div>
    )
  }

  const { badges, body } = parseToolBadges(message.text)

  // Assistant
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'flex-start',
      marginBottom: 4,
      animation: 'fadeIn 0.25s ease',
    }}>
      {/* Avatar */}
      <div style={{
        width: 28, height: 28,
        borderRadius: 8,
        background: 'var(--accent)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
        marginRight: 10,
        marginTop: 2,
        fontSize: 13,
        color: '#fff',
        fontWeight: 700,
        letterSpacing: '-0.02em',
      }}>
        O
      </div>

      <div style={{
        maxWidth: 'calc(100% - 42px)',
        background: 'var(--assistant-bg)',
        color: 'var(--text)',
        borderRadius: '4px 18px 18px 18px',
        padding: '10px 14px',
        fontSize: 14.5,
        lineHeight: 1.65,
        wordBreak: 'break-word',
        minWidth: message.streaming && !message.text ? 60 : 0,
      }}>
        {message.streaming && !message.text ? (
          <TypingIndicator />
        ) : message.blockDetail ? (
          <BlockCard detail={message.blockDetail} />
        ) : (
          <div className="message-content">
            {/* Tool use badges */}
            {badges.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                {badges.map((b, i) => (
                  <span key={i} style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4,
                    background: 'rgba(37,99,235,0.08)',
                    border: '1px solid rgba(37,99,235,0.18)',
                    borderRadius: 20,
                    padding: '2px 10px',
                    fontSize: 12,
                    color: '#1d4ed8',
                    fontWeight: 500,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    maxWidth: 320,
                    textOverflow: 'ellipsis',
                  }}>
                    {b}
                  </span>
                ))}
              </div>
            )}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {body}
            </ReactMarkdown>
            {message.streaming && <span style={{ animation: 'blink 1s infinite', marginLeft: 2 }}>▌</span>}
          </div>
        )}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', padding: '2px 0' }}>
      {[0, 1, 2].map(i => (
        <div key={i} style={{
          width: 7, height: 7,
          borderRadius: '50%',
          background: 'var(--text-3)',
          animation: `pulse 1.2s ease ${i * 0.2}s infinite`,
        }} />
      ))}
    </div>
  )
}
