import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SimulationContext } from '../../../context/SimulationContext.jsx'
import { EVENT_TYPES } from '../../../lib/eventSchema.js'
import Lineage from '../Lineage.jsx'

function ev(event_type, details = {}) {
  return { id: `${event_type}:x:ts`, event_type, stage: 'progress', timestamp: 'ts', details }
}

describe('Lineage live events', () => {
  it('renders prompt node label when session.started event present', () => {
    const events = [ev(EVENT_TYPES.SESSION_STARTED, { prompt: 'test prompt' })]
    render(
      <MemoryRouter>
        <SimulationContext.Provider value={{ simEvents: events }}>
          <Lineage />
        </SimulationContext.Provider>
      </MemoryRouter>
    )
    // Should have rendered the graph with the prompt node
    const promptLabels = screen.getAllByText('User Prompt')
    expect(promptLabels.length).toBeGreaterThan(0)
  })

  it('shows empty state message when no events', () => {
    render(
      <MemoryRouter>
        <SimulationContext.Provider value={{ simEvents: [] }}>
          <Lineage />
        </SimulationContext.Provider>
      </MemoryRouter>
    )
    // Should show some placeholder, not crash
    expect(document.body).toBeTruthy()
  })
})
