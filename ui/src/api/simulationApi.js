/**
 * simulationApi.js
 * ─────────────────
 * API integration for the Simulation Lab.
 *
 * Calls the agent-orchestrator-service (POST /api/v1/sessions,
 * GET /api/v1/sessions/{id}/events) to run real policy simulations.
 *
 * URL resolution:
 *   VITE_ORCHESTRATOR_URL  — override base for the orchestrator (e.g. http://localhost:8094/api/v1)
 *   VITE_API_URL           — shared API base (e.g. /api), used to derive the default
 *   default                — /api/v1  (assumes a reverse-proxy mapping /api/v1/* → orchestrator)
 */

const BASE             = import.meta.env.VITE_API_URL        || '/api'
const ORCHESTRATOR_BASE = import.meta.env.VITE_ORCHESTRATOR_URL || `${BASE}/v1`

// ── Token management ──────────────────────────────────────────────────────────
// Mirrors the pattern in api.js — fetches a dev JWT from the platform gateway.

let _token       = null
let _tokenExpiry = 0

async function getToken() {
  const now = Date.now() / 1000
  if (_token && _tokenExpiry > now + 60) return _token
  try {
    const res = await fetch(`${BASE}/dev-token`)
    if (!res.ok) throw new Error('Token fetch failed')
    const data = await res.json()
    _token       = data.token
    _tokenExpiry = now + (data.expires_in ?? 86400)
    return _token
  } catch {
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

  const res = await fetch(`${ORCHESTRATOR_BASE}/sessions/${sessionId}/events`, { headers })

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
