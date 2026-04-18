/**
 * simulationApi.js
 * ─────────────────
 * API integration for the Simulation Lab.
 *
 * Calls the agent-orchestrator-service (POST /api/v1/sessions,
 * GET /api/v1/sessions/{id}/events) to run real policy simulations.
 *
 * URL resolution:
 *   VITE_ORCHESTRATOR_URL  — relative override only (e.g. /api/v1). Absolute http://
 *                            URLs are intentionally ignored because a direct browser
 *                            request to the service port bypasses the Vite proxy and
 *                            is blocked by CORS.
 *   VITE_API_URL           — shared API base (e.g. /api), used to derive the default
 *   default                — /api/v1  (Vite proxy maps /api/v1/* → orchestrator:8094)
 */

const BASE = import.meta.env.VITE_API_URL || '/api'

// Only use VITE_ORCHESTRATOR_URL when it is a relative path (starts with '/').
// If it is an absolute http(s):// URL, ignore it and fall back to the proxy path —
// direct browser requests to the service port are blocked by CORS.
const _rawOrch = import.meta.env.VITE_ORCHESTRATOR_URL || ''
const ORCHESTRATOR_BASE = (_rawOrch && !_rawOrch.startsWith('http')) ? _rawOrch : `${BASE}/v1`

// ── Token management ──────────────────────────────────────────────────────────
// Mirrors the pattern in api.js — fetches a dev JWT from the platform gateway.

let _token       = null
let _tokenExpiry = 0

async function getToken() {
  const now = Date.now() / 1000
  if (_token && _tokenExpiry > now + 60) { console.log('[SimAPI] getToken: cache hit'); return _token }
  console.log('[SimAPI] getToken: fetching from', `${BASE}/dev-token`)
  try {
    const res = await fetch(`${BASE}/dev-token`)
    console.log('[SimAPI] getToken: fetch returned status', res.status)
    if (!res.ok) throw new Error('Token fetch failed')
    const data = await res.json()
    _token       = data.token
    _tokenExpiry = now + (data.expires_in ?? 86400)
    console.log('[SimAPI] getToken: token cached, expiry in', data.expires_in, 's')
    return _token
  } catch (e) {
    console.error('[SimAPI] getToken: error', e.message)
    return null   // callers send requests unauthenticated; orchestrator may reject
  }
}

// ── createSession ─────────────────────────────────────────────────────────────

/**
 * POST /api/v1/sessions
 *
 * Submits a prompt to the agent-orchestrator pipeline which runs:
 *   risk scoring → policy evaluation → (optional) LLM execution
 *
 * @param {Object}   params
 * @param {string}   params.agentId   Agent identifier (e.g. "FinanceAssistant-v2")
 * @param {string}   params.prompt    Test payload
 * @param {string[]} [params.tools]   Tools available to the agent (default [])
 * @param {Object}   [params.context] Arbitrary context (model, environment, …)
 * @returns {Promise<{
 *   session_id: string,
 *   status: string,
 *   agent_id: string,
 *   risk:   { score: number, tier: string, signals: string[] },
 *   policy: { decision: string, reason: string, policy_version: string },
 *   trace_id: string,
 *   created_at: string,
 * }>}
 */
export async function createSession({ agentId, prompt, tools = [], context = {} }) {
  const token   = await getToken()
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${ORCHESTRATOR_BASE}/sessions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ agent_id: agentId, prompt, tools, context }),
  })

  if (!res.ok) {
    const err    = await res.json().catch(() => ({}))
    const detail = err.detail
    const msg =
      typeof detail === 'object' && detail !== null
        ? detail.message ?? detail.error ?? JSON.stringify(detail)
        : detail ?? `Session creation failed (${res.status})`
    throw new Error(msg)
  }

  return res.json()
}

// ── fetchSessionEvents ────────────────────────────────────────────────────────

/**
 * GET /api/v1/sessions/{id}/events
 *
 * Retrieves the ordered lifecycle event log for a completed session.
 * Each event corresponds to one pipeline step (prompt.received,
 * risk.calculated, policy.decision, session.created / session.blocked, …).
 *
 * @param {string} sessionId  UUID returned by createSession
 * @returns {Promise<{
 *   session_id:     string,
 *   correlation_id: string,
 *   event_count:    number,
 *   events: Array<{
 *     step:       number,
 *     event_type: string,
 *     status:     string,
 *     summary:    string,
 *     timestamp:  string,
 *     payload:    Object | null,
 *   }>,
 * }>}
 */
export async function fetchSessionEvents(sessionId) {
  const token   = await getToken()
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const url = `${ORCHESTRATOR_BASE}/sessions/${sessionId}/events`
  console.log('[SimAPI] fetchSessionEvents: GET', url, 'hasToken=', !!token)
  const res = await fetch(url, { headers })
  console.log('[SimAPI] fetchSessionEvents: response status', res.status)

  if (!res.ok) {
    const err    = await res.json().catch(() => ({}))
    const detail = err.detail
    const msg =
      typeof detail === 'object' && detail !== null
        ? detail.message ?? detail.error ?? JSON.stringify(detail)
        : detail ?? `Events fetch failed (${res.status})`
    throw new Error(msg)
  }

  return res.json()
}

// ── fetchSessionResults ───────────────────────────────────────────────────────

/**
 * GET /api/v1/sessions/{id}/results
 *
 * Returns the structured SessionResults object built from lifecycle events.
 * Returns partial results (meta.partial=true) while the pipeline is running.
 *
 * @param {string} sessionId  UUID returned by createSession
 * @returns {Promise<{
 *   meta:           { session_id: string, agent_id: string|null, event_count: number, partial: boolean },
 *   status:         string,
 *   decision:       string,
 *   decision_trace: Array<{ step: number, event_type: string, status: string, summary: string, timestamp: string, latency_ms: number|null, payload: Object }>,
 *   risk:           { score: number, tier: string, signals: string[], anomaly_flags: string[] },
 *   policy:         { decision: string, reason: string, policy_version: string, risk_score_at_decision: number|null },
 *   output:         { verdict: string|null, pii_types: string[], secret_types: string[], scan_notes: string[], llm_model: string|null, response_length: number|null, latency_ms: number|null },
 *   recommendations: Array<{ id: string, priority: string, title: string, detail: string, action: string }>,
 * }>}
 */
export async function fetchSessionResults(sessionId) {
  const token   = await getToken()
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${ORCHESTRATOR_BASE}/sessions/${sessionId}/results`, { headers })

  if (!res.ok) {
    const err    = await res.json().catch(() => ({}))
    const detail = err.detail
    const msg =
      typeof detail === 'object' && detail !== null
        ? detail.message ?? detail.error ?? JSON.stringify(detail)
        : detail ?? `Results fetch failed (${res.status})`
    throw new Error(msg)
  }

  return res.json()
}

// ── fetchAllSessions ──────────────────────────────────────────────────────────

/**
 * Fetch all recent sessions across all agents.
 *
 * @param {string[]} agentIds   Ignored — kept for API compatibility
 * @param {number}   [limit=200] Max sessions to return
 * @returns {Promise<Array<{
 *   session_id: string, agent_id: string, status: string,
 *   risk_score: number, risk_tier: string, policy_decision: string,
 *   created_at: string,
 * }>>} Flat list sorted by created_at desc
 */
export async function fetchAllSessions(agentIds, limit = 200) {
  const token   = await getToken()
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const r = await fetch(`${ORCHESTRATOR_BASE}/sessions?limit=${limit}`, { headers })
  if (!r.ok) {
    const err    = await r.json().catch(() => ({}))
    const detail = err.detail
    const msg =
      typeof detail === 'object' && detail !== null
        ? detail.message ?? detail.error ?? JSON.stringify(detail)
        : detail ?? `Sessions fetch failed (${r.status})`
    throw new Error(msg)
  }
  const body = await r.json()
  const all  = body.sessions ?? []

  // Sort newest-first, deduplicate by session_id
  const seen = new Set()
  return all
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .filter(s => { if (seen.has(s.session_id)) return false; seen.add(s.session_id); return true })
}

// ── runSinglePromptSimulation ─────────────────────────────────────────────────

/**
 * Start a single-prompt simulation.
 * Connects to POST /api/simulate/single.
 * Returns { session_id, status }.
 *
 * @param {Object}  params
 * @param {string}  params.prompt         The prompt to simulate
 * @param {string}  params.sessionId      Session identifier
 * @param {string}  [params.executionMode='live'] Execution mode (e.g. 'live', 'sandbox')
 * @param {string}  [params.attackType='custom'] Attack type for simulation
 * @returns {Promise<{ session_id: string, status: string }>}
 */
export async function runSinglePromptSimulation({ prompt, sessionId, executionMode = 'live', attackType = 'custom' }) {
  const res = await fetch('/api/simulate/single', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      session_id: sessionId,
      execution_mode: executionMode,
      attack_type: attackType,
    }),
  })
  if (!res.ok) throw new Error(`simulate/single failed: ${res.status}`)
  return res.json()
}

// ── runGarakSimulation ────────────────────────────────────────────────────────

/**
 * Start a Garak simulation.
 * Connects to POST /api/simulate/garak.
 * Returns { session_id, status }.
 *
 * @param {Object} params
 * @param {Object} params.garakConfig    Garak configuration object
 * @param {string} params.sessionId      Session identifier
 * @param {string} [params.executionMode='live'] Execution mode (e.g. 'live', 'sandbox')
 * @returns {Promise<{ session_id: string, status: string }>}
 */
export async function runGarakSimulation({ garakConfig, sessionId, executionMode = 'live' }) {
  const res = await fetch('/api/simulate/garak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      execution_mode: executionMode,
      garak_config: garakConfig,
    }),
  })
  if (!res.ok) throw new Error(`simulate/garak failed: ${res.status}`)
  return res.json()
}
