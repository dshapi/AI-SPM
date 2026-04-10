import { PageContainer }       from '../../components/layout/PageContainer.jsx'
import { PageHeader }           from '../../components/layout/PageHeader.jsx'
import { SectionGrid }          from '../../components/layout/SectionGrid.jsx'
import { KpiCard }              from '../../components/display/KpiCard.jsx'
import { SectionCard }          from '../../components/display/SectionCard.jsx'
import { Button }               from '../../components/ui/Button.jsx'
import { Badge }                from '../../components/ui/Badge.jsx'
import TopRisksPanel            from '../components/TopRisksPanel.jsx'
import RiskDistributionPanel    from '../components/RiskDistributionPanel.jsx'
import TimelineBars             from '../components/TimelineBars.jsx'
import InventoryBreakdown       from '../components/InventoryBreakdown.jsx'

// ── Static data ───────────────────────────────────────────────────────────────

const KPIS = [
  { label: 'Models Registered', value: '12',   delta: '+2 this week',       up: true  },
  { label: 'Active Alerts',      value: '4',    delta: '−1 since yesterday', up: false },
  { label: 'Policy Violations',  value: '27',   delta: '+5 today',           up: false },
  { label: 'Avg Posture Score',  value: '0.82', delta: '+0.03 vs last week', up: true  },
]

const SEV_VARIANT = { Critical: 'critical', High: 'high', Medium: 'medium', Low: 'low' }

const ALERTS = [
  { sev: 'High',     model: 'gpt-4-turbo',      rule: 'Prompt injection detected', time: '2m ago'  },
  { sev: 'Medium',   model: 'claude-sonnet-4-6', rule: 'Output PII exposure',       time: '15m ago' },
  { sev: 'Low',      model: 'llama-3-70b',       rule: 'Rate limit threshold hit',  time: '1h ago'  },
  { sev: 'High',     model: 'gpt-4o',            rule: 'Model gate block',          time: '2h ago'  },
  { sev: 'Critical', model: 'mixtral-8x7b',      rule: 'Jailbreak pattern matched', time: '3h ago'  },
]

const TABLE_HEADERS = ['Severity', 'Model', 'Rule', 'Time']

// ── Dashboard page — thin composition layer ───────────────────────────────────

export default function Dashboard() {
  return (
    <PageContainer>

      {/* Page header */}
      <PageHeader
        title="Dashboard"
        subtitle="AI security posture across all agents and models"
        actions={
          <>
            <Button variant="outline">Export</Button>
            <Button>+ Add Model</Button>
          </>
        }
      />

      {/* KPI row — 4 equal columns */}
      <SectionGrid cols={4}>
        {KPIS.map(k => <KpiCard key={k.label} {...k} />)}
      </SectionGrid>

      {/* Risk row — 7 + 5 */}
      <SectionGrid>
        <div className="col-span-7"><RiskDistributionPanel /></div>
        <div className="col-span-5"><TopRisksPanel /></div>
      </SectionGrid>

      {/* Timeline + Inventory row — 5 + 7 */}
      <SectionGrid>
        <div className="col-span-5">
          <TimelineBars
            title="Alerts Timeline"
            subtitle="Daily event count — last 30 days"
            labels={['Mar 9', 'Mar 23', 'Apr 8']}
          />
        </div>
        <div className="col-span-7"><InventoryBreakdown /></div>
      </SectionGrid>

      {/* Alerts table */}
      <SectionCard
        title="Recent Alerts"
        subtitle={`${ALERTS.length} events in the last 24 hours`}
        action={
          <button className="text-sm font-semibold text-blue-600 hover:text-blue-700 transition-colors">
            View all →
          </button>
        }
        contentClassName="p-0"
      >
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              {TABLE_HEADERS.map((h, i) => (
                <th
                  key={h}
                  className={`px-6 py-3 text-[11px] font-semibold uppercase tracking-[0.06em] text-gray-400 text-left whitespace-nowrap ${i === 4 ? 'text-right' : ''}`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ALERTS.map((row, i) => (
              <tr
                key={i}
                className="border-b border-gray-100 last:border-0 hover:bg-gray-50/70 transition-colors duration-100 cursor-pointer"
              >
                <td className="px-6 py-3.5">
                  <Badge variant={SEV_VARIANT[row.sev] ?? 'neutral'}>{row.sev}</Badge>
                </td>
                <td className="px-6 py-3.5">
                  <span className="font-mono text-[13px] text-gray-600 whitespace-nowrap">{row.model}</span>
                </td>
                <td className="px-6 py-3.5">
                  <span className="text-[13px] text-gray-600">{row.rule}</span>
                </td>
                <td className="px-6 py-3.5 text-right">
                  <span className="text-[12px] text-gray-400 tabular-nums">{row.time}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>

    </PageContainer>
  )
}
