/**
 * Recommendations.jsx
 * ───────────────────
 * Renders the recommendation list produced by useRecommendations().
 *
 * Contract
 * ────────
 * • Reads from simulationState — no raw events, no re-aggregation.
 * • Empty state is ALWAYS meaningful — either "no issues detected" (healthy)
 *   or a specific "analysing…" / "run a simulation" prompt.
 * • Severity-first ordering; visual style matches PolicyImpact so the
 *   Recommendations tab feels like a peer, not a debug dump.
 */
import { AlertTriangle, AlertCircle, Info, CheckCircle2, ShieldAlert } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { useRecommendations } from '../../hooks/useRecommendations.js'

const SEVERITY_CFG = {
  critical: {
    bg:     'bg-red-50/60',
    border: 'border-red-200',
    iconBg: 'bg-red-100',
    icon:   AlertCircle,
    iconCl: 'text-red-600',
    chip:   'bg-red-100 border-red-200 text-red-700',
    label:  'CRITICAL',
  },
  high: {
    bg:     'bg-amber-50/60',
    border: 'border-amber-200',
    iconBg: 'bg-amber-100',
    icon:   AlertTriangle,
    iconCl: 'text-amber-600',
    chip:   'bg-amber-100 border-amber-200 text-amber-700',
    label:  'HIGH',
  },
  medium: {
    bg:     'bg-yellow-50/60',
    border: 'border-yellow-200',
    iconBg: 'bg-yellow-100',
    icon:   ShieldAlert,
    iconCl: 'text-yellow-600',
    chip:   'bg-yellow-100 border-yellow-200 text-yellow-700',
    label:  'MEDIUM',
  },
  low: {
    bg:     'bg-blue-50/60',
    border: 'border-blue-200',
    iconBg: 'bg-blue-100',
    icon:   Info,
    iconCl: 'text-blue-600',
    chip:   'bg-blue-100 border-blue-200 text-blue-700',
    label:  'LOW',
  },
}

function RecommendationCard({ rec }) {
  const cfg = SEVERITY_CFG[rec.severity] ?? SEVERITY_CFG.low
  const Icon = cfg.icon
  return (
    <div
      className={cn('rounded-xl border p-3.5 flex items-start gap-3', cfg.bg, cfg.border)}
      data-rule={rec.rule}
      data-severity={rec.severity}
    >
      <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0', cfg.iconBg)}>
        <Icon size={14} className={cfg.iconCl} strokeWidth={1.75} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <span className="text-[12px] font-semibold text-gray-800">{rec.title}</span>
          <span className={cn(
            'text-[9px] font-bold tracking-wide px-1.5 py-0.5 rounded-full border',
            cfg.chip,
          )}>
            {cfg.label}
          </span>
          {rec.count > 1 && (
            <span className="text-[10px] text-gray-500 font-mono tabular-nums">
              × {rec.count}
            </span>
          )}
        </div>
        <p className="text-[11px] text-gray-600 leading-snug">{rec.detail}</p>
      </div>
    </div>
  )
}

/**
 * Recommendations tab content.
 *
 * Props:
 *   simulationState  SimulationState  — from useSimulationState()
 */
export function Recommendations({ simulationState }) {
  const { recommendations, hasIssues, emptyMessage } = useRecommendations(simulationState)

  if (!hasIssues) {
    return (
      <div className="p-4">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 flex items-start gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center shrink-0">
            <CheckCircle2 size={14} className="text-emerald-600" strokeWidth={1.75} />
          </div>
          <div>
            <p className="text-[12px] font-semibold text-emerald-800">All clear</p>
            <p className="text-[11px] text-emerald-700/80 mt-0.5 leading-snug">
              {emptyMessage}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3">
      <p className="text-[11px] text-gray-400">
        Actionable findings derived from probe attempts, guard decisions, and policy attribution.
      </p>
      {recommendations.map(rec => (
        <RecommendationCard key={rec.id} rec={rec} />
      ))}
    </div>
  )
}

export default Recommendations
