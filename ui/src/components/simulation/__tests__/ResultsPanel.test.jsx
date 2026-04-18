/**
 * ResultsPanel.test.jsx
 * ─────────────────────
 * Regression tests for the Simulation Results panel.
 *
 * Covers:
 *   1. Idle empty state renders correctly (no tabs, FlaskConical icon)
 *   2. Spinner state renders with animated steps (no tabs)
 *   3. Tab bar is visible once a result or events exist
 *   4. Tab switching works and active state is preserved
 *   5. No tabs disappear unexpectedly after rendering
 *   6. Summary tab renders with result data
 *   7. Decision Trace tab renders connector-style trace
 *   8. Output tab shows REQUEST TERMINATED for blocked verdict
 *   9. Output tab shows terminal chrome for allowed/flagged verdict
 *  10. Policy Impact tab renders with severity-based styling
 *  11. Timeline tab renders events during streaming
 *  12. Risk Analysis tab renders RiskTrend when events exist
 *  13. Explainability tab renders with no selected event
 *  14. Garak tabs appear only for garak mode
 *  15. Auto-switch to Decision Trace when result arrives
 *  16. Auto-switch to Timeline only for Garak runs
 *  17. Empty state panel is shown (not tab bar) in idle state
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ResultsPanel } from '../ResultsPanel.jsx'

// ── Mocks ─────────────────────────────────────────────────────────────────────

// Lightweight mock for ExplainabilityPanel
vi.mock('../../ExplainabilityPanel.jsx', () => ({
  ExplainabilityPanel: ({ event }) => (
    <div data-testid="explainability-panel">
      {event?.details?.explanation ?? 'No explanation'}
    </div>
  ),
}))

// Lightweight mock for RiskTrend
vi.mock('../RiskTrend.jsx', () => ({
  RiskTrend: ({ events }) => (
    <div data-testid="risk-trend">{events.length} events</div>
  ),
}))

// Lightweight mock for PhaseSection
vi.mock('../PhaseSection.jsx', () => ({
  PhaseSection: ({ phase, events }) => (
    <div data-testid={`phase-${phase}`}>{events.length} events in {phase}</div>
  ),
}))

// Lightweight mock for phaseGrouping
vi.mock('../../../lib/phaseGrouping.js', () => ({
  groupByPhase: (events) => ({
    System: events,
  }),
  groupByPhaseAndProbe: (events) => ({
    System: events,
  }),
}))

// ── Test fixtures ─────────────────────────────────────────────────────────────

const IDLE_SIMULATION = { state: 'idle', events: [], mode: 'single' }

const MOCK_RESULT = {
  verdict:           'blocked',
  riskScore:         94,
  riskLevel:         'Critical',
  executionMs:       38,
  policiesTriggered: ['Prompt-Guard v3'],
  decisionTrace: [
    { step: 1, label: 'Prompt received', status: 'ok',       detail: '23 tokens', ts: '09:14:03.002' },
    { step: 2, label: 'Policy decision', status: 'critical', detail: 'BLOCK',      ts: '09:14:03.018' },
  ],
  output:         null,
  blockedMessage: 'Request terminated by policy engine.',
  policyImpact: [
    { policy: 'Prompt-Guard v3', action: 'BLOCK', trigger: 'Injection pattern 0.97', severity: 'critical' },
  ],
  risk: {
    injectionDetected: true,
    anomalyScore:      0.94,
    techniques:        ['Instruction override'],
    explanation:       'Injection pattern detected.',
  },
  recommendations: [],
}

const ALLOWED_RESULT = {
  ...MOCK_RESULT,
  verdict:           'allowed',
  riskScore:         12,
  output:            'Hello, how can I help?',
  blockedMessage:    null,
  policiesTriggered: [],
  policyImpact:      [],
}

const MOCK_CONFIG = {
  agent:       'TestAgent-v1',
  model:       'gpt-4o',
  environment: 'Production',
  attackType:  'injection',
  execMode:    'live',
}

const MOCK_EVENTS = [
  {
    id:         'evt-1',
    event_type: 'prompt.received',
    stage:      'started',
    timestamp:  '2024-01-01T00:00:00Z',
    details:    { message: 'Prompt received' },
  },
  {
    id:         'evt-2',
    event_type: 'policy.decision',
    stage:      'blocked',
    timestamp:  '2024-01-01T00:00:01Z',
    details:    { message: 'Blocked by policy', explanation: 'Injection detected.' },
  },
]

// ── Helper ────────────────────────────────────────────────────────────────────

function renderPanel(props = {}) {
  const defaults = {
    simulation:        IDLE_SIMULATION,
    result:            null,
    attackType:        'injection',
    config:            MOCK_CONFIG,
    running:           false,
    apiError:          null,
    sessionId:         null,
    connectionStatus:  'idle',
  }
  return render(<ResultsPanel {...defaults} {...props} />)
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ResultsPanel — idle state', () => {
  it('shows empty state panel with FlaskConical icon text', () => {
    renderPanel()
    expect(screen.getByText(/No simulation run yet/i)).toBeInTheDocument()
    expect(screen.getByText(/Configure an attack type/i)).toBeInTheDocument()
  })

  it('does NOT show the tab bar in idle state', () => {
    renderPanel()
    expect(screen.queryByRole('button', { name: 'Summary' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Decision Trace' })).not.toBeInTheDocument()
  })

  it('renders the Results header in idle state', () => {
    renderPanel()
    expect(screen.getByText('Results')).toBeInTheDocument()
  })
})

describe('ResultsPanel — spinner state', () => {
  it('shows spinner with animated steps when running with no events', () => {
    renderPanel({
      running:    true,
      simulation: { state: 'connecting', events: [], mode: 'single' },
    })
    expect(screen.getByText(/Simulating attack|Connecting/i)).toBeInTheDocument()
    expect(screen.getByText(/Assembling context/i)).toBeInTheDocument()
    expect(screen.getByText(/Evaluating policy chain/i)).toBeInTheDocument()
  })

  it('does NOT show tab bar during spinner state (no events)', () => {
    renderPanel({
      running:    true,
      simulation: { state: 'connecting', events: [], mode: 'single' },
    })
    expect(screen.queryByRole('button', { name: 'Summary' })).not.toBeInTheDocument()
  })

  it('shows tab bar (not spinner) once events start streaming', () => {
    renderPanel({
      running:    true,
      simulation: { state: 'running', events: MOCK_EVENTS, mode: 'single' },
    })
    // Tab bar must be visible
    expect(screen.getByRole('button', { name: 'Timeline' })).toBeInTheDocument()
    // Spinner steps should NOT appear since tabs are now rendered
    expect(screen.queryByText(/Assembling context/i)).not.toBeInTheDocument()
  })
})

describe('ResultsPanel — tab bar', () => {
  it('shows all standard tabs when result exists', () => {
    renderPanel({ result: MOCK_RESULT })
    const standardTabs = ['Summary', 'Decision Trace', 'Output', 'Policy Impact', 'Risk Analysis', 'Recommendations', 'Timeline', 'Explainability']
    for (const tab of standardTabs) {
      expect(screen.getByRole('button', { name: tab })).toBeInTheDocument()
    }
  })

  it('does NOT show Garak tabs for single-prompt mode', () => {
    renderPanel({ result: MOCK_RESULT, simulation: { state: 'completed', events: [], mode: 'single' } })
    expect(screen.queryByRole('button', { name: 'Probe Results' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Coverage' })).not.toBeInTheDocument()
  })

  it('shows Garak tabs for garak mode', () => {
    renderPanel({
      result:     MOCK_RESULT,
      simulation: { state: 'completed', events: MOCK_EVENTS, mode: 'garak' },
    })
    expect(screen.getByRole('button', { name: 'Probe Results' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Coverage' })).toBeInTheDocument()
  })

  it('switches active tab on click', () => {
    renderPanel({ result: MOCK_RESULT })
    const outputTab = screen.getByRole('button', { name: 'Output' })
    fireEvent.click(outputTab)
    // Now Output tab should be active (border-blue-600 class)
    expect(outputTab.className).toMatch(/border-blue-600/)
    // Summary should no longer be active
    expect(screen.getByRole('button', { name: 'Summary' }).className).toMatch(/border-transparent/)
  })

  it('preserves active tab state after re-render with same result', () => {
    const { rerender } = renderPanel({ result: MOCK_RESULT })
    const policyTab = screen.getByRole('button', { name: 'Policy Impact' })
    fireEvent.click(policyTab)
    // Simulate a parent re-render that doesn't change result
    rerender(
      <ResultsPanel
        simulation={IDLE_SIMULATION}
        result={MOCK_RESULT}
        attackType="injection"
        config={MOCK_CONFIG}
        running={false}
        apiError={null}
        sessionId={null}
        connectionStatus="closed"
      />
    )
    // Policy Impact should still be active (no auto-switch since result hasn't changed)
    expect(screen.getByRole('button', { name: 'Policy Impact' }).className).toMatch(/border-blue-600/)
  })

  it('no tabs disappear — all 8 base tabs remain visible after switching', () => {
    renderPanel({ result: MOCK_RESULT })
    const tabs = ['Summary', 'Decision Trace', 'Output', 'Policy Impact', 'Risk Analysis', 'Recommendations', 'Timeline', 'Explainability']
    // Click through a few tabs
    fireEvent.click(screen.getByRole('button', { name: 'Timeline' }))
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    // All tabs must still exist
    for (const tab of tabs) {
      expect(screen.getByRole('button', { name: tab })).toBeInTheDocument()
    }
  })
})

describe('ResultsPanel — Summary tab', () => {
  beforeEach(() => {
    renderPanel({ result: MOCK_RESULT })
    // Switch to Decision Trace (auto-switched) → go back to Summary manually
    fireEvent.click(screen.getByRole('button', { name: 'Summary' }))
  })

  it('shows verdict label in hero section', () => {
    expect(screen.getAllByText('BLOCKED').length).toBeGreaterThan(0)
  })

  it('shows risk score in hero', () => {
    expect(screen.getByText('94')).toBeInTheDocument()
  })

  it('shows policies triggered with Shield icon section', () => {
    expect(screen.getByText('Policies Triggered')).toBeInTheDocument()
    expect(screen.getByText('Prompt-Guard v3')).toBeInTheDocument()
  })

  it('shows simulation config expandable section', () => {
    expect(screen.getByText('Simulation config')).toBeInTheDocument()
  })

  it('shows stats row with Risk Level, Policies Hit, Exec Time', () => {
    expect(screen.getByText('Risk Level')).toBeInTheDocument()
    expect(screen.getByText('Policies Hit')).toBeInTheDocument()
    expect(screen.getByText('Exec Time')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Decision Trace tab', () => {
  it('shows empty state when no result', () => {
    renderPanel()
    // In idle state, we see the "no simulation run yet" panel
    // Navigate to a state where we have tab bar but no result
    renderPanel({
      simulation: { state: 'completed', events: MOCK_EVENTS, mode: 'single' },
      result:     null,
      running:    false,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Decision Trace' }))
    expect(screen.getByText(/Decision trace will appear here/i)).toBeInTheDocument()
  })

  it('renders trace steps with connector-style layout when result exists', () => {
    renderPanel({ result: MOCK_RESULT })
    // Auto-switched to Decision Trace since result was just provided
    expect(screen.getByText('Prompt received')).toBeInTheDocument()
    expect(screen.getByText('Policy decision')).toBeInTheDocument()
  })

  it('shows step numbers in trace', () => {
    renderPanel({ result: MOCK_RESULT })
    expect(screen.getByText('01')).toBeInTheDocument()
    expect(screen.getByText('02')).toBeInTheDocument()
  })

  it('shows timing info in Decision Trace', () => {
    renderPanel({ result: MOCK_RESULT })
    expect(screen.getByText('38ms total')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Output tab', () => {
  it('shows REQUEST TERMINATED chrome for blocked verdict', () => {
    renderPanel({ result: MOCK_RESULT })
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    expect(screen.getByText('REQUEST TERMINATED')).toBeInTheDocument()
    expect(screen.getByText('Attack Blocked')).toBeInTheDocument()
    expect(screen.getByText(/Safety message returned to user/i)).toBeInTheDocument()
    expect(screen.getByText('Request terminated by policy engine.')).toBeInTheDocument()
  })

  it('shows terminal chrome (traffic lights + model name) for allowed verdict', () => {
    renderPanel({ result: ALLOWED_RESULT })
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    // Terminal header shows model name
    expect(screen.getByText('gpt-4o')).toBeInTheDocument()
    // Output text is shown
    expect(screen.getByText('Hello, how can I help?')).toBeInTheDocument()
    // Footer shows char count
    expect(screen.getByText(/chars/)).toBeInTheDocument()
  })

  it('shows empty state when no result', () => {
    renderPanel({
      simulation: { state: 'completed', events: MOCK_EVENTS, mode: 'single' },
      result:     null,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    expect(screen.getByText(/AI output will appear here/i)).toBeInTheDocument()
  })
})

describe('ResultsPanel — Policy Impact tab', () => {
  it('renders policies with severity-based styling', () => {
    renderPanel({ result: MOCK_RESULT })
    fireEvent.click(screen.getByRole('button', { name: 'Policy Impact' }))
    expect(screen.getByText('Prompt-Guard v3')).toBeInTheDocument()
    expect(screen.getByText('Injection pattern 0.97')).toBeInTheDocument()
  })

  it('shows "No policies triggered" when policyImpact is empty', () => {
    renderPanel({ result: { ...MOCK_RESULT, policyImpact: [] } })
    fireEvent.click(screen.getByRole('button', { name: 'Policy Impact' }))
    expect(screen.getByText(/No policies triggered/i)).toBeInTheDocument()
  })

  it('renders BLOCK badge for BLOCK action policies', () => {
    renderPanel({ result: MOCK_RESULT })
    fireEvent.click(screen.getByRole('button', { name: 'Policy Impact' }))
    expect(screen.getByText('BLOCK')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Timeline tab', () => {
  it('shows idle message when no events', () => {
    renderPanel({
      simulation: { state: 'idle', events: [], mode: 'single' },
      result:     null,
    })
    // We need tab bar to be visible — put some events or a result
    // Actually in idle state we see empty state panel. Let's use completed+no events.
    renderPanel({
      simulation:       { state: 'completed', events: [], mode: 'single' },
      result:           null,
      connectionStatus: 'closed',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Timeline' }))
    expect(screen.getByText(/Run a simulation to see events here|No events yet/i)).toBeInTheDocument()
  })

  it('renders phase sections when events exist', () => {
    renderPanel({
      simulation: { state: 'running', events: MOCK_EVENTS, mode: 'single' },
      running:    true,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Timeline' }))
    expect(screen.getByTestId('phase-System')).toBeInTheDocument()
  })

  it('shows LIVE status label when running', () => {
    renderPanel({
      simulation: { state: 'running', events: MOCK_EVENTS, mode: 'single' },
      running:    true,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Timeline' }))
    expect(screen.getByText('LIVE')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Risk Analysis tab', () => {
  it('shows RiskTrend component when sim events exist', () => {
    renderPanel({
      simulation: { state: 'completed', events: MOCK_EVENTS, mode: 'single' },
      result:     MOCK_RESULT,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByTestId('risk-trend')).toBeInTheDocument()
  })

  it('shows anomaly score bar when result.risk exists', () => {
    renderPanel({ result: MOCK_RESULT })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByText('Anomaly Score')).toBeInTheDocument()
    expect(screen.getByText('0.94')).toBeInTheDocument()
  })

  it('shows techniques when present', () => {
    renderPanel({ result: MOCK_RESULT })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByText('Instruction override')).toBeInTheDocument()
  })

  it('shows empty state message when no events and no result', () => {
    renderPanel({
      simulation: { state: 'completed', events: [], mode: 'single' },
      result:     null,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByText(/Risk analysis will appear after/i)).toBeInTheDocument()
  })
})

describe('ResultsPanel — Explainability tab', () => {
  it('shows hint text when no event is selected', () => {
    renderPanel({
      simulation: { state: 'completed', events: MOCK_EVENTS, mode: 'single' },
      result:     null,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Explainability' }))
    expect(screen.getByText(/Click a timeline event/i)).toBeInTheDocument()
  })
})

describe('ResultsPanel — auto-switch behaviour', () => {
  it('auto-switches to Decision Trace when a result arrives', () => {
    const { rerender } = renderPanel({
      simulation:       { state: 'completed', events: MOCK_EVENTS, mode: 'single' },
      result:           null,
      connectionStatus: 'closed',
    })
    // Manually switch to Timeline
    fireEvent.click(screen.getByRole('button', { name: 'Timeline' }))
    expect(screen.getByRole('button', { name: 'Timeline' }).className).toMatch(/border-blue-600/)

    // Now a result arrives
    rerender(
      <ResultsPanel
        simulation={{ state: 'completed', events: MOCK_EVENTS, mode: 'single' }}
        result={MOCK_RESULT}
        attackType="injection"
        config={MOCK_CONFIG}
        running={false}
        apiError={null}
        sessionId={null}
        connectionStatus="closed"
      />
    )
    // Should have switched to Decision Trace
    expect(screen.getByRole('button', { name: 'Decision Trace' }).className).toMatch(/border-blue-600/)
  })

  it('does NOT auto-switch to Timeline for single-prompt runs', () => {
    const { rerender } = renderPanel({
      simulation:       { state: 'idle', events: [], mode: 'single' },
      result:           MOCK_RESULT,        // result exists → active = Decision Trace
      connectionStatus: 'closed',
    })
    // Currently on Decision Trace (auto-switched on result)
    expect(screen.getByRole('button', { name: 'Decision Trace' }).className).toMatch(/border-blue-600/)

    // Simulation transitions to running (single-prompt mode)
    rerender(
      <ResultsPanel
        simulation={{ state: 'running', events: MOCK_EVENTS, mode: 'single' }}
        result={MOCK_RESULT}
        attackType="injection"
        config={MOCK_CONFIG}
        running={true}
        apiError={null}
        sessionId="sid-1"
        connectionStatus="connected"
      />
    )
    // Should NOT have switched to Timeline for single-prompt mode
    expect(screen.getByRole('button', { name: 'Decision Trace' }).className).toMatch(/border-blue-600/)
  })

  it('DOES auto-switch to Timeline for Garak runs', () => {
    const { rerender } = renderPanel({
      simulation:       { state: 'idle', events: [], mode: 'garak' },
      result:           MOCK_RESULT,
      connectionStatus: 'closed',
    })
    // Currently on Decision Trace

    // Garak run starts
    rerender(
      <ResultsPanel
        simulation={{ state: 'connecting', events: [], mode: 'garak' }}
        result={null}
        attackType="custom"
        config={{ ...MOCK_CONFIG, customMode: 'garak' }}
        running={true}
        apiError={null}
        sessionId="sid-garak"
        connectionStatus="connecting"
      />
    )
    // Should have switched to Timeline for Garak mode
    // (Tab bar visible because it's in spinner-with-events or garak mode triggers)
    // Note: in garak mode with state=connecting, spinner shows since no events yet
    // The auto-switch fires, but spinner hides tabs — once events arrive tabs show Timeline active
    // We can't easily test the hidden spinner case, so let's confirm via events
    rerender(
      <ResultsPanel
        simulation={{ state: 'running', events: MOCK_EVENTS, mode: 'garak' }}
        result={null}
        attackType="custom"
        config={{ ...MOCK_CONFIG, customMode: 'garak' }}
        running={true}
        apiError={null}
        sessionId="sid-garak"
        connectionStatus="connected"
      />
    )
    // Timeline tab should be active
    expect(screen.getByRole('button', { name: 'Timeline' }).className).toMatch(/border-blue-600/)
  })
})

describe('ResultsPanel — error / edge cases', () => {
  it('shows apiError "Simulated" badge when apiError is set', () => {
    renderPanel({
      result:    MOCK_RESULT,
      apiError:  'Connection refused',
      sessionId: 'sid-1',
    })
    expect(screen.getByText('Simulated')).toBeInTheDocument()
  })

  it('renders with no result and no simulation state gracefully (fully idle)', () => {
    // Should not throw
    expect(() => renderPanel()).not.toThrow()
    expect(screen.getByText(/No simulation run yet/i)).toBeInTheDocument()
  })

  it('handles result with undefined optional fields', () => {
    const minimalResult = {
      verdict:           'allowed',
      riskScore:         10,
      riskLevel:         'Low',
      executionMs:       20,
      policiesTriggered: [],
      decisionTrace:     [],
      output:            'OK',
      blockedMessage:    null,
      policyImpact:      [],
      risk:              undefined,
      recommendations:   undefined,
    }
    // Should not throw
    expect(() => renderPanel({ result: minimalResult })).not.toThrow()
  })
})
