import { cn } from '../../lib/utils.js'

/**
 * Separator — thin visual divider.
 * orientation: horizontal (default) | vertical
 */
export function Separator({ orientation = 'horizontal', className, ...props }) {
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={cn(
        'shrink-0 bg-gray-200',
        orientation === 'vertical' ? 'w-px h-5' : 'h-px w-full',
        className,
      )}
      {...props}
    />
  )
}
