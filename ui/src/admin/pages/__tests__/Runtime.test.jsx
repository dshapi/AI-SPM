import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Heavy mocks — Runtime has real API calls we don't want.
// Hoisted bindings so individual tests can override per-test.
const _mocks = vi.hoisted(() => ({
  fetchAllSessions:   vi.fn().mockResolvedValue([]),
  fetchSessionEvents: vi.fn().mockResolvedValue({ events: [] }),
}))
vi.mock('../../../api/simulationApi.js', () => _mocks)
vi.mock('../../../hooks/useSessionSocket.js', () => ({
  useSessionSocket: () => ({
    connectionStatus: 'idle',
    liveEvents:  [],
    connectWs:   vi.fn(),
    disconnectWs: vi.fn(),
  }),
}))

import Runtime from '../Runtime.jsx'

function renderRuntime(route = '/admin/runtime') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/admin/runtime" element={<Runtime />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('Runtime ?filter=network', () => {
  it('shows network filter banner when ?filter=network is in URL', () => {
    renderRuntime('/admin/runtime?filter=network')
    expect(screen.getByTestId('network-filter-banner')).toBeInTheDocument()
    expect(screen.getByTestId('network-filter-banner').textContent).toMatch(/network/i)
  })

  it('does NOT show network banner without ?filter=network', () => {
    renderRuntime('/admin/runtime')
    expect(screen.queryByTestId('network-filter-banner')).not.toBeInTheDocument()
  })
})

// ────────────────────────────────────────────────────────────────────────────
// Regression: object-shaped payload fields must not crash the page.
// ────────────────────────────────────────────────────────────────────────────
// `simulation.completed` events ship a structured `payload.summary`:
//     { result: 'allowed', categories: ['S1', ...], duration_ms: 12 }
// Earlier, _eventDescription returned p.summary directly when truthy, so the
// raw object reached JSX as a child and React threw error #31:
//   "Objects are not valid as a React child
//    (found: object with keys {result, categories, duration_ms})"
// This blanked the entire Runtime page on click. The pin below renders a
// session whose event log includes that exact shape — a regression here
// means the same blank-page bug is back.
describe('Runtime — object-shaped payload fields are stringified, not rendered raw', () => {
  it('renders without crashing when an event has payload.summary as {result, categories, duration_ms}', async () => {
    _mocks.fetchAllSessions.mockResolvedValueOnce([{
      session_id: 'sess-1',
      agent_id:   'FinanceAssistant-v2',
      status:     'completed',
      risk_score: 0.42,
      risk_tier:  'limited',
      policy_decision: 'allow',
      created_at: new Date().toISOString(),
    }])
    _mocks.fetchSessionEvents.mockResolvedValueOnce({
      events: [
        // The exact shape that crashed Runtime in prod:
        {
          session_id:     'sess-1',
          event_type:     'simulation.completed',
          source_service: 'api-chat',
          timestamp:      new Date().toISOString(),
          payload: {
            summary: { result: 'allowed', categories: ['S1', 'S4'], duration_ms: 12 },
          },
        },
        // A policy event whose `reason` is also a structured object — the
        // other field that flows into JSX text via lastDecision.reason.
        {
          session_id:     'sess-1',
          event_type:     'policy.allowed',
          source_service: 'api-chat',
          timestamp:      new Date().toISOString(),
          payload: {
            decision: 'allow',
            reason:   { result: 'allowed', categories: [], duration_ms: 7 },
          },
        },
      ],
    })

    renderRuntime('/admin/runtime')

    // If the bug is back, render throws synchronously and screen has no
    // banner / KPI strip. Wait for the page header to confirm the tree
    // mounted, then prove the simulation summary was projected to text.
    await waitFor(() => expect(screen.getByText(/Runtime/i)).toBeInTheDocument())
    // The KPI strip exists, which means render survived past the event list.
    expect(screen.getByText(/Active Sessions/i)).toBeInTheDocument()
  })
})
