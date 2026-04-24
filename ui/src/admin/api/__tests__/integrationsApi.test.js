/**
 * integrationsApi.test.js
 * ───────────────────────
 * Unit tests for ../integrationsApi.js.  All fetch is mocked — no real HTTP.
 *
 * Mirrors the pattern from ui/src/api/__tests__/findingsApi.test.js:
 *
 *   1. vi.stubGlobal('fetch', mockFetch([...]))
 *   2. the first mocked response is always the /api/dev-token fetch
 *   3. the second (and later) responses feed the actual API call(s)
 *
 * The module keeps a top-level token cache that vitest does NOT clear
 * between tests — _resetTokenCacheForTests() is exported for that reason.
 * Forgetting the reset yields the confusing symptom of the token-fetch
 * mock never being consumed (the cached token short-circuits the branch)
 * and the API-call mock being returned for the FIRST fetch, breaking
 * every URL assertion downstream.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  _resetTokenCacheForTests,
  _resetConnectorTypesCacheForTests,
  listIntegrations,
  getIntegrationsMetrics,
  getIntegration,
  createIntegration,
  updateIntegration,
  deleteIntegration,
  getIntegrationOverview,
  getIntegrationConnection,
  getIntegrationAuth,
  getIntegrationCoverage,
  getIntegrationActivity,
  getIntegrationWorkflows,
  getIntegrationLogs,
  getIntegrationDocs,
  configureIntegration,
  testIntegration,
  enableIntegration,
  disableIntegration,
  rotateCredentials,
  syncIntegration,
  bootstrapIntegrations,
  getConnectorTypes,
} from '../integrationsApi.js'

// ── Helpers ────────────────────────────────────────────────────────────────────

const MOCK_TOKEN_RESPONSE = {
  token: 'header.eyJzdWIiOiJ0ZXN0Iiwicm9sZXMiOlsic3BtOmFkbWluIl19.sig',
  expires_in: 86400,
}

/**
 * Queue-based fetch mock.  Hands out responses in insertion order, sticking
 * the last one if a caller over-consumes.  The response shape is a partial
 * Response — { ok, status, body } — and supports `status: 204` for the
 * DELETE path that returns no content.
 */
function mockFetch(responses) {
  let i = 0
  return vi.fn().mockImplementation(() => {
    const resp = responses[i] ?? responses[responses.length - 1]
    i++
    return Promise.resolve({
      ok: resp.ok ?? true,
      status: resp.status ?? 200,
      // apiFetch calls res.json().catch(() => ({})), so for 204 we can just
      // return a body-less JSON resolution and let the code path drop it.
      json: () => Promise.resolve(resp.body ?? {}),
    })
  })
}

/** Return the single fetch call whose URL contains `needle`. */
function findCall(needle) {
  const hit = fetch.mock.calls.find(([url]) => String(url).includes(needle))
  if (!hit) throw new Error(`No fetch call matched ${needle}`)
  return hit
}

/** All the API endpoints live under `/api/spm/integrations`. */
const BASE = '/api/spm/integrations'

// ── Lifecycle ──────────────────────────────────────────────────────────────────

beforeEach(() => {
  // Vitest does NOT clear the module-level _token cache between tests.  Without
  // this reset the first test leaves a cached token in place and the rest of
  // the suite short-circuits the token fetch — which means the first mock
  // entry (meant for /api/dev-token) gets handed to the FIRST API call
  // instead, and every URL assertion fails.
  _resetTokenCacheForTests()
  _resetConnectorTypesCacheForTests()
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ═══════════════════════════════════════════════════════════════════════════════
// List / metrics
// ═══════════════════════════════════════════════════════════════════════════════

describe('listIntegrations', () => {
  it('GETs /integrations with no query string when no filters are passed', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },
    ]))
    await listIntegrations()
    const [url, opts] = findCall('/integrations')
    expect(url).toBe(`${BASE}`)
    expect(opts.method ?? 'GET').toBe('GET')
    expect(opts.headers.Authorization).toMatch(/^Bearer /)
  })

  it('serialises category, status, and q into the query string', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },
    ]))
    await listIntegrations({ category: 'AI Providers', status: 'Healthy', q: 'anthropic' })
    const [url] = findCall('/integrations?')
    expect(url).toContain('category=AI+Providers')
    expect(url).toContain('status=Healthy')
    expect(url).toContain('q=anthropic')
  })

  it('drops "All Categories" / "All Statuses" sentinels', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },
    ]))
    await listIntegrations({ category: 'All Categories', status: 'All Statuses' })
    const [url] = findCall('/integrations')
    expect(url).not.toContain('category=')
    expect(url).not.toContain('status=')
  })

  it('trims whitespace from q and drops it if empty', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },
    ]))
    await listIntegrations({ q: '   ' })
    const [url] = findCall('/integrations')
    expect(url).not.toContain('q=')
  })

  it('returns [] when the server returns a non-array (defensive)', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { unexpected: 'shape' } },
    ]))
    const result = await listIntegrations()
    expect(result).toEqual([])
  })

  it('throws a status-annotated error on 500', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { ok: false, status: 500, body: { detail: 'boom' } },
    ]))
    await expect(listIntegrations()).rejects.toMatchObject({
      status: 500,
      message: 'boom',
    })
  })
})

describe('getIntegrationsMetrics', () => {
  it('GETs /integrations/metrics', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { total: 18, connected: 12, healthy: 9, needs_attention: 3, failed_syncs_24h: 1 } },
    ]))
    const m = await getIntegrationsMetrics()
    expect(m.total).toBe(18)
    const [url] = findCall('/integrations/metrics')
    expect(url).toBe(`${BASE}/metrics`)
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// CRUD
// ═══════════════════════════════════════════════════════════════════════════════

describe('getIntegration', () => {
  it('URL-encodes the id path segment', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'int-001', name: 'Anthropic' } },
    ]))
    // intentionally hostile id with a slash to confirm encodeURIComponent is used
    await getIntegration('int/001')
    const [url] = findCall('/integrations/')
    expect(url).toBe(`${BASE}/int%2F001`)
  })
})

describe('createIntegration', () => {
  it('POSTs to /integrations with the body JSON-stringified', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'int-new', name: 'NewCo' } },
    ]))
    await createIntegration({ name: 'NewCo', category: 'AI Providers' })
    const [url, opts] = findCall('/integrations')
    expect(url).toBe(`${BASE}`)
    expect(opts.method).toBe('POST')
    expect(opts.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(opts.body)).toEqual({ name: 'NewCo', category: 'AI Providers' })
  })
})

describe('updateIntegration', () => {
  it('PATCHes /integrations/{id} with the patch body', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'int-001', enabled: false } },
    ]))
    await updateIntegration('int-001', { enabled: false })
    const [url, opts] = findCall('/integrations/int-001')
    expect(url).toBe(`${BASE}/int-001`)
    expect(opts.method).toBe('PATCH')
    expect(JSON.parse(opts.body)).toEqual({ enabled: false })
  })
})

describe('deleteIntegration', () => {
  it('DELETEs /integrations/{id} and returns null on 204', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { ok: true, status: 204, body: {} },
    ]))
    const result = await deleteIntegration('int-001')
    expect(result).toBeNull()
    const [url, opts] = findCall('/integrations/int-001')
    expect(opts.method).toBe('DELETE')
    expect(url).toBe(`${BASE}/int-001`)
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// Tab reads
// ═══════════════════════════════════════════════════════════════════════════════

describe('tab readers', () => {
  // Table-driven: each row is [fn, suffix] pair.  Easier to maintain than
  // one describe-block per endpoint and catches any future mis-routing.
  const cases = [
    [getIntegrationOverview,    '/overview'  ],
    [getIntegrationConnection,  '/connection'],
    [getIntegrationAuth,        '/auth'      ],
    [getIntegrationCoverage,    '/coverage'  ],
    [getIntegrationWorkflows,   '/workflows' ],
    [getIntegrationDocs,        '/docs'      ],
  ]

  for (const [fn, suffix] of cases) {
    it(`${fn.name} GETs /integrations/{id}${suffix}`, async () => {
      vi.stubGlobal('fetch', mockFetch([
        { body: MOCK_TOKEN_RESPONSE },
        { body: {} },
      ]))
      await fn('int-001')
      const [url, opts] = findCall(suffix)
      expect(url).toBe(`${BASE}/int-001${suffix}`)
      expect(opts.method ?? 'GET').toBe('GET')
    })
  }

  it('getIntegrationActivity uses default limit=50', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },
    ]))
    await getIntegrationActivity('int-001')
    const [url] = findCall('/activity')
    expect(url).toBe(`${BASE}/int-001/activity?limit=50`)
  })

  it('getIntegrationActivity honours custom limit', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },
    ]))
    await getIntegrationActivity('int-001', { limit: 10 })
    const [url] = findCall('/activity')
    expect(url).toBe(`${BASE}/int-001/activity?limit=10`)
  })

  it('getIntegrationLogs uses default limit=200', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },
    ]))
    await getIntegrationLogs('int-001')
    const [url] = findCall('/logs')
    expect(url).toBe(`${BASE}/int-001/logs?limit=200`)
  })

  it('getIntegrationLogs propagates 403 with status attached', async () => {
    // Auditor/admin gated; a plain viewer should see a real 403 surface.
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { ok: false, status: 403, body: { detail: 'forbidden' } },
    ]))
    await expect(getIntegrationLogs('int-001')).rejects.toMatchObject({
      status: 403,
    })
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// Actions
// ═══════════════════════════════════════════════════════════════════════════════

describe('configureIntegration', () => {
  it('POSTs to /configure with api_key + config merged into the body', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'int-001', enabled: true } },
    ]))
    await configureIntegration('int-001', {
      api_key: 'sk-ant-test',
      config: { model: 'claude-3-opus' },
    })
    const [url, opts] = findCall('/configure')
    expect(url).toBe(`${BASE}/int-001/configure`)
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({
      api_key: 'sk-ant-test',
      config: { model: 'claude-3-opus' },
    })
  })
})

describe('testIntegration', () => {
  it('POSTs to /test with no body', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { ok: true, message: 'ok', latency_ms: 12 } },
    ]))
    const r = await testIntegration('int-001')
    expect(r.ok).toBe(true)
    const [url, opts] = findCall('/test')
    expect(url).toBe(`${BASE}/int-001/test`)
    expect(opts.method).toBe('POST')
    // apiFetch only sets Content-Type when a body is present; without one,
    // the request should not carry a body property.
    expect(opts.body).toBeUndefined()
  })
})

describe('enable / disable', () => {
  it('enableIntegration POSTs to /enable', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'int-001', enabled: true } },
    ]))
    await enableIntegration('int-001')
    const [url, opts] = findCall('/enable')
    expect(url).toBe(`${BASE}/int-001/enable`)
    expect(opts.method).toBe('POST')
  })

  it('disableIntegration POSTs to /disable', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'int-001', enabled: false } },
    ]))
    await disableIntegration('int-001')
    const [url, opts] = findCall('/disable')
    expect(url).toBe(`${BASE}/int-001/disable`)
    expect(opts.method).toBe('POST')
  })
})

describe('rotateCredentials', () => {
  it('POSTs to /rotate-credentials with { api_key }', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'int-001' } },
    ]))
    await rotateCredentials('int-001', { api_key: 'sk-new' })
    const [url, opts] = findCall('/rotate-credentials')
    expect(url).toBe(`${BASE}/int-001/rotate-credentials`)
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ api_key: 'sk-new' })
  })
})

describe('syncIntegration', () => {
  it('POSTs to /sync and returns the server payload', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { ok: true, last_sync_full: '2026-04-23T00:00:00Z' } },
    ]))
    const r = await syncIntegration('int-001')
    expect(r.ok).toBe(true)
    expect(r.last_sync_full).toBe('2026-04-23T00:00:00Z')
    const [url, opts] = findCall('/sync')
    expect(url).toBe(`${BASE}/int-001/sync`)
    expect(opts.method).toBe('POST')
  })
})

describe('bootstrapIntegrations', () => {
  it('POSTs to /integrations/bootstrap', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { ok: true, merged: 18 } },
    ]))
    await bootstrapIntegrations()
    const [url, opts] = findCall('/bootstrap')
    expect(url).toBe(`${BASE}/bootstrap`)
    expect(opts.method).toBe('POST')
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// Auth / token handling
// ═══════════════════════════════════════════════════════════════════════════════

describe('auth header', () => {
  it('fetches /api/dev-token once and caches the token across calls', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [] },  // first list
      { body: [] },  // second list — no second token fetch expected
    ]))
    await listIntegrations()
    await listIntegrations()
    const tokenCalls = fetch.mock.calls.filter(([url]) => String(url).includes('/api/dev-token'))
    expect(tokenCalls).toHaveLength(1)
  })

  it('omits Authorization when the token fetch fails', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { ok: false, status: 500, body: {} },   // token endpoint fails
      { body: [] },                            // list call still goes through
    ]))
    await listIntegrations()
    const [, opts] = findCall('/integrations')
    expect(opts.headers.Authorization).toBeUndefined()
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// getConnectorTypes — vendor catalog for the schema-driven modals
// ═══════════════════════════════════════════════════════════════════════════════

describe('getConnectorTypes', () => {
  it('GETs /integrations/connector-types and returns the array', async () => {
    const types = [
      { key: 'postgres', label: 'PostgreSQL', category: 'Data / Storage', fields: [] },
      { key: 'openai',   label: 'OpenAI',     category: 'AI Providers',   fields: [] },
    ]
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: types },
    ]))
    const result = await getConnectorTypes()
    const [url] = findCall('/integrations/connector-types')
    expect(url).toBe(`${BASE}/connector-types`)
    expect(result).toEqual(types)
  })

  it('caches the result across calls (no second round-trip)', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: [{ key: 'redis', label: 'Redis', category: 'Data / Storage', fields: [] }] },
    ]))
    const a = await getConnectorTypes()
    const b = await getConnectorTypes()
    expect(a).toBe(b)
    // Only two fetches total: dev-token + one connector-types GET.
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('returns [] when the server returns a non-array (defensive)', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { unexpected: 'shape' } },
    ]))
    expect(await getConnectorTypes()).toEqual([])
  })
})
