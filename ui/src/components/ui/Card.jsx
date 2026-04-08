import { cn } from '../../lib/utils.js'

/**
 * Card — base surface primitive.
 *
 * Composition:
 *   <Card>
 *     <CardHeader>
 *       <CardTitle>…</CardTitle>
 *       <CardDescription>…</CardDescription>
 *     </CardHeader>
 *     <CardContent>…</CardContent>
 *     <CardFooter>…</CardFooter>
 *   </Card>
 *
 * All subcomponents forward `className` and `...props` so callers can
 * override spacing, borders, etc. without breaking the base style.
 */

export function Card({ className, children, ...props }) {
  return (
    <div
      className={cn(
        'bg-white border border-gray-200 rounded-xl shadow-sm',
        'transition-colors duration-150',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ className, children, ...props }) {
  return (
    <div
      className={cn('px-5 py-4 border-b border-gray-100 flex items-start justify-between gap-4', className)}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardTitle({ className, children, ...props }) {
  return (
    <p className={cn('text-sm font-semibold text-gray-900 leading-snug', className)} {...props}>
      {children}
    </p>
  )
}

export function CardDescription({ className, children, ...props }) {
  return (
    <p className={cn('text-xs text-gray-400 mt-0.5 leading-snug', className)} {...props}>
      {children}
    </p>
  )
}

export function CardContent({ className, children, ...props }) {
  return (
    <div className={cn('p-5', className)} {...props}>
      {children}
    </div>
  )
}

export function CardFooter({ className, children, ...props }) {
  return (
    <div
      className={cn('px-5 py-3 border-t border-gray-100 flex items-center', className)}
      {...props}
    >
      {children}
    </div>
  )
}
