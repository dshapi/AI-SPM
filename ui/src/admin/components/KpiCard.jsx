/**
 * KpiCard — enterprise KPI widget.
 *
 * Design tokens:
 *   card      → p-6 rounded-xl border border-gray-200 shadow-sm
 *   label     → text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-400
 *   value     → text-[2rem] font-bold text-gray-900 tabular-nums
 *   trend     → text-[12px] font-medium  (green / red)
 *   arrow     → inline SVG for consistent cross-OS rendering
 */

const TrendArrow = ({ up }) => (
  <svg
    width="8" height="8" viewBox="0 0 8 8" fill="currentColor"
    className="shrink-0 mt-px"
  >
    {up
      ? <polygon points="4,0 8,8 0,8" />
      : <polygon points="0,0 8,0 4,8" />}
  </svg>
)

export default function KpiCard({ label, value, delta, up }) {
  const color = up ? 'text-emerald-500' : 'text-red-500'

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm hover:border-gray-300 transition-colors duration-150 flex flex-col justify-between min-h-[136px]">

      {/* Label */}
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-400 leading-none">
        {label}
      </p>

      {/* Value */}
      <p className="text-[2rem] font-bold text-gray-900 tabular-nums leading-none mt-3">
        {value}
      </p>

      {/* Trend */}
      <div className={`flex items-center gap-1.5 mt-3 ${color}`}>
        <TrendArrow up={up} />
        <span className="text-[12px] font-medium leading-none">{delta}</span>
      </div>

    </div>
  )
}
