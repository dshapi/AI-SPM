/**
 * admin/api/integrationsApi.js
 * ────────────────────────────
 * REST client for the spm-api integrations module (services/spm_api/
 * integrations_routes.py).
 *
 * Routing:
 *   /api/spm/integrations/*     →  spm-api  (port 8092, rewrite strips /api/spm)
 *
 * Auth: dev-token Bearer JWT minted by vite.config.js's devTokenPlugin.
 *       The dev token already carries `spm:admin` + `spm:auditor` roles, so
 *       every endpoint (including the admin-only Configure / Bootstrap
 *       mutations) will pass the role check in dev.
 *
 * Contract parity: the shapes returned here are the IntegrationSummary /
 * IntegrationDetail Pydantic models — camelCase aliases (`authMethod`,
 * `ownerDisplay`, `lastSync`, …) are already applied server-side, so the
 * existing Integrations.jsx mock shape is drop-in compatible.
 */

const SPM_BASE      = '/api/spm'
const DEV_TOKEN_URL = '/api/dev-token'

// ── Token cache (same pattern as findingsApi / admin/spm.js) ─────────────────
let _token = null
let _tokenExpiry = 0

async function getToken() {
  const now = Date.now() / 1000
  if (_token && _tokenExpiry > now + 60) return _token
  try {
    const res = await fetch(DEV_TOKEN_URL)
    if (!res.ok) throw new Error('token fetch failed')
    const data = await res.json()
    _token = data.token
    _tokenExpiry = now + (data.expires_in || 86400)
    return _token
  } catch {
    return null
  }
}

/**
 * Reset the module-level token cache.  Exposed for tests; production code
 * should never need to call this.  Vitest's vi.stubGlobal('fetch', ...) does
 * not clear this cache between tests, so without an explicit reset a stubbed
 * token from an earlier test will survive into the next and the `getToken()`
 * branch that calls fetch('/api/dev-token') is never exercised.
 */
export function _resetTokenCacheForTests() {
  _token = null
  _tokenExpiry = 0
}

// ── Error shape (matches admin/api/spm.js _errFrom) ───────────────────────────
function _errFrom(res, body) {
  const detail = body?.detail ?? null
  if (detail && typeof detail === 'object') {
    const e = new Error(detail.message || detail.error || `Request failed (${res.status})`)
    e.status = res.status
    e.detail = detail
    return e
  }
  const e = new Error(
    (typeof detail === 'string' && detail) || `Request failed (${res.status})`,
  )
  e.status = res.status
  return e
}

// ── Authenticated fetch helper ────────────────────────────────────────────────
//
// Exported because other admin modules (e.g. ActivityTab.jsx) need the
// same auth + base-URL handling for one-off `/agents/*` calls and there's
// no benefit to maintaining two copies of the dev-token + bearer plumbing.
export async function apiFetch(path, { method = 'GET', body, headers } = {}) {
  const token = await getToken()
  const res = await fetch(`${SPM_BASE}${path}`, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })

  // 204 No Content (DELETE path) — no body to parse.
  if (res.status === 204) {
    if (!res.ok) throw _errFrom(res, {})
    return null
  }

  const parsed = await res.json().catch(() => ({}))
  if (!res.ok) throw _errFrom(res, parsed)
  return parsed
}

// ═══════════════════════════════════════════════════════════════════════════════
// Connector catalog (schema-driven Add / Configure modal)
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Fetch the full list of connector types known to the server (21 vendors).
 * Each item has `{ key, label, category, vendor, icon_hint, description,
 * fields: FieldSpec[] }` — the `fields` list drives <SchemaForm>.
 *
 * Cached for the lifetime of the page since the schema is static per
 * deploy; a hard reload is the intended invalidation path.
 */
let _connectorTypesCache = null
export async function getConnectorTypes() {
  if (_connectorTypesCache) return _connectorTypesCache
  const data = await apiFetch(`/integrations/connector-types`)
  _connectorTypesCache = Array.isArray(data) ? data : []
  return _connectorTypesCache
}

/** Test-only cache reset — same pattern as `_resetTokenCacheForTests`. */
export function _resetConnectorTypesCacheForTests() {
  _connectorTypesCache = null
}

// ═══════════════════════════════════════════════════════════════════════════════
// List / metrics
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * List integrations.  All filters are optional.
 *
 * @param {object} [opts]
 * @param {string} [opts.category]  e.g. 'AI Providers'.  'All Categories' is
 *        treated as no filter (matches the dropdown label in Integrations.jsx).
 * @param {string} [opts.status]    e.g. 'Healthy'.  'All Statuses' → no filter.
 * @param {string} [opts.q]         case-insensitive name/description search.
 * @returns {Promise<IntegrationSummary[]>}
 */
export async function listIntegrations({ category, status, q } = {}) {
  const p = new URLSearchParams()
  if (category && category !== 'All Categories') p.set('category', category)
  if (status   && status   !== 'All Statuses'  ) p.set('status',   status)
  if (q        && q.trim())                      p.set('q',        q.trim())
  const qs = p.toString()
  const data = await apiFetch(`/integrations${qs ? `?${qs}` : ''}`)
  return Array.isArray(data) ? data : []
}

/**
 * Top-of-page KPIs:
 *   { total, connected, healthy, needs_attention, failed_syncs_24h }
 */
export async function getIntegrationsMetrics() {
  return apiFetch(`/integrations/metrics`)
}

// ═══════════════════════════════════════════════════════════════════════════════
// CRUD
// ═══════════════════════════════════════════════════════════════════════════════

/** Fetch one integration's full detail (all nested tab fields). */
export async function getIntegration(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}`)
}

/**
 * Create a new integration.  Admin-only on the server.
 *
 * @param {object} body
 * @param {string} body.name
 * @param {string} body.category
 * @param {string} [body.auth_method='API Key']
 * @param {string} [body.environment='Production']
 * @param {string} [body.status='Not Configured']
 * @param {boolean} [body.enabled=true]
 * @param {string} [body.owner]
 * @param {string} [body.owner_display]
 * @param {string} [body.description]
 * @param {string} [body.vendor]
 * @param {string[]} [body.tags]
 * @param {object} [body.config]
 * @returns {Promise<IntegrationDetail>}
 */
export async function createIntegration(body) {
  return apiFetch(`/integrations`, { method: 'POST', body })
}

/** PATCH top-level fields.  Admin-only on the server. */
export async function updateIntegration(id, patch) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: patch,
  })
}

/** Hard delete.  Admin-only.  Returns null on success (204). */
export async function deleteIntegration(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab reads (one endpoint per tab so the detail panel can lazy-load)
// ═══════════════════════════════════════════════════════════════════════════════

export async function getIntegrationOverview(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/overview`)
}
export async function getIntegrationConnection(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/connection`)
}
export async function getIntegrationAuth(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/auth`)
}
export async function getIntegrationCoverage(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/coverage`)
}
export async function getIntegrationActivity(id, { limit = 50 } = {}) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/activity?limit=${limit}`)
}
export async function getIntegrationWorkflows(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/workflows`)
}
/** Admin/auditor-gated on the server — plain users get 403. */
export async function getIntegrationLogs(id, { limit = 200 } = {}) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/logs?limit=${limit}`)
}
export async function getIntegrationDocs(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/docs`)
}

// ═══════════════════════════════════════════════════════════════════════════════
// Actions (all admin-only on the server)
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Update the primary API key and/or non-secret config knobs (e.g. model).
 *
 * @param {string} id
 * @param {object} body
 * @param {string} [body.api_key]  plain-text secret (server base64-encodes)
 * @param {object} [body.config]   merged into integrations.config JSONB
 * @returns {Promise<IntegrationDetail>}
 */
export async function configureIntegration(id, body) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/configure`, {
    method: 'POST',
    body,
  })
}

/**
 * Vendor health check.  Returns `{ ok, message, latency_ms }`.
 * Today this is a stub that just checks for credential presence; production
 * would POST to the vendor's /v1/models or equivalent.
 */
export async function testIntegration(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/test`, { method: 'POST' })
}

export async function enableIntegration(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/enable`, { method: 'POST' })
}
export async function disableIntegration(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/disable`, { method: 'POST' })
}

/**
 * Rotate the primary api_key.  Server requires body.api_key to be set.
 */
export async function rotateCredentials(id, { api_key }) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/rotate-credentials`, {
    method: 'POST',
    body: { api_key },
  })
}

/**
 * Manual sync trigger.  Bumps last_sync on the connection row.
 * Returns `{ ok: true, last_sync_full }`.
 */
export async function syncIntegration(id) {
  return apiFetch(`/integrations/${encodeURIComponent(id)}/sync`, { method: 'POST' })
}

// ═══════════════════════════════════════════════════════════════════════════════
// Bootstrap (admin-only, idempotent)
//
// Re-seeds the 18 integrations rows from services/spm_api/
// integrations_seed_data.py.  Safe to call on every deploy — it's a merge,
// not a replace.  Usually invoked via `make bootstrap-integrations` but
// exposed here for an Admin UI "re-bootstrap" button.
// ═══════════════════════════════════════════════════════════════════════════════

export async function bootstrapIntegrations() {
  return apiFetch(`/integrations/bootstrap`, { method: 'POST' })
}
