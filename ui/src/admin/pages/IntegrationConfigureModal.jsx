/**
 * IntegrationConfigureModal.jsx
 * ──────────────────────────────
 * Admin-only modal that wraps POST /integrations/{id}/configure.
 *
 * Two rendering paths
 *   1. Schema-driven (preferred) — integrations with a `connectorType`
 *      stored on the row fetch the full FieldSpec list from
 *      GET /integrations/connector-types and render the form via
 *      <SchemaForm>.  Submissions go through body.fields and the
 *      server splits secrets vs config using the registry.
 *   2. Legacy archetype (fallback) — integrations that predate the
 *      registry (no connectorType) render one of three hand-coded
 *      forms: ai_provider / cert / basic_auth.  We keep this path so
 *      existing seed rows and unmigrated tenants still work; it's
 *      purely additive.
 *
 * Secrets handling (both paths)
 *   • Password / textarea cert fields are never rendered back as values.
 *   • Submitting an empty secret field is the "leave as-is" signal.
 *   • The server reveals `value_hint` ('••••abcd') for existing creds;
 *     we surface that next to the input so users know something is
 *     configured even though we can't show the real secret.
 */

import { useEffect, useMemo, useState } from 'react'
import { X, KeyRound, Cpu, Link as LinkIcon, AlertTriangle, Loader2, RefreshCw, User, Lock, FileText, Server } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { Button } from '../../components/ui/Button.jsx'
import { configureIntegration, getConnectorTypes } from '../api/integrationsApi.js'
import { getModelsForProvider } from '../data/providerModels.js'
import { SchemaForm, buildInitialFormValue } from '../components/SchemaForm.jsx'

/**
 * Three fundamentally different credential shapes share this modal:
 *
 *   • 'ai_provider'  — API Key + Model + optional Base URL.  For LLM
 *                      and embedding vendors, where the "model" knob
 *                      is the per-request target.
 *   • 'cert'         — Service Account Certificate (PEM / JSON) +
 *                      Bootstrap Servers.  For brokers / service-
 *                      principal vendors (Kafka, Azure Sentinel,
 *                      Vertex AI) where the credential is a cert blob,
 *                      not a password.
 *   • 'basic_auth'   — Username + Password + Endpoint URL.  For SIEMs,
 *                      ticketing, identity, storage, messaging — any
 *                      vendor where the user authenticates with a
 *                      login rather than an opaque key.
 *
 * Dispatch rule: if the integration has a credential slot of type
 * ``service_account_json`` we render the cert archetype regardless of
 * category (so Vertex AI in "AI Providers" gets the cert form, and
 * Kafka in "Data / Storage" gets it too).  Otherwise we fall back to
 * category-based dispatch.  Defaulting to 'ai_provider' for unknown
 * categories is a conscious fallback — that's what Add Integration
 * creates most often.
 */
function archetypeFor(integration) {
  const creds = Array.isArray(integration?.credentials) ? integration.credentials : []
  if (creds.some(c => c?.credential_type === 'service_account_json')) return 'cert'

  const category = integration?.category
  // Everything in these five non-AI categories uses login-style creds.
  // Messaging / Collab (Slack, Teams) also fits this pattern better
  // than the AI shape — webhooks don't have a model knob.
  const nonAiCategories = new Set([
    'Security / SIEM',
    'Ticketing / Workflow',
    'Identity / Access',
    'Data / Storage',
    'Messaging / Collab',
  ])
  if (nonAiCategories.has(category)) return 'basic_auth'
  return 'ai_provider'
}

// Sentinel select value that means "render the custom text input instead".
// Kept as a symbol-ish string so it can't collide with a real model ID.
const CUSTOM_MODEL_SENTINEL = '__custom__'

/**
 * Translate an integration base_url into something the browser can reach.
 * Ollama rows typically store `http://host.docker.internal:11434` because
 * that's what services inside docker-compose need to use, but that
 * hostname isn't resolvable from the user's browser — it's a Docker
 * Desktop magic DNS.  Swapping to `localhost` gives the browser the same
 * endpoint the backend talks to when the user is running a local Ollama.
 */
function browserReachableUrl(u) {
  if (!u) return null
  try {
    const parsed = new URL(u)
    if (parsed.hostname === 'host.docker.internal') parsed.hostname = 'localhost'
    return parsed.toString().replace(/\/$/, '')
  } catch {
    return null
  }
}

/**
 * Fetch the model list from a local Ollama instance.
 *   GET {base_url}/api/tags  →  { models: [{ name, ... }, ...] }
 *
 * Ollama's default CORS config permits localhost origins, so this works
 * from the browser without a proxy.  Returns an array of model IDs, or
 * throws so the caller can fall back to the static registry.
 */
async function fetchOllamaModels(baseUrl, signal) {
  const browserUrl = browserReachableUrl(baseUrl)
  if (!browserUrl) throw new Error('Invalid base URL')
  const res = await fetch(`${browserUrl}/api/tags`, { signal })
  if (!res.ok) throw new Error(`Ollama responded ${res.status}`)
  const json = await res.json()
  const names = (json?.models || []).map(m => m?.name).filter(Boolean)
  // Deduplicate while keeping first-seen order — Ollama occasionally
  // reports the same name twice under different tags.
  return Array.from(new Set(names))
}

/**
 * @param {object}   props
 * @param {object}   props.integration        current detail view-model (may be null while loading)
 * @param {boolean}  props.open
 * @param {() => void}                                              props.onClose
 * @param {(updated: any) => (void | Promise<void>)}                props.onSaved
 */
export function IntegrationConfigureModal({ integration, open, onClose, onSaved }) {
  // ──  Which rendering path to use  ─────────────────────────────────────────
  // The row carries `connectorType` if it was created via the schema-driven
  // flow (or backfilled by Alembic 004).  When present, we fetch the
  // connector schema and hand off to <SchemaForm>.  Otherwise we fall
  // back to the legacy archetype code below.
  const connectorKey = integration?.connectorType || null
  const [schema,        setSchema]        = useState(null)
  const [schemaLoading, setSchemaLoading] = useState(false)
  const [schemaError,   setSchemaError]   = useState(null)
  const [fieldValues,   setFieldValues]   = useState({})

  // ──  Legacy-path form state  ──────────────────────────────────────────────
  // Seed the model input with whatever the detail row already has so the
  // user sees "this is what's live" rather than an empty box.  Re-seed every
  // time the modal re-opens against a different integration.
  // AI-provider fields
  const [apiKey,      setApiKey]      = useState('')
  // `model` is the canonical string that will be saved. `modelSelect` is
  // the dropdown's value — usually equal to `model`, except when the
  // user has chosen Custom…, in which case it's the sentinel and the
  // actual value lives in `model` (typed into the companion input).
  const [model,       setModel]       = useState('')
  const [modelSelect, setModelSelect] = useState('')
  const [baseUrl,     setBaseUrl]     = useState('')

  // Basic-auth fields
  const [username,    setUsername]    = useState('')
  const [password,    setPassword]    = useState('')
  const [endpointUrl, setEndpointUrl] = useState('')

  // Cert archetype fields (Kafka, Vertex AI, Azure Sentinel, …)
  const [cert,              setCert]              = useState('')
  const [bootstrapServers,  setBootstrapServers]  = useState('')

  const [saving,      setSaving]      = useState(false)
  const [error,       setError]       = useState(null)

  const archetype = archetypeFor(integration)
  const isAi      = archetype === 'ai_provider'
  const isCert    = archetype === 'cert'

  // Live Ollama discovery state — populated when the integration is Ollama
  // and we've successfully hit its /api/tags endpoint.  Stays null for
  // other providers; the dropdown falls back to the static registry then.
  const [liveModels,        setLiveModels]        = useState(null)
  const [liveModelsLoading, setLiveModelsLoading] = useState(false)
  const [liveModelsError,   setLiveModelsError]   = useState(null)

  // Resolve the provider's known model list once per modal open.  When the
  // integration isn't in the registry (null), the Model field falls back
  // to the original free-form text input so users can always type a value.
  const providerModels = useMemo(
    () => getModelsForProvider(integration?.name),
    [integration?.name],
  )
  const isOllama = (integration?.name || '').toLowerCase() === 'ollama'

  // ── Schema fetch on open (only when connectorType is set) ─────────────────
  useEffect(() => {
    if (!open || !connectorKey) {
      setSchema(null)
      return
    }
    setSchemaLoading(true)
    setSchemaError(null)
    getConnectorTypes()
      .then(types => {
        const found = (types || []).find(t => t.key === connectorKey) || null
        setSchema(found)
        // Seed the form with defaults overlaid by the current config, so
        // the user sees what's live in the database.  Secrets stay blank
        // (per buildInitialFormValue) — their hint comes from value_hint.
        if (found) {
          const existing = integration?.config || {}
          setFieldValues(buildInitialFormValue(found, existing))
        }
      })
      .catch(err => setSchemaError(err))
      .finally(() => setSchemaLoading(false))
  }, [open, connectorKey, integration?.id])

  // ── Legacy-path reseed on open ────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    // Reset on every open — don't carry api_key / password across opens.
    setApiKey('')
    setPassword('')
    const existingModel = integration?.config?.model || ''
    setModel(existingModel)
    // If the existing value is one of the known models, preselect it; if
    // it's a free-form custom value (e.g. a fine-tune), drop into Custom
    // mode with the value pre-filled so nothing is silently lost.
    if (providerModels && existingModel && !providerModels.models.includes(existingModel)) {
      setModelSelect(CUSTOM_MODEL_SENTINEL)
    } else {
      setModelSelect(existingModel)
    }
    setBaseUrl(integration?.config?.base_url || '')
    // basic_auth seed values — username lives in config (non-secret);
    // password is never returned by the server, only its hint.
    setUsername(integration?.config?.username || '')
    setEndpointUrl(integration?.config?.endpoint_url || '')
    // Cert archetype — cert body is never returned (secret), but
    // bootstrap_servers is a plain config knob so we show it back.
    setCert('')
    setBootstrapServers(integration?.config?.bootstrap_servers || '')
    setError(null)
    // Reset any stale Ollama fetch state from a previous open.
    setLiveModels(null)
    setLiveModelsError(null)
  }, [open, integration?.id, providerModels])

  // ──  Ollama live model discovery  ─────────────────────────────────────────
  // When the integration is a local Ollama install, hit /api/tags and pull
  // the real list of pulled models.  Falls back to the static registry on
  // error (network, CORS, bad URL), so the modal is always usable.
  useEffect(() => {
    if (!open || !isOllama || connectorKey) return   // schema path owns its own Model knob
    const target = integration?.config?.base_url || 'http://localhost:11434'
    const ctrl = new AbortController()
    setLiveModelsLoading(true)
    setLiveModelsError(null)
    fetchOllamaModels(target, ctrl.signal)
      .then(names => {
        setLiveModels(names)
        // If the previously-saved model is now part of the live list,
        // snap the dropdown back to it (previous open may have parked
        // the user in Custom mode because we hadn't loaded yet).
        const existing = integration?.config?.model || ''
        if (existing && names.includes(existing)) {
          setModelSelect(existing)
          setModel(existing)
        }
      })
      .catch(err => {
        if (err.name !== 'AbortError') setLiveModelsError(err.message || String(err))
      })
      .finally(() => setLiveModelsLoading(false))
    return () => ctrl.abort()
  }, [open, isOllama, connectorKey, integration?.config?.base_url, integration?.config?.model, integration?.id])

  /**
   * Manual re-fetch trigger for the refresh icon button next to the
   * Ollama dropdown — useful if the user just `ollama pull`'d a new
   * model and wants it to show up without closing/reopening the modal.
   */
  async function refreshOllamaModels() {
    if (!isOllama) return
    const target = baseUrl || integration?.config?.base_url || 'http://localhost:11434'
    setLiveModelsLoading(true)
    setLiveModelsError(null)
    try {
      const names = await fetchOllamaModels(target)
      setLiveModels(names)
    } catch (err) {
      setLiveModelsError(err.message || String(err))
    } finally {
      setLiveModelsLoading(false)
    }
  }

  // Escape-to-close — Dialog-lite ergonomics without pulling in a library.
  useEffect(() => {
    if (!open) return
    function onKey(e) { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || !integration) return null

  // The "credentials hint" comes from the detail response — the server sets
  // `is_configured: true` and a `value_hint` ('••••…xyz') when a credential
  // exists, without exposing the secret itself.  We look up by
  // credential_type so a row with both api_key and password (unusual but
  // possible) shows the right hint next to the right field.
  const credList = integration.credentials || []
  const apiKeyCred   = credList.find(c => c.credential_type === 'api_key') || null
  const passwordCred = credList.find(c => c.credential_type === 'password') || null
  const certCred     = credList.find(c => c.credential_type === 'service_account_json') || null
  const hasExistingKey      = !!apiKeyCred?.is_configured
  const existingKeyHint     = apiKeyCred?.value_hint || null
  const hasExistingPassword = !!passwordCred?.is_configured
  const existingPasswordHint = passwordCred?.value_hint || null
  const hasExistingCert     = !!certCred?.is_configured
  const existingCertHint    = certCred?.value_hint || null

  // Only show the Base URL field when it already has a value or when the
  // integration's category is one that commonly needs it (self-hosted
  // providers like Ollama, or region-specific endpoints).  Hiding it by
  // default keeps the 95% case clean.
  const showBaseUrl = !!integration?.config?.base_url
                   || integration?.name === 'Ollama'
                   || integration?.name === 'Groq'

  // ══════════════════════════════════════════════════════════════════════════
  //  Schema-driven submit
  // ══════════════════════════════════════════════════════════════════════════
  async function handleSchemaSubmit(e) {
    e?.preventDefault?.()
    if (!schema) return
    setSaving(true)
    setError(null)
    try {
      // Build the payload.  Empty strings are preserved as-is — the server
      // treats them as "leave unchanged" for both plaintext config and
      // secrets (see configure_integration in integrations_routes.py).
      // We still drop truly empty (undefined) entries for a tidy payload.
      const fields = {}
      for (const f of schema.fields || []) {
        const v = fieldValues?.[f.key]
        if (v === undefined || v === null) continue
        fields[f.key] = v
      }
      // Reject no-op saves at the client so we don't round-trip an
      // entirely-empty body through the HTTP path.  A value is "meaningful"
      // if it's not the empty string (an empty secret means "keep").
      const somethingTyped = Object.values(fields).some(
        v => !(typeof v === 'string' && v.trim() === '') && v !== false,
      )
      if (!somethingTyped) {
        setError(new Error('Nothing to save — edit a field to submit.'))
        setSaving(false)
        return
      }
      const updated = await configureIntegration(integration.id, { fields })
      await onSaved?.(updated)
      onClose?.()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  Legacy archetype submit
  // ══════════════════════════════════════════════════════════════════════════
  async function handleLegacySubmit(e) {
    e?.preventDefault?.()
    setSaving(true)
    setError(null)
    try {
      const body = { config: {} }
      if (isAi) {
        // AI-provider archetype: api_key + model (+ optional base_url).
        // Only send api_key if the user typed one — Configure doubles as
        // rotate on the server, and we never want to accidentally
        // clobber a key with "" on a model-only change.
        if (apiKey.trim()) body.api_key           = apiKey.trim()
        if (model.trim())  body.config.model      = model.trim()
        if (baseUrl.trim()) body.config.base_url  = baseUrl.trim()
      } else if (isCert) {
        // Cert archetype: service_account_json cert body + Bootstrap
        // Servers.  Like password, the cert is a secret — only send
        // when the user has typed a new one so saving a
        // bootstrap_servers change doesn't clobber the stored cert.
        if (cert.trim())             body.service_account_json = cert.trim()
        if (bootstrapServers.trim()) body.bootstrap_servers    = bootstrapServers.trim()
      } else {
        // basic_auth archetype: username + password (+ endpoint_url).
        // Same "only send if typed" rule for password — leaving it
        // blank must NOT clobber the existing stored password.
        if (username.trim())    body.username              = username.trim()
        if (password.trim())    body.password              = password.trim()
        if (endpointUrl.trim()) body.config.endpoint_url   = endpointUrl.trim()
      }
      // Tally whether anything was actually supplied; empty-form saves
      // are rejected before the round-trip to keep the server log clean.
      const nothingTyped = isAi
        ? !body.api_key  && Object.keys(body.config).length === 0
        : isCert
          ? !body.service_account_json && !body.bootstrap_servers
            && Object.keys(body.config).length === 0
          : !body.username && !body.password && Object.keys(body.config).length === 0
      if (nothingTyped) {
        setError(new Error(
          isAi
            ? 'Nothing to save — enter a key, model, or URL.'
            : isCert
              ? 'Nothing to save — paste a certificate or bootstrap servers.'
              : 'Nothing to save — enter a username, password, or endpoint.',
        ))
        setSaving(false)
        return
      }
      const updated = await configureIntegration(integration.id, body)
      await onSaved?.(updated)
      onClose?.()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const handleSubmit = connectorKey && schema ? handleSchemaSubmit : handleLegacySubmit

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      // Click-outside-to-close; swallow clicks on the dialog body itself.
      onClick={onClose}
    >
      <form
        onSubmit={handleSubmit}
        onClick={e => e.stopPropagation()}
        className="w-[520px] max-w-[94vw] bg-white rounded-2xl shadow-xl border border-gray-200 overflow-hidden"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center shrink-0">
            <KeyRound size={16} className="text-blue-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-[14px] font-bold text-gray-900 leading-tight">
              Configure {integration.name}
            </h2>
            <p className="text-[11px] text-gray-500 mt-0.5">
              {connectorKey
                ? `Update connection fields for ${schema?.label || integration.name}.`
                : isAi
                  ? 'Update the API key and model for this integration.'
                  : isCert
                    ? 'Paste the service account certificate and set bootstrap servers.'
                    : 'Update credentials and endpoint for this integration.'}
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
          {connectorKey ? (
          // ── Schema-driven path ─────────────────────────────────────────────
          // Row has a connectorType — render via <SchemaForm>.  While the
          // schema is loading we show a spinner; on fetch failure we fall
          // back to the legacy archetype so the user is never locked out.
          schemaLoading ? (
            <div className="flex items-center gap-2 text-[11.5px] text-gray-500 py-6 justify-center">
              <Loader2 size={12} className="animate-spin" /> Loading connector schema…
            </div>
          ) : schemaError || !schema ? (
            <div className="flex items-start gap-2.5 px-3 py-2.5 bg-amber-50 border border-amber-200 border-l-[3px] border-l-amber-500 rounded-lg">
              <AlertTriangle size={12} className="text-amber-600 mt-0.5 shrink-0" />
              <div>
                <p className="text-[11.5px] font-semibold text-amber-800">Schema unavailable</p>
                <p className="text-[11px] text-amber-700 mt-0.5 leading-snug">
                  Couldn't load the connector schema
                  {schemaError?.message ? ` (${schemaError.message})` : ''}. This integration
                  can still be edited in its raw form below.
                </p>
              </div>
            </div>
          ) : (
            <SchemaForm
              schema={schema}
              value={fieldValues}
              onChange={setFieldValues}
              existingCredentials={credList}
              mode="configure"
            />
          )
          ) : isAi ? (
          // ── AI-provider archetype: API Key + Model (+ Base URL) ────────────
          <>
          {/* API key */}
          <Field
            label="API Key"
            icon={KeyRound}
            hint={
              hasExistingKey
                ? `Currently configured${existingKeyHint ? ` (${existingKeyHint})` : ''}. Leave blank to keep as-is.`
                : 'Not yet configured. Enter a key to connect this integration.'
            }
          >
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder={hasExistingKey ? '•••••• (leave blank to keep)' : 'sk-…'}
              className={inputCls}
            />
          </Field>

          {/* Model
           *  ────
           *  For providers we have a model list for, render a dropdown
           *  seeded with the vendor's flagship models; otherwise fall
           *  back to a free-form input so unknown providers (or HF
           *  endpoint repo IDs) aren't blocked.  When the user picks
           *  "Custom…" we flip to a companion text input without
           *  losing the previously-saved value.  For Ollama we fetch
           *  the user's actually-pulled models live from /api/tags so
           *  the dropdown matches what `ollama list` would show. */}
          <Field
            label="Model"
            icon={Cpu}
            hint={
              isOllama
                ? (liveModels
                    ? `Live list from ${integration?.config?.base_url || 'http://localhost:11434'} (${liveModels.length} pulled). Use Custom… to type a tag you haven't pulled yet.`
                    : liveModelsError
                      ? `Couldn't reach Ollama (${liveModelsError}). Showing default tags — use Custom… to type your own.`
                      : 'Loading your local Ollama tags…')
                : providerModels
                  ? `Pick from ${integration?.name || 'the provider'}'s current models, or choose Custom… to type a value.`
                  : 'Logical model identifier (e.g. claude-sonnet-4-6, gpt-4o, llama3.2).'
            }
          >
            {providerModels ? (
              <>
                <div className="flex items-center gap-1.5">
                  <select
                    value={modelSelect}
                    onChange={e => {
                      const v = e.target.value
                      setModelSelect(v)
                      // Update the saved value to match the selection unless
                      // the user picked Custom…, in which case we leave
                      // `model` alone so any already-typed value survives.
                      if (v !== CUSTOM_MODEL_SENTINEL) setModel(v)
                    }}
                    className={selectCls}
                  >
                    {/* Empty option so the field isn't silently pre-filled
                        with a model the user didn't choose. */}
                    <option value="">— Select a model —</option>
                    {(liveModels && liveModels.length > 0
                      ? liveModels
                      : providerModels.models
                    ).map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    {providerModels.custom && (
                      <option value={CUSTOM_MODEL_SENTINEL}>Custom…</option>
                    )}
                  </select>
                  {isOllama && (
                    <button
                      type="button"
                      onClick={refreshOllamaModels}
                      disabled={liveModelsLoading}
                      title="Reload models from your Ollama instance"
                      className="h-9 w-9 flex items-center justify-center rounded-lg border border-gray-200 text-gray-500 hover:text-gray-700 hover:bg-gray-50 disabled:opacity-50 shrink-0"
                    >
                      {liveModelsLoading
                        ? <Loader2 size={13} className="animate-spin" />
                        : <RefreshCw size={13} />}
                    </button>
                  )}
                </div>
                {modelSelect === CUSTOM_MODEL_SENTINEL && (
                  <input
                    type="text"
                    value={model}
                    onChange={e => setModel(e.target.value)}
                    placeholder={isOllama ? 'llama3.2:3b' : 'your-custom-model-id'}
                    className={cn(inputCls, 'mt-2')}
                    autoFocus
                  />
                )}
              </>
            ) : (
              <input
                type="text"
                value={model}
                onChange={e => setModel(e.target.value)}
                placeholder={integration?.config?.model || 'claude-sonnet-4-6'}
                className={inputCls}
              />
            )}
          </Field>

          {/* Base URL (optional, conditionally shown) */}
          {showBaseUrl && (
            <Field
              label="Base URL"
              icon={LinkIcon}
              hint="Override the default vendor endpoint (self-hosted / proxy)."
            >
              <input
                type="url"
                value={baseUrl}
                onChange={e => setBaseUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
                className={inputCls}
              />
            </Field>
          )}
          </>
          ) : isCert ? (
          // ── cert archetype: Service Account Cert + Bootstrap Servers ──────
          // Kafka brokers, Azure Sentinel service principals, Vertex AI —
          // anything where the credential is a PEM/JSON blob pasted in
          // rather than a password typed inline.  Cert goes into
          // integration_credentials as credential_type='service_account_json';
          // bootstrap_servers lives in the config dict so the probe can
          // read it back without a credentials lookup.
          <>
          <Field
            label="Bootstrap Servers"
            icon={Server}
            hint="Comma-separated host:port list (e.g. broker-1.kafka.local:9093,broker-2.kafka.local:9093)."
          >
            <input
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={bootstrapServers}
              onChange={e => setBootstrapServers(e.target.value)}
              placeholder="broker-1.example.com:9093"
              className={inputCls}
            />
          </Field>

          <Field
            label="Service Account Certificate"
            icon={FileText}
            hint={
              hasExistingCert
                ? `Currently configured${existingCertHint ? ` (${existingCertHint})` : ''}. Leave blank to keep as-is.`
                : 'Paste the full PEM or JSON cert body. The value is base64-encoded at rest.'
            }
          >
            <textarea
              autoComplete="off"
              spellCheck={false}
              value={cert}
              onChange={e => setCert(e.target.value)}
              placeholder={hasExistingCert
                ? '•••••• (leave blank to keep existing cert)'
                : '-----BEGIN CERTIFICATE-----\n…\n-----END CERTIFICATE-----'}
              rows={6}
              className={cn(inputCls, 'h-auto py-2 font-mono text-[11px] leading-snug resize-y')}
            />
          </Field>
          </>
          ) : (
          // ── basic_auth archetype: Username + Password + Endpoint URL ──────
          // Used for SIEM, ticketing, identity, storage, messaging — any
          // vendor where the user authenticates with a login rather than
          // an opaque key that encodes the caller's identity.
          <>
          <Field
            label="Username"
            icon={User}
            hint="Account or service-account username used by this integration."
          >
            <input
              type="text"
              autoComplete="off"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="e.g. spm-svc, admin@example.com"
              className={inputCls}
            />
          </Field>

          <Field
            label="Password"
            icon={Lock}
            hint={
              hasExistingPassword
                ? `Currently configured${existingPasswordHint ? ` (${existingPasswordHint})` : ''}. Leave blank to keep as-is.`
                : 'Password or API token for the service account above.'
            }
          >
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder={hasExistingPassword ? '•••••• (leave blank to keep)' : '••••••••'}
              className={inputCls}
            />
          </Field>

          <Field
            label="Endpoint URL"
            icon={LinkIcon}
            hint="Base URL of the vendor instance (e.g. SIEM HEC URL, Okta tenant, Jira base URL)."
          >
            <input
              type="url"
              value={endpointUrl}
              onChange={e => setEndpointUrl(e.target.value)}
              placeholder="https://example.splunkcloud.com:8088"
              className={inputCls}
            />
          </Field>
          </>
          )}

          {/* Error banner */}
          {error && (
            <div className="flex items-start gap-2.5 px-3 py-2.5 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-lg">
              <AlertTriangle size={12} className="text-red-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-[11.5px] font-semibold text-red-700">Couldn't save</p>
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
            disabled={saving || (connectorKey && (schemaLoading || !schema))}
            className="gap-1.5"
          >
            {saving && <Loader2 size={12} className="animate-spin" />}
            {saving ? 'Saving…' : 'Save'}
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

function Field({ label, icon: Icon, hint, children }) {
  return (
    <div>
      <label className="flex items-center gap-1.5 text-[10.5px] font-black uppercase tracking-[0.08em] text-gray-500 mb-1.5">
        {Icon && <Icon size={10} className="text-gray-400" />}
        {label}
      </label>
      {children}
      {hint && <p className="text-[10.5px] text-gray-400 mt-1 leading-snug">{hint}</p>}
    </div>
  )
}

export default IntegrationConfigureModal
