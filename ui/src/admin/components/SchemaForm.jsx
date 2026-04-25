/**
 * SchemaForm.jsx
 * ──────────────
 * Schema-driven form renderer for integration connector types.
 *
 * Inputs
 *   • schema   — ConnectorType dict from GET /integrations/connector-types:
 *                `{ key, label, category, fields: FieldSpec[], ... }`
 *   • value    — controlled form state; map of `{ [fieldKey]: value, ... }`.
 *                Only keys that appear in the schema are written back; unknown
 *                keys survive round-trips unchanged so the caller can keep
 *                extra state (e.g. tags, notes) on the same dict.
 *   • onChange — called with the next value on every edit. Pure update —
 *                the caller owns the state.
 *   • existingCredentials — optional array of `{ credential_type, is_configured,
 *                value_hint }` from IntegrationDetail, used to render
 *                "Currently configured (••••xyz). Leave blank to keep."
 *                hints next to secret fields.
 *   • mode     — "create" | "configure".  In create mode, required fields
 *                show a red asterisk; in configure mode, secrets show the
 *                "leave blank to keep" placeholder and required is softened.
 *
 * FieldSpec contract (mirrors connector_registry.py FieldSpec)
 *   { key, label, type, required?, secret?, default?, placeholder?,
 *     options?, hint?, group? }
 *
 *   type →  "string"   → <input type=text>
 *           "integer"  → <input type=number step=1>
 *           "password" → <input type=password>
 *           "enum"     → <select> (needs options[])
 *           "textarea" → <textarea rows=6>
 *           "boolean"  → <input type=checkbox>
 *           "url"      → <input type=url>
 *
 * Grouping
 *   Fields declaring group="Connection" / "Credentials" / "Advanced" render
 *   under collapsible section headers.  Fields with no `group` land in
 *   "Connection" by default so authors don't have to specify it everywhere.
 *
 * Tests live alongside in __tests__/SchemaForm.test.jsx.  The key behaviors
 * under test: each field type renders the right widget; defaults are
 * seeded when value is empty; secret field in configure-mode shows the
 * leave-blank hint; onChange carries unrelated keys through untouched.
 */

import { useEffect, useMemo, useState } from 'react'
import { cn } from '../../lib/utils.js'
import { listIntegrations } from '../api/integrationsApi.js'

// ── enum_integration option resolution ────────────────────────────────────────
//
// FieldSpec.options_provider is one of a fixed set of identifiers the
// backend exposes — we resolve each to a (category, vendor) filter pair
// matching connector_registry.OPTIONS_PROVIDERS. Anything we don't know
// falls back to "show all" so a new provider added on the backend still
// gives the user something pickable instead of a blank list.

const OPTIONS_PROVIDERS = {
  ai_provider_integrations: { category: 'AI Providers', vendor: null },
  tavily_integrations:      { category: 'AI Providers', vendor: 'Tavily' },
}

function filterIntegrationsForProvider(all, providerName) {
  const spec = OPTIONS_PROVIDERS[providerName]
  if (!spec) return all
  return (all || []).filter(row => {
    if (spec.category && row.category !== spec.category) return false
    if (spec.vendor && (row.vendor || '').toLowerCase()
                       !== spec.vendor.toLowerCase()) return false
    return true
  })
}

// ── Section grouping ──────────────────────────────────────────────────────────

const GROUP_ORDER = ['Connection', 'Credentials', 'Advanced']
const DEFAULT_GROUP = 'Connection'

function groupFields(fields) {
  const buckets = new Map()
  for (const g of GROUP_ORDER) buckets.set(g, [])
  for (const f of fields || []) {
    const g = f.group && GROUP_ORDER.includes(f.group) ? f.group : DEFAULT_GROUP
    buckets.get(g).push(f)
  }
  return buckets
}

// ── Secret credential hint lookup ─────────────────────────────────────────────
// The backend returns `credentials: [{ credential_type, is_configured,
// value_hint }]` on IntegrationDetail.  We match by `credential_type` to
// the FieldSpec.key so a per-vendor secret (e.g. `api_token`) lights up
// the right hint.

function credentialFor(fieldKey, existingCredentials) {
  if (!Array.isArray(existingCredentials)) return null
  return existingCredentials.find(c => c?.credential_type === fieldKey) || null
}

// ── Widget renderers ──────────────────────────────────────────────────────────

const inputCls = cn(
  'w-full h-9 px-2.5 text-[12.5px] text-gray-800 bg-white',
  'border border-gray-200 rounded-lg',
  'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400',
  'placeholder:text-gray-300',
)
const selectCls = cn(
  'w-full h-9 px-2 text-[12.5px] text-gray-800 bg-white',
  'border border-gray-200 rounded-lg',
  'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400',
)

/**
 * Render a single FieldSpec.  Pure: reads from `value[field.key]` and calls
 * `onFieldChange(field.key, next)` on user input.  Secret fields in
 * configure mode render with a "leave blank to keep" placeholder when an
 * existing credential is present.
 */
function FieldRow({ field, value, onFieldChange, existingCredentials, mode,
                    integrationOptions }) {
  const v = value?.[field.key]
  const secretHint =
    field.secret && mode === 'configure'
      ? credentialFor(field.key, existingCredentials)
      : null
  const hasExistingSecret = !!secretHint?.is_configured
  const secretPlaceholder = hasExistingSecret
    ? `•••••• (leave blank to keep${secretHint?.value_hint ? ` — ${secretHint.value_hint}` : ''})`
    : field.placeholder

  // The hint text shown under the field.  Combines the author-provided hint
  // with an auto-generated "Currently configured" blurb for secrets.
  const computedHint = (() => {
    const parts = []
    if (hasExistingSecret) {
      parts.push(
        `Currently configured${secretHint?.value_hint ? ` (${secretHint.value_hint})` : ''}. Leave blank to keep as-is.`,
      )
    }
    if (field.hint) parts.push(field.hint)
    return parts.length ? parts.join(' ') : null
  })()

  let control = null
  switch (field.type) {
    case 'password':
      control = (
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={v ?? ''}
          onChange={e => onFieldChange(field.key, e.target.value)}
          placeholder={secretPlaceholder || ''}
          className={inputCls}
          data-testid={`field-${field.key}`}
        />
      )
      break
    case 'integer':
      control = (
        <input
          type="number"
          step={1}
          value={v === null || v === undefined || v === '' ? '' : v}
          onChange={e => {
            const raw = e.target.value
            // Empty string passes through as '' so the caller can drop empty
            // fields from the payload; a real number becomes a JS number.
            if (raw === '') onFieldChange(field.key, '')
            else {
              const n = Number(raw)
              onFieldChange(field.key, Number.isFinite(n) ? n : raw)
            }
          }}
          placeholder={field.placeholder || ''}
          className={inputCls}
          data-testid={`field-${field.key}`}
        />
      )
      break
    case 'enum':
      control = (
        <select
          value={v ?? ''}
          onChange={e => onFieldChange(field.key, e.target.value)}
          className={selectCls}
          data-testid={`field-${field.key}`}
        >
          {!field.required && <option value="">— Not set —</option>}
          {(field.options || []).map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      )
      break
    case 'enum_integration': {
      // Cross-reference to another integration row. Backend resolves the
      // FieldSpec.options_provider to a (category, vendor) filter; we do
      // the same lookup client-side over the cached integrations list
      // we fetched once at the SchemaForm level.
      const filtered = filterIntegrationsForProvider(
        integrationOptions.list, field.options_provider,
      )
      const loading = integrationOptions.loading
      const error   = integrationOptions.error
      const empty   = !loading && !error && filtered.length === 0
      control = (
        <select
          value={v ?? ''}
          onChange={e => onFieldChange(field.key, e.target.value)}
          className={selectCls}
          data-testid={`field-${field.key}`}
          disabled={loading || empty}
        >
          <option value="">
            {loading ? '— Loading…'
              : error ? '— Error loading integrations —'
              : empty ? '— No matching integrations configured yet —'
              : '— Select an integration —'}
          </option>
          {filtered.map(row => (
            <option key={row.id} value={row.id}>
              {row.name || row.id}
              {row.vendor ? ` · ${row.vendor}` : ''}
              {row.status && row.status !== 'Healthy' ? ` (${row.status})` : ''}
            </option>
          ))}
        </select>
      )
      break
    }
    case 'textarea':
      control = (
        <textarea
          rows={6}
          autoComplete="off"
          spellCheck={false}
          value={v ?? ''}
          onChange={e => onFieldChange(field.key, e.target.value)}
          placeholder={secretPlaceholder || field.placeholder || ''}
          className={cn(inputCls, 'h-auto py-2 font-mono text-[11px] leading-snug resize-y')}
          data-testid={`field-${field.key}`}
        />
      )
      break
    case 'boolean':
      control = (
        <label className="inline-flex items-center gap-2 text-[12px] text-gray-700 select-none">
          <input
            type="checkbox"
            checked={!!v}
            onChange={e => onFieldChange(field.key, e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500/30"
            data-testid={`field-${field.key}`}
          />
          <span>{field.placeholder || 'Enabled'}</span>
        </label>
      )
      break
    case 'url':
      control = (
        <input
          type="url"
          value={v ?? ''}
          onChange={e => onFieldChange(field.key, e.target.value)}
          placeholder={field.placeholder || ''}
          className={inputCls}
          data-testid={`field-${field.key}`}
        />
      )
      break
    case 'string':
    default:
      control = (
        <input
          type="text"
          value={v ?? ''}
          onChange={e => onFieldChange(field.key, e.target.value)}
          placeholder={field.placeholder || ''}
          className={inputCls}
          data-testid={`field-${field.key}`}
        />
      )
      break
  }

  return (
    <div>
      <label className="flex items-center gap-1.5 text-[10.5px] font-black uppercase tracking-[0.08em] text-gray-500 mb-1.5">
        <span>{field.label || field.key}</span>
        {field.required && mode === 'create' && (
          <span className="text-red-500 normal-case">*</span>
        )}
      </label>
      {control}
      {computedHint && (
        <p className="text-[10.5px] text-gray-400 mt-1 leading-snug">{computedHint}</p>
      )}
    </div>
  )
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * @param {object}   props
 * @param {object}   props.schema               connector-type dict from API
 * @param {object}   props.value                controlled field-values map
 * @param {(next: object) => void} props.onChange
 * @param {Array}    [props.existingCredentials] IntegrationDetail.credentials
 * @param {'create'|'configure'} [props.mode='configure']
 */
export function SchemaForm({
  schema,
  value,
  onChange,
  existingCredentials,
  mode = 'configure',
}) {
  const grouped = useMemo(() => groupFields(schema?.fields || []), [schema])

  // Fetch the integrations list once if any field is enum_integration.
  // Cached in component state so a connector with two enum_integration
  // fields (e.g. agent-runtime: Default LLM + Tavily) only fires one
  // request.
  const needsIntegrations = useMemo(
    () => (schema?.fields || []).some(f => f?.type === 'enum_integration'),
    [schema],
  )
  const [integrationOptions, setIntegrationOptions] = useState({
    loading: false, error: null, list: [],
  })
  useEffect(() => {
    if (!needsIntegrations) return
    let cancelled = false
    setIntegrationOptions(s => ({ ...s, loading: true, error: null }))
    listIntegrations()
      .then(rows => {
        if (cancelled) return
        setIntegrationOptions({ loading: false, error: null, list: rows || [] })
      })
      .catch(err => {
        if (cancelled) return
        setIntegrationOptions({ loading: false, error: err, list: [] })
      })
    return () => { cancelled = true }
  }, [needsIntegrations])

  function onFieldChange(fieldKey, next) {
    onChange({ ...(value || {}), [fieldKey]: next })
  }

  if (!schema || !Array.isArray(schema.fields) || schema.fields.length === 0) {
    return (
      <div className="text-[12px] text-gray-500 italic px-1 py-2">
        No fields for this connector type.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {GROUP_ORDER.map(group => {
        const fields = grouped.get(group) || []
        if (fields.length === 0) return null
        return (
          <section key={group} className="space-y-3">
            <h3 className="text-[10px] font-black uppercase tracking-[0.1em] text-gray-400 border-b border-gray-100 pb-1">
              {group}
            </h3>
            <div className="space-y-3">
              {fields.map(field => (
                <FieldRow
                  key={field.key}
                  field={field}
                  value={value}
                  onFieldChange={onFieldChange}
                  existingCredentials={existingCredentials}
                  mode={mode}
                  integrationOptions={integrationOptions}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

/**
 * Build the initial form `value` for a schema.  Seeds every field with its
 * declared `default` (if any) so the user sees sensible starting values —
 * e.g. `kafka-broker:9092`, `spm-db`, `us-east-1`.  Fields with no default
 * get '' so controlled inputs don't flip warning-spam about undefined→value.
 */
export function buildInitialFormValue(schema, overrides = {}) {
  const out = {}
  if (!schema?.fields) return { ...overrides }
  for (const f of schema.fields) {
    // Don't seed secrets with defaults even if one is declared — we never
    // want a placeholder cred persisted on a create round-trip.
    if (f.secret) {
      out[f.key] = ''
      continue
    }
    if (f.default !== undefined) out[f.key] = f.default
    else if (f.type === 'boolean') out[f.key] = false
    else if (f.type === 'enum_integration') out[f.key] = ''  // user picks
    else out[f.key] = ''
  }
  return { ...out, ...overrides }
}

export default SchemaForm
