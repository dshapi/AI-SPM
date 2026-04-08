import { cn } from '../../lib/utils.js'

/**
 * Badge — semantic label pill.
 *
 * Variants: critical | high | medium | low | info | success | neutral
 *
 * Replaces MetricBadge. Keeps the same visual style but driven by
 * a clean variant prop system.
 */

const variants = {
  critical: 'bg-red-50    text-red-600    border-red-200',
  high:     'bg-orange-50 text-orange-600 border-orange-200',
  medium:   'bg-yellow-50 text-yellow-700 border-yellow-200',
  low:      'bg-green-50  text-green-700  border-green-200',
  success:  'bg-emerald-50 text-emerald-700 border-emerald-200',
  info:     'bg-blue-50   text-blue-600   border-blue-200',
  neutral:  'bg-gray-100  text-gray-500   border-gray-200',
}

export function Badge({ variant = 'neutral', className, children, ...props }) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded-md border',
        'text-[11px] font-semibold tracking-wide whitespace-nowrap',
        variants[variant] ?? variants.neutral,
        className,
      )}
      {...props}
    >
      {children}
    </span>
  )
}
