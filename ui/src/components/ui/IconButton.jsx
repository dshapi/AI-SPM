import { cn } from '../../lib/utils.js'

/**
 * IconButton — square icon-only control.
 *
 * Always 40×40px (h-10 w-10) to align with the design system control height.
 * Use `size="sm"` for 32px contexts (e.g. inside dense tables).
 */

const sizes = {
  sm: 'w-8  h-8',
  md: 'w-10 h-10',
}

export function IconButton({
  size = 'md',
  active = false,
  className,
  children,
  ...props
}) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-lg shrink-0',
        'transition-colors duration-150 focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-gray-300 focus-visible:ring-offset-1',
        'disabled:opacity-50 disabled:pointer-events-none',
        active
          ? 'bg-gray-100 text-gray-900'
          : 'text-gray-400 hover:text-gray-700 hover:bg-gray-100',
        sizes[size] ?? sizes.md,
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
