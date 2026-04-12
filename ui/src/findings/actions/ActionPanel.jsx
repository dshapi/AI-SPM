/**
 * ActionPanel.jsx
 * ───────────────
 * Renders context-aware investigation actions for a finding.
 *
 * The action list is driven entirely by actionRegistry.js — no type-specific
 * logic lives in this component.  Adding a new finding type only requires
 * an entry in actionRegistry.js (and a handler in actionHandlers.js if needed).
 *
 * Layout:
 *   • Primary action — full-width blue CTA button
 *   • Secondary actions — compact text buttons below
 *   • No actions — fallback "No actions available" message
 */

import { useNavigate }             from 'react-router-dom'
import { ChevronRight, Zap }       from 'lucide-react'
import { cn }                      from '../../lib/utils.js'
import { getActionsForFinding }    from './actionRegistry.js'
import { dispatch }                from './actionHandlers.js'

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * @param {{ finding: object }} props
 *   finding — a normalized finding object (from normalizeFinding in findingsApi.js)
 */
export function ActionPanel({ finding }) {
  const navigate = useNavigate()
  const actions  = getActionsForFinding(finding)

  // ── Empty state ────────────────────────────────────────────────────────────
  if (actions.length === 0) {
    return (
      <p
        className="text-[12px] text-gray-300 italic"
        data-testid="action-panel-empty"
      >
        No actions available for this finding type.
      </p>
    )
  }

  const primary   = actions.find(a => a.primary)
  const secondary = actions.filter(a => !a.primary)

  return (
    <div data-testid="action-panel" className="space-y-1.5">

      {/* ── Primary action — hero CTA ──────────────────────────────────── */}
      {primary && (() => {
        const disabled = primary.disabledWhen?.(finding) ?? false
        return (
          <button
            key={primary.id}
            data-testid={`action-${primary.id}`}
            disabled={disabled}
            onClick={() => !disabled && dispatch(primary.action, finding, navigate)}
            className={cn(
              'w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-[12px] font-semibold transition-colors',
              disabled
                ? 'bg-gray-100 text-gray-300 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700',
            )}
          >
            <Zap size={12} className="shrink-0" />
            <span className="flex-1 text-left">{primary.label}</span>
          </button>
        )
      })()}

      {/* ── Secondary actions ─────────────────────────────────────────── */}
      {secondary.length > 0 && (
        <div className="space-y-0.5">
          {secondary.map(action => {
            const disabled = action.disabledWhen?.(finding) ?? false
            return (
              <button
                key={action.id}
                data-testid={`action-${action.id}`}
                disabled={disabled}
                onClick={() => !disabled && dispatch(action.action, finding, navigate)}
                className={cn(
                  'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-colors',
                  disabled
                    ? 'text-gray-300 cursor-not-allowed'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-800',
                )}
              >
                <ChevronRight size={10} className="shrink-0 text-gray-300" />
                <span className="flex-1 text-left">{action.label}</span>
              </button>
            )
          })}
        </div>
      )}

    </div>
  )
}
