/**
 * Alerts.test.jsx
 * ─────────────────
 * Integration tests for the Findings page (Alerts.jsx).
 *
 * Strategy: mock useFindings hook so tests never hit a real server.
 * Focus areas:
 *   1. Table renders findings correctly
 *   2. Detail panel shows AI-enrichment fields
 *   3. Status update flow works
 *   4. API errors are handled gracefully
 *   5. Loading skeleton renders
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Alerts from '../Alerts.jsx'

// ── Mock the hooks ────────────────────────────────────────────────────────────
// We mock useFindings and useFinding at the module level so the component
// never issues real network requests.

const mockMarkStatus  = vi.fn().mockResolvedValue(undefined)
const mockAttachCase  = vi.fn().mockResolvedValue(undefined)
const mockRefetch     = vi.fn()

vi.mock('../../../hooks/useFindings.js', () => ({
  useFindings: vi.fn(),
  useFinding:  vi.fn().mockReturnValue({ finding: null, loading: false, error: null }),
}))

// Also mock useFilterParams so URL state doesn't need a real router
vi.mock('../../../hooks/useFilterParams.js', () => ({
  useFilterParams: (defaults) => ({
    values:  defaults,
    setters: Object.fromEntries(
      Object.keys(defaults).map(k => [`set${k.charAt(0).toUpperCase()}${k.slice(1)}`, vi.fn()])
    ),
  }),
}))

import { useFindings } from '../../../hooks/useFindings.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FINDING_1 = {
  id: 'f-001',
  batch_hash: 'bh-001',
  title: 'Prompt Injection Detected',
  type: 'threat-hunting-agent',
  severity: 'Critical',
  status: 'Open',
  asset: { name: 'CustomerSupport-GPT', type: 'Agent' },
  description: 'Adversarial prompt detected.',
  timestamp: '2m ago',
  timestampFull: 'Apr 12, 2026 · 10:00 UTC',
  environment: 'Production',
  confidence: 0.91,
  risk_score: 0.87,
  hypothesis: 'Attacker attempted jailbreak via roleplay framing.',
  evidence: ['Evidence line 1', 'Evidence line 2'],
  correlated_findings: ['f-002', 'f-003'],
  policy_signals: [{ type: 'JAILBREAK', policy: 'Prompt-Guard v3' }],
  triggered_policies: [],
  triggeredPolicies: ['Prompt-Guard v3'],
  recommended_actions: ['Block session immediately'],
  recommendedActions: [],
  correlated_events: [],
  should_open_case: true,
  case_id: null,
  source: 'threat-hunting-agent',
  timeline: [],
  rootCause: 'Attacker attempted jailbreak via roleplay framing.',
  contextSnippet: '',
  ttps: ['T1059'],
  owner: undefined,
}

const FINDING_2 = {
  ...FINDING_1,
  id: 'f-002',
  batch_hash: 'bh-002',
  title: 'Data Exfiltration via RAG',
  severity: 'High',
  status: 'Investigating',
  confidence: 0.72,
  risk_score: 0.65,
  evidence: [],
  hypothesis: null,
  policy_signals: [],
  correlated_findings: [],
  recommended_actions: [],
}

function renderAlerts(route = '/admin/alerts') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/admin/alerts"           element={<Alerts />} />
        <Route path="/admin/alerts/:alertId"  element={<Alerts />} />
      </Routes>
    </MemoryRouter>
  )
}

function setupHook(overrides = {}) {
  useFindings.mockReturnValue({
    findings: [FINDING_1, FINDING_2],
    total:    2,
    loading:  false,
    error:    null,
    refetch:  mockRefetch,
    markStatus:  mockMarkStatus,
    attachCase:  mockAttachCase,
    ...overrides,
  })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Findings table', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupHook()
  })

  it('renders the findings table with both rows', () => {
    renderAlerts()
    const table = screen.getByTestId('findings-table')
    expect(within(table).getByText('Prompt Injection Detected')).toBeInTheDocument()
    expect(within(table).getByText('Data Exfiltration via RAG')).toBeInTheDocument()
  })

  it('shows confidence as percentage in the table', () => {
    renderAlerts()
    // FINDING_1 confidence = 0.91 → 91%
    expect(screen.getByText('91%')).toBeInTheDocument()
    // FINDING_2 confidence = 0.72 → 72%
    expect(screen.getByText('72%')).toBeInTheDocument()
  })

  it('shows risk_score formatted to 2 decimals', () => {
    renderAlerts()
    expect(screen.getByText('0.87')).toBeInTheDocument()
    expect(screen.getByText('0.65')).toBeInTheDocument()
  })

  it('shows severity badges for each row', () => {
    renderAlerts()
    // getAllByText handles the case where the badge text appears in both rows
    expect(screen.getAllByText('Critical').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('High').length).toBeGreaterThanOrEqual(1)
  })

  it('shows loading skeleton when loading=true', () => {
    useFindings.mockReturnValue({
      findings: [], total: 0, loading: true, error: null,
      refetch: mockRefetch, markStatus: mockMarkStatus, attachCase: mockAttachCase,
    })
    renderAlerts()
    // Should not show any real finding title
    expect(screen.queryByText('Prompt Injection Detected')).not.toBeInTheDocument()
    // Table header is still visible
    expect(screen.getByText('Conf')).toBeInTheDocument()
  })

  it('shows empty state message when no findings match filters', () => {
    useFindings.mockReturnValue({
      findings: [], total: 0, loading: false, error: null,
      refetch: mockRefetch, markStatus: mockMarkStatus, attachCase: mockAttachCase,
    })
    renderAlerts()
    expect(screen.getByText(/No findings match your filters/i)).toBeInTheDocument()
  })
})

describe('Detail panel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupHook()
  })

  it('opens the detail panel when a finding row is clicked', async () => {
    renderAlerts()
    fireEvent.click(screen.getByTestId('finding-row-f-001'))
    await waitFor(() => {
      expect(screen.getByTestId('finding-detail-panel')).toBeInTheDocument()
    })
  })

  it('detail panel shows hypothesis section', async () => {
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => {
      const panel = screen.getByTestId('finding-detail-panel')
      expect(within(panel).getByText(/Attacker attempted jailbreak/i)).toBeInTheDocument()
    })
  })

  it('detail panel shows evidence lines', async () => {
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => {
      const panel = screen.getByTestId('finding-detail-panel')
      expect(within(panel).getByText('Evidence line 1')).toBeInTheDocument()
      expect(within(panel).getByText('Evidence line 2')).toBeInTheDocument()
    })
  })

  it('detail panel shows correlated findings', async () => {
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => {
      const panel = screen.getByTestId('finding-detail-panel')
      expect(within(panel).getByText('f-002')).toBeInTheDocument()
    })
  })

  it('detail panel shows policy signals', async () => {
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => {
      const panel = screen.getByTestId('finding-detail-panel')
      // JAILBREAK is unique to the policy_signals section
      expect(within(panel).getByText('JAILBREAK')).toBeInTheDocument()
      // Prompt-Guard v3 appears in both Policy Signals and Triggered Policies
      expect(within(panel).getAllByText('Prompt-Guard v3').length).toBeGreaterThanOrEqual(1)
    })
  })

  it('detail panel shows confidence and risk score in header', async () => {
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => {
      const panel = screen.getByTestId('finding-detail-panel')
      // Confidence label exists in header area
      expect(within(panel).getByText('Conf')).toBeInTheDocument()
      expect(within(panel).getByText('Risk')).toBeInTheDocument()
    })
  })
})

describe('Status update', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupHook()
  })

  it('calls markStatus with "resolved" when "Mark as Resolved" is clicked', async () => {
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => screen.getByTestId('finding-detail-panel'))

    const resolveBtn = screen.getByText(/Mark as Resolved/i)
    fireEvent.click(resolveBtn)

    await waitFor(() => {
      expect(mockMarkStatus).toHaveBeenCalledWith('f-001', 'resolved')
    })
  })

  it('calls markStatus with "investigating" when "Investigate" is clicked (status=Open)', async () => {
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => screen.getByTestId('finding-detail-panel'))

    // Click the button that contains "Investigate" within the footer area
    const investigateBtns = screen.getAllByText(/Investigate/i)
    // The actionable button (not a badge/label) is a <button> element
    const btn = investigateBtns.find(el => el.closest('button'))
    fireEvent.click(btn.closest('button'))

    await waitFor(() => {
      expect(mockMarkStatus).toHaveBeenCalledWith('f-001', 'investigating')
    })
  })

  it('disables "Mark as Resolved" when finding is already resolved', async () => {
    setupHook({
      findings: [{ ...FINDING_1, status: 'Resolved' }],
      total: 1,
    })
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => screen.getByTestId('finding-detail-panel'))

    const resolveBtn = screen.getByText(/Already Resolved/i)
    expect(resolveBtn.closest('button')).toBeDisabled()
  })

  it('shows error message when markStatus throws', async () => {
    mockMarkStatus.mockRejectedValueOnce(new Error('API unavailable'))
    renderAlerts('/admin/alerts/f-001')
    await waitFor(() => screen.getByTestId('finding-detail-panel'))

    fireEvent.click(screen.getByText(/Mark as Resolved/i))
    await waitFor(() => {
      expect(screen.getByText('API unavailable')).toBeInTheDocument()
    })
  })
})

describe('API error handling', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows error banner when useFindings returns an error', () => {
    useFindings.mockReturnValue({
      findings: [], total: 0, loading: false,
      error: 'Failed to load findings',
      refetch: mockRefetch, markStatus: mockMarkStatus, attachCase: mockAttachCase,
    })
    renderAlerts()
    expect(screen.getByText('Failed to load findings')).toBeInTheDocument()
  })

  it('error banner has a Retry button that calls refetch', () => {
    useFindings.mockReturnValue({
      findings: [], total: 0, loading: false,
      error: 'Network error',
      refetch: mockRefetch, markStatus: mockMarkStatus, attachCase: mockAttachCase,
    })
    renderAlerts()
    fireEvent.click(screen.getByText('Retry'))
    expect(mockRefetch).toHaveBeenCalledTimes(1)
  })
})
