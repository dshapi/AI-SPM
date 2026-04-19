/**
 * EmptyState.jsx
 * ──────────────
 * Reusable empty-state panel used when no simulation has been run yet,
 * or when a tab has no content to display.
 *
 * Props
 * ─────
 *   title     string        — primary line, default "No data yet"
 *   subtitle  string|null   — secondary line
 *   icon      LucideIcon    — icon component, default FlaskConical
 *   className string        — optional extra Tailwind classes on root
 */
import { FlaskConical } from 'lucide-react'
import { cn }           from '../../lib/utils.js'

export function EmptyState({
  title    = 'No data yet',
  subtitle = 'Run a simulation to see results here.',
  icon: Icon = FlaskConical,
  className,
}) {
  return (
    <div className={cn(
      'flex flex-col items-center justify-center gap-3 text-center px-8 py-16',
      className,
    )}>
      <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center">
        <Icon size={18} className="text-gray-400" />
      </div>
      <div>
        <p className="text-[13px] font-medium text-gray-500">{title}</p>
        {subtitle && (
          <p className="text-[11px] text-gray-400 mt-1 max-w-xs leading-snug">
            {subtitle}
          </p>
        )}
      </div>
    </div>
  )
}

/**
 * TabEmpty — ultra-compact variant used inside tab content areas
 * where vertical space is constrained.
 */
export function TabEmpty({ label = 'No data yet', className }) {
  return (
    <div className={cn(
      'flex items-center justify-center py-16 px-8 text-center',
      className,
    )}>
      <p className="text-[12px] text-gray-400">{label}</p>
    </div>
  )
}
