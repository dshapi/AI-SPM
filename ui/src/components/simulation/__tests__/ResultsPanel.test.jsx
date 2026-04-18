/**
 * ResultsPanel.test.jsx
 * ─────────────────────
 * Regression tests for the rebuilt Simulation Results panel.
 *
 * Key contract changes vs. prior version
 * ───────────────────────────────────────
 * • Component accepts simulationState (from useSimulationState) + mode prop.
 *   Old separate props (simulation, result, running, sessionId, connectionStatus)
 *   have been consolidated into simulationState.
 * • Tabs are ALWAYS visible — even in idle state — so the tab bar is never
 *   conditionally hidden. The Summary tab handles each status internally.
 *
 * Coverage
 * ────────
 *   1.  Idle: tab bar visible, Summary shows empty state (not a standalone panel)
 *   2.  Running: tab bar visible, Summary shows spinner inline
 *   3.  Completed: tab bar visible, Summary shows full result
 *   4.  Failed: tab bar visible, Summary shows error panel
 *   5.  Tab switching and active state preservation
 *   6.  No tabs disappear after switching
 *   7.  Summary tab — completed result rendering
 *   8.  Decision Trace tab — connector layout
 *   9.  Output tab — REQUEST TERMINATED (blocked)
 *  10.  Output tab — terminal chrome (allowed)
 *  11.  Policy Impact tab — severity-based styling
 *  12.  Timeline tab — live events during streaming
 *  13.  Risk Analysis tab — RiskTrend + anomaly bar
 *  14.  Explainability tab — empty state when no event selected
 *  15.  Garak tabs appear only for garak mode
 *  16.  Auto-switch to Summary on result arrival (single-prompt)
 *  17.  Auto-switch to Decision Trace on result arrival (garak)
 *  18.  Auto-switch to Timeline when Garak run starts
 *  19.  Edge cases and graceful rendering
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent }             from '@testing-library/react'
import { ResultsPanel }                          from '../ResultsPanel.jsx'

// ── Mocks ─────────────────────────────────────────────────────────────────────

// ExplainabilityPanel is used inside Explainability.jsx which re-imports it
vi.mock('../../ExplainabilityPanel.jsx', () => ({
  ExplainabilityPanel: ({ event }) => (
    <div data-testid="explainability-panel">
      {event?.details?.explanation ?? 'No explanation'}
    </div>
  ),
}))

vi.mock('../RiskTrend.jsx', () => ({
  RiskTrend: ({ events }) => (
    <div data-testid="risk-trend">{events.length} events</div>
  ),
}))

vi.mock('../PhaseSection.jsx', () => ({
  PhaseSection: ({ phase, events }) => (
    <div data-testid={`phase-${phase}`}>{events.length} events in {phase}</div>
  ),
}))

vi.mock('../../../lib/phaseGrouping.js', () => ({
  groupByPhase:         (events) => ({ System: events }),
  groupByPhaseAndProbe: (events) => ({ System: events }),
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** Build a SimulationState matching the useSimulationState contract. */
function makeSimState(overrides = {}) {
  return {
    status:          'idle',
    steps:           [],
    partialResults:  [],
    finalResults:    null,
    error:           undefined,
    startedAt:       undefined,
    completedAt:     undefined,
    sessionId:       null,
    simEvents:       [],
    connectionStatus:'idle',
    ...overrides,
  }
}

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
    simulationState: makeSimState(),
    mode:            'single',
    attackType:      'injection',
    config:          MOCK_CONFIG,
    apiError:        null,
  }
  return render(<ResultsPanel {...defaults} {...props} />)
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ResultsPanel — idle state', () => {
  it('renders the tab bar even in idle state', () => {
    renderPanel()
    // Tabs are always visible — idle state does NOT hide the tab bar
    expect(screen.getByRole('button', { name: 'Summary' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Timeline/ })).toBeInTheDocument()
  })

  it('shows "No simulation run yet" inside the Summary tab when idle', () => {
    renderPanel()
    // Summary is the default active tab — its empty state is rendered inline
    expect(screen.getByText(/No simulation run yet/i)).toBeInTheDocument()
    expect(screen.getByText(/Configure an attack type/i)).toBeInTheDocument()
  })

  it('renders the "Simulation Results" header', () => {
    renderPanel()
    expect(screen.getByText('Simulation Results')).toBeInTheDocument()
  })

  it('switches to Timeline tab and shows idle message', () => {
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    expect(screen.getByText(/Run a simulation to see events here/i)).toBeInTheDocument()
  })
})

describe('ResultsPanel — running state', () => {
  it('tab bar is visible while simulation is running', () => {
    renderPanel({
      simulationState: makeSimState({
        status:          'running',
        connectionStatus:'connecting',
      }),
    })
    expect(screen.getByRole('button', { name: 'Summary' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Timeline/ })).toBeInTheDocument()
  })

  it('Summary tab shows spinner when running with no result', () => {
    renderPanel({
      simulationState: makeSimState({
        status:          'running',
        connectionStatus:'connecting',
      }),
    })
    // Summary is active by default for single-prompt runs
    expect(screen.getByText(/Simulating attack|Connecting/i)).toBeInTheDocument()
  })

  it('shows step count in spinner when steps have arrived', () => {
    const steps = [
      { id: 's1', label: 'Simulation started', status: 'done',    timestamp: Date.now() },
      { id: 's2', label: 'Policy evaluation',  status: 'running', timestamp: Date.now() },
    ]
    renderPanel({
      simulationState: makeSimState({
        status:          'running',
        connectionStatus:'connected',
        steps,
      }),
    })
    expect(screen.getByText(/2 events received/i)).toBeInTheDocument()
  })

  it('Timeline tab shows LIVE label when running', () => {
    renderPanel({
      simulationState: makeSimState({
        status:          'running',
        connectionStatus:'connected',
        simEvents:       MOCK_EVENTS,
      }),
    })
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    expect(screen.getByText('LIVE')).toBeInTheDocument()
  })
})

describe('ResultsPanel — failed state', () => {
  it('tab bar is visible even when simulation failed', () => {
    renderPanel({
      simulationState: makeSimState({
        status: 'failed',
        error:  'Simulation timeout.',
      }),
    })
    expect(screen.getByRole('button', { name: 'Summary' })).toBeInTheDocument()
  })

  it('Summary tab shows error panel when failed', () => {
    renderPanel({
      simulationState: makeSimState({
        status: 'failed',
        error:  'Simulation timeout — no response received.',
      }),
    })
    expect(screen.getByText('Simulation failed')).toBeInTheDocument()
    expect(screen.getByText(/Simulation timeout/i)).toBeInTheDocument()
  })

  it('shows generic error when no error message provided', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'failed' }),
    })
    expect(screen.getByText('Simulation failed')).toBeInTheDocument()
  })
})

describe('ResultsPanel — tab bar', () => {
  it('shows all 8 standard tabs when completed with a result', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    const standardTabs = [
      'Summary', 'Decision Trace', 'Output', 'Policy Impact',
      'Risk Analysis', 'Recommendations', 'Timeline', 'Explainability',
    ]
    for (const tab of standardTabs) {
      expect(screen.getByRole('button', { name: tab })).toBeInTheDocument()
    }
  })

  it('does NOT show Garak tabs for single-prompt mode', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
      mode:            'single',
    })
    expect(screen.queryByRole('button', { name: 'Probe Results' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Coverage' })).not.toBeInTheDocument()
  })

  it('shows Garak tabs when mode === "garak"', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT, simEvents: MOCK_EVENTS }),
      mode:            'garak',
    })
    expect(screen.getByRole('button', { name: 'Probe Results' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Coverage' })).toBeInTheDocument()
  })

  it('switches active tab on click', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    const outputTab = screen.getByRole('button', { name: 'Output' })
    fireEvent.click(outputTab)
    expect(outputTab.className).toMatch(/border-blue-600/)
    expect(screen.getByRole('button', { name: 'Summary' }).className).toMatch(/border-transparent/)
  })

  it('all 8 base tabs remain visible after switching between them', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    const tabs = [
      'Summary', 'Decision Trace', 'Output', 'Policy Impact',
      'Risk Analysis', 'Recommendations', 'Timeline', 'Explainability',
    ]
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    for (const tab of tabs) {
      expect(screen.getByRole('button', { name: tab })).toBeInTheDocument()
    }
  })

  it('shows event count pill on Timeline tab when events exist', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'running', simEvents: MOCK_EVENTS, connectionStatus: 'connected' }),
    })
    // The pill shows the event count next to the Timeline tab label
    expect(screen.getByText('2')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Summary tab', () => {
  beforeEach(() => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    // Default tab after result arrives (single-prompt) is Summary
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
  it('shows empty state text when no result', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Decision Trace' }))
    expect(screen.getByText(/Decision trace will appear here/i)).toBeInTheDocument()
  })

  it('shows "Building decision trace…" while running', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'running', connectionStatus: 'connected', simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Decision Trace' }))
    expect(screen.getByText(/Building decision trace/i)).toBeInTheDocument()
  })

  it('renders trace steps with connector-style layout when result exists', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    // Default: Summary tab active for single-prompt result — switch to Decision Trace
    fireEvent.click(screen.getByRole('button', { name: 'Decision Trace' }))
    expect(screen.getByText('Prompt received')).toBeInTheDocument()
    expect(screen.getByText('Policy decision')).toBeInTheDocument()
  })

  it('shows padded step numbers in Decision Trace', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Decision Trace' }))
    expect(screen.getByText('01')).toBeInTheDocument()
    expect(screen.getByText('02')).toBeInTheDocument()
  })

  it('shows timing info in Decision Trace', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Decision Trace' }))
    expect(screen.getByText('38ms total')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Output tab', () => {
  it('shows REQUEST TERMINATED chrome for blocked verdict', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    expect(screen.getByText('REQUEST TERMINATED')).toBeInTheDocument()
    expect(screen.getByText('Attack Blocked')).toBeInTheDocument()
    expect(screen.getByText(/Safety message returned to user/i)).toBeInTheDocument()
    expect(screen.getByText('Request terminated by policy engine.')).toBeInTheDocument()
  })

  it('shows terminal chrome (traffic lights + model name) for allowed verdict', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: ALLOWED_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    expect(screen.getByText('gpt-4o')).toBeInTheDocument()
    expect(screen.getByText('Hello, how can I help?')).toBeInTheDocument()
    expect(screen.getByText(/chars/)).toBeInTheDocument()
  })

  it('shows empty state when no result', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Output' }))
    expect(screen.getByText(/AI output will appear here/i)).toBeInTheDocument()
  })
})

describe('ResultsPanel — Policy Impact tab', () => {
  it('renders policies with severity-based styling', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Policy Impact' }))
    expect(screen.getByText('Prompt-Guard v3')).toBeInTheDocument()
    expect(screen.getByText('Injection pattern 0.97')).toBeInTheDocument()
  })

  it('shows "No policies triggered" when policyImpact is empty', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: { ...MOCK_RESULT, policyImpact: [] } }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Policy Impact' }))
    expect(screen.getByText(/No policies triggered/i)).toBeInTheDocument()
  })

  it('renders BLOCK badge for BLOCK action policies', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Policy Impact' }))
    expect(screen.getByText('BLOCK')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Timeline tab', () => {
  it('shows idle message in Timeline when no events (completed with no events)', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed' }),
    })
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    expect(screen.getByText(/No events recorded|Run a simulation to see events/i)).toBeInTheDocument()
  })

  it('renders phase sections when events exist', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'running', connectionStatus: 'connected', simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    expect(screen.getByTestId('phase-System')).toBeInTheDocument()
  })

  it('shows LIVE status label when running', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'running', connectionStatus: 'connected', simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    expect(screen.getByText('LIVE')).toBeInTheDocument()
  })

  it('shows Completed label when status is completed', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT, simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })
})

describe('ResultsPanel — Risk Analysis tab', () => {
  it('shows RiskTrend component when sim events exist', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT, simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByTestId('risk-trend')).toBeInTheDocument()
  })

  it('shows anomaly score bar when result.risk exists', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByText('Anomaly Score')).toBeInTheDocument()
    expect(screen.getByText('0.94')).toBeInTheDocument()
  })

  it('shows techniques when present', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByText('Instruction override')).toBeInTheDocument()
  })

  it('shows empty state message when no events and no result', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed' }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Risk Analysis' }))
    expect(screen.getByText(/Risk analysis will appear after/i)).toBeInTheDocument()
  })
})

describe('ResultsPanel — Explainability tab', () => {
  it('shows hint text when no event is selected', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', simEvents: MOCK_EVENTS }),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Explainability' }))
    expect(screen.getByText(/No event selected/i)).toBeInTheDocument()
    expect(screen.getByText(/Click a Timeline event/i)).toBeInTheDocument()
  })
})

describe('ResultsPanel — auto-switch behaviour', () => {
  it('auto-switches to Summary when single-prompt result arrives', () => {
    const { rerender } = renderPanel({
      simulationState: makeSimState({ status: 'running', connectionStatus: 'connected', simEvents: MOCK_EVENTS }),
    })
    // Manually switch away from Summary
    fireEvent.click(screen.getByRole('button', { name: /^Timeline/ }))
    expect(screen.getByRole('button', { name: /^Timeline/ }).className).toMatch(/border-blue-600/)

    // Result arrives — single-prompt: Summary is active
    rerender(
      <ResultsPanel
        simulationState={makeSimState({ status: 'completed', finalResults: MOCK_RESULT, simEvents: MOCK_EVENTS })}
        mode="single"
        attackType="injection"
        config={MOCK_CONFIG}
        apiError={null}
      />
    )
    expect(screen.getByRole('button', { name: 'Summary' }).className).toMatch(/border-blue-600/)
  })

  it('auto-switches to Decision Trace when Garak result arrives', () => {
    const { rerender } = renderPanel({
      simulationState: makeSimState({ status: 'running', connectionStatus: 'connected', simEvents: MOCK_EVENTS }),
      mode:            'garak',
    })
    // Garak auto-switches to Timeline while running
    expect(screen.getByRole('button', { name: /^Timeline/ }).className).toMatch(/border-blue-600/)

    // Garak result arrives
    rerender(
      <ResultsPanel
        simulationState={makeSimState({ status: 'completed', finalResults: MOCK_RESULT, simEvents: MOCK_EVENTS })}
        mode="garak"
        attackType="custom"
        config={MOCK_CONFIG}
        apiError={null}
      />
    )
    expect(screen.getByRole('button', { name: 'Decision Trace' }).className).toMatch(/border-blue-600/)
  })

  it('auto-switches to Timeline when Garak run starts', () => {
    const { rerender } = renderPanel({
      simulationState: makeSimState(),   // idle
      mode:            'garak',
    })
    // Start Garak simulation
    rerender(
      <ResultsPanel
        simulationState={makeSimState({
          status:          'running',
          connectionStatus:'connected',
          simEvents:       MOCK_EVENTS,
        })}
        mode="garak"
        attackType="custom"
        config={MOCK_CONFIG}
        apiError={null}
      />
    )
    expect(screen.getByRole('button', { name: /^Timeline/ }).className).toMatch(/border-blue-600/)
  })

  it('does NOT auto-switch to Timeline for single-prompt runs', () => {
    const { rerender } = renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
      mode:            'single',
    })
    // Summary is active (result present, single mode)
    expect(screen.getByRole('button', { name: 'Summary' }).className).toMatch(/border-blue-600/)

    // Simulation starts again — single-prompt mode: stays on Summary
    rerender(
      <ResultsPanel
        simulationState={makeSimState({ status: 'running', connectionStatus: 'connected', simEvents: MOCK_EVENTS })}
        mode="single"
        attackType="injection"
        config={MOCK_CONFIG}
        apiError={null}
      />
    )
    // Should switch to Summary (single-prompt auto-switch), not Timeline
    expect(screen.getByRole('button', { name: 'Summary' }).className).toMatch(/border-blue-600/)
  })
})

describe('ResultsPanel — error / edge cases', () => {
  it('shows apiError "Simulated" badge when apiError is set', () => {
    renderPanel({
      simulationState: makeSimState({ status: 'completed', finalResults: MOCK_RESULT }),
      apiError:        'Connection refused',
    })
    expect(screen.getByText('Simulated')).toBeInTheDocument()
  })

  it('renders without crashing when simulationState is null', () => {
    expect(() =>
      render(
        <ResultsPanel
          simulationState={null}
          mode="single"
          attackType="injection"
          config={MOCK_CONFIG}
          apiError={null}
        />
      )
    ).not.toThrow()
  })

  it('renders gracefully in fully idle default state', () => {
    expect(() => renderPanel()).not.toThrow()
    expect(screen.getByText(/No simulation run yet/i)).toBeInTheDocument()
  })

  it('handles result with undefined optional fields without crashing', () => {
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
    expect(() =>
      renderPanel({
        simulationState: makeSimState({ status: 'completed', finalResults: minimalResult }),
      })
    ).not.toThrow()
  })

  it('shows duration in header when startedAt and completedAt are set', () => {
    const now = Date.now()
    renderPanel({
      simulationState: makeSimState({
        status:      'completed',
        finalResults: MOCK_RESULT,
        startedAt:   now - 1500,
        completedAt: now,
      }),
    })
    // Duration should show something like "1.5s"
    expect(screen.getByText(/\d+(\.\d+)?s/)).toBeInTheDocument()
  })
})
