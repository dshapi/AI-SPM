import { cn } from '../../lib/utils.js'

/**
 * SectionCard — titled card panel for dashboard sections.
 *
 * Composes Card primitives into the standard panel layout:
 *   - White card with border + rounded-xl
 *   - Header row: title + optional subtitle + optional action
 *   - Content slot: full control over inner layout
 *
 * Used for any full-card panel that needs a consistent header style.
 * Panels with their own custom headers (TopRisks, RiskDist) can skip
 * this and handle their own CardHeader.
 */
export function SectionCard({ title, subtitle, action, className, contentClassName, children }) {
  return (
    <div
      className={cn(
        'bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden',
        'hover:border-gray-300 transition-colors duration-150 h-full flex flex-col',
        className,
      )}
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between shrink-0">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 leading-snug">{title}</p>
          {subtitle && (
            <p className="text-xs text-gray-400 mt-0.5 leading-snug">{subtitle}</p>
          )}
        </div>
        {action && <div className="shrink-0 ml-4">{action}</div>}
      </div>

      {/* Content */}
      <div className={cn('flex-1', contentClassName)}>
        {children}
      </div>
    </div>
  )
}
