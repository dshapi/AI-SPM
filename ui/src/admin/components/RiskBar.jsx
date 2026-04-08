/**
 * RiskBar — Datadog-style labelled progress bar row.
 */
export default function RiskBar({ label, count, pct, color, text }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className={`text-xs font-semibold ${text}`}>{label}</span>
        <span className="text-xs text-gray-400 tabular-nums">{count}</span>
      </div>
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
