/**
 * ErrorState.jsx
 * ──────────────
 * Reusable error/failed-state panel rendered when a simulation
 * terminates with status === 'failed'.
 *
 * Props
 * ─────
 *   error     string        — human-readable error message
 *   onRetry   function|null — optional callback; shows Retry button when provided
 *   className string        — optional extra Tailwind classes on root
 */
import { AlertCircle, RefreshCw } from 'lucide-react'
import { cn }                     from '../../lib/utils.js'
import { Button }                 from '../ui/Button.jsx'

export function ErrorState({
  error     = 'An unexpected error occurred. Check the console for details.',
  onRetry,
  className,
}) {
  return (
    <div className={cn(
      'flex flex-col items-center justify-center gap-3 text-center px-8 py-16',
      className,
    )}>
      <div className="w-10 h-10 rounded-xl bg-red-50 flex items-center justify-center">
        <AlertCircle size={18} className="text-red-400" />
      </div>

      <div>
        <p className="text-[13px] font-medium text-gray-700">Simulation failed</p>
        <p className="text-[11px] text-gray-400 mt-1 max-w-xs leading-snug">{error}</p>
      </div>

      {onRetry && (
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5 mt-1"
          onClick={onRetry}
        >
          <RefreshCw size={11} strokeWidth={2} />
          Retry
        </Button>
      )}
    </div>
  )
}
