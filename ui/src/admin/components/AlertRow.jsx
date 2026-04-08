import MetricBadge from './MetricBadge.jsx'

const SEV = { Critical: 'critical', High: 'high', Medium: 'medium', Low: 'low' }

/**
 * AlertRow — single table row for the recent-alerts table.
 *
 * Design tokens:
 *   row height   → py-3.5 on each td (NOT h-12 on tr — h-12 is unreliable in tables)
 *   cell padding → px-6
 *   model name   → font-mono text-[13px] text-gray-600
 *   rule text    → text-[13px] text-gray-600 (same scale as model)
 *   time         → text-[12px] text-gray-400 tabular-nums
 */
export default function AlertRow({ sev, model, rule, tenant, time }) {
  return (
    <tr className="border-b border-gray-100 last:border-0 hover:bg-gray-50/70 transition-colors cursor-pointer">
      <td className="px-6 py-3.5">
        <MetricBadge label={sev} variant={SEV[sev] ?? 'neutral'} />
      </td>
      <td className="px-6 py-3.5">
        <span className="font-mono text-[13px] text-gray-600 whitespace-nowrap">{model}</span>
      </td>
      <td className="px-6 py-3.5">
        <span className="text-[13px] text-gray-600">{rule}</span>
      </td>
      <td className="px-6 py-3.5">
        <MetricBadge label={tenant} variant="info" />
      </td>
      <td className="px-6 py-3.5 text-right">
        <span className="text-[12px] text-gray-400 tabular-nums">{time}</span>
      </td>
    </tr>
  )
}
