/**
 * PolicyImpact.jsx
 * ────────────────
 * Policy Impact tab content.
 *
 * Non-negotiable behaviour
 * ────────────────────────
 * • NEVER shows the word "Unknown".  If a policy decision arrived without a
 *   named policy, the card renders "Unresolved Policy" and the fallback
 *   source (e.g. "Default guard (promptinject)") so operators can always see
 *   WHY a decision was made even when the policy registry has a hole.
 * • Consumes the result object built by buildResultFromSimEvents so it lines
 *   up with the rest of the tab set — no separate event-stream re-reading.
 * • Deterministic ordering preserved — we render in the order policies
 *   arrived from the backend.
 */
import { Shield, AlertTriangle, XCircle, CheckCircle2, ArrowRight } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { Badge } from '../ui/Badge.jsx'
import { TabEmpty } from './EmptyState.jsx'
import { resolvePolicyDecision } from '../../lib/policyResolution.js'

const POLICY_ACTION_CFG = {
  BLOCK:    { badge: 'critical', icon: XCircle       },
  ESCALATE: { badge: 'high',     icon: AlertTriangle },
  FLAG:     { badge: 'high',     icon: AlertTriangle },
  ALLOW:    { badge: 'success',  icon: CheckCircle2  },
  SKIP:     { badge: 'neutral',  icon: ArrowRight    },
}

// Severity → card chrome.  Unresolved policies get an amber warning treatment
// regardless of action so operators immediately recognise the attribution gap.
function cardChrome({ unresolved, severity }) {
  if (unresolved) {
    return {
      card:    'bg-amber-50/60 border-amber-300',
      iconBg:  'bg-amber-100',
      iconCl:  'text-amber-700',
    }
  }
  if (severity === 'critical') {
    return {
      card:    'bg-red-50/60 border-red-200',
      iconBg:  'bg-red-100',
      iconCl:  'text-red-600',
    }
  }
  if (severity === 'high') {
    return {
      card:    'bg-amber-50/60 border-amber-200',
      iconBg:  'bg-amber-100',
      iconCl:  'text-amber-600',
    }
  }
  return {
    card:    'bg-gray-50 border-gray-200',
    iconBg:  'bg-gray-100',
    iconCl:  'text-gray-500',
  }
}

function PolicyCard({ impact }) {
  const resolved = resolvePolicyDecision({
    policyName: impact.policy,
    probeName:  impact.probe,
    action:     impact.action,
  })
  const acfg   = POLICY_ACTION_CFG[resolved.action] ?? POLICY_ACTION_CFG.SKIP
  const chrome = cardChrome({ unresolved: resolved.unresolved, severity: impact.severity })

  return (
    <div
      className={cn('rounded-xl border p-3.5 flex items-start gap-3', chrome.card)}
      data-unresolved={resolved.unresolved ? 'true' : 'false'}
    >
      <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0', chrome.iconBg)}>
        {resolved.unresolved
          ? <AlertTriangle size={14} className={chrome.iconCl} strokeWidth={1.75} />
          : <Shield         size={14} className={chrome.iconCl} strokeWidth={1.75} />
        }
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <span className="text-[12px] font-semibold text-gray-800">
            {resolved.unresolved ? (
              <>
                <span aria-hidden="true">⚠ </span>
                Unresolved Policy
              </>
            ) : resolved.displayName}
          </span>
          <Badge variant={acfg.badge}>{resolved.action}</Badge>
        </div>
        {resolved.unresolved && (
          <p className="text-[10.5px] font-medium text-amber-800 mb-0.5">
            Fallback: {resolved.sourceLabel}
          </p>
        )}
        {impact.trigger && (
          <p className="text-[10.5px] text-gray-600 leading-snug">
            {impact.trigger}
          </p>
        )}
        {!resolved.unresolved && resolved.probe && (
          <p className="text-[10px] text-gray-400 mt-1 font-mono">
            Source: {resolved.sourceLabel}
          </p>
        )}
      </div>
    </div>
  )
}

/**
 * PolicyImpact tab content.
 *
 * Props:
 *   result   object | null   — buildResultFromSimEvents output
 *   status   string          — simulationState.status (for the loading state)
 */
export function PolicyImpact({ result, status }) {
  if (!result) {
    return (
      <TabEmpty
        label={status === 'running'
          ? 'Evaluating policies…'
          : 'Policy evaluation results will appear here after a simulation runs.'}
      />
    )
  }

  const impacts = result.policyImpact ?? []
  if (impacts.length === 0) {
    return (
      <div className="p-4">
        <p className="text-[11px] text-gray-400 mb-3">
          How each policy evaluated this request.
        </p>
        <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-6 text-center">
          <p className="text-[12px] text-gray-500">No policies triggered on this request.</p>
          <p className="text-[10.5px] text-gray-400 mt-1">
            The request passed through the policy engine without firing any rule.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3">
      <p className="text-[11px] text-gray-400">How each policy evaluated this request.</p>
      {impacts.map((impact, i) => (
        <PolicyCard key={`${impact.policy}-${i}`} impact={impact} />
      ))}
    </div>
  )
}

export default PolicyImpact
