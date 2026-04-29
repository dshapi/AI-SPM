// SPM admin-side REST helpers.
//
// All calls go through the Vite proxy:
//   /api/spm/*    →  spm_api   (port 8092)
//   /api/v1/*     →  orchestrator (port 8094) — used here only for policies
//
// Token handling follows the same dev-token pattern as ui/src/api.js so we get
// a Bearer token with the `spm:admin` role (minted by vite.config.js in dev).

const SPM_BASE       = '/api/spm'
const POLICIES_BASE  = '/api/v1/policies'
const DEV_TOKEN_URL  = '/api/dev-token'

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
  const detail = (body && body.detail) ?? null
  // Backend returns {detail: {error, message, ...}} for structured errors
  // (e.g. duplicate model), and {detail: "..."} for plain-string errors.
  if (detail && typeof detail === 'object') {
    const e = new Error(detail.message || detail.error || `Request failed (${res.status})`)
    e.status = res.status
    e.detail = detail
    return e
  }
  const e = new Error((typeof detail === 'string' && detail) || `Request failed (${res.status})`)
  e.status = res.status
  return e
}

// ── Models ──────────────────────────────────────────────────────────────────

export async function fetchModels({ tenant_id } = {}) {
  const qs   = tenant_id ? `?tenant_id=${encodeURIComponent(tenant_id)}` : ''
  const res  = await fetch(`${SPM_BASE}/models${qs}`, { headers: await _authHeaders() })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw _errFrom(res, body)
  return Array.isArray(body) ? body : []
}

/**
 * Register a new model via multipart upload.
 *
 * @param {FormData} formData — must include `name`, `version`, and `file` plus
 *        any optional metadata fields (provider, owner, model_type, notes, …).
 * @param {object} [opts]
 * @param {(pct: number) => void} [opts.onProgress] — called with 0..100 as the
 *        file uploads. fetch() has no upload-progress API, so this uses XHR.
 * @param {AbortSignal} [opts.signal] — abort the in-flight upload.
 * @returns {Promise<object>} the created ModelResponse row.
 * @throws {Error & {status:number, detail?:object}} on HTTP failure.
 */
export function registerModelWithFile(formData, { onProgress, signal } = {}) {
  return new Promise(async (resolve, reject) => {
    const token = await getToken()
    const xhr   = new XMLHttpRequest()
    xhr.open('POST', `${SPM_BASE}/models/upload`, true)
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
        // Mirror the fetch error shape so callers can branch on `.status` / `.detail`
        const fakeRes = { status: xhr.status }
        reject(_errFrom(fakeRes, body))
      }
    }
    xhr.onerror   = () => reject(Object.assign(new Error('Network error during upload'), { status: 0 }))
    xhr.onabort   = () => reject(Object.assign(new Error('Upload cancelled'),           { status: 0, aborted: true }))
    xhr.ontimeout = () => reject(Object.assign(new Error('Upload timed out'),           { status: 0 }))

    if (signal) {
      if (signal.aborted) { xhr.abort(); return }
      signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }

    xhr.send(formData)
  })
}

// ── Posture (real data from seeded posture_snapshots table) ─────────────────
//
// The Posture page used to render entirely from hardcoded JS constants even
// though seed_db.py seeds 30 daily PostureSnapshot rows on first boot.
// These two helpers wire the page to the real seeded data.
//
// Both fetchers degrade to a safe empty-shape on network/API failure so the
// page can still render its rich (still-mocked) sub-sections offline.

export async function fetchPostureSnapshots({ days = 30, tenantId = 'global', modelId } = {}) {
  try {
    const qs = new URLSearchParams({ days: String(days), tenant_id: tenantId })
    if (modelId) qs.set('model_id', modelId)
    const res = await fetch(`${SPM_BASE}/posture/snapshots?${qs}`, { headers: await _authHeaders() })
    if (!res.ok) return []
    const body = await res.json().catch(() => [])
    return Array.isArray(body) ? body : []
  } catch {
    return []
  }
}

export async function fetchPostureSummary({ days = 30, tenantId = 'global', modelId } = {}) {
  try {
    const qs = new URLSearchParams({ days: String(days), tenant_id: tenantId })
    if (modelId) qs.set('model_id', modelId)
    const res = await fetch(`${SPM_BASE}/posture/summary?${qs}`, { headers: await _authHeaders() })
    if (!res.ok) return null
    return await res.json().catch(() => null)
  } catch {
    return null
  }
}

// ── Policies (read from CPM via orchestrator) ───────────────────────────────

export async function fetchPolicies() {
  try {
    const res  = await fetch(POLICIES_BASE, { headers: await _authHeaders() })
    if (!res.ok) return []                  // orchestrator offline → empty list
    const body = await res.json().catch(() => [])
    if (!Array.isArray(body)) return []
    return body.map(p => ({
      id:       p.id ?? p.policy_id ?? p.name,
      name:     p.name ?? p.title ?? String(p.id ?? 'policy'),
      state:    p.state ?? null,
      is_active: !!p.is_active,
    }))
  } catch {
    return []
  }
}
