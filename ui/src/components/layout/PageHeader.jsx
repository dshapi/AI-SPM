import { cn } from '../../lib/utils.js'

/**
 * PageHeader — page-level title row.
 *
 * Replaces SectionHeader. Enforces design system typography:
 *   title    → text-2xl font-semibold text-gray-900
 *   subtitle → text-sm text-gray-500
 *
 * Accepts an optional `actions` slot (right side).
 */
export function PageHeader({ title, subtitle, actions, className, ...props }) {
  return (
    <div className={cn('flex items-start justify-between gap-4', className)} {...props}>
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold text-gray-900 tracking-tight leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-sm text-gray-500 mt-1 leading-snug">{subtitle}</p>
        )}
      </div>

      {actions && (
        <div className="flex items-center gap-2 shrink-0 pt-0.5">
          {actions}
        </div>
      )}
    </div>
  )
}
