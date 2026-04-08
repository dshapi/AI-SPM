const BASE = import.meta.env.VITE_API_URL || '/api'

let _token = null
let _tokenExpiry = 0

async function getToken() {
  const now = Date.now() / 1000
  if (_token && _tokenExpiry > now + 60) return _token
  try {
    const res = await fetch(`${BASE}/dev-token`)
    if (!res.ok) throw new Error('Token fetch failed')
    const data = await res.json()
    _token = data.token
    _tokenExpiry = now + (data.expires_in || 86400)
    return _token
  } catch {
    return null
  }
}

export async function sendMessage(prompt, sessionId) {
  const token = await getToken()

  if (!token) {
    // API unreachable — fall back to mock
    return mockResponse(prompt)
  }

  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ prompt, session_id: sessionId }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = err.detail
    const msg = typeof detail === 'object' && detail !== null
      ? (detail.error || JSON.stringify(detail))
      : (detail || `Request failed (${res.status})`)
    throw new Error(msg)
  }

  const data = await res.json()

  // If Anthropic is wired, the response field has the real answer
  if (data.response) return { text: data.response, source: 'claude' }

  // Otherwise the platform accepted the message for async processing
  return {
    text: "Your request has been received and is being processed securely through the platform.",
    source: 'platform',
  }
}

export async function sendMessageStream(prompt, sessionId, { onToken, onBadge, onDone, onError }) {
  const token = await getToken()

  let res
  try {
    res = await fetch(`${BASE}/chat/stream`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ prompt, session_id: sessionId }),
    })
  } catch (e) {
    onError(new Error('Network error: ' + e.message))
    return
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = err.detail
    const msg = typeof detail === 'object' && detail !== null
      ? (detail.error || JSON.stringify(detail))
      : (detail || `Request failed (${res.status})`)
    onError(new Error(msg))
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() // keep any incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6))
          if (event.type === 'token')  onToken(event.text)
          else if (event.type === 'badge')  onBadge(event.text)
          else if (event.type === 'done')   onDone(event)
          else if (event.type === 'error')  onError(new Error(event.message))
        } catch { /* malformed SSE line — skip */ }
      }
    }
  } catch (e) {
    onError(new Error('Stream read error: ' + e.message))
  }
}

// ── Mock responses for offline / no-API mode ─────────────────────────────────
const MOCK = [
  "I'm here to help. What would you like to know?",
  "That's a great question. Let me think through that carefully.\n\nBased on what you've described, here are a few things to consider:\n\n1. **Context matters** — the specifics of your situation will shape the best approach.\n2. **Start simple** — often the most direct path is the most effective.\n3. **Iterate** — don't try to solve everything at once.\n\nWould you like me to go deeper on any of these points?",
  "Here's a concise summary:\n\n```\nKey points:\n- Point one\n- Point two  \n- Point three\n```\n\nLet me know if you need more detail.",
  "I understand what you're looking for. Here's my thinking on this...\n\nThe core issue is how to balance competing priorities while maintaining clarity. In practice, this usually means making a deliberate choice about what to optimize for first.",
  "Absolutely. Let me break that down step by step so it's easy to follow.",
]

let _mockIdx = 0
function mockResponse(prompt) {
  const text = MOCK[_mockIdx % MOCK.length]
  _mockIdx++
  return { text, source: 'mock' }
}
