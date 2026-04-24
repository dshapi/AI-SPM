/**
 * IntegrationCreateModal.jsx
 * ───────────────────────────
 * Admin-only modal that wraps POST /integrations, now schema-driven.
 *
 * Shape
 *   Step 1: pick a vendor from the catalog (21 entries, from GET
 *           /integrations/connector-types).  The catalog carries the
 *           field schema, category, description, and default values.
 *   Step 2: fill in the vendor-specific fields via <SchemaForm>, plus
 *           three free-form cross-vendor knobs (Display Name,
 *           Environment, Description).  Submit → POST /integrations.
 *
 * Why vendor-first
 *   The form you need to fill in for "Anthropic" is fundamentally
 *   different from "Postgres": Anthropic wants an API key and a model,
 *   Postgres wants host/port/db/user/password/sslmode.  Asking the user
 *   to pick the vendor first lets the form reflect what the vendor
 *   actually needs, instead of the generic AI-Provider / Basic-Auth /
 *   Cert archetypes the modal used before.
 *
 * Backwards compat
 *   The server still accepts the legacy camelCase body shape (name,
 *   category, auth_method, …).  This modal now also sends
 *   `connector_type` and a `credentials` dict that the backend splits
 *   into credentials vs config per the registry's secret_field_keys().
 *   Legacy callers of POST /integrations continue to work.
 */

import { useEffect, useMemo, useState } from 'react'
import { X, Plus, AlertTriangle, Loader2, Search, ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { Button } from '../../components/ui/Button.jsx'
import { createIntegration, getConnectorTypes } from '../api/integrationsApi.js'
import { SchemaForm, buildInitialFormValue } from '../components/SchemaForm.jsx'

const ENVIRONMENTS = ['Production', 'Staging', 'Development']

// Given the server's connector schema + the user's submitted field-values,
// split the payload into `config` (plaintext) and `credentials` (encrypted
// at rest) using the `secret` flag on each FieldSpec.  Mirrors the
// server-side secret_field_keys() helper.
function splitConfigCredentials(schema, values) {
  const config = {}
  const credentials = {}
  for (const f of schema?.fields || []) {
    const v = values?.[f.key]
    // Leave blank → don't send.  For secrets this preserves "leave blank
    // to keep"; for plaintext it avoids polluting config with empty strings.
    if (v === undefined || v === null || v === '') continue
    if (f.secret) credentials[f.key] = v
    else config[f.key] = v
  }
  return { config, credentials }
}

/**
 * @param {object}   props
 * @param {boolean}  props.open
 * @param {() => void}                                              props.onClose
 * @param {(created: any) => (void | Promise<void>)}                props.onCreated
 */
export function IntegrationCreateModal({ open, onClose, onCreated }) {
  // ── Vendor catalog (fetched once per modal open) ────────────────────────────
  const [catalog,       setCatalog]       = useState(null)
  const [catalogError,  setCatalogError]  = useState(null)
  const [catalogLoading,setCatalogLoading]= useState(false)

  // ── Selection ───────────────────────────────────────────────────────────────
  const [connectorKey,  setConnectorKey]  = useState('')
  const [catalogSearch, setCatalogSearch] = useState('')

  // ── Cross-vendor metadata ──────────────────────────────────────────────────
  const [displayName,   setDisplayName]   = useState('')
  const [environment,   setEnvironment]   = useState('Production')
  const [description,   setDescription]   = useState('')

  // ── Schema-driven field values ─────────────────────────────────────────────
  // Shape: `{ [fieldKey]: value }`.  Initialized from the selected
  // connector's defaults whenever the user switches connectors.
  const [fieldValues,   setFieldValues]   = useState({})

  const [saving,        setSaving]        = useState(false)
  const [error,         setError]         = useState(null)

  // Re-seed state every time the modal opens.  Guards against a cancelled
  // half-filled form leaking into the next "Add Integration" click.
  useEffect(() => {
    if (!open) return
    setConnectorKey('')
    setCatalogSearch('')
    setDisplayName('')
    setEnvironment('Production')
    setDescription('')
    setFieldValues({})
    setError(null)
    // Fetch the catalog lazily (after token + mount), caches across opens
    // via the module-level cache in integrationsApi.js.
    setCatalogLoading(true)
    getConnectorTypes()
      .then(types => {
        setCatalog(types)
        setCatalogError(null)
      })
      .catch(err => {
        setCatalog([])
        setCatalogError(err)
      })
      .finally(() => setCatalogLoading(false))
  }, [open])

  // Escape-to-close
  useEffect(() => {
    if (!open) return
    function onKey(e) { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // The selected connector schema (or null while on step 1).
  const selectedConnector = useMemo(
    () => (catalog || []).find(c => c.key === connectorKey) || null,
    [catalog, connectorKey],
  )

  // When the user picks a new vendor, seed the form with the schema's
  // declared defaults and snap the Display Name to the vendor label so
  // the typical "call it what it is" flow needs zero typing.
  function selectConnector(key) {
    const ct = (catalog || []).find(c => c.key === key) || null
    setConnectorKey(key)
    setFieldValues(ct ? buildInitialFormValue(ct) : {})
    // Only overwrite Display Name if the user hasn't typed something.
    if (ct && !displayName.trim()) setDisplayName(ct.label || '')
  }

  // Filter + group the catalog for the picker.  We keep the group order
  // stable so the picker reads the same across sessions.
  const groupedCatalog = useMemo(() => {
    const term = catalogSearch.trim().toLowerCase()
    const matching = (catalog || []).filter(c => {
      if (!term) return true
      return (
        (c.label || '').toLowerCase().includes(term) ||
        (c.vendor || '').toLowerCase().includes(term) ||
        (c.description || '').toLowerCase().includes(term)
      )
    })
    const out = new Map()
    for (const c of matching) {
      const arr = out.get(c.category) || []
      arr.push(c)
      out.set(c.category, arr)
    }
    return Array.from(out.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [catalog, catalogSearch])

  if (!open) return null

  async function handleSubmit(e) {
    e?.preventDefault?.()
    if (!selectedConnector) {
      setError(new Error('Pick an integration type first.'))
      return
    }
    const trimmedName = displayName.trim() || selectedConnector.label
    // Enforce the schema's required-on-create rule.  Required fields
    // with empty values → early bail so the user sees which one's missing.
    const missing = (selectedConnector.fields || []).find(
      f => f.required && (fieldValues[f.key] === undefined
                        || fieldValues[f.key] === null
                        || fieldValues[f.key] === ''),
    )
    if (missing) {
      setError(new Error(`Required field missing: ${missing.label || missing.key}`))
      return
    }
    setSaving(true)
    setError(null)
    try {
      const { config, credentials } = splitConfigCredentials(selectedConnector, fieldValues)
      const body = {
        name:           trimmedName,
        category:       selectedConnector.category,
        auth_method:    'API Key',           // legacy column; unused by schema flow
        environment,
        connector_type: selectedConnector.key,
        vendor:         selectedConnector.vendor || undefined,
        description:    description.trim() || selectedConnector.description || undefined,
        config,
        credentials,
      }
      const created = await createIntegration(body)
      await onCreated?.(created)
      onClose?.()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <form
        onSubmit={handleSubmit}
        onClick={e => e.stopPropagation()}
        className="w-[640px] max-w-[94vw] bg-white rounded-2xl shadow-xl border border-gray-200 overflow-hidden"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center shrink-0">
            <Plus size={16} className="text-blue-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-[14px] font-bold text-gray-900 leading-tight">
              Add Integration
            </h2>
            <p className="text-[11px] text-gray-500 mt-0.5">
              {selectedConnector
                ? `Configuring ${selectedConnector.label}. Fields below reflect what ${selectedConnector.vendor || selectedConnector.label} needs to connect.`
                : 'Pick a vendor to see the fields required to connect.'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded-md hover:bg-black/[0.06] text-gray-400 hover:text-gray-600 transition-colors shrink-0 mt-0.5"
            aria-label="Close"
          >
            <X size={13} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4 max-h-[72vh] overflow-y-auto">
          {/* ── Step 1: vendor picker ─────────────────────────────────────── */}
          {!selectedConnector ? (
            <>
              <div className="relative">
                <Search
                  size={14}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
                />
                <input
                  type="text"
                  value={catalogSearch}
                  onChange={e => setCatalogSearch(e.target.value)}
                  placeholder="Search vendors (OpenAI, Postgres, Slack…)"
                  className={cn(inputCls, 'pl-8')}
                  autoFocus
                  data-testid="catalog-search"
                />
              </div>

              {catalogLoading && (
                <div className="flex items-center gap-2 text-[11.5px] text-gray-500 py-6 justify-center">
                  <Loader2 size={12} className="animate-spin" /> Loading vendor catalog…
                </div>
              )}

              {catalogError && !catalogLoading && (
                <div className="flex items-start gap-2.5 px-3 py-2.5 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-lg">
                  <AlertTriangle size={12} className="text-red-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-[11.5px] font-semibold text-red-700">Couldn't load catalog</p>
                    <p className="text-[11px] text-red-600 mt-0.5 leading-snug">
                      {catalogError.message || 'Unexpected error.'}
                    </p>
                  </div>
                </div>
              )}

              {!catalogLoading && !catalogError && groupedCatalog.length === 0 && (
                <p className="text-[11.5px] text-gray-500 italic py-4 text-center">
                  No vendors match your search.
                </p>
              )}

              {!catalogLoading && groupedCatalog.map(([category, items]) => (
                <div key={category} className="space-y-1.5">
                  <h3 className="text-[10px] font-black uppercase tracking-[0.1em] text-gray-400">
                    {category}
                  </h3>
                  <div className="grid grid-cols-2 gap-2">
                    {items.map(item => (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => selectConnector(item.key)}
                        className="text-left p-2.5 rounded-lg border border-gray-200 hover:border-blue-400 hover:bg-blue-50/30 transition-colors"
                        data-testid={`catalog-item-${item.key}`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[12.5px] font-semibold text-gray-800 truncate">
                            {item.label}
                          </span>
                          <ChevronDown size={12} className="text-gray-400 -rotate-90" />
                        </div>
                        {item.vendor && (
                          <p className="text-[10.5px] text-gray-500 mt-0.5 truncate">{item.vendor}</p>
                        )}
                        {item.description && (
                          <p className="text-[10.5px] text-gray-400 mt-1 leading-snug line-clamp-2">
                            {item.description}
                          </p>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </>
          ) : (
            // ── Step 2: vendor-specific fields + cross-vendor metadata ─────
            <>
              {/* Breadcrumb / change-vendor link */}
              <div className="flex items-center justify-between -mt-1">
                <div className="flex items-center gap-1.5 text-[10.5px]">
                  <span className="font-semibold text-gray-600">{selectedConnector.category}</span>
                  <span className="text-gray-300">/</span>
                  <span className="font-semibold text-gray-800">{selectedConnector.label}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setConnectorKey('')}
                  className="text-[10.5px] font-semibold text-blue-600 hover:underline"
                >
                  Change vendor
                </button>
              </div>

              {/* Cross-vendor metadata — one row, minimalist */}
              <div className="grid grid-cols-2 gap-3">
                <Field label="Display Name" required>
                  <input
                    type="text"
                    value={displayName}
                    onChange={e => setDisplayName(e.target.value)}
                    placeholder={selectedConnector.label}
                    className={inputCls}
                  />
                </Field>
                <Field label="Environment">
                  <select
                    value={environment}
                    onChange={e => setEnvironment(e.target.value)}
                    className={selectCls}
                  >
                    {ENVIRONMENTS.map(env => <option key={env} value={env}>{env}</option>)}
                  </select>
                </Field>
              </div>

              <Field label="Description" hint="Short summary shown in the list.">
                <textarea
                  rows={2}
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder={selectedConnector.description || 'What is this integration used for?'}
                  className={cn(inputCls, 'h-auto py-2 resize-none')}
                />
              </Field>

              {/* Schema-driven vendor fields */}
              <SchemaForm
                schema={selectedConnector}
                value={fieldValues}
                onChange={setFieldValues}
                mode="create"
              />
            </>
          )}

          {/* Error banner */}
          {error && (
            <div className="flex items-start gap-2.5 px-3 py-2.5 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-lg">
              <AlertTriangle size={12} className="text-red-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-[11.5px] font-semibold text-red-700">Couldn't create integration</p>
                <p className="text-[11px] text-red-600 mt-0.5 leading-snug">
                  {error.message || 'Unexpected error. Please try again.'}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t border-gray-100 flex items-center justify-end gap-2 bg-gray-50/60">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            disabled={saving || !selectedConnector}
            className="gap-1.5"
          >
            {saving && <Loader2 size={12} className="animate-spin" />}
            {saving ? 'Creating…' : 'Create'}
          </Button>
        </div>
      </form>
    </div>
  )
}

// ── Presentation helpers ──────────────────────────────────────────────────────

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

function Field({ label, hint, required, children }) {
  return (
    <div>
      <label className="flex items-center gap-1.5 text-[10.5px] font-black uppercase tracking-[0.08em] text-gray-500 mb-1.5">
        {label}
        {required && <span className="text-red-500 normal-case">*</span>}
      </label>
      {children}
      {hint && <p className="text-[10.5px] text-gray-400 mt-1 leading-snug">{hint}</p>}
    </div>
  )
}

export default IntegrationCreateModal
