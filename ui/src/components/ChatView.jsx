import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble.jsx'

export default function ChatView({ messages }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div style={{
      height: '100%',
      overflowY: 'auto',
      padding: '24px 20px 12px',
    }}>
      <div style={{
        maxWidth: 720,
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
      }}>
        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={bottomRef} style={{ height: 1 }} />
      </div>
    </div>
  )
}
