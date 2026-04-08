import { clsx } from 'clsx'

/**
 * cn — class-name composition utility.
 *
 * Wraps clsx so components can merge conditional class strings cleanly.
 * Drop-in compatible with shadcn/ui's cn() signature.
 *
 * Usage:
 *   cn('px-4 py-2', isActive && 'bg-blue-50', className)
 */
export function cn(...inputs) {
  return clsx(inputs)
}
