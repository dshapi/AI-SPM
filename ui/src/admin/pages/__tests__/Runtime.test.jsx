import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Heavy mocks — Runtime has real API calls we don't want
vi.mock('../../../api/simulationApi.js', () => ({
  fetchAllSessions:   vi.fn().mockResolvedValue([]),
  fetchSessionEvents: vi.fn().mockResolvedValue([]),
}))
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
