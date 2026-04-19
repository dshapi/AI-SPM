import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { SimulationContext } from '../../../context/SimulationContext.jsx'
import Lineage from '../Lineage.jsx'

function renderLineage(route = '/admin/lineage', simEvents = []) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <SimulationContext.Provider value={{ simEvents }}>
        <Routes>
          <Route path="/admin/lineage" element={<Lineage />} />
        </Routes>
      </SimulationContext.Provider>
    </MemoryRouter>
  )
}

function ev(event_type, details = {}) {
  return { id: `${event_type}:x:ts`, event_type, stage: 'progress', timestamp: 'ts', details }
}

describe('Lineage context banner', () => {
  it('shows no banner when no query params present', () => {
    const { SESSION_STARTED } = { SESSION_STARTED: 'SESSION_STARTED' }
    renderLineage('/admin/lineage', [ev('SESSION_STARTED', { prompt: 'test' })])
    expect(screen.queryByTestId('lineage-context-banner')).not.toBeInTheDocument()
  })

  it('shows banner with asset name when ?asset= is present', () => {
    renderLineage('/admin/lineage?asset=CustomerSupport-GPT&finding_id=f-001', [ev('SESSION_STARTED', { prompt: 'test' })])
    const banner = screen.getByTestId('lineage-context-banner')
    expect(banner).toBeInTheDocument()
    expect(banner.textContent).toMatch(/CustomerSupport-GPT/)
  })

  it('shows finding_id in the banner', () => {
    renderLineage('/admin/lineage?asset=MyAgent&finding_id=f-xyz', [ev('SESSION_STARTED', { prompt: 'test' })])
    expect(screen.getByTestId('lineage-context-banner').textContent).toMatch(/f-xyz/)
  })

  it('banner can be dismissed', () => {
    renderLineage('/admin/lineage?asset=MyAgent&finding_id=f-001', [ev('SESSION_STARTED', { prompt: 'test' })])
    expect(screen.getByTestId('lineage-context-banner')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('lineage-banner-dismiss'))
    expect(screen.queryByTestId('lineage-context-banner')).not.toBeInTheDocument()
  })
})
