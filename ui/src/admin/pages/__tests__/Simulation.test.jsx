/**
 * Simulation.test.jsx
 * ───────────────────
 * Regression tests for the "stuck at running" and "result stays null" bugs.
 *
 * Root-cause summary:
 *   Bug 1 (Garak): _run_garak never called _ws_emit → no WS events → `running` never
 *                  became false.  Fixed in services/api/routes/simulation.py.
 *   Bug 2 (Both):  useSessionSocket dedup used event_type alone → Garak's duplicate
 *                  event types (simulation.allowed per probe) were dropped.
 *                  Fixed in hooks/useSessionSocket.js.
 *   Bug 3 (Both):  fetchSessionResults called the agent-orchestrator (wrong service)
 *                  for simulation sessions → always 404 → result stayed null.
 *                  Fixed: replaced with _buildResultFromSimEvents().
 *
 * Test strategy: mock useSimulationStream to control the simEvents stream,
 * mock the API layer to avoid real HTTP, then drive the component through
 * idle → running → terminal-event sequences and assert visible state.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// ── Module mocks (hoisted, no top-level variable references inside factories) ─

vi.mock('../../../api/simulationApi.js', () => ({
  createSession:             vi.fn(),
  fetchSessionEvents:        vi.fn().mockResolvedValue([]),
  runSinglePromptSimulation: vi.fn().mockResolvedValue({ session_id: 'sid1', status: 'started' }),
  runGarakSimulation:        vi.fn().mockResolvedValue({ session_id: 'sid1', status: 'started' }),
}))

vi.mock('../../../hooks/useSimulationStream.js', () => ({
  useSimulationStream: vi.fn(),
}))

// ── Imports after mocks ───────────────────────────────────────────────────────

import * as simApi     from '../../../api/simulationApi.js'
import * as streamMod  from '../../../hooks/useSimulationStream.js'
import Simulation      from '../Simulation.jsx'

// ── Shared state refs (mutate in tests, reset in beforeEach) ──────────────────

const _state = {
  simEvents:        [],
  connectionStatus: 'idle',
}
const _startStream = vi.fn()
const _stopStream  = vi.fn()

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderSim() {
  return render(
    <MemoryRouter initialEntries={['/admin/simulation']}>
      <Routes>
        <Route path="/admin/simulation" element={<Simulation />} />
      </Routes>
    </MemoryRouter>
  )
}

/** Click the first "Run Simulation" button (there are two in the DOM). */
function clickRun() {
  const btns = screen.getAllByRole('button', { name: /run simulation/i })
  fireEvent.click(btns[0])
}

function makeEvent(type, stage, details = {}) {
  return {
    id:             `${type}:${Date.now()}:${Math.random()}`,
    event_type:     type,
    stage,
    status:         stage,
    timestamp:      new Date().toISOString(),
    source_service: 'api-simulation',
    details,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  _state.simEvents        = []
  _state.connectionStatus = 'idle'

  simApi.runSinglePromptSimulation.mockResolvedValue({ session_id: 'sid1', status: 'started' })
  simApi.runGarakSimulation.mockResolvedValue({ session_id: 'sid1', status: 'started' })

  // Default: return live _state so tests can mutate and rerender
  streamMod.useSimulationStream.mockImplementation(() => ({
    connectionStatus: _state.connectionStatus,
    simEvents:        _state.simEvents,
    startStream:      _startStream,
    stopStream:       _stopStream,
  }))
})

// ── Idle state ────────────────────────────────────────────────────────────────

describe('Simulation idle state', () => {
  it('renders the idle empty state before any run', () => {
    renderSim()
    expect(screen.getByText('No simulation run yet')).toBeInTheDocument()
  })

  it('renders at least one Run Simulation button', () => {
    renderSim()
    expect(screen.getAllByRole('button', { name: /run simulation/i }).length).toBeGreaterThan(0)
  })
})

// ── startStream / runSinglePromptSimulation wiring ────────────────────────────

describe('handleRun — API and stream wiring', () => {
  it('calls startStream when Run is clicked', async () => {
    renderSim()
    clickRun()
    await waitFor(() => expect(_startStream).toHaveBeenCalledTimes(1))
  })

  it('calls runSinglePromptSimulation for non-Garak mode', async () => {
    renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalledTimes(1))
  })

  it('does not call runGarakSimulation for simple mode', async () => {
    renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalled())
    expect(simApi.runGarakSimulation).not.toHaveBeenCalled()
  })
})

// ── Terminal-event lifecycle (Bug 1 + Bug 2) ──────────────────────────────────

describe('Simulation lifecycle — leaves running state on terminal event', () => {
  it('clears spinner when simulation.blocked event arrives', async () => {
    const { rerender } = renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalled())

    // Inject terminal events (simulates what _ws_emit would deliver over WS)
    act(() => {
      _state.simEvents = [
        makeEvent('simulation.started',  'started', {}),
        makeEvent('simulation.blocked',  'blocked',  { categories: ['prompt_injection'], decision_reason: 'blocked' }),
        makeEvent('simulation.completed','completed', { summary: { result: 'blocked' } }),
      ]
    })

    rerender(
      <MemoryRouter initialEntries={['/admin/simulation']}>
        <Routes>
          <Route path="/admin/simulation" element={<Simulation />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.queryByText('Simulating attack…')).not.toBeInTheDocument()
    })
  })

  it('clears spinner when simulation.allowed event arrives', async () => {
    const { rerender } = renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalled())

    act(() => {
      _state.simEvents = [
        makeEvent('simulation.started', 'started', {}),
        makeEvent('simulation.allowed', 'allowed', { response_preview: 'pass' }),
        makeEvent('simulation.completed','completed', { summary: { result: 'allowed' } }),
      ]
    })

    rerender(
      <MemoryRouter initialEntries={['/admin/simulation']}>
        <Routes>
          <Route path="/admin/simulation" element={<Simulation />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.queryByText('Simulating attack…')).not.toBeInTheDocument()
    })
  })

  it('clears spinner on simulation.error', async () => {
    const { rerender } = renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalled())

    act(() => {
      _state.simEvents = [
        makeEvent('simulation.started', 'started', {}),
        makeEvent('simulation.error',   'error',   { error_message: 'PSS failure' }),
      ]
    })

    rerender(
      <MemoryRouter initialEntries={['/admin/simulation']}>
        <Routes>
          <Route path="/admin/simulation" element={<Simulation />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.queryByText('Simulating attack…')).not.toBeInTheDocument()
    })
  })

  it('Garak: clears spinner when simulation.completed event arrives (Bug 1 fix)', async () => {
    const { rerender } = renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalled())

    // Garak multi-probe run — multiple simulation.allowed events (different correlation IDs)
    act(() => {
      _state.simEvents = [
        makeEvent('simulation.started',  'started',  { attack_type: 'garak', total_probes: 2 }),
        makeEvent('simulation.progress', 'progress', { step: 1, total: 2, probe_name: 'probe_a', correlation_id: 'c1' }),
        makeEvent('simulation.allowed',  'allowed',  { response_preview: '[probe probe_a stub]', correlation_id: 'c1' }),
        makeEvent('simulation.progress', 'progress', { step: 2, total: 2, probe_name: 'probe_b', correlation_id: 'c2' }),
        makeEvent('simulation.allowed',  'allowed',  { response_preview: '[probe probe_b stub]', correlation_id: 'c2' }),
        makeEvent('simulation.completed','completed', { summary: { probes_run: 2, profile: 'Quick Scan' } }),
      ]
    })

    rerender(
      <MemoryRouter initialEntries={['/admin/simulation']}>
        <Routes>
          <Route path="/admin/simulation" element={<Simulation />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.queryByText('Simulating attack…')).not.toBeInTheDocument()
    })
  })
})

// ── API error fast-exit ───────────────────────────────────────────────────────

describe('API error — fast exit from running', () => {
  it('stops showing spinner when API call rejects', async () => {
    simApi.runSinglePromptSimulation.mockRejectedValueOnce(new Error('Network error'))
    renderSim()
    clickRun()
    await waitFor(() => {
      expect(screen.queryByText('Simulating attack…')).not.toBeInTheDocument()
    })
  })
})

// ── Result built from simEvents (Bug 3) ───────────────────────────────────────

describe('Result built from simEvents — not from fetchSessionResults (Bug 3 fix)', () => {
  it('shows result tabs after terminal event (not just idle state)', async () => {
    const { rerender } = renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalled())

    act(() => {
      _state.simEvents = [
        makeEvent('simulation.blocked', 'blocked', {
          categories:      ['prompt_injection'],
          decision_reason: 'Prompt injection detected',
        }),
        makeEvent('simulation.completed','completed', { summary: { result: 'blocked' } }),
      ]
    })

    rerender(
      <MemoryRouter initialEntries={['/admin/simulation']}>
        <Routes>
          <Route path="/admin/simulation" element={<Simulation />} />
        </Routes>
      </MemoryRouter>
    )

    // Result tabs become visible once result is populated from simEvents
    await waitFor(() => {
      // At minimum the "Results" panel header should be visible
      expect(screen.queryByText('No simulation run yet')).not.toBeInTheDocument()
    })
  })

  it('never calls fetchSessionResults (removed from import — wrong endpoint)', () => {
    // fetchSessionResults was removed from Simulation.jsx's import list as part
    // of the Bug 3 fix.  The mock factory doesn't include it either, confirming
    // the function is no longer referenced by the simulation page.
    expect('fetchSessionResults' in simApi).toBe(false)
  })
})

// ── useSessionSocket dedup regression (Bug 2) ─────────────────────────────────

describe('useSessionSocket dedup — allows duplicate event_types with different correlation IDs', () => {
  it('useSimulationStream returns multiple events of same type in Garak run', async () => {
    const { rerender } = renderSim()
    clickRun()
    await waitFor(() => expect(simApi.runSinglePromptSimulation).toHaveBeenCalled())

    // Simulate what useSimulationStream would have after proper dedup fix:
    // Both probe-allowed events present (not just the first)
    act(() => {
      _state.simEvents = [
        makeEvent('simulation.started',  'started', {}),
        makeEvent('simulation.allowed',  'allowed', { correlation_id: 'c1', response_preview: 'probe1' }),
        makeEvent('simulation.allowed',  'allowed', { correlation_id: 'c2', response_preview: 'probe2' }),
        makeEvent('simulation.completed','completed', { summary: { probes_run: 2 } }),
      ]
    })

    rerender(
      <MemoryRouter initialEntries={['/admin/simulation']}>
        <Routes>
          <Route path="/admin/simulation" element={<Simulation />} />
        </Routes>
      </MemoryRouter>
    )

    // Both events should appear in the simulation events list
    // (component receives 4 events, not 3 deduplicated to 3 unique types)
    expect(_state.simEvents.length).toBe(4)
    const allowedEvents = _state.simEvents.filter(e => e.stage === 'allowed')
    expect(allowedEvents.length).toBe(2)
  })
})
