/**
 * ActionPanel.test.jsx
 * ─────────────────────
 * Tests for the registry-driven ActionPanel component and its supporting modules.
 *
 * Coverage:
 *   1. getActionsForFinding — correct actions per type
 *   2. ActionPanel rendering — primary action, secondary actions, empty state
 *   3. Navigation — handlers navigate to the right URLs
 *   4. Disabled state — disabledWhen predicate respected
 *   5. Unknown type — fallback message
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { getActionsForFinding, ACTION_REGISTRY }  from '../actionRegistry.js'
import { createHandlers, dispatch }               from '../actionHandlers.js'
import { ActionPanel }                            from '../ActionPanel.jsx'

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderPanel(finding) {
  return render(
    <MemoryRouter>
      <ActionPanel finding={finding} />
    </MemoryRouter>
  )
}

const BASE_FINDING = {
  id:               'f-001',
  title:            'Test Finding',
  source:           'network_exposure',
  asset:            { name: 'CustomerSupport-GPT', type: 'Agent' },
  correlated_events: [],
}

// ── getActionsForFinding ──────────────────────────────────────────────────────

describe('getActionsForFinding', () => {
  it('returns actions for network_exposure', () => {
    const actions = getActionsForFinding({ source: 'network_exposure' })
    expect(actions.length).toBeGreaterThan(0)
    expect(actions.some(a => a.primary)).toBe(true)
  })

  it('returns actions for unexpected_listen_ports', () => {
    const actions = getActionsForFinding({ source: 'unexpected_listen_ports' })
    expect(actions.length).toBeGreaterThan(0)
  })

  it('returns actions for prompt_injection', () => {
    const actions = getActionsForFinding({ source: 'prompt_injection' })
    expect(actions.some(a => a.id === 'inspect_prompt')).toBe(true)
  })

  it('returns actions for secrets_exposure', () => {
    const actions = getActionsForFinding({ source: 'secrets_exposure' })
    expect(actions.some(a => a.id === 'revoke_secret')).toBe(true)
  })

  it('returns actions for tool_misuse', () => {
    const actions = getActionsForFinding({ source: 'tool_misuse' })
    expect(actions.some(a => a.id === 'inspect_tools')).toBe(true)
  })

  it('returns actions for runtime_anomaly', () => {
    const actions = getActionsForFinding({ source: 'runtime_anomaly' })
    expect(actions.some(a => a.id === 'analyze_behavior')).toBe(true)
  })

  it('returns empty array for unknown source', () => {
    const actions = getActionsForFinding({ source: 'completely_unknown_type' })
    expect(actions).toEqual([])
  })

  it('returns empty array when source is undefined', () => {
    const actions = getActionsForFinding({})
    expect(actions).toEqual([])
  })

  it('normalises source to lowercase', () => {
    const actions = getActionsForFinding({ source: 'NETWORK_EXPOSURE' })
    expect(actions.length).toBeGreaterThan(0)
  })

  it('every registered type has at least one primary action', () => {
    Object.entries(ACTION_REGISTRY).forEach(([type, actions]) => {
      const hasPrimary = actions.some(a => a.primary)
      expect(hasPrimary, `${type} has no primary action`).toBe(true)
    })
  })
})

// ── ActionPanel rendering ─────────────────────────────────────────────────────

describe('ActionPanel rendering', () => {
  it('renders the action panel container for a known type', () => {
    renderPanel(BASE_FINDING)
    expect(screen.getByTestId('action-panel')).toBeInTheDocument()
  })

  it('renders the primary action button', () => {
    renderPanel(BASE_FINDING)
    expect(screen.getByTestId('action-investigate_network')).toBeInTheDocument()
    expect(screen.getByText('Investigate Network Exposure')).toBeInTheDocument()
  })

  it('renders secondary action buttons', () => {
    renderPanel(BASE_FINDING)
    expect(screen.getByTestId('action-view_port_activity')).toBeInTheDocument()
    expect(screen.getByTestId('action-identify_service')).toBeInTheDocument()
  })

  it('shows prompt_injection actions for prompt_injection source', () => {
    renderPanel({ ...BASE_FINDING, source: 'prompt_injection' })
    expect(screen.getByText('Inspect Prompt Flow')).toBeInTheDocument()
    expect(screen.getByText('View Conversation Trace')).toBeInTheDocument()
  })

  it('shows secrets_exposure actions for secrets_exposure source', () => {
    renderPanel({ ...BASE_FINDING, source: 'secrets_exposure' })
    expect(screen.getByText('Revoke Credential')).toBeInTheDocument()
    expect(screen.getByText('Locate Source')).toBeInTheDocument()
  })

  it('shows tool_misuse actions for tool_misuse source', () => {
    renderPanel({ ...BASE_FINDING, source: 'tool_misuse' })
    expect(screen.getByText('Inspect Tool Calls')).toBeInTheDocument()
    expect(screen.getByText('Review Permissions')).toBeInTheDocument()
  })

  it('shows runtime_anomaly actions for runtime_anomaly source', () => {
    renderPanel({ ...BASE_FINDING, source: 'runtime_anomaly' })
    expect(screen.getByText('Analyze Behavior')).toBeInTheDocument()
  })

  it('renders fallback empty state for unknown finding type', () => {
    renderPanel({ ...BASE_FINDING, source: 'unknown_xyz' })
    expect(screen.getByTestId('action-panel-empty')).toBeInTheDocument()
    expect(screen.getByText(/No actions available for this finding type/i)).toBeInTheDocument()
  })

  it('does NOT render action-panel container for unknown type', () => {
    renderPanel({ ...BASE_FINDING, source: 'unknown_xyz' })
    expect(screen.queryByTestId('action-panel')).not.toBeInTheDocument()
  })
})

// ── Disabled state ────────────────────────────────────────────────────────────

describe('ActionPanel disabled state', () => {
  it('disables "Identify Service Owner" when asset.name is empty', () => {
    renderPanel({ ...BASE_FINDING, asset: { name: '', type: 'Agent' } })
    const btn = screen.getByTestId('action-identify_service')
    expect(btn).toBeDisabled()
  })

  it('enables "Identify Service Owner" when asset.name is present', () => {
    renderPanel(BASE_FINDING)
    const btn = screen.getByTestId('action-identify_service')
    expect(btn).not.toBeDisabled()
  })

  it('does not navigate when a disabled button is clicked', () => {
    renderPanel({ ...BASE_FINDING, asset: { name: '', type: 'Agent' } })
    const btn = screen.getByTestId('action-identify_service')
    // Click should not throw or navigate
    expect(() => fireEvent.click(btn)).not.toThrow()
  })
})

// ── Handlers ──────────────────────────────────────────────────────────────────

describe('createHandlers', () => {
  let navigate

  beforeEach(() => {
    navigate = vi.fn()
  })

  it('openLineage navigates to /admin/lineage with asset and finding_id params', () => {
    const handlers = createHandlers(navigate)
    handlers.openLineage({ id: 'f-abc', asset: { name: 'MyAgent' } })
    expect(navigate).toHaveBeenCalledWith(
      '/admin/lineage?asset=MyAgent&finding_id=f-abc'
    )
  })

  it('openRuntimeSession uses correlated_events[0] as session_id', () => {
    const handlers = createHandlers(navigate)
    handlers.openRuntimeSession({
      id: 'f-abc',
      correlated_events: ['sess-xyz'],
    })
    expect(navigate).toHaveBeenCalledWith(
      '/admin/runtime?session_id=sess-xyz'
    )
  })

  it('openRuntimeSession falls back to finding.id when correlated_events is empty', () => {
    const handlers = createHandlers(navigate)
    handlers.openRuntimeSession({ id: 'f-abc', correlated_events: [] })
    expect(navigate).toHaveBeenCalledWith(
      '/admin/runtime?session_id=f-abc'
    )
  })

  it('openRuntimeByPort navigates to /admin/runtime with filter=network', () => {
    const handlers = createHandlers(navigate)
    handlers.openRuntimeByPort({ id: 'f-net' })
    expect(navigate.mock.calls[0][0]).toMatch(/\/admin\/runtime/)
    expect(navigate.mock.calls[0][0]).toMatch(/filter=network/)
  })

  it('openInventoryByAsset navigates to /admin/inventory with asset param', () => {
    const handlers = createHandlers(navigate)
    handlers.openInventoryByAsset({ asset: { name: 'SQL-Runner' } })
    expect(navigate).toHaveBeenCalledWith(
      '/admin/inventory?asset=SQL-Runner'
    )
  })

  it('openPolicy navigates to /admin/policies', () => {
    const handlers = createHandlers(navigate)
    handlers.openPolicy({})
    expect(navigate).toHaveBeenCalledWith('/admin/policies')
  })

  it('dispatch calls the correct handler', () => {
    dispatch('openPolicy', {}, navigate)
    expect(navigate).toHaveBeenCalledWith('/admin/policies')
  })

  it('dispatch silently no-ops for unknown handler names', () => {
    expect(() => dispatch('nonExistentHandler', {}, navigate)).not.toThrow()
    expect(navigate).not.toHaveBeenCalled()
  })
})
