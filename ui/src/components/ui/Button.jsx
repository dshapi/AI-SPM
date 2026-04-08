import { cn } from '../../lib/utils.js'

/**
 * Button — base interactive control.
 *
 * Variants:  default | outline | ghost | destructive
 * Sizes:     sm (h-8) | md (h-10) | lg (h-11)
 *
 * All heights follow the 40px (h-10) control standard by default.
 * Focus rings use ring-offset-white for clean white-background alignment.
 */

const variants = {
  default:     'bg-blue-600 text-white border-transparent hover:bg-blue-700 focus-visible:ring-blue-500',
  outline:     'bg-white text-gray-700 border-gray-200 hover:bg-gray-50 focus-visible:ring-gray-300',
  ghost:       'bg-transparent text-gray-600 border-transparent hover:bg-gray-100 focus-visible:ring-gray-300',
  destructive: 'bg-red-600 text-white border-transparent hover:bg-red-700 focus-visible:ring-red-500',
}

const sizes = {
  sm: 'h-8  px-3 text-xs  gap-1.5',
  md: 'h-10 px-4 text-sm  gap-2',
  lg: 'h-11 px-5 text-sm  gap-2',
}

export function Button({
  variant = 'default',
  size = 'md',
  className,
  children,
  disabled,
  ...props
}) {
  return (
    <button
      disabled={disabled}
      className={cn(
        // Base
        'inline-flex items-center justify-center rounded-lg border font-medium',
        'transition-colors duration-150 select-none whitespace-nowrap',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-white',
        'disabled:opacity-50 disabled:pointer-events-none',
        // Variant + size
        variants[variant] ?? variants.default,
        sizes[size]     ?? sizes.md,
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
