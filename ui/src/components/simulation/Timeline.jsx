/**
 * Timeline.jsx
 * ────────────
 * Simulation timeline tab — always rendered so events stream in live.
 *
 * Groups SimulationEvents by phase (Recon → Injection → Exploitation →
 * Exfiltration → System → Other) and delegates each group to PhaseSection.
 *
 * Props
 * ─────
 *   simulationState  SimulationState   — full state from useSimulationState
 *   mode             'single'|'garak'  — determines grouping strategy
 *   selectedId       string|null       — ID of currently selected event
 *   onSelect         (event) => void   — called when user clicks an event node
 */
import { cn }          from '../../lib/utils.js'
import { PhaseSection } from './PhaseSection.jsx'
import { groupByPhase, groupByPhaseAndProbe } from '../../lib/phaseGrouping.js'

// ── Constants ──────────────────────────────────────────────────────────────────

const STAGE_RISK = {
  started:   10,
  progress:  50,
  blocked:   90,
  allowed:   30,
  error:     70,
  completed: 10,
}

const PHASE_ORDER = ['Recon', 'Injection', 'Exploitation', 'Exfiltration', 'System', 'Other']

// ── Helpers ────────────────────────────────────────────────────────────────────

function getRiskScore(event) {
  const explicit = event?.details?.risk_score
  if (typeof explicit === 'number') return Math.min(100, Math.max(0, explicit))
  return STAGE_RISK[event?.stage] ?? 50
}

// ── Status label ───────────────────────────────────────────────────────────────

function StatusLabel({ status }) {
  if (status === 'running') {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] text-emerald-600 font-semibold">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse inline-block" />
        LIVE
      </span>
    )
  }
  if (status === 'completed') {
    return <span className="text-[11px] text-gray-400">Completed</span>
  }
  if (status === 'failed') {
    return <span className="text-[11px] text-red-500 font-medium">Failed</span>
  }
  return <span className="text-[11px] text-gray-400">Idle</span>
}

// ── Timeline ───────────────────────────────────────────────────────────────────

export function Timeline({
  simulationState,
  mode       = 'single',
  selectedId = null,
  onSelect,
}) {
  const {
    status,
    simEvents = [],
  } = simulationState ?? {}

  const isGarak = mode === 'garak'

  // Empty state — show status label + context-aware message
  if (simEvents.length === 0) {
    return (
      <div className="p-4">
        <div className="mb-3">
          <StatusLabel status={status} />
        </div>
        <p className="text-[12px] text-gray-400">
          {status === 'idle'
            ? 'Run a simulation to see events here.'
            : status === 'running'
              ? 'Waiting for events…'
              : 'No events recorded.'}
        </p>
      </div>
    )
  }

  // Group events by phase — use probe-aware grouping for Garak
  const grouped = isGarak
    ? groupByPhaseAndProbe(simEvents)
    : groupByPhase(simEvents)

  // Stable phase ordering: canonical phases first, unknown phases appended
  const sortedPhases = [
    ...PHASE_ORDER.filter(p => grouped[p]),
    ...Object.keys(grouped).filter(p => !PHASE_ORDER.includes(p)),
  ]

  return (
    <div className="p-4">
      <div className="mb-3">
        <StatusLabel status={status} />
      </div>

      {sortedPhases.map(phase => (
        <PhaseSection
          key={phase}
          phase={phase}
          events={grouped[phase]}
          isGarak={isGarak}
          selectedId={selectedId}
          onSelect={onSelect}
          getRiskScore={getRiskScore}
        />
      ))}
    </div>
  )
}
