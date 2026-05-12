/**
 * findingsApi.js
 * ──────────────
 * REST client for the /api/v1/findings endpoints on the
 * agent-orchestrator-service.
 *
 * Auth: Keycloak Bearer JWT obtained via getToken() from ui/src/api.js.
 * Base URL: /api/v1  (proxied to localhost:8094 in dev by vite.config.js)
 */

import { getToken } from '../api.js'

const BASE = '/api/v1'

// ── Authenticated fetch helper ────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const token = await getToken()
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const msg  = body.detail?.message || body.detail || `HTTP ${res.status}`
    throw Object.assign(new Error(String(msg)), { status: res.status, body })
  }
  return res.json()
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

function timeAgo(iso) {
  if (!iso) return '—'
  const delta = (Date.now() - new Date(iso).getTime()) / 1000
  if (delta < 60)    return `${Math.round(delta)}s ago`
  if (delta < 3600)  return `${Math.floor(delta / 60)}m ago`
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`
  return `${Math.floor(delta / 86400)}d ago`
}

function formatFull(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    })
  } catch {
    return iso
  }
}

function guessAssetType(asset) {
  if (!asset) return 'Agent'
  const a = asset.toLowerCase()
  if (a.includes('model') || a.includes('gpt') || a.includes('claude') ||
      a.includes('llm')   || a.includes('embedding'))              return 'Model'
  if (a.includes('tool')  || a.includes('func') || a.includes('api')) return 'Tool'
  if (a.includes('db')    || a.includes('data') || a.includes('store') ||
      a.includes('record') || a.includes('index'))                 return 'Data'
  return 'Agent'
}

// ── Normalizer ────────────────────────────────────────────────────────────────

/**
 * Normalize a raw API finding to the internal UI shape.
 *
 * Preserves ALL new AI-enrichment fields AND fills legacy-compat fields so
 * existing panel sections (Root Cause, Context Snapshot, etc.) keep working.
 */
export function normalizeFinding(f) {
  if (!f) return null

  const severity = capitalize(f.severity) || 'Low'
  const status   = capitalize(f.status)   || 'Open'

  // Evidence: always normalize to an array of strings
  const evidenceList = Array.isArray(f.evidence)
    ? f.evidence.map(e => (typeof e === 'string' ? e : JSON.stringify(e, null, 2)))
    : []

  return {
    // ── Core identity ─────────────────────────────────────────────────────
    id:          f.id,
    batch_hash:  f.batch_hash,
    title:       f.title        || 'Untitled Finding',
    type:        f.source       || 'Threat Hunt',
    severity,
    status,
    tenant_id:   f.tenant_id,

    // ── Asset ─────────────────────────────────────────────────────────────
    // Treat bare "unknown" (legacy default) the same as missing — fall back
    // to source tag or the Threat Hunting AI Agent label.
    asset: (() => {
      const raw = f.asset && f.asset.toLowerCase() !== 'unknown' ? f.asset : null
      const name = raw || (f.source === 'threat_hunt' ? 'Threat Hunting AI Agent' : null)
                       || f.tenant_id || 'Unknown'
      return { name, type: guessAssetType(name) }
    })(),
    // True only when the API returned a real, non-placeholder asset name.
    // Quick Links use this to disable navigation that would land on blank pages.
    hasRealAsset: !!(f.asset && f.asset.toLowerCase() !== 'unknown'),

    // ── Description / timing / environment ───────────────────────────────
    description:   f.description || f.hypothesis || '',
    timestamp:     timeAgo(f.created_at    || f.timestamp),
    timestampFull: formatFull(f.created_at || f.timestamp),
    environment:   capitalize(f.environment) || 'Production',
    owner:         undefined,

    // ── Legacy-compat fields (existing panel sections use these) ──────────
    rootCause:       f.hypothesis  || f.description || '',
    contextSnippet:  evidenceList.join('\n'),
    triggeredPolicies: Array.isArray(f.triggered_policies) ? f.triggered_policies
                       : Array.isArray(f.ttps)             ? f.ttps
                       : [],
    // recommendedActions are stored as strings — rendered differently in
    // the new panel; we keep an empty array for the legacy section
    recommendedActions: [],
    timeline:          [], // API v1 doesn't return timeline events yet

    // ── New AI-enrichment fields ──────────────────────────────────────────
    confidence:          f.confidence         ?? null,
    risk_score:          f.risk_score         ?? null,
    hypothesis:          f.hypothesis         ?? null,
    evidence:            evidenceList,
    correlated_events:   Array.isArray(f.correlated_events)   ? f.correlated_events   : [],
    correlated_findings: Array.isArray(f.correlated_findings) ? f.correlated_findings : [],
    policy_signals:      Array.isArray(f.policy_signals)      ? f.policy_signals      : [],
    recommended_actions: Array.isArray(f.recommended_actions) ? f.recommended_actions : [],
    should_open_case:    f.should_open_case ?? false,
    case_id:             f.case_id          ?? null,
    source:              f.source           ?? null,
    ttps:                Array.isArray(f.ttps) ? f.ttps : [],
    created_at:          f.created_at,
    updated_at:          f.updated_at,
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * List findings with optional filters.
 *
 * Returns { items: NormalizedFinding[], total, limit, offset }
 */
export async function listFindings({
  severity, status, asset, min_risk_score,
  from_time, to_time, has_case,
  limit = 50, offset = 0, sort_by,
} = {}) {
  const p = new URLSearchParams()

  if (severity  && severity  !== 'All Severity') p.set('severity',  severity.toLowerCase())
  if (status    && status    !== 'All Status'  ) p.set('status',    status.toLowerCase())
  if (asset     && asset     !== 'All Types'   ) p.set('asset',     asset)
  if (min_risk_score  != null                  ) p.set('min_risk_score', min_risk_score)
  if (from_time                                ) p.set('from_time', from_time)
  if (to_time                                  ) p.set('to_time',   to_time)
  if (has_case  != null                        ) p.set('has_case',  has_case)
  if (sort_by                                  ) p.set('sort_by',   sort_by)
  p.set('limit',  String(limit))
  p.set('offset', String(offset))

  const qs   = p.toString()
  const data = await apiFetch(`/findings?${qs}`)
  return {
    items:  (data.items || []).map(normalizeFinding),
    total:  data.total  ?? 0,
    limit:  data.limit  ?? limit,
    offset: data.offset ?? offset,
  }
}

/** Fetch a single finding's full detail. */
export async function getFinding(id) {
  const data = await apiFetch(`/findings/${id}`)
  return normalizeFinding(data)
}

/**
 * Update a finding's status.
 * @param {string} id
 * @param {'open'|'investigating'|'resolved'} status   lowercase
 */
export async function updateFindingStatus(id, status) {
  return apiFetch(`/findings/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status: status.toLowerCase() }),
  })
}

/**
 * Link an existing case to a finding.
 * @param {string} id       - finding id
 * @param {string} case_id  - case id
 */
export async function linkFindingCase(id, case_id) {
  return apiFetch(`/findings/${id}/link-case`, {
    method: 'POST',
    body: JSON.stringify({ case_id }),
  })
}

// ── Audit Alerts ─────────────────────────────────────────────────────────────

const ALERT_CATEGORY = {
  guard_model_block:           'Prompt Security',
  lexical_block:               'Prompt Security',
  obfuscation_block:           'Prompt Security',
  opa_prompt_block:            'Prompt Security',
  model_gate_block:            'Model Registry',
  output_blocked:              'Output Security',
  output_redacted:             'Output Security',
  secret_in_output:            'Output Security',
  memory_injection_attempt:    'Memory & Retrieval',
  memory_integrity_violation:  'Memory & Retrieval',
  context_tampering_detected:  'Memory & Retrieval',
  tool_blocked:                'Tool & Agent',
  tool_approval_requested:     'Tool & Agent',
  agent_frozen_skip:           'Tool & Agent',
  cep_critical:                'Behavioral',
  cep_high:                    'Behavioral',
  cep_medium:                  'Behavioral',
  cep_low:                     'Behavioral',
}

function normalizeAlert(a) {
  const category = ALERT_CATEGORY[a.event_type] || 'Security Event'
  return {
    id:          a.id,
    source:      'audit',
    category,
    event_type:  a.event_type,
    severity:    a.severity,
    component:   a.component || '',
    session_id:  a.session_id || '',
    tenant_id:   a.tenant_id,
    details:     a.details || {},
    status:      a.status || 'new',
    created_at:  a.created_at,
    ts:          a.ts,
    title:       `${category}: ${a.event_type.replace(/_/g, ' ')}`,
    description: a.component ? `Detected by ${a.component}` : 'Security event detected',
    time_ago:    timeAgo(a.created_at),
    time_full:   formatFull(a.created_at),
  }
}

/**
 * Fetch audit alerts from /api/v1/alerts.
 * @param {Object} params  - optional filters: severity, event_type, status, tenant_id, limit, offset
 */
export async function listAlerts(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  ).toString()
  const data = await apiFetch(`/alerts${qs ? `?${qs}` : ''}`)
  return (data.items || []).map(normalizeAlert)
}

/**
 * Update an alert's status (acknowledge / suppress).
 * @param {string} id
 * @param {'new'|'acknowledged'|'suppressed'} status
 */
export async function updateAlertStatus(id, status) {
  return apiFetch(`/alerts/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}
