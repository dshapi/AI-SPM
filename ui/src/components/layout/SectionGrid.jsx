import { cn } from '../../lib/utils.js'

/**
 * SectionGrid — 12-column responsive grid.
 *
 * gap enforces the design system's 24px section spacing.
 * Children use `col-span-N` to control width.
 *
 * Shorthand cols prop for equal-width columns:
 *   cols={4}  → grid-cols-4 (bypasses 12-col system for simple rows)
 */
export function SectionGrid({ cols, className, children, ...props }) {
  return (
    <div
      className={cn(
        'grid gap-6',
        cols ? `grid-cols-${cols}` : 'grid-cols-12',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
