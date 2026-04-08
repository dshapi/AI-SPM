import { cn } from '../../lib/utils.js'

/**
 * PageContainer — outer wrapper for every admin page.
 *
 * Enforces:
 *   - page background: bg-[#f6f7fb]
 *   - max-width cap: max-w-[1440px]
 *   - consistent horizontal padding: px-8
 *   - consistent vertical padding: py-8
 *   - consistent section spacing: space-y-6
 */
export function PageContainer({ className, children, ...props }) {
  return (
    <div className={cn('bg-[#f6f7fb] min-h-full', className)} {...props}>
      <div className="max-w-[1440px] mx-auto px-8 py-8 space-y-6">
        {children}
      </div>
    </div>
  )
}
