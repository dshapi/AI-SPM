/**
 * SchemaForm.test.jsx
 * ────────────────────
 * Unit tests for the schema-driven form renderer.  Coverage focuses on
 * the contract surface the two integration modals depend on:
 *
 *   1. Every field type (string, integer, password, enum, textarea,
 *      boolean, url) renders the expected widget.
 *   2. `buildInitialFormValue` seeds declared defaults but NOT secrets.
 *   3. `onChange` receives a new value-dict with ONLY the edited key
 *      updated, preserving other entries (important for nested payloads).
 *   4. In configure mode, a field marked `secret=true` whose
 *      `credential_type` appears in `existingCredentials` as
 *      is_configured:true renders the "leave blank to keep" hint.
 *   5. Fields are grouped into Connection / Credentials / Advanced
 *      section headers based on their `group` attribute.
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SchemaForm, buildInitialFormValue } from '../SchemaForm.jsx'

const POSTGRES_SCHEMA = {
  key: 'postgres',
  label: 'PostgreSQL',
  category: 'Data / Storage',
  fields: [
    { key: 'host', label: 'Host', type: 'string',
      group: 'Connection', required: true, default: 'spm-db' },
    { key: 'port', label: 'Port', type: 'integer',
      group: 'Connection', required: true, default: 5432 },
    { key: 'sslmode', label: 'SSL Mode', type: 'enum',
      group: 'Advanced', options: ['disable', 'prefer', 'require'],
      default: 'prefer' },
    { key: 'use_iam', label: 'Use IAM', type: 'boolean',
      group: 'Advanced', default: false },
    { key: 'password', label: 'Password', type: 'password',
      group: 'Credentials', required: true, secret: true },
  ],
}

const KAFKA_SCHEMA = {
  key: 'kafka',
  fields: [
    { key: 'bootstrap_servers', label: 'Bootstrap Servers', type: 'string',
      group: 'Connection', required: true, default: 'kafka-broker:9092' },
    { key: 'base_url', label: 'Dashboard URL', type: 'url',
      group: 'Connection' },
    { key: 'service_account_json', label: 'Cert', type: 'textarea',
      group: 'Credentials', secret: true },
  ],
}

describe('SchemaForm — rendering each field type', () => {
  it('renders every declared widget type for the Postgres schema', () => {
    const onChange = vi.fn()
    render(
      <SchemaForm
        schema={POSTGRES_SCHEMA}
        value={buildInitialFormValue(POSTGRES_SCHEMA)}
        onChange={onChange}
        mode="configure"
      />,
    )

    // string → text input
    const host = screen.getByTestId('field-host')
    expect(host.tagName).toBe('INPUT')
    expect(host.getAttribute('type')).toBe('text')
    expect(host.value).toBe('spm-db')

    // integer → number input
    const port = screen.getByTestId('field-port')
    expect(port.getAttribute('type')).toBe('number')
    expect(port.value).toBe('5432')

    // enum → select
    const sslmode = screen.getByTestId('field-sslmode')
    expect(sslmode.tagName).toBe('SELECT')
    expect(sslmode.value).toBe('prefer')

    // boolean → checkbox
    const useIam = screen.getByTestId('field-use_iam')
    expect(useIam.getAttribute('type')).toBe('checkbox')
    expect(useIam.checked).toBe(false)

    // password → password input
    const pwd = screen.getByTestId('field-password')
    expect(pwd.getAttribute('type')).toBe('password')
  })

  it('renders textarea for textarea-type and url for url-type', () => {
    render(
      <SchemaForm
        schema={KAFKA_SCHEMA}
        value={buildInitialFormValue(KAFKA_SCHEMA)}
        onChange={vi.fn()}
        mode="configure"
      />,
    )
    const cert = screen.getByTestId('field-service_account_json')
    expect(cert.tagName).toBe('TEXTAREA')

    const url = screen.getByTestId('field-base_url')
    expect(url.getAttribute('type')).toBe('url')
  })
})

describe('SchemaForm — buildInitialFormValue', () => {
  it('seeds declared defaults but not secrets', () => {
    const init = buildInitialFormValue(POSTGRES_SCHEMA)
    expect(init.host).toBe('spm-db')
    expect(init.port).toBe(5432)
    expect(init.sslmode).toBe('prefer')
    expect(init.use_iam).toBe(false)
    // Secrets are always empty in the initial form, even if the schema
    // author set a default — we never want to round-trip a baked-in secret.
    expect(init.password).toBe('')
  })

  it('merges explicit overrides on top of defaults', () => {
    const init = buildInitialFormValue(POSTGRES_SCHEMA, { host: 'prod-db', database: 'custom' })
    expect(init.host).toBe('prod-db')
    expect(init.port).toBe(5432)
    expect(init.database).toBe('custom')
  })

  it('returns an empty object when schema is missing', () => {
    expect(buildInitialFormValue(null)).toEqual({})
    expect(buildInitialFormValue({})).toEqual({})
  })
})

describe('SchemaForm — onChange semantics', () => {
  it('emits a new object with only the edited field updated', () => {
    const onChange = vi.fn()
    const initial = buildInitialFormValue(POSTGRES_SCHEMA)
    render(
      <SchemaForm schema={POSTGRES_SCHEMA} value={initial} onChange={onChange} mode="configure" />,
    )
    fireEvent.change(screen.getByTestId('field-host'), { target: { value: 'other-host' } })
    expect(onChange).toHaveBeenCalledTimes(1)
    const next = onChange.mock.calls[0][0]
    expect(next.host).toBe('other-host')
    // Every other field retains its initial value.
    expect(next.port).toBe(5432)
    expect(next.sslmode).toBe('prefer')
    expect(next.password).toBe('')
  })

  it('coerces integer-type input to a JS number', () => {
    const onChange = vi.fn()
    render(
      <SchemaForm
        schema={POSTGRES_SCHEMA}
        value={buildInitialFormValue(POSTGRES_SCHEMA)}
        onChange={onChange}
        mode="configure"
      />,
    )
    fireEvent.change(screen.getByTestId('field-port'), { target: { value: '5433' } })
    expect(onChange.mock.calls[0][0].port).toBe(5433)
  })

  it('preserves unknown keys on the value-dict through edits', () => {
    const onChange = vi.fn()
    const initial = { ...buildInitialFormValue(POSTGRES_SCHEMA), extra_knob: 'keep-me' }
    render(
      <SchemaForm schema={POSTGRES_SCHEMA} value={initial} onChange={onChange} mode="configure" />,
    )
    fireEvent.change(screen.getByTestId('field-host'), { target: { value: 'x' } })
    expect(onChange.mock.calls[0][0].extra_knob).toBe('keep-me')
  })
})

describe('SchemaForm — secret leave-blank hint', () => {
  it('shows the "Currently configured" hint for secrets with existing creds', () => {
    render(
      <SchemaForm
        schema={POSTGRES_SCHEMA}
        value={buildInitialFormValue(POSTGRES_SCHEMA)}
        onChange={vi.fn()}
        existingCredentials={[
          { credential_type: 'password', is_configured: true, value_hint: '••••abcd' },
        ]}
        mode="configure"
      />,
    )
    expect(screen.getByText(/Currently configured \(••••abcd\)/i)).toBeInTheDocument()
  })

  it('does NOT show the leave-blank hint in create mode', () => {
    render(
      <SchemaForm
        schema={POSTGRES_SCHEMA}
        value={buildInitialFormValue(POSTGRES_SCHEMA)}
        onChange={vi.fn()}
        existingCredentials={[
          { credential_type: 'password', is_configured: true, value_hint: '••••abcd' },
        ]}
        mode="create"
      />,
    )
    expect(screen.queryByText(/Currently configured/i)).toBeNull()
  })
})

describe('SchemaForm — field grouping', () => {
  it('renders Connection / Credentials / Advanced section headers when fields exist in each', () => {
    render(
      <SchemaForm
        schema={POSTGRES_SCHEMA}
        value={buildInitialFormValue(POSTGRES_SCHEMA)}
        onChange={vi.fn()}
        mode="configure"
      />,
    )
    expect(screen.getByText('Connection')).toBeInTheDocument()
    expect(screen.getByText('Credentials')).toBeInTheDocument()
    expect(screen.getByText('Advanced')).toBeInTheDocument()
  })

  it('skips section headers for groups with no fields', () => {
    const simple = {
      key: 'simple',
      fields: [{ key: 'token', label: 'Token', type: 'password', group: 'Credentials', secret: true }],
    }
    render(<SchemaForm schema={simple} value={{}} onChange={vi.fn()} mode="create" />)
    expect(screen.queryByText('Connection')).toBeNull()
    expect(screen.queryByText('Advanced')).toBeNull()
    expect(screen.getByText('Credentials')).toBeInTheDocument()
  })
})

describe('SchemaForm — empty / missing schema', () => {
  it('renders a graceful placeholder when schema has no fields', () => {
    render(<SchemaForm schema={{ key: 'x', fields: [] }} value={{}} onChange={vi.fn()} />)
    expect(screen.getByText(/No fields/i)).toBeInTheDocument()
  })
})
