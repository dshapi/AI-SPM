/**
 * integrationsViewModel.test.js
 * ──────────────────────────────
 * The view-model adapter sits between the backend (which has nested
 * `connection` / `auth` / `coverage` / `activity` / `workflows`) and the
 * page renderers (which were built against a flat mock shape).  Getting
 * this mapping wrong is the most likely way to crash the detail panel
 * at render time, so the tests pin the contract tightly.
 */

import { describe, it, expect } from 'vitest'
import { summaryToListRow, detailToViewModel } from '../integrationsViewModel.js'

describe('summaryToListRow', () => {
  const MINIMAL = {
    id: 'int-1',
    name: 'Anthropic',
    category: 'AI Providers',
    environment: 'Production',
    enabled: true,
    status: 'Healthy',
    authMethod: 'API Key',
  }

  it('returns null for null input', () => {
    expect(summaryToListRow(null)).toBeNull()
  })

  it('passes through camelCase fields from the backend', () => {
    const row = summaryToListRow({
      ...MINIMAL,
      ownerDisplay: 'Raj Patel',
      lastSync:     '4m ago',
      avgLatency:   '218ms',
      healthHistory: ['ok', 'ok', 'warn'],
    })
    expect(row.ownerDisplay).toBe('Raj Patel')
    expect(row.lastSync).toBe('4m ago')
    expect(row.avgLatency).toBe('218ms')
    expect(row.healthHistory).toEqual(['ok', 'ok', 'warn'])
  })

  it('coerces null lastSync to "Never" so IntegrationRow.includes() is safe', () => {
    // This is the single most important defensive default — IntegrationRow
    // does `int.lastSync.includes('2d')` without a null check, and a real
    // null from the server would crash the list.
    const row = summaryToListRow({ ...MINIMAL, lastSync: null })
    expect(row.lastSync).toBe('Never')
  })

  it('derives a 2-char abbrev from a multi-word name', () => {
    const row = summaryToListRow({ ...MINIMAL, name: 'Amazon Bedrock' })
    expect(row.abbrev).toBe('AB')
  })

  it('derives a 2-char abbrev from a single-word name', () => {
    const row = summaryToListRow({ ...MINIMAL, name: 'Anthropic' })
    expect(row.abbrev).toBe('AN')
  })

  it('prefers the backend-provided abbrev over the derived one', () => {
    const row = summaryToListRow({ ...MINIMAL, name: 'Anthropic', abbrev: 'An' })
    expect(row.abbrev).toBe('An')
  })

  it('defaults missing owner_display to the owner or an em-dash', () => {
    expect(summaryToListRow({ ...MINIMAL, owner: 'raj' }).ownerDisplay).toBe('raj')
    expect(summaryToListRow({ ...MINIMAL }).ownerDisplay).toBe('—')
  })

  it('treats non-array tags defensively', () => {
    expect(summaryToListRow({ ...MINIMAL, tags: null }).tags).toEqual([])
    expect(summaryToListRow({ ...MINIMAL, tags: 'not-an-array' }).tags).toEqual([])
  })

  it('passes through connectorType so the schema-driven Configure modal sees it', () => {
    // Regression guard: when this field was dropped, the modal would
    // ignore the registry key on every row (even after Alembic 004
    // backfilled it) and fall back to the legacy 3-field form for
    // postgres / redis / kafka — which doesn't expose host / port /
    // database / sslmode at all.  The bug only surfaced once a user
    // tried to Test Connection on a row whose probe needed a config
    // key (postgres host) the legacy form had no way to enter.
    const camel = summaryToListRow({ ...MINIMAL, connectorType: 'postgres' })
    expect(camel.connectorType).toBe('postgres')

    // Defensive: accept snake_case too, in case anything ever serialises
    // this without `populate_by_name=True` / by_alias=True.
    const snake = summaryToListRow({ ...MINIMAL, connector_type: 'redis' })
    expect(snake.connectorType).toBe('redis')

    // Default to null when the backend omits it (legacy unmigrated row).
    const none = summaryToListRow({ ...MINIMAL })
    expect(none.connectorType).toBeNull()
  })

  it('accepts snake_case auth_method as a fallback', () => {
    // The canonical alias is authMethod, but if a row ever slips through
    // with the raw Python attribute name (e.g. from a raw DB fixture),
    // the page shouldn't crash.
    const row = summaryToListRow({
      id: 'int-x', name: 'Test', category: 'AI Providers',
      environment: 'Production', enabled: true, status: 'Healthy',
      auth_method: 'IAM Role',
    })
    expect(row.authMethod).toBe('IAM Role')
  })
})

describe('detailToViewModel', () => {
  it('returns null for null input', () => {
    expect(detailToViewModel(null)).toBeNull()
  })

  it('flattens nested connection/auth/coverage/activity/workflows into the mock shape', () => {
    const vm = detailToViewModel({
      id: 'int-3', name: 'Anthropic', category: 'AI Providers',
      status: 'Healthy', authMethod: 'API Key', environment: 'Production', enabled: true,
      createdAt: '2026-03-01T00:00:00Z',
      lastModified: '2026-03-20T00:00:00Z',
      connection: {
        last_sync: '8m ago',
        last_sync_full: 'Apr 8 · 14:24 UTC',
        last_failed_sync: null,
        avg_latency: '245ms',
        uptime: '99.99%',
        health_history: ['ok', 'ok'],
      },
      auth: {
        token_expiry: 'Never (static key)',
        scopes: ['messages:write', 'models:read'],
        missing_scopes: [],
        setup_progress: null,
      },
      coverage: [
        { label: 'Execute model completions', enabled: true  },
        { label: 'Generate embeddings',       enabled: false },
      ],
      activity: [
        { ts: 'Apr 8 · 14:24 UTC', event: 'API key validated', result: 'Success', actor: 'System' },
      ],
      workflows: { playbooks: ['P1'], alerts: ['A1'], policies: [], cases: [] },
    })

    expect(vm.lastSyncFull).toBe('Apr 8 · 14:24 UTC')
    expect(vm.lastFailedSync).toBeNull()
    expect(vm.avgLatency).toBe('245ms')
    expect(vm.uptime).toBe('99.99%')
    expect(vm.healthHistory).toEqual(['ok', 'ok'])

    expect(vm.tokenExpiry).toBe('Never (static key)')
    expect(vm.scopes).toEqual(['messages:write', 'models:read'])
    expect(vm.missingScopes).toEqual([])
    expect(vm.setupProgress).toBeNull()

    expect(vm.capabilities).toHaveLength(2)
    expect(vm.capabilities[0]).toEqual({ label: 'Execute model completions', enabled: true })

    expect(vm.recentActivity).toHaveLength(1)
    expect(vm.recentActivity[0].result).toBe('Success')

    expect(vm.linkedWorkflows.playbooks).toEqual(['P1'])
    expect(vm.linkedWorkflows.alerts).toEqual(['A1'])
    expect(vm.linkedWorkflows.policies).toEqual([])
    expect(vm.linkedWorkflows.cases).toEqual([])
  })

  it('defaults token_expiry to "Not configured" string when auth is missing', () => {
    // Detail renderer calls .includes() on tokenExpiry — null or undefined
    // would throw.  This is a defensive contract.
    const vm = detailToViewModel({
      id: 'x', name: 'X', category: 'AI Providers',
      status: 'Not Configured', authMethod: 'API Key',
      environment: 'Production', enabled: false,
      auth: null,
    })
    expect(typeof vm.tokenExpiry).toBe('string')
    expect(vm.tokenExpiry).toBe('Not configured')
  })

  it('supplies empty arrays for missing coverage/activity/workflows', () => {
    const vm = detailToViewModel({
      id: 'x', name: 'X', category: 'AI Providers',
      status: 'Not Configured', authMethod: 'API Key',
      environment: 'Production', enabled: false,
    })
    expect(vm.capabilities).toEqual([])
    expect(vm.recentActivity).toEqual([])
    expect(vm.linkedWorkflows).toEqual({ playbooks: [], alerts: [], policies: [], cases: [] })
  })

  it('falls through to lastSync when connection.last_sync_full is absent', () => {
    const vm = detailToViewModel({
      id: 'x', name: 'X', category: 'AI Providers',
      status: 'Healthy', authMethod: 'API Key',
      environment: 'Production', enabled: true,
      lastSync: '4m ago',
      connection: null,
    })
    expect(vm.lastSyncFull).toBe('4m ago')  // falls back to the top-level lastSync
  })

  it('passes through the credentials array so Configure modal can read is_configured', () => {
    // Regression guard: if this array is dropped, IntegrationConfigureModal
    // falls back to "Not yet configured" even when the DB has a live key,
    // which is exactly the bug that shipped when this field was missing.
    const vm = detailToViewModel({
      id: 'int-3', name: 'Anthropic', category: 'AI Providers',
      status: 'Healthy', authMethod: 'API Key',
      environment: 'Production', enabled: true,
      credentials: [
        { credential_type: 'api_key', name: 'api_key', is_configured: true, value_hint: 'sk-a…UgAA' },
      ],
    })
    expect(Array.isArray(vm.credentials)).toBe(true)
    expect(vm.credentials).toHaveLength(1)
    expect(vm.credentials[0].is_configured).toBe(true)
    expect(vm.credentials[0].value_hint).toBe('sk-a…UgAA')
  })

  it('defaults credentials to an empty array when the backend omits it', () => {
    const vm = detailToViewModel({
      id: 'x', name: 'X', category: 'AI Providers',
      status: 'Not Configured', authMethod: 'API Key',
      environment: 'Production', enabled: false,
    })
    expect(vm.credentials).toEqual([])
  })
})
