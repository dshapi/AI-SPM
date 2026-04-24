/**
 * integrationsViewModel.js
 * ────────────────────────
 * Adapters that translate spm-api responses into the flat mock-compatible
 * shape the Integrations page renderers were originally written against.
 *
 * Why a separate adapter file?
 *   - The IntegrationRow / IntegrationDetailPanel / RecentActivityTable
 *     renderers pre-date the backend and expect fields like `lastSyncFull`,
 *     `tokenExpiry`, `capabilities`, `recentActivity`, `linkedWorkflows`,
 *     `setupProgress` — all of which the backend delivers under nested
 *     objects (`connection`, `auth`, `coverage`, `activity`, `workflows`).
 *   - Doing the mapping inline in the page would couple presentation to
 *     transport.  A standalone adapter keeps the renderers dumb, lets us
 *     unit-test the mapping, and gives us one obvious place to add any
 *     future backfill logic (e.g. synthesising a `lastFailedSync` from
 *     recent activity if the connection row is null).
 *
 * Defensive defaults matter: IntegrationRow does `.lastSync.includes('2d')`
 * without a null guard, so a real `null` lastSync from the server would
 * throw at render.  We coerce to 'Never' here to keep the renderers
 * untouched.
 */

/**
 * Map a backend IntegrationSummary (list endpoint) to the flat shape
 * expected by IntegrationRow.  Safe to call with an already-flat object.
 */
export function summaryToListRow(s) {
  if (!s) return null
  return {
    id:           s.id,
    external_id:  s.external_id ?? null,
    name:         s.name,
    abbrev:       s.abbrev || deriveAbbrev(s.name),
    category:     s.category,
    status:       s.status || 'Not Configured',
    authMethod:   s.authMethod || s.auth_method || 'API Key',
    owner:        s.owner ?? null,
    ownerDisplay: s.ownerDisplay || s.owner_display || s.owner || '—',
    environment:  s.environment || 'Production',
    enabled:      !!s.enabled,
    description:  s.description || '',
    vendor:       s.vendor || '',
    tags:         Array.isArray(s.tags) ? s.tags : [],
    config:       s.config && typeof s.config === 'object' ? s.config : {},
    // ``IntegrationRow`` calls .includes on this string — coerce null → 'Never'
    // so we don't have to touch the renderer.
    lastSync:     s.lastSync || s.last_sync || 'Never',
    avgLatency:   s.avgLatency || s.avg_latency || null,
    uptime:       s.uptime || null,
    healthHistory: s.healthHistory || s.health_history || null,
  }
}

/**
 * Map a backend IntegrationDetail (detail endpoint) to the flat mock-shape
 * consumed by IntegrationDetailPanel.
 */
export function detailToViewModel(d) {
  if (!d) return null
  const base = summaryToListRow(d)
  const conn = d.connection || null
  const auth = d.auth       || null
  const wf   = d.workflows  || null

  return {
    ...base,
    createdAt:     d.createdAt     || d.created_at  || null,
    lastModified:  d.lastModified  || d.updated_at  || null,

    // Credentials — pass-through so the Configure modal can read
    // is_configured / value_hint without re-fetching.  Without this the
    // modal always renders "Not yet configured" even when the DB has a key.
    credentials: Array.isArray(d.credentials) ? d.credentials : [],

    // Connection-tab fields
    lastSyncFull:   conn?.last_sync_full   ?? base.lastSync,
    lastFailedSync: conn?.last_failed_sync ?? null,
    avgLatency:     conn?.avg_latency      ?? base.avgLatency,
    uptime:         conn?.uptime           ?? base.uptime,
    healthHistory:  conn?.health_history   ?? base.healthHistory ?? [],

    // Auth-tab fields — the renderer assumes string-ness for .includes()
    tokenExpiry:   auth?.token_expiry   || 'Not configured',
    scopes:        auth?.scopes         || [],
    missingScopes: auth?.missing_scopes || [],
    setupProgress: auth?.setup_progress || null,

    // Coverage-tab rename
    capabilities: (d.coverage || []).map(c => ({
      label:   c.label,
      enabled: !!c.enabled,
    })),

    // Activity-tab rename
    recentActivity: (d.activity || []).map(a => ({
      ts:     a.ts,
      event:  a.event,
      result: a.result || 'Info',
      actor:  a.actor  || null,
    })),

    // Workflows-tab rename + defensive defaults
    linkedWorkflows: {
      playbooks: wf?.playbooks || [],
      alerts:    wf?.alerts    || [],
      policies:  wf?.policies  || [],
      cases:     wf?.cases     || [],
    },
  }
}

/**
 * Turn an initials string out of a display name.  Used as a fallback when
 * the backend row is missing its 2-char abbrev (not all hand-added rows
 * will have one — the seed data does).
 */
function deriveAbbrev(name = '') {
  const parts = String(name).trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '??'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}
