// ui/src/admin/api/agents.js
//
// Admin-side REST helpers for the agent runtime control plane.
//
// Mirrors the dev-token + auth-headers pattern from ./spm.js so the
// Vite proxy at /api/spm/* receives a JWT with the spm:admin role
// minted by vite.config.js in dev.
//
// Wire shape — see Phase 1 plan, services/spm_api/agent_routes.py:
//
//   GET    /api/spm/agents                 → Agent[]
//   GET    /api/spm/agents/{id}            → Agent
//   POST   /api/spm/agents (multipart)     → Agent      [201]
//   PATCH  /api/spm/agents/{id}            → Agent      (subset of fields)
//   DELETE /api/spm/agents/{id}            → 204
//   POST   /api/spm/agents/{id}/start      → {status:"starting"}  [202]
//   POST   /api/spm/agents/{id}/stop       → {status:"stopping"}  [202]
//
// The `mcp_token` and `llm_api_key` columns are NEVER present in
// responses (the backend strips them) — callers must not look for them.

const SPM_BASE      = '/api/spm'
const DEV_TOKEN_URL = '/api/dev-token'

let _token = null
let _tokenExpiry = 0


async function getToken() {
  const now = Date.now() / 1000
  if (_token && _tokenExpiry > now + 60) return _token
  try {
    const res = await fetch(DEV_TOKEN_URL)
    if (!res.ok) throw new Error('Token fetch failed')
    const data = await res.json()
    _token = data.token
    _tokenExpiry = now + (data.expires_in || 86400)
    return _token
  } catch {
    return null
  }
}


async function _authHeaders() {
  const token = await getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}


function _errFrom(res, body) {
  // Same error envelope discipline as spm.js so callers can branch on
  // .status / .detail uniformly across both modules.
  const detail = (body && body.detail) ?? null
  if (detail && typeof detail === 'object') {
    const e = new Error(detail.message || detail.error || `Request failed (${res.status})`)
    e.status = res.status
    e.detail = detail
    return e
  }
  if (Array.isArray(detail)) {
    // 422 from validate_agent_code — list of error strings.
    const e = new Error(detail.join(' / ') || `Request failed (${res.status})`)
    e.status = res.status
    e.detail = detail
    return e
  }
  const e = new Error(
    (typeof detail === 'string' && detail) || `Request failed (${res.status})`
  )
  e.status = res.status
  return e
}


// ── List / get / patch / delete ─────────────────────────────────────────────

export async function listAgents() {
  const res  = await fetch(`${SPM_BASE}/agents`, { headers: await _authHeaders() })
  const body = await res.json().catch(() => [])
  if (!res.ok) throw _errFrom(res, body)
  return Array.isArray(body) ? body : []
}


export async function getAgent(agentId) {
  if (!agentId) throw new Error('getAgent: agentId required')
  const res  = await fetch(`${SPM_BASE}/agents/${encodeURIComponent(agentId)}`,
                            { headers: await _authHeaders() })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw _errFrom(res, body)
  return body
}


/**
 * PATCH a subset of fields. Backend's ALLOWED_PATCH_FIELDS gates the keys —
 * see services/spm_api/agent_routes.py.
 */
export async function patchAgent(agentId, body) {
  if (!agentId) throw new Error('patchAgent: agentId required')
  const res = await fetch(`${SPM_BASE}/agents/${encodeURIComponent(agentId)}`, {
    method:  'PATCH',
    headers: { 'Content-Type': 'application/json', ...await _authHeaders() },
    body:    JSON.stringify(body),
  })
  const out = await res.json().catch(() => ({}))
  if (!res.ok) throw _errFrom(res, out)
  return out
}


/**
 * Retire — stops container, deletes Kafka topics, drops the row. 204 on success.
 */
export async function deleteAgent(agentId) {
  if (!agentId) throw new Error('deleteAgent: agentId required')
  const res = await fetch(`${SPM_BASE}/agents/${encodeURIComponent(agentId)}`, {
    method:  'DELETE',
    headers: await _authHeaders(),
  })
  if (res.status !== 204 && !res.ok) {
    const body = await res.json().catch(() => ({}))
    throw _errFrom(res, body)
  }
}


// ── Lifecycle (start / stop) ────────────────────────────────────────────────

export async function startAgent(agentId) {
  if (!agentId) throw new Error('startAgent: agentId required')
  const res = await fetch(`${SPM_BASE}/agents/${encodeURIComponent(agentId)}/start`, {
    method:  'POST',
    headers: await _authHeaders(),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw _errFrom(res, body)
  return body
}


export async function stopAgent(agentId) {
  if (!agentId) throw new Error('stopAgent: agentId required')
  const res = await fetch(`${SPM_BASE}/agents/${encodeURIComponent(agentId)}/stop`, {
    method:  'POST',
    headers: await _authHeaders(),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw _errFrom(res, body)
  return body
}


// ── Multipart upload (XHR for progress) ─────────────────────────────────────

/**
 * Register a new agent via multipart upload.
 *
 * @param {object}     opts
 * @param {string}     opts.name
 * @param {string}     opts.version
 * @param {string}     opts.agentType        — langchain|llamaindex|autogpt|openai_assistant|custom
 * @param {string}     [opts.owner]
 * @param {string}     [opts.description]
 * @param {boolean}    [opts.deployAfter=true]
 * @param {File}       opts.file             — the agent.py contents
 * @param {(p:number)=>void} [opts.onProgress] — 0..100 upload progress
 * @param {AbortSignal}      [opts.signal]
 * @returns {Promise<object>} the created Agent row (no tokens).
 */
export function createAgentWithFile({
  name, version, agentType, owner, description = '',
  deployAfter = true, file, onProgress, signal,
}) {
  if (!file) return Promise.reject(new Error('createAgentWithFile: file required'))

  const fd = new FormData()
  fd.append('name',         name)
  fd.append('version',      version)
  fd.append('agent_type',   agentType)
  if (owner)        fd.append('owner',       owner)
  if (description)  fd.append('description', description)
  fd.append('deploy_after', deployAfter ? 'true' : 'false')
  fd.append('code', file)

  return new Promise(async (resolve, reject) => {
    const token = await getToken()
    const xhr   = new XMLHttpRequest()
    xhr.open('POST', `${SPM_BASE}/agents`, true)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (ev) => {
      if (!onProgress || !ev.lengthComputable) return
      onProgress(Math.round((ev.loaded / ev.total) * 100))
    }

    xhr.onload = () => {
      let body
      try { body = JSON.parse(xhr.responseText || '{}') } catch { body = {} }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body)
      } else {
        reject(_errFrom({ status: xhr.status }, body))
      }
    }
    xhr.onerror   = () => reject(Object.assign(new Error('Network error during upload'), { status: 0 }))
    xhr.onabort   = () => reject(Object.assign(new Error('Upload cancelled'),           { status: 0, aborted: true }))
    xhr.ontimeout = () => reject(Object.assign(new Error('Upload timed out'),           { status: 0 }))

    if (signal) {
      if (signal.aborted) { xhr.abort(); return }
      signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }

    xhr.send(fd)
  })
}


// ── Phase 4 — policy attachment ────────────────────────────────────────────
//
// Read + atomic-replace surface the UI's PolicySelector component
// uses. The fine-grained POST/DELETE endpoints exist on the backend
// but the UI calls PUT for every change for atomicity (the user
// "saves" their selection by toggling a chip; we PUT the full list).

export async function listAgentPolicies(agentId) {
  if (!agentId) throw new Error('listAgentPolicies: agentId required')
  const res = await fetch(
    `${SPM_BASE}/agents/${encodeURIComponent(agentId)}/policies`,
    { headers: await _authHeaders() },
  )
  const body = await res.json().catch(() => [])
  if (!res.ok) throw _errFrom(res, body)
  return Array.isArray(body) ? body : []
}


/**
 * Replace the agent's full policy set in one call.
 * @param {string}   agentId
 * @param {string[]} policyIds  — final list (empty array clears).
 * @returns {Promise<Array>}    — the new full set.
 */
export async function setAgentPolicies(agentId, policyIds) {
  if (!agentId) throw new Error('setAgentPolicies: agentId required')
  const res = await fetch(
    `${SPM_BASE}/agents/${encodeURIComponent(agentId)}/policies`,
    {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json',
                  ...await _authHeaders() },
      body:    JSON.stringify({ policy_ids: policyIds || [] }),
    },
  )
  const body = await res.json().catch(() => [])
  if (!res.ok) throw _errFrom(res, body)
  return Array.isArray(body) ? body : []
}


// ── Internal — exported only for tests ─────────────────────────────────────

function _resetTokenCache() {
  _token = null
  _tokenExpiry = 0
}

export const __internals = { getToken, _authHeaders, _resetTokenCache }
