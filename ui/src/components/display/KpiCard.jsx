import { cn } from '../../lib/utils.js'

/**
 * KpiCard — enterprise metric tile.
 *
 * Design tokens (from spec):
 *   label → text-xs uppercase tracking-wide text-gray-400
 *   value → text-3xl font-semibold text-gray-900
 *   delta → text-xs font-medium  (green when up, red when down)
 *   arrow → inline SVG polygon for consistent cross-OS rendering
 */

function TrendArrow({ up }) {
  return (
    <svg
      width="7" height="7" viewBox="0 0 8 8"
      fill="currentColor" className="shrink-0 mt-px"
    >
      {up
        ? <polygon points="4,0 8,8 0,8" />
        : <polygon points="0,0 8,0 4,8" />}
    </svg>
  )
}

export function KpiCard({ label, value, delta, up, className }) {
  const trendColor = up ? 'text-emerald-500' : 'text-red-500'

  return (
    <div
      className={cn(
        'bg-white border border-gray-200 rounded-xl p-5 shadow-sm',
        'hover:border-gray-300 transition-colors duration-150',
        'flex flex-col justify-between min-h-[130px]',
        className,
      )}
    >
      {/* Label */}
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-gray-400 leading-none">
        {label}
      </p>

      {/* Value */}
      <p className="text-3xl font-semibold text-gray-900 tabular-nums leading-none mt-3">
        {value}
      </p>

      {/* Trend */}
      {delta && (
        <div className={cn('flex items-center gap-1.5 mt-3', trendColor)}>
          <TrendArrow up={up} />
          <span className="text-xs font-medium leading-none">{delta}</span>
        </div>
      )}
    </div>
  )
}
