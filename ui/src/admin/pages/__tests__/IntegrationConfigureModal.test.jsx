/**
 * IntegrationConfigureModal.test.jsx
 * ────────────────────────────────────
 * Submit-path coverage for the Configure modal.  We don't try to exercise
 * focus management or CSS — just the contract that matters:
 *
 *   1. Empty key + empty model ≠ HTTP call    (prevents no-op POSTs that
 *      would otherwise clobber the in-place config with an empty dict)
 *   2. Model-only save omits api_key          (never accidentally rotate)
 *   3. API-key + model save includes both     (happy path)
 *   4. Successful save fires onSaved and then onClose
 *   5. Failed save surfaces the error message and keeps the modal open
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { IntegrationConfigureModal } from '../IntegrationConfigureModal.jsx'

// Mock the API module so we don't hit the real fetch path.  Declaring the
// spy inside the factory keeps vi's hoisting happy.
vi.mock('../../api/integrationsApi.js', () => ({
  configureIntegration: vi.fn(),
}))
import { configureIntegration } from '../../api/integrationsApi.js'

const INT = {
  id:   'int-003',
  name: 'Anthropic',
  category: 'AI Providers',
  config: { model: 'claude-sonnet-4-6' },
  credentials: [
    { credential_type: 'api_key', name: 'Primary API key', is_configured: true, value_hint: '••••abcd' },
  ],
}

// A fixture for the non-AI archetype — basic_auth form renders Username,
// Password, Endpoint URL instead of Key + Model.  Used by the
// "basic_auth archetype" tests further down.
const SPLUNK = {
  id:   'int-004',
  name: 'Splunk',
  category: 'Security / SIEM',
  config: {},
  credentials: [],
}

// Cert-archetype fixture — the presence of a service_account_json slot
// on the credentials array flips the modal into cert mode regardless
// of category.  Kafka is the canonical example (seeded disconnected).
const KAFKA = {
  id:   'int-015',
  name: 'Kafka',
  category: 'Data / Storage',
  config: { bootstrap_servers: 'broker-1.example.com:9093' },
  credentials: [
    { credential_type: 'service_account_json', name: 'Service account cert',
      is_configured: false, value_hint: null },
  ],
}

function open(props = {}) {
  return render(
    <IntegrationConfigureModal
      integration={props.integration || INT}
      open={true}
      onClose={props.onClose || vi.fn()}
      onSaved={props.onSaved || vi.fn()}
    />,
  )
}

beforeEach(() => {
  configureIntegration.mockReset()
})

describe('IntegrationConfigureModal', () => {
  describe('AI-provider archetype', () => {
    it('renders the current model selected in the Model dropdown', () => {
      open()
      // Known providers (Anthropic is in the registry) render the Model
      // field as a <select>, with the integration's current config.model
      // pre-selected so the user sees "this is what's live".
      const modelSelect = screen.getByRole('combobox')
      expect(modelSelect).toHaveValue('claude-sonnet-4-6')
    })

    it('refuses to POST when neither a key nor a model has been entered', async () => {
      open()
      // Clear the seeded model by selecting the empty "— Select a model —"
      // option so the form is truly empty.
      const modelSelect = screen.getByRole('combobox')
      fireEvent.change(modelSelect, { target: { value: '' } })

      fireEvent.click(screen.getByRole('button', { name: /save/i }))

      await screen.findByText(/nothing to save/i)
      expect(configureIntegration).not.toHaveBeenCalled()
    })

    it('sends config.model without api_key when only the model changes', async () => {
      configureIntegration.mockResolvedValueOnce({ id: INT.id })
      const onClose = vi.fn()
      const onSaved = vi.fn()
      open({ onClose, onSaved })

      const modelSelect = screen.getByRole('combobox')
      fireEvent.change(modelSelect, { target: { value: 'claude-opus-4-6' } })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))

      await waitFor(() => expect(configureIntegration).toHaveBeenCalledTimes(1))
      const [id, body] = configureIntegration.mock.calls[0]
      expect(id).toBe('int-003')
      expect(body.api_key).toBeUndefined()
      expect(body.config).toEqual({ model: 'claude-opus-4-6' })

      await waitFor(() => expect(onSaved).toHaveBeenCalled())
      expect(onClose).toHaveBeenCalled()
    })

    it('includes api_key and config.model when both are supplied', async () => {
      configureIntegration.mockResolvedValueOnce({ id: INT.id })
      open()

      // API-key input is the only password-type field; target it by attribute
      // rather than label text to sidestep the visual label wrapping.
      const keyInput    = document.querySelector('input[type="password"]')
      const modelSelect = screen.getByRole('combobox')
      fireEvent.change(keyInput,    { target: { value: 'sk-ant-newkey' } })
      fireEvent.change(modelSelect, { target: { value: 'claude-opus-4-6' } })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))

      await waitFor(() => expect(configureIntegration).toHaveBeenCalledTimes(1))
      const [, body] = configureIntegration.mock.calls[0]
      expect(body.api_key).toBe('sk-ant-newkey')
      expect(body.config.model).toBe('claude-opus-4-6')
    })

    it('renders the server error inline and leaves the modal open on failure', async () => {
      configureIntegration.mockRejectedValueOnce(
        Object.assign(new Error('forbidden'), { status: 403 }),
      )
      const onClose = vi.fn()
      open({ onClose })

      const modelSelect = screen.getByRole('combobox')
      fireEvent.change(modelSelect, { target: { value: 'claude-opus-4-6' } })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))

      await screen.findByText(/forbidden/)
      // Importantly: we do NOT close the modal on failure, so the user can
      // retry or correct their input.
      expect(onClose).not.toHaveBeenCalled()
    })
  })

  describe('basic_auth archetype', () => {
    // These tests cover the credential shape used by every non-AI
    // category — SIEM, ticketing, identity, storage.  The form must
    // render username/password/endpoint fields instead of key+model.

    it('renders Username, Password and Endpoint URL fields (no Model dropdown)', () => {
      open({ integration: SPLUNK })
      // No model dropdown for non-AI categories.
      expect(screen.queryByRole('combobox')).toBeNull()
      // Three inputs visible — username (text), password, endpoint (url).
      expect(document.querySelector('input[type="password"]')).not.toBeNull()
      expect(document.querySelector('input[type="url"]')).not.toBeNull()
      // Username-field check via placeholder so we don't depend on label text.
      expect(screen.getByPlaceholderText(/spm-svc|admin@example\.com/i)).not.toBeNull()
    })

    it('sends username + password + config.endpoint_url on submit', async () => {
      configureIntegration.mockResolvedValueOnce({ id: SPLUNK.id })
      open({ integration: SPLUNK })

      const usernameInput = screen.getByPlaceholderText(/spm-svc|admin@example\.com/i)
      const passwordInput = document.querySelector('input[type="password"]')
      const endpointInput = document.querySelector('input[type="url"]')

      fireEvent.change(usernameInput, { target: { value: 'spm-svc' } })
      fireEvent.change(passwordInput, { target: { value: 'p@ss' } })
      fireEvent.change(endpointInput, { target: { value: 'https://splunk.example.com:8088' } })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))

      await waitFor(() => expect(configureIntegration).toHaveBeenCalledTimes(1))
      const [id, body] = configureIntegration.mock.calls[0]
      expect(id).toBe('int-004')
      expect(body.username).toBe('spm-svc')
      expect(body.password).toBe('p@ss')
      expect(body.config.endpoint_url).toBe('https://splunk.example.com:8088')
      // Crucially, the AI-only fields must NOT be sent.
      expect(body.api_key).toBeUndefined()
      expect(body.config.model).toBeUndefined()
    })

    it('blocks submit when basic_auth form is completely empty', async () => {
      open({ integration: SPLUNK })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))
      await screen.findByText(/nothing to save/i)
      expect(configureIntegration).not.toHaveBeenCalled()
    })
  })

  describe('cert archetype', () => {
    // Archetype is picked by credential_type, not category — any
    // integration with a service_account_json credential slot flips
    // into the cert form.  Kafka is the fixture; the same form
    // applies to Vertex AI and Azure Sentinel service principals.

    it('renders Bootstrap Servers + a cert textarea (no Model, no password)', () => {
      open({ integration: KAFKA })
      // No model dropdown and no <input type="password"> — the cert
      // lives in a textarea so users can paste multi-line PEM.
      expect(screen.queryByRole('combobox')).toBeNull()
      expect(document.querySelector('input[type="password"]')).toBeNull()
      expect(document.querySelector('textarea')).not.toBeNull()
      // Bootstrap servers comes seeded from config.
      const bootstrap = screen.getByPlaceholderText(/broker-1\.example\.com/i)
      expect(bootstrap).toHaveValue('broker-1.example.com:9093')
    })

    it('sends service_account_json + bootstrap_servers on submit', async () => {
      configureIntegration.mockResolvedValueOnce({ id: KAFKA.id })
      open({ integration: KAFKA })

      const bootstrap = screen.getByPlaceholderText(/broker-1\.example\.com/i)
      const certTA    = document.querySelector('textarea')
      fireEvent.change(bootstrap, { target: { value: 'kafka.prod:9094' } })
      fireEvent.change(certTA,    { target: { value: '-----BEGIN CERTIFICATE-----\nMIIC…\n-----END CERTIFICATE-----' } })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))

      await waitFor(() => expect(configureIntegration).toHaveBeenCalledTimes(1))
      const [id, body] = configureIntegration.mock.calls[0]
      expect(id).toBe('int-015')
      expect(body.service_account_json).toMatch(/^-----BEGIN CERTIFICATE-----/)
      expect(body.bootstrap_servers).toBe('kafka.prod:9094')
      // Crucially, AI / basic_auth fields must NOT be sent.
      expect(body.api_key).toBeUndefined()
      expect(body.password).toBeUndefined()
      expect(body.username).toBeUndefined()
    })

    it('omits service_account_json when only bootstrap_servers changes', async () => {
      // A user wants to point the broker elsewhere without rotating
      // the cert — the payload must NOT include service_account_json
      // (which would clobber the stored cert with an empty string,
      // same semantics as the api_key "leave blank to keep" rule).
      configureIntegration.mockResolvedValueOnce({ id: KAFKA.id })
      open({ integration: KAFKA })

      const bootstrap = screen.getByPlaceholderText(/broker-1\.example\.com/i)
      fireEvent.change(bootstrap, { target: { value: 'kafka.new:9094' } })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))

      await waitFor(() => expect(configureIntegration).toHaveBeenCalledTimes(1))
      const [, body] = configureIntegration.mock.calls[0]
      expect(body.bootstrap_servers).toBe('kafka.new:9094')
      expect(body.service_account_json).toBeUndefined()
    })

    it('blocks submit when the cert form is completely empty', async () => {
      // Clear the seeded bootstrap_servers so the form is truly empty.
      open({ integration: { ...KAFKA, config: {} } })
      fireEvent.click(screen.getByRole('button', { name: /save/i }))
      await screen.findByText(/nothing to save/i)
      expect(configureIntegration).not.toHaveBeenCalled()
    })
  })

  it('returns null when `open` is false (no backdrop rendered)', () => {
    const { container } = render(
      <IntegrationConfigureModal integration={INT} open={false} onClose={vi.fn()} onSaved={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })
})
