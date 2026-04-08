import { cn } from '../../lib/utils.js'

/**
 * Avatar — initials-based user avatar.
 *
 * Sizes: sm (w-6 h-6) | md (w-8 h-8) | lg (w-10 h-10)
 */

const sizes = {
  sm: 'w-6  h-6  text-[10px]',
  md: 'w-8  h-8  text-xs',
  lg: 'w-10 h-10 text-sm',
}

export function Avatar({ initials = 'A', size = 'md', className, ...props }) {
  return (
    <div
      className={cn(
        'rounded-full bg-gradient-to-br from-blue-500 to-blue-700',
        'flex items-center justify-center font-bold text-white shrink-0',
        sizes[size] ?? sizes.md,
        className,
      )}
      {...props}
    >
      {initials}
    </div>
  )
}
