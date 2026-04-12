/**
 * findingsApi.test.js
 * ────────────────────
 * Unit tests for normalizeFinding() and the API surface.
 * No real HTTP calls — all fetch is mocked via vi.stubGlobal.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { normalizeFinding, listFindings, updateFindingStatus, linkFindingCase } from '../findingsApi.js'

// ── normalizeFinding ───────────────────────────────────────────────────────────

describe('normalizeFinding', () => {
  it('capitalizes severity and status', () => {
    const f = normalizeFinding({ id: '1', batch_hash: 'bh', title: 'T', severity: 'critical', status: 'open', description: 'D', evidence: [], ttps: [], tenant_id: 't1' })
    expect(f.severity).toBe('Critical')
    expect(f.status).toBe('Open')
  })

  it('maps confidence and risk_score through unchanged', () => {
    const f = normalizeFinding({ id: '1', batch_hash: 'bh', title: 'T', severity: 'high', status: 'open', confidence: 0.91, risk_score: 0.87, evidence: [], ttps: [], tenant_id: 't1' })
    expect(f.confidence).toBe(0.91)
    expect(f.risk_score).toBe(0.87)
  })

  it('normalizes evidence list to array of strings', () => {
    const f = normalizeFinding({ id: '1', batch_hash: 'bh', title: 'T', severity: 'low', status: 'open', evidence: ['line1', { raw: 'obj' }], ttps: [], tenant_id: 't1' })
    expect(f.evidence).toHaveLength(2)
    expect(typeof f.evidence[0]).toBe('string')
    expect(typeof f.evidence[1]).toBe('string')
  })

  it('falls back to empty arrays for missing list fields', () => {
    const f = normalizeFinding({ id: '1', batch_hash: 'bh', title: 'T', severity: 'low', status: 'open', tenant_id: 't1' })
    expect(f.evidence).toEqual([])
    expect(f.correlated_findings).toEqual([])
    expect(f.policy_signals).toEqual([])
    expect(f.triggered_policies || f.ttps).toBeTruthy()
  })

  it('sets rootCause to hypothesis when available', () => {
    const f = normalizeFinding({ id: '1', batch_hash: 'bh', title: 'T', severity: 'high', status: 'open', hypothesis: 'H1', description: 'D1', tenant_id: 't1', evidence: [], ttps: [] })
    expect(f.rootCause).toBe('H1')
    expect(f.hypothesis).toBe('H1')
  })

  it('sets asset name from asset field', () => {
    const f = normalizeFinding({ id: '1', batch_hash: 'bh', title: 'T', severity: 'low', status: 'open', asset: 'CustomerSupport-GPT', tenant_id: 't1', evidence: [], ttps: [] })
    expect(f.asset.name).toBe('CustomerSupport-GPT')
  })

  it('guesses Model asset type for model-like names', () => {
    const f = normalizeFinding({ id: '1', batch_hash: 'bh', title: 'T', severity: 'low', status: 'open', asset: 'gpt-4-turbo', tenant_id: 't1', evidence: [], ttps: [] })
    expect(f.asset.type).toBe('Model')
  })

  it('returns null for null input', () => {
    expect(normalizeFinding(null)).toBeNull()
  })
})

// ── API calls ─────────────────────────────────────────────────────────────────

const MOCK_TOKEN_RESPONSE = { token: 'header.eyJzdWIiOiJ0ZXN0Iiwicm9sZXMiOlsiYWRtaW4iXX0.sig', expires_in: 86400 }

const MOCK_LIST_RESPONSE = {
  items: [
    { id: 'f-1', batch_hash: 'bh1', title: 'Test Finding', severity: 'high', status: 'open', description: 'D', evidence: [], ttps: [], tenant_id: 't1', confidence: 0.85, risk_score: 0.72 },
  ],
  total: 1,
  limit: 50,
  offset: 0,
}

function mockFetch(responses) {
  let callIndex = 0
  return vi.fn().mockImplementation((url) => {
    const resp = responses[callIndex] ?? responses[responses.length - 1]
    callIndex++
    return Promise.resolve({
      ok: resp.ok ?? true,
      status: resp.status ?? 200,
      json: () => Promise.resolve(resp.body),
    })
  })
}

describe('listFindings', () => {
  beforeEach(() => {
    // Reset token cache so every test gets a fresh token fetch
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: MOCK_LIST_RESPONSE  },
    ]))
  })
  afterEach(() => vi.restoreAllMocks())

  it('returns normalized findings', async () => {
    const result = await listFindings()
    expect(result.items).toHaveLength(1)
    expect(result.items[0].severity).toBe('High')
    expect(result.items[0].confidence).toBe(0.85)
    expect(result.total).toBe(1)
  })

  it('builds correct query string for severity filter', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { items: [], total: 0, limit: 50, offset: 0 } },
    ]))
    await listFindings({ severity: 'High', status: 'Open' })
    // Second fetch call is the actual findings request
    const calls = fetch.mock.calls
    const findingsCall = calls.find(([url]) => url.includes('/findings'))
    expect(findingsCall[0]).toContain('severity=high')
    expect(findingsCall[0]).toContain('status=open')
  })

  it('does not include "All Severity" in query string', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { items: [], total: 0, limit: 50, offset: 0 } },
    ]))
    await listFindings({ severity: 'All Severity' })
    const calls = fetch.mock.calls
    const findingsCall = calls.find(([url]) => url.includes('/findings'))
    expect(findingsCall[0]).not.toContain('severity=')
  })
})

describe('updateFindingStatus', () => {
  afterEach(() => vi.restoreAllMocks())

  it('sends PATCH with lowercase status', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'f-1', status: 'resolved' } },
    ]))
    await updateFindingStatus('f-1', 'Resolved')
    const calls = fetch.mock.calls
    const patchCall = calls.find(([url]) => url.includes('/status'))
    expect(patchCall[1].method).toBe('PATCH')
    expect(JSON.parse(patchCall[1].body)).toEqual({ status: 'resolved' })
  })
})

describe('linkFindingCase', () => {
  afterEach(() => vi.restoreAllMocks())

  it('sends POST to link-case endpoint', async () => {
    vi.stubGlobal('fetch', mockFetch([
      { body: MOCK_TOKEN_RESPONSE },
      { body: { id: 'f-1', case_id: 'case-123' } },
    ]))
    await linkFindingCase('f-1', 'case-123')
    const calls = fetch.mock.calls
    const postCall = calls.find(([url]) => url.includes('link-case'))
    expect(postCall[1].method).toBe('POST')
    expect(JSON.parse(postCall[1].body)).toEqual({ case_id: 'case-123' })
  })
})
