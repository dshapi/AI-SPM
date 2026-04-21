/**
 * ProbeResults.jsx
 * ────────────────
 * Probe Results tab — AGGREGATED STATS ONLY.
 *
 * Contract (enforced by tab responsibility rules)
 * ───────────────────────────────────────────────
 * This tab renders per-probe counts and risk averages.  It DOES NOT show:
 *   • prompt text
 *   • guard input
 *   • model response
 *   • lineage / trace / correlation ids
 * All of those live in Explainability.  That separation is intentional — the
 * previous version of this tab was a duplicate of the trace view.
 *
 * Contract (data source)
 * ──────────────────────
 * The summary is computed from Attempt rows (the canonical shape from
 * buildAttemptsFromEvents).  Raw envelope events never reach this component.
 *
 * Optional UX:
 *   onFocusProbe(probeName) — if provided, clicking a probe row invokes it
 *   so parent containers can jump to a filtered Timeline view.
 */
import { useMemo } from 'react'
import { cn } from '../../lib/utils.js'
import { TabEmpty } from './EmptyState.jsx'
import { buildAttemptsFromEvents } from '../../simulation/buildAttemptsFromEvents.js'

// ── Risk normalisation ─────────────────────────────────────────────────────

function toUnit(score) {
  if (typeof score !== 'number' || Number.isNaN(score)) return null
  if (score <= 1) return Math.max(0, score)
  return Math.max(0, Math.min(1, score / 100))
}

function formatRisk(avg) {
  if (avg == null) return '—'
  return avg.toFixed(2)
}

function riskColor(avg) {
  if (avg == null) return 'text-gray-400'
  if (avg >= 0.8)  return 'text-red-600'
  if (avg >= 0.5)  return 'text-amber-600'
  return 'text-emerald-600'
}

// ── Aggregation ────────────────────────────────────────────────────────────

/**
 * Pure aggregator — exposed for tests.  Returns rows sorted by (blocked desc,
 * avg_risk desc, probe asc) so the most-interesting probes float to the top.
 */
export function aggregateProbeRows(attempts) {
  if (!Array.isArray(attempts) || attempts.length === 0) return []

  const byProbe = new Map()
  for (const a of attempts) {
    const key = a.probe || '(unknown)'
    if (!byProbe.has(key)) {
      byProbe.set(key, { probe: key, blocked: 0, allowed: 0, errored: 0, riskSum: 0, riskN: 0 })
    }
    const row = byProbe.get(key)
    switch (a.result) {
      case 'blocked': row.blocked += 1; break
      case 'allowed': row.allowed += 1; break
      case 'error':   row.errored += 1; break
      default: /* ignore */
    }
    const r = toUnit(a.risk_score)
    if (r != null) { row.riskSum += r; row.riskN += 1 }
  }

  const rows = Array.from(byProbe.values()).map(r => ({
    ...r,
    total:   r.blocked + r.allowed + r.errored,
    avgRisk: r.riskN > 0 ? r.riskSum / r.riskN : null,
  }))

  rows.sort((a, b) => {
    if (a.blocked !== b.blocked) return b.blocked - a.blocked
    const ar = a.avgRisk ?? -1
    const br = b.avgRisk ?? -1
    if (ar !== br) return br - ar
    return a.probe.localeCompare(b.probe)
  })

  return rows
}

// ── Row ────────────────────────────────────────────────────────────────────

function ProbeRow({ row, onFocusProbe }) {
  const clickable = typeof onFocusProbe === 'function' && row.probe !== '(unknown)'
  const handleClick = clickable ? () => onFocusProbe(row.probe) : undefined

  return (
    <div
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={handleClick}
      onKeyDown={clickable ? (e) => { if (e.key === 'Enter') onFocusProbe(row.probe) } : undefined}
      className={cn(
        'flex items-center gap-4 rounded-xl border border-gray-200 bg-white px-3.5 py-2.5',
        clickable && 'cursor-pointer hover:border-blue-300 hover:bg-blue-50/30 transition-colors',
      )}
    >
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-semibold text-gray-800 truncate">{row.probe}</p>
        <p className="text-[10px] text-gray-400 mt-0.5">
          {row.total} attempt{row.total === 1 ? '' : 's'}
        </p>
      </div>

      <div className="flex items-center gap-3 shrink-0 tabular-nums text-[11px]">
        <span className="inline-flex items-center gap-1" title="Blocked">
          <span className="w-2 h-2 rounded-full bg-red-500" />
          <span className="font-bold text-red-700">{row.blocked}</span>
        </span>
        <span className="inline-flex items-center gap-1" title="Allowed">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="font-bold text-emerald-700">{row.allowed}</span>
        </span>
        {row.errored > 0 && (
          <span className="inline-flex items-center gap-1" title="Errors">
            <span className="w-2 h-2 rounded-full bg-orange-500" />
            <span className="font-bold text-orange-700">{row.errored}</span>
          </span>
        )}
        <span className="text-gray-300">·</span>
        <span className="text-[10px] text-gray-400">avg risk</span>
        <span className={cn('font-bold', riskColor(row.avgRisk))}>
          {formatRisk(row.avgRisk)}
        </span>
      </div>
    </div>
  )
}

// ── Tab content ────────────────────────────────────────────────────────────

/**
 * ProbeResults tab content.
 *
 * Props:
 *   simulationState  SimulationState  — from useSimulationState()
 *   status           string           — simulationState.status
 *   onFocusProbe     (probe)=>void    — optional; parent uses this to jump
 *                                       to a Timeline filtered by probe
 */
export function ProbeResults({ simulationState, status, onFocusProbe }) {
  const simEvents = simulationState?.simEvents ?? []

  const rows = useMemo(() => {
    const { attempts } = buildAttemptsFromEvents(simEvents)
    return aggregateProbeRows(attempts)
  }, [simEvents])

  if (rows.length === 0) {
    return (
      <TabEmpty
        label={status === 'idle'
          ? 'Run a Garak scan to see per-probe results.'
          : 'Waiting for probe results…'}
      />
    )
  }

  // Overall rollup across probes
  const totals = rows.reduce(
    (acc, r) => {
      acc.blocked += r.blocked
      acc.allowed += r.allowed
      acc.errored += r.errored
      return acc
    },
    { blocked: 0, allowed: 0, errored: 0 },
  )

  return (
    <div className="p-4 space-y-3">
      {/* Rollup strip — aggregate across every probe */}
      <div className="grid grid-cols-3 gap-2 mb-1">
        {[
          { label: 'Blocked', value: totals.blocked, color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200'     },
          { label: 'Allowed', value: totals.allowed, color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
          { label: 'Errors',  value: totals.errored, color: 'text-orange-600',  bg: 'bg-orange-50',  border: 'border-orange-200'  },
        ].map(({ label, value, color, bg, border }) => (
          <div key={label} className={cn('rounded-xl border p-3 text-center', bg, border)}>
            <div className={cn('text-[24px] font-black tabular-nums', color)}>{value}</div>
            <div className="text-[9.5px] text-gray-400 font-medium mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      <p className="text-[11px] text-gray-400">
        Aggregated statistics per probe.  For trace detail see the Explainability tab.
      </p>

      <div className="space-y-1.5">
        {rows.map(row => (
          <ProbeRow key={row.probe} row={row} onFocusProbe={onFocusProbe} />
        ))}
      </div>
    </div>
  )
}

export default ProbeResults
