const BASE = import.meta.env.VITE_API_URL || '/api'

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL || ''  // empty = same origin; /realms/* proxied to Keycloak via VirtualService
const KC_REALM     = import.meta.env.VITE_KC_REALM     || 'aispm'
const KC_CLIENT_ID = import.meta.env.VITE_KC_CLIENT_ID || 'aispm-ui'

// ── Token state ──────────────────────────────────────────────────────────────
// Mirrored to sessionStorage so the OAuth Authorization Code redirect round-trip
// (which causes a full page reload) doesn't lose the tokens. sessionStorage
// scopes them to the tab — closing the tab signs the user out, which is what we
// want for a security-sensitive admin app. localStorage would persist longer
// but is exposed to any XSS on the same origin, so deliberately avoiding it.
let _token        = null
let _tokenExpiry  = 0
let _refreshToken = null

// Rehydrate from sessionStorage on module load (handles page navigation/reload)
;(() => {
  try {
    const t   = sessionStorage.getItem('aispm.access_token')
    const r   = sessionStorage.getItem('aispm.refresh_token')
    const exp = sessionStorage.getItem('aispm.token_expiry')
    if (t && exp) {
      _token        = t
      _refreshToken = r
      _tokenExpiry  = parseInt(exp, 10)
    }
  } catch { /* sessionStorage may be unavailable in private modes */ }
})()

function _persistTokens() {
  try {
    sessionStorage.setItem('aispm.access_token',  _token  || '')
    sessionStorage.setItem('aispm.refresh_token', _refreshToken || '')
    sessionStorage.setItem('aispm.token_expiry',  String(_tokenExpiry))
  } catch {}
}

function _clearTokens() {
  _token = null; _refreshToken = null; _tokenExpiry = 0
  try {
    sessionStorage.removeItem('aispm.access_token')
    sessionStorage.removeItem('aispm.refresh_token')
    sessionStorage.removeItem('aispm.token_expiry')
  } catch {}
}

// ── PKCE helpers (RFC 7636) ─────────────────────────────────────────────────
// Vanilla Web Crypto — no library dependency. Verifier = 32 random bytes,
// base64url-encoded; challenge = SHA-256(verifier), base64url-encoded.

function _base64UrlEncode(bytes) {
  let s = ''
  for (const b of bytes) s += String.fromCharCode(b)
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function _randomBase64Url(byteLen = 32) {
  return _base64UrlEncode(crypto.getRandomValues(new Uint8Array(byteLen)))
}

async function _pkceChallenge(verifier) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return _base64UrlEncode(new Uint8Array(hash))
}

// ── Authorization Code + PKCE flow ──────────────────────────────────────────
// Replaces the previous Resource Owner Password Credentials grant. Browser is
// redirected to Keycloak's hosted login page, which renders username/password
// AND the Google identity-provider button. After the user authenticates, they
// land back at /auth/callback?code=... where handleAuthCallback() exchanges
// the code for tokens.
//
// The previous `login(username, password)` ROPC export is removed: it was only
// safe because Keycloak's `aispm-ui` client has directAccessGrantsEnabled=true,
// which we should also flip off in the helm bootstrap once nothing in the app
// (or tests) calls ROPC anymore. Leaving the server-side flag enabled today is
// defense-in-depth, not a backdoor we use.

export async function loginRedirect(returnTo = '/admin/overview') {
  const verifier  = _randomBase64Url(32)
  const challenge = await _pkceChallenge(verifier)
  const state     = _randomBase64Url(16)

  sessionStorage.setItem('aispm.pkce_verifier', verifier)
  sessionStorage.setItem('aispm.pkce_state',    state)
  sessionStorage.setItem('aispm.return_to',     returnTo)

  const params = new URLSearchParams({
    client_id:             KC_CLIENT_ID,
    response_type:         'code',
    scope:                 'openid email profile',
    redirect_uri:          `${window.location.origin}/auth/callback`,
    code_challenge:        challenge,
    code_challenge_method: 'S256',
    state,
  })
  window.location.href =
    `${KEYCLOAK_URL}/realms/${KC_REALM}/protocol/openid-connect/auth?${params}`
}

export async function handleAuthCallback() {
  const search = new URLSearchParams(window.location.search)
  const code   = search.get('code')
  const state  = search.get('state')
  const error  = search.get('error')

  // Pull and immediately consume the per-flow secrets so a stale tab can't
  // replay them.
  const expectedState = sessionStorage.getItem('aispm.pkce_state')
  const verifier      = sessionStorage.getItem('aispm.pkce_verifier')
  const returnTo      = sessionStorage.getItem('aispm.return_to') || '/admin/overview'
  sessionStorage.removeItem('aispm.pkce_state')
  sessionStorage.removeItem('aispm.pkce_verifier')
  sessionStorage.removeItem('aispm.return_to')

  if (error) throw new Error(`Authorization error: ${error} ${search.get('error_description') || ''}`.trim())
  if (!code) throw new Error('No authorization code in callback URL.')
  if (!state || state !== expectedState) {
    throw new Error('State mismatch — refusing token exchange (possible CSRF).')
  }
  if (!verifier) {
    throw new Error('PKCE verifier missing — login was not initiated from this tab.')
  }

  const url  = `${KEYCLOAK_URL}/realms/${KC_REALM}/protocol/openid-connect/token`
  const body = new URLSearchParams({
    grant_type:    'authorization_code',
    client_id:     KC_CLIENT_ID,
    code,
    redirect_uri:  `${window.location.origin}/auth/callback`,
    code_verifier: verifier,
  })
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`Token exchange failed (${resp.status}): ${detail}`)
  }
  const data = await resp.json()
  _token        = data.access_token
  _refreshToken = data.refresh_token
  _tokenExpiry  = Date.now() + (data.expires_in - 30) * 1000
  _persistTokens()
  return returnTo
}

async function _refreshAccessToken() {
  const url = `${KEYCLOAK_URL}/realms/${KC_REALM}/protocol/openid-connect/token`
  const body = new URLSearchParams({
    grant_type:    'refresh_token',
    client_id:     KC_CLIENT_ID,
    refresh_token: _refreshToken,
  })
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!resp.ok) { _clearTokens(); return null }
  const data = await resp.json()
  _token        = data.access_token
  _refreshToken = data.refresh_token
  _tokenExpiry  = Date.now() + (data.expires_in - 30) * 1000
  _persistTokens()
  return _token
}

export async function getToken() {
  if (_token && Date.now() < _tokenExpiry) return _token
  if (_refreshToken) return _refreshAccessToken()
  return null
}

export async function sendMessage(prompt, sessionId) {
  const token = await getToken()

  if (!token) {
    window.location.href = '/login'
    throw new Error('Not authenticated')
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
    let msg
    if (typeof detail === 'object' && detail !== null) {
      msg = detail.explanation || detail.error || JSON.stringify(detail)
      if (detail.matched_rule) msg += ` — rule: ${detail.matched_rule}`
    } else {
      msg = detail || `Request failed (${res.status})`
    }
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
  // Track whether a terminal callback fired so we can synthesize one if the
  // SSE stream closes without a final event.  Without this, a server that
  // hangs up mid-stream leaves the assistant bubble stuck in the typing
  // state forever (no onDone / no onError means setLoading(false) is never
  // called in App.jsx).
  let terminated = false
  const fireDone  = (ev) => { if (!terminated) { terminated = true; onDone(ev || {}) } }
  const fireError = (e)  => { if (!terminated) { terminated = true; onError(e)       } }

  const token = await getToken()
  if (!token) {
    // No valid token — surface a clear error instead of posting
    // Bearer null and getting an opaque 401 or hang.
    fireError(new Error('API unreachable — could not obtain auth token. Check that the api service is running.'))
    return
  }

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
    fireError(new Error('Network error: ' + e.message))
    return
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = err.detail
    let msg
    if (typeof detail === 'object' && detail !== null) {
      msg = detail.explanation || detail.error || JSON.stringify(detail)
      if (detail.matched_rule) msg += ` — rule: ${detail.matched_rule}`
    } else {
      msg = detail || `Request failed (${res.status})`
    }
    const blockErr = new Error(msg)
    if (typeof detail === 'object' && detail !== null) blockErr.blockDetail = detail
    fireError(blockErr)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawAnyEvent = false

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
          sawAnyEvent = true
          if (event.type === 'token')      onToken(event.text)
          else if (event.type === 'badge') onBadge(event.text)
          else if (event.type === 'done')  fireDone(event)
          else if (event.type === 'error') fireError(new Error(event.message))
        } catch { /* malformed SSE line — skip */ }
      }
    }
  } catch (e) {
    fireError(new Error('Stream read error: ' + e.message))
    return
  }

  // Stream closed cleanly but no terminal event arrived.  This happens when
  // the backend exits the generator without yielding a {type: 'done'} frame
  // (e.g. Anthropic SDK swallows an exception, or the LLM returns zero text
  // because every block was a tool_use that produced no follow-up text).
  // Surface SOMETHING so the bubble doesn't hang.
  if (!terminated) {
    if (sawAnyEvent) {
      // We got tokens/badges but no explicit done — treat the close as done.
      fireDone({})
    } else {
      fireError(new Error('Empty response from server — the stream closed without any content. Check api logs.'))
    }
  }
}


/**
 * sendAgentMessageStream
 * ──────────────────────
 * Streaming chat against a SPECIFIC custom agent's runtime, instead of the
 * default LLM that ``sendMessageStream`` targets.  POSTs to
 * ``/api/spm/agents/{id}/chat`` (Phase 4 agent-runtime control plane;
 * see services/spm_api/agent_chat.py for the SSE pipeline) with body
 * ``{message, session_id}`` — note the field name is ``message``, NOT
 * ``prompt`` like the default chat endpoint.
 *
 * Same callback contract as ``sendMessageStream`` (onToken / onBadge /
 * onDone / onError) so it can be a drop-in inside App.jsx when the
 * caller passes an ``agentBinding``.
 *
 * Failure modes that the agent_chat backend surfaces as SSE error frames
 * (prompt-guard / policy-decider blocks, agent reply timeout, output-guard
 * fail-closed) all funnel through onError just like the main chat — the
 * only path-specific failure is HTTP 409 "agent is 'stopped'; start it
 * before chatting", which we map to a clear user message.
 */
export async function sendAgentMessageStream(
  agentId, prompt, sessionId,
  { onToken, onBadge, onDone, onError },
) {
  let terminated = false
  const fireDone  = (ev) => { if (!terminated) { terminated = true; onDone(ev || {}) } }
  const fireError = (e)  => { if (!terminated) { terminated = true; onError(e)       } }

  const token = await getToken()
  if (!token) {
    fireError(new Error('API unreachable — could not obtain auth token. Check that the api service is running.'))
    return
  }

  let res
  try {
    res = await fetch(
      `${BASE}/spm/agents/${encodeURIComponent(agentId)}/chat`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
          Accept:         'text/event-stream',
        },
        body: JSON.stringify({ message: prompt, session_id: sessionId }),
      },
    )
  } catch (e) {
    fireError(new Error('Network error: ' + e.message))
    return
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail = err.detail
    let msg
    if (typeof detail === 'object' && detail !== null) {
      msg = detail.explanation || detail.error || JSON.stringify(detail)
      if (detail.matched_rule) msg += ` — rule: ${detail.matched_rule}`
    } else if (typeof detail === 'string') {
      msg = detail
    } else {
      msg = `Request failed (${res.status})`
    }
    // Special-case the most common operator error so the chat panel
    // can render a clear message instead of "Request failed (409)".
    if (res.status === 409) {
      msg = `This agent isn't running. Start it from the Inventory page, then retry. (${msg})`
    }
    const blockErr = new Error(msg)
    if (typeof detail === 'object' && detail !== null) blockErr.blockDetail = detail
    fireError(blockErr)
    return
  }

  const reader  = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawAnyEvent = false

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (!line.startsWith('data: ') && !line.startsWith('data:')) continue
        const payload = line.replace(/^data:\s*/, '')
        try {
          const event = JSON.parse(payload)
          sawAnyEvent = true
          if (event.type === 'token')      onToken(event.text)
          else if (event.type === 'badge') onBadge(event.text)
          else if (event.type === 'done')  fireDone(event)
          else if (event.type === 'error') fireError(new Error(event.message || event.text || 'Agent error'))
        } catch { /* malformed SSE line — skip */ }
      }
    }
  } catch (e) {
    fireError(new Error('Stream read error: ' + e.message))
    return
  }

  if (!terminated) {
    if (sawAnyEvent) fireDone({})
    else fireError(new Error('Empty response from agent — the stream closed without any content.'))
  }
}

// ── Session event log (Lineage backfill + session picker) ────────────────────
// Surfaces the ConnectionManager's in-memory persistent log so the admin
// Lineage page can hydrate after reload / direct-link navigation, and offer
// a recent-sessions dropdown to re-inspect prior runs.

/**
 * List recent sessions (most-recent-first) from the backend's persistent log.
 * Returns [] on failure — the caller can silently fall back to live state or
 * to localStorage.
 */
export async function listSessions() {
  try {
    const token = await getToken()
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    const res = await fetch(`${BASE}/sessions`, { headers })
    if (!res.ok) return []
    const data = await res.json()
    return Array.isArray(data.sessions) ? data.sessions : []
  } catch {
    return []
  }
}

/**
 * Fetch the recorded event stream for a single session. Returns the events
 * in WS-wire shape (`session_id`, `event_type`, `correlation_id`, `timestamp`,
 * `payload`, ...) — identical to what /ws/sessions/{sid} streams live, so
 * the caller can feed them straight through normalizeEvent().
 */
export async function fetchSessionEvents(sessionId) {
  if (!sessionId) return []
  try {
    const token = await getToken()
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    const res = await fetch(
      `${BASE}/sessions/${encodeURIComponent(sessionId)}/events`,
      { headers },
    )
    if (!res.ok) return []
    const data = await res.json()
    return Array.isArray(data.events) ? data.events : []
  } catch {
    return []
  }
}

// ── Logout ────────────────────────────────────────────────────────────────────

/**
 * logout() — clears tokens (memory + sessionStorage) and ends the Keycloak
 * session via OIDC RP-Initiated Logout, so the user can't silently
 * re-authenticate from a stale Keycloak SSO cookie. After Keycloak processes
 * the end-session, it redirects back to /login per post_logout_redirect_uri.
 */
export function logout() {
  const idToken = sessionStorage.getItem('aispm.id_token')  // optional, set if scope=openid returned one
  _clearTokens()
  try { sessionStorage.removeItem('aispm.id_token') } catch {}

  const params = new URLSearchParams({
    post_logout_redirect_uri: `${window.location.origin}/login`,
    client_id: KC_CLIENT_ID,
  })
  if (idToken) params.set('id_token_hint', idToken)

  window.location.href =
    `${KEYCLOAK_URL}/realms/${KC_REALM}/protocol/openid-connect/logout?${params}`
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
