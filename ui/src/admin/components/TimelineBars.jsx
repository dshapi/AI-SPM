/**
 * TimelineBars — bar chart panel for event timelines.
 *
 * Design tokens:
 *   card header  → border-b border-gray-100 pb-4 mb-5
 *   panel title  → text-sm font-semibold text-gray-900
 *   panel sub    → text-xs text-gray-400 mt-0.5
 *   range chip   → text-[11px] font-medium text-gray-400 bg-gray-50 border border-gray-200 px-2 py-1 rounded-md
 *   chart area   → bg-gray-50 rounded-lg
 *   bar fill     → bg-blue-500 opacity-80 hover:opacity-100
 *   x-axis label → text-[11px] text-gray-400
 */
export default function TimelineBars({
  title    = 'Alerts Timeline',
  subtitle = 'Daily event count across all tenants',
  bars,
  labels   = ['Mar 9', 'Mar 23', 'Apr 8'],
}) {
  const data = bars ?? Array.from({ length: 30 }, (_, i) =>
    Math.round(35 + Math.sin(i * 0.4) * 18 + (i % 5) * 6)
  )
  const max = Math.max(...data)

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm hover:border-gray-300 transition-colors duration-150 h-full flex flex-col">

      {/* ── Panel header ─────────────────────────────────────────── */}
      <div className="border-b border-gray-100 pb-4 mb-5 flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-900">{title}</p>
          <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>
        </div>
        <span className="text-[11px] font-medium text-gray-400 bg-gray-50 border border-gray-200 px-2 py-1 rounded-md whitespace-nowrap shrink-0 mt-0.5">
          Last 30 days
        </span>
      </div>

      {/* ── Chart area ───────────────────────────────────────────── */}
      <div className="flex-1 bg-gray-50 rounded-lg px-4 pt-4 pb-3 flex flex-col">
        <div className="flex-1 flex items-end gap-[3px] min-h-[100px]">
          {data.map((v, i) => (
            <div
              key={i}
              className="flex-1 bg-blue-500 rounded-sm opacity-70 hover:opacity-100 transition-opacity cursor-default"
              style={{ height: `${(v / max) * 100}%` }}
            />
          ))}
        </div>
        {/* X-axis labels */}
        <div className="flex justify-between mt-2.5">
          {labels.map(l => (
            <span key={l} className="text-[11px] text-gray-400">{l}</span>
          ))}
        </div>
      </div>

    </div>
  )
}
