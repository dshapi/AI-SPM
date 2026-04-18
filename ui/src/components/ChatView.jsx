import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble.jsx'

export default function ChatView({ messages }) {
  const scrollRef = useRef(null)
  const isUserScrollingRef = useRef(false)
  const scrollTimeoutRef = useRef(null)

  // Detect manual scroll-up so we don't yank the user back down mid-read
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      if (!atBottom) {
        isUserScrollingRef.current = true
        clearTimeout(scrollTimeoutRef.current)
        scrollTimeoutRef.current = setTimeout(() => {
          isUserScrollingRef.current = false
        }, 2000)
      } else {
        isUserScrollingRef.current = false
      }
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  // Scroll to bottom on every message update (new message or streamed token).
  // rAF defers one frame so scrollHeight reflects the newly painted content.
  useEffect(() => {
    if (isUserScrollingRef.current) return
    const el = scrollRef.current
    if (!el) return
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
  }, [messages])

  return (
    <div
      ref={scrollRef}
      style={{
        position: 'absolute',
        top: 0, left: 0, right: 0, bottom: 0,
        overflowY: 'auto',
        padding: '24px 20px 12px',
      }}
    >
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
        <div style={{ height: 8 }} />
      </div>
    </div>
  )
}
