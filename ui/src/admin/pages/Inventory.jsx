import { useState } from 'react'
import {
  Search, SlidersHorizontal, LayoutGrid, List,
  ChevronRight, X, ExternalLink, AlertTriangle,
  Bot, Cpu, Wrench, Database, Activity,
  Shield, ShieldAlert, ShieldCheck, ShieldOff,
  User, Cloud, Clock, ArrowUpRight,
  CheckCircle2, XCircle, AlertCircle, Share2,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'

// ── Mock data ──────────────────────────────────────────────────────────────────

const RISK_VARIANT  = { Critical: 'critical', High: 'high', Medium: 'medium', Low: 'low' }
const RISK_DOT      = {
  Critical: 'bg-red-500',
  High:     'bg-orange-500',
  Medium:   'bg-yellow-400',
  Low:      'bg-emerald-500',
}

const ASSETS = {
  agents: [
    { id: 'ag-001', name: 'CustomerSupport-GPT',       type: 'LangChain Agent',    risk: 'High',     owner: 'ml-platform',    provider: 'AWS',   policyStatus: 'partial', lastSeen: '2m ago',   description: 'Handles tier-1 customer tickets with escalation routing. Integrates with Zendesk and Jira.', linkedPolicies: ['PII-Guard v2', 'Rate-Limiter'],         linkedAlerts: 2 },
    { id: 'ag-002', name: 'CodeReview-Assistant',      type: 'OpenAI Assistant',   risk: 'Medium',   owner: 'devex-team',     provider: 'Azure', policyStatus: 'full',    lastSeen: '14m ago',  description: 'Automated code review agent for PR analysis. Reads GitHub diffs, outputs structured feedback.', linkedPolicies: ['CodeScan v1'],                      linkedAlerts: 0 },
    { id: 'ag-003', name: 'DataPipeline-Orchestrator', type: 'AutoGPT',            risk: 'Critical', owner: 'data-eng',       provider: 'GCP',   policyStatus: 'none',    lastSeen: '1h ago',   description: 'Orchestrates multi-step ETL pipelines. Has write access to production databases.', linkedPolicies: [],                                       linkedAlerts: 5 },
    { id: 'ag-004', name: 'HRIntake-Bot',              type: 'LlamaIndex Agent',   risk: 'Low',      owner: 'people-ops',     provider: 'AWS',   policyStatus: 'full',    lastSeen: '3h ago',   description: 'Handles new employee onboarding queries. Access to HR knowledge base only.', linkedPolicies: ['PII-Guard v2', 'Access-Scope v3'],      linkedAlerts: 0 },
    { id: 'ag-005', name: 'ThreatHunter-AI',           type: 'Custom Agent',       risk: 'High',     owner: 'security-ops',   provider: 'Azure', policyStatus: 'partial', lastSeen: '30m ago',  description: 'Autonomous threat hunting across SIEM data. Triggers automated containment playbooks.', linkedPolicies: ['Audit-Log v1'],                     linkedAlerts: 1 },
  ],
  models: [
    { id: 'md-001', name: 'gpt-4-turbo',              type: 'LLM',                risk: 'High',     owner: 'ml-platform',    provider: 'Azure', policyStatus: 'partial', lastSeen: '1m ago',   description: 'Primary completion model. Used by 8 downstream agents. Context window 128k tokens.', linkedPolicies: ['Output-Filter v2'],                   linkedAlerts: 3 },
    { id: 'md-002', name: 'claude-sonnet-4-6',         type: 'LLM',                risk: 'Medium',   owner: 'ml-platform',    provider: 'AWS',   policyStatus: 'full',    lastSeen: '5m ago',   description: 'Secondary reasoning model. Deployed for analytical tasks and summarization.', linkedPolicies: ['PII-Guard v2', 'Rate-Limiter'],         linkedAlerts: 1 },
    { id: 'md-003', name: 'llama-3-70b',               type: 'Open Source LLM',    risk: 'Medium',   owner: 'infra-team',     provider: 'GCP',   policyStatus: 'partial', lastSeen: '22m ago',  description: 'Self-hosted open-source model. On-prem deployment for sensitive data workloads.', linkedPolicies: ['Access-Scope v3'],                  linkedAlerts: 1 },
    { id: 'md-004', name: 'text-embedding-3-large',    type: 'Embedding Model',    risk: 'Low',      owner: 'data-eng',       provider: 'Azure', policyStatus: 'full',    lastSeen: '8m ago',   description: 'Embedding model for semantic search and RAG pipelines. Read-only data access.', linkedPolicies: ['Audit-Log v1'],                       linkedAlerts: 0 },
    { id: 'md-005', name: 'whisper-large-v3',          type: 'Audio Model',        risk: 'Low',      owner: 'product-team',   provider: 'AWS',   policyStatus: 'full',    lastSeen: '2h ago',   description: 'Speech-to-text for call transcription. Handles PII audio — retention policy applied.', linkedPolicies: ['PII-Guard v2', 'Retention-Policy v1'], linkedAlerts: 0 },
    { id: 'md-006', name: 'mixtral-8x7b',              type: 'Open Source LLM',    risk: 'Critical', owner: undefined,        provider: 'GCP',   policyStatus: 'none',    lastSeen: '3h ago',   description: 'Unowned model discovered via API traffic analysis. No policies applied. Flagged for review.', linkedPolicies: [],                             linkedAlerts: 4 },
  ],
  tools: [
    { id: 'tl-001', name: 'SQL-Query-Runner',          type: 'Database Tool',      risk: 'Critical', owner: 'data-eng',       provider: 'AWS',   policyStatus: 'partial', lastSeen: '5m ago',   description: 'Executes SQL queries against production DBs. Exposed to 3 agents with broad permissions.', linkedPolicies: ['Audit-Log v1'],                   linkedAlerts: 2 },
    { id: 'tl-002', name: 'Slack-Notifier',            type: 'Messaging Tool',     risk: 'Low',      owner: 'devex-team',     provider: 'Azure', policyStatus: 'full',    lastSeen: '11m ago',  description: 'Posts notifications to Slack channels. Scoped to engineering channels only.', linkedPolicies: ['Rate-Limiter'],                         linkedAlerts: 0 },
    { id: 'tl-003', name: 'GitHub-PR-Creator',         type: 'VCS Tool',           risk: 'Medium',   owner: 'devex-team',     provider: 'Azure', policyStatus: 'partial', lastSeen: '45m ago',  description: 'Creates and merges pull requests. Used by CodeReview-Assistant agent.', linkedPolicies: ['CodeScan v1'],                         linkedAlerts: 0 },
    { id: 'tl-004', name: 'BrowserScraper',            type: 'Web Tool',           risk: 'High',     owner: undefined,        provider: 'GCP',   policyStatus: 'none',    lastSeen: '2h ago',   description: 'Headless browser tool. Unowned, no egress restrictions. Can access arbitrary URLs.', linkedPolicies: [],                                   linkedAlerts: 3 },
    { id: 'tl-005', name: 'Email-Sender',              type: 'Messaging Tool',     risk: 'High',     owner: 'product-team',   provider: 'AWS',   policyStatus: 'partial', lastSeen: '20m ago',  description: 'Sends transactional emails. Missing data-loss-prevention policy.', linkedPolicies: ['Rate-Limiter'],                             linkedAlerts: 1 },
  ],
  data: [
    { id: 'ds-001', name: 'Customer-Records-DB',       type: 'PostgreSQL',         risk: 'Critical', owner: 'data-platform',  provider: 'AWS',   policyStatus: 'partial', lastSeen: '1m ago',   description: 'Primary CRM database. Contains PII for 2.4M customers. Accessed by 4 agents.', linkedPolicies: ['PII-Guard v2'],                       linkedAlerts: 3 },
    { id: 'ds-002', name: 'HR-Knowledge-Base',         type: 'Vector Store',       risk: 'Medium',   owner: 'people-ops',     provider: 'Azure', policyStatus: 'full',    lastSeen: '1h ago',   description: 'Pinecone vector store with HR policies, benefits docs, and org charts.', linkedPolicies: ['Access-Scope v3', 'Retention-Policy v1'], linkedAlerts: 0 },
    { id: 'ds-003', name: 'Code-Repository-Index',     type: 'Vector Store',       risk: 'Low',      owner: 'devex-team',     provider: 'Azure', policyStatus: 'full',    lastSeen: '30m ago',  description: 'Indexed codebase for semantic code search. Read-only. Updated on each merge.', linkedPolicies: ['Audit-Log v1'],                       linkedAlerts: 0 },
    { id: 'ds-004', name: 'FinancialReports-S3',       type: 'Object Storage',     risk: 'High',     owner: undefined,        provider: 'AWS',   policyStatus: 'none',    lastSeen: '4h ago',   description: 'S3 bucket with quarterly financial reports. Unowned, no access controls configured.', linkedPolicies: [],                                 linkedAlerts: 2 },
    { id: 'ds-005', name: 'SIEM-Event-Stream',         type: 'Kafka Topic',        risk: 'Medium',   owner: 'security-ops',   provider: 'GCP',   policyStatus: 'partial', lastSeen: '3m ago',   description: 'Real-time security event stream. Read by ThreatHunter-AI agent.', linkedPolicies: ['Audit-Log v1'],                             linkedAlerts: 1 },
  ],
  sessions: [
    { id: 'ss-001', name: 'sess_a1b2c3d4',             type: 'Agent Session',      risk: 'High',     owner: 'CustomerSupport-GPT',          provider: 'AWS',   policyStatus: 'partial', lastSeen: '2m ago',   description: 'Active session: CustomerSupport-GPT handling ticket #49201. Prompt injection attempt detected.', linkedPolicies: ['PII-Guard v2'], linkedAlerts: 2 },
    { id: 'ss-002', name: 'sess_e5f6g7h8',             type: 'Agent Session',      risk: 'Low',      owner: 'CodeReview-Assistant',         provider: 'Azure', policyStatus: 'full',    lastSeen: '14m ago',  description: 'Completed session: PR #1842 review. 0 policy violations. Duration: 43s.', linkedPolicies: ['CodeScan v1'],                                                        linkedAlerts: 0 },
    { id: 'ss-003', name: 'sess_i9j0k1l2',             type: 'Agent Session',      risk: 'Critical', owner: 'DataPipeline-Orchestrator',    provider: 'GCP',   policyStatus: 'none',    lastSeen: '1h ago',   description: 'Terminated session: Attempted write to production DB outside policy window. Auto-blocked.', linkedPolicies: [],                                                     linkedAlerts: 4 },
    { id: 'ss-004', name: 'sess_m3n4o5p6',             type: 'User Session',       risk: 'Medium',   owner: 'alice@orbyx.io',               provider: 'Azure', policyStatus: 'full',    lastSeen: '5m ago',   description: 'Active user session. Elevated privilege query detected — under review.', linkedPolicies: ['Access-Scope v3'],                                                   linkedAlerts: 1 },
  ],
}

const TABS = [
  { key: 'agents',   label: 'Agents',       icon: Bot,      count: ASSETS.agents.length   },
  { key: 'models',   label: 'Models',       icon: Cpu,      count: ASSETS.models.length   },
  { key: 'tools',    label: 'Tools',        icon: Wrench,   count: ASSETS.tools.length    },
  { key: 'data',     label: 'Data Sources', icon: Database, count: ASSETS.data.length     },
  { key: 'sessions', label: 'Sessions',     icon: Activity, count: ASSETS.sessions.length },
]

const PROVIDERS     = ['All Providers', 'AWS', 'Azure', 'GCP']
const RISK_LEVELS   = ['All Risk', 'Critical', 'High', 'Medium', 'Low']
const POLICY_STATUS = ['All Coverage', 'full', 'partial', 'none']

const POLICY_LABEL   = { full: 'Covered', partial: 'Partial', none: 'None' }
const POLICY_VARIANT = { full: 'success', partial: 'medium', none: 'critical' }

// ── Summary strip ──────────────────────────────────────────────────────────────

function summaryFor(assets) {
  const total         = assets.length
  const highRisk      = assets.filter(a => a.risk === 'Critical' || a.risk === 'High').length
  const unowned       = assets.filter(a => !a.owner).length
  const missingPolicy = assets.filter(a => a.policyStatus === 'none').length
  return { total, highRisk, unowned, missingPolicy }
}

function SummaryStrip({ assets }) {
  const { total, highRisk, unowned, missingPolicy } = summaryFor(assets)

  const items = [
    { label: 'Total Assets',    value: total,         icon: LayoutGrid,    iconColor: 'text-blue-600',   iconBg: 'bg-blue-50',    accent: 'border-blue-200'   },
    { label: 'High / Critical', value: highRisk,      icon: ShieldAlert,   iconColor: 'text-red-500',    iconBg: 'bg-red-50',     accent: 'border-red-200'    },
    { label: 'Unowned',         value: unowned,       icon: ShieldOff,     iconColor: 'text-orange-500', iconBg: 'bg-orange-50',  accent: 'border-orange-200' },
    { label: 'Missing Policy',  value: missingPolicy, icon: AlertTriangle, iconColor: 'text-yellow-600', iconBg: 'bg-yellow-50',  accent: 'border-yellow-200' },
  ]

  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map(({ label, value, icon: Icon, iconColor, iconBg, accent }) => (
        <div
          key={label}
          className={cn(
            'bg-white border-l-[3px] border border-gray-200 rounded-xl pl-4 pr-5 py-3.5',
            'flex items-center gap-3.5 shadow-sm hover:shadow transition-shadow duration-150',
            accent,
          )}
        >
          <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0', iconBg)}>
            <Icon size={15} className={iconColor} />
          </div>
          <div className="min-w-0">
            <p className="text-xl font-semibold text-gray-900 leading-none tabular-nums">{value}</p>
            <p className="text-[11px] text-gray-400 mt-1 whitespace-nowrap">{label}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Filter bar ─────────────────────────────────────────────────────────────────

function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className={cn(
        'h-8 px-2.5 pr-7 rounded-lg border border-gray-200 bg-white',
        'text-[12px] text-gray-600 font-medium appearance-none',
        'hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400',
        'transition-colors duration-150 cursor-pointer',
        'bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'10\' height=\'10\' viewBox=\'0 0 24 24\'%3E%3Cpath d=\'M6 9l6 6 6-6\' stroke=\'%239ca3af\' stroke-width=\'2.5\' fill=\'none\' stroke-linecap=\'round\'/%3E%3C/svg%3E")]',
        'bg-no-repeat bg-[right_0.5rem_center]',
      )}
    >
      {options.map(o => (
        <option key={o} value={o}>
          {o === 'full' ? 'Covered' : o === 'partial' ? 'Partial' : o === 'none' ? 'None' : o}
        </option>
      ))}
    </select>
  )
}

function FilterBar({ search, setSearch, provider, setProvider, risk, setRisk, policy, setPolicy, view, setView }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">

      {/* Search */}
      <div className="relative w-56 shrink-0">
        <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder="Search assets…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className={cn(
            'w-full h-8 pl-[26px] pr-3 rounded-lg border border-gray-200 bg-white',
            'text-[12px] text-gray-700 placeholder:text-gray-400',
            'hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400',
            'transition-colors duration-150',
          )}
        />
      </div>

      {/* Divider */}
      <div className="w-px h-5 bg-gray-200 shrink-0" />

      {/* Selects */}
      <Select value={provider} onChange={setProvider} options={PROVIDERS} />
      <Select value={risk}     onChange={setRisk}     options={RISK_LEVELS} />
      <Select value={policy}   onChange={setPolicy}   options={POLICY_STATUS} />

      <div className="flex-1" />

      {/* View toggle */}
      <div className="flex items-center border border-gray-200 rounded-lg overflow-hidden bg-white shrink-0 h-8">
        {[
          { key: 'table', icon: List,        title: 'Table view' },
          { key: 'graph', icon: Share2,      title: 'Graph view' },
        ].map(({ key, icon: Icon, title }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            title={title}
            className={cn(
              'w-8 h-8 flex items-center justify-center transition-colors duration-150',
              view === key
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:bg-gray-50 hover:text-gray-600',
            )}
          >
            <Icon size={13} strokeWidth={2} />
          </button>
        ))}
      </div>

      {/* Filters button */}
      <Button variant="outline" size="sm" className="h-8 px-3 gap-1.5 text-[12px] shrink-0">
        <SlidersHorizontal size={12} />
        Filters
      </Button>
    </div>
  )
}

// ── Tab strip ──────────────────────────────────────────────────────────────────

function TabStrip({ activeTab, setActiveTab }) {
  return (
    <div className="flex items-end border-b border-gray-200 -mx-5 px-5">
      {TABS.map(({ key, label, icon: Icon, count }) => {
        const active = activeTab === key
        return (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-2.5 text-[13px] border-b-2 -mb-px',
              'transition-colors duration-150 whitespace-nowrap select-none',
              active
                ? 'border-blue-600 text-blue-600 font-semibold'
                : 'border-transparent text-gray-500 font-medium hover:text-gray-800 hover:border-gray-300',
            )}
          >
            <Icon size={13} strokeWidth={active ? 2.2 : 1.75} />
            {label}
            <span
              className={cn(
                'inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded text-[10px] font-bold',
                active ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-400',
              )}
            >
              {count}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ── Policy status indicator ────────────────────────────────────────────────────

function PolicyIcon({ status }) {
  if (status === 'full')    return <CheckCircle2 size={13} className="text-emerald-500" />
  if (status === 'partial') return <AlertCircle  size={13} className="text-yellow-500" />
  return <XCircle size={13} className="text-red-400" />
}

// ── Risk chip with dot ─────────────────────────────────────────────────────────

function RiskChip({ risk }) {
  return (
    <Badge variant={RISK_VARIANT[risk] ?? 'neutral'} className="gap-1 pl-1.5">
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', RISK_DOT[risk] ?? 'bg-gray-400')} />
      {risk}
    </Badge>
  )
}

// ── Asset table ────────────────────────────────────────────────────────────────

const HEADERS = [
  { label: 'Name',      className: '' },
  { label: 'Type',      className: '' },
  { label: 'Risk',      className: 'w-28' },
  { label: 'Owner',     className: '' },
  { label: 'Provider',  className: 'w-20' },
  { label: 'Policy',    className: 'w-32' },
  { label: 'Alerts',    className: 'w-16 text-right' },
  { label: 'Last Seen', className: 'w-24 text-right' },
  { label: '',          className: 'w-8' },
]

function AssetTable({ assets, selectedId, onSelect }) {
  if (assets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-44 gap-1.5">
        <p className="text-sm font-semibold text-gray-400">No assets found</p>
        <p className="text-xs text-gray-300">Try adjusting your search or filters</p>
      </div>
    )
  }

  return (
    <table className="w-full">
      <thead>
        <tr className="border-b border-gray-100">
          {HEADERS.map((h, i) => (
            <th
              key={h.label || i}
              className={cn(
                'px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-gray-400 text-left bg-gray-50/60',
                h.className,
              )}
            >
              {h.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {assets.map(asset => {
          const selected = selectedId === asset.id
          return (
            <tr
              key={asset.id}
              onClick={() => onSelect(selected ? null : asset)}
              className={cn(
                'group border-b border-gray-100/80 last:border-0 cursor-pointer',
                'transition-colors duration-100',
                selected
                  ? 'bg-blue-50/50'
                  : 'hover:bg-gray-50/60',
              )}
            >
              {/* Name */}
              <td className="px-4 py-2.5">
                <div className="flex items-center gap-2">
                  {selected && <span className="w-0.5 h-4 bg-blue-500 rounded-full shrink-0 -ml-1.5" />}
                  <span className="text-[13px] font-medium text-gray-800 whitespace-nowrap leading-none">{asset.name}</span>
                </div>
              </td>

              {/* Type */}
              <td className="px-4 py-2.5">
                <span className="text-[12px] text-gray-400 whitespace-nowrap">{asset.type}</span>
              </td>

              {/* Risk */}
              <td className="px-4 py-2.5">
                <RiskChip risk={asset.risk} />
              </td>

              {/* Owner */}
              <td className="px-4 py-2.5">
                {asset.owner
                  ? <span className="text-[12px] text-gray-600 font-mono whitespace-nowrap">{asset.owner}</span>
                  : <span className="inline-flex items-center gap-1 text-[12px] text-orange-500 font-medium">
                      <ShieldOff size={11} />
                      Unowned
                    </span>}
              </td>

              {/* Provider */}
              <td className="px-4 py-2.5">
                <span className="text-[12px] text-gray-500 font-medium">{asset.provider}</span>
              </td>

              {/* Policy */}
              <td className="px-4 py-2.5">
                <div className="flex items-center gap-1.5">
                  <PolicyIcon status={asset.policyStatus} />
                  <Badge variant={POLICY_VARIANT[asset.policyStatus]} className="text-[10px]">
                    {POLICY_LABEL[asset.policyStatus]}
                  </Badge>
                </div>
              </td>

              {/* Alerts */}
              <td className="px-4 py-2.5 text-right">
                {asset.linkedAlerts > 0
                  ? <span className="inline-flex items-center gap-1 text-[12px] font-semibold text-red-500">
                      <AlertTriangle size={11} />
                      {asset.linkedAlerts}
                    </span>
                  : <span className="text-[12px] text-gray-200">—</span>}
              </td>

              {/* Last seen */}
              <td className="px-4 py-2.5 text-right">
                <span className="text-[12px] text-gray-400 tabular-nums whitespace-nowrap">{asset.lastSeen}</span>
              </td>

              {/* Expand chevron */}
              <td className="pr-4 py-2.5">
                <ChevronRight
                  size={13}
                  className={cn(
                    'text-gray-300 transition-all duration-150 ml-auto',
                    selected ? 'rotate-90 text-blue-400' : 'group-hover:text-gray-400',
                  )}
                />
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Graph view placeholder ─────────────────────────────────────────────────────

function GraphView({ assets }) {
  const riskCounts = { Critical: 0, High: 0, Medium: 0, Low: 0 }
  assets.forEach(a => { if (a.risk in riskCounts) riskCounts[a.risk]++ })

  const ringNodes = [
    { label: 'Critical', count: riskCounts.Critical, ring: 'ring-red-400',    bg: 'bg-red-500',    text: 'text-red-600',    lightBg: 'bg-red-50',    cx: '20%', cy: '22%' },
    { label: 'High',     count: riskCounts.High,     ring: 'ring-orange-400', bg: 'bg-orange-500', text: 'text-orange-600', lightBg: 'bg-orange-50', cx: '78%', cy: '22%' },
    { label: 'Medium',   count: riskCounts.Medium,   ring: 'ring-yellow-400', bg: 'bg-yellow-500', text: 'text-yellow-700', lightBg: 'bg-yellow-50', cx: '22%', cy: '76%' },
    { label: 'Low',      count: riskCounts.Low,      ring: 'ring-green-400',  bg: 'bg-emerald-500',text: 'text-emerald-700',lightBg: 'bg-emerald-50', cx: '78%', cy: '76%' },
  ]

  return (
    <div className="flex flex-col items-center py-10 px-8 gap-8 select-none">

      {/* Canvas */}
      <div className="relative w-full max-w-lg border-2 border-dashed border-gray-200 rounded-2xl bg-gray-50/40 h-64 overflow-hidden">

        {/* SVG connector lines */}
        <svg className="absolute inset-0 w-full h-full">
          {ringNodes.map((n, i) => (
            <line
              key={i}
              x1="50%" y1="50%"
              x2={n.cx} y2={n.cy}
              stroke="#d1d5db"
              strokeWidth="1.5"
              strokeDasharray="5 4"
            />
          ))}
          {/* Secondary cross-links */}
          {[
            ['20%','22%','78%','22%'],
            ['22%','76%','78%','76%'],
          ].map(([x1,y1,x2,y2], i) => (
            <line key={`x${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#e5e7eb" strokeWidth="1" strokeDasharray="4 4" />
          ))}
        </svg>

        {/* Central hub */}
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-10">
          <div className="w-14 h-14 rounded-full bg-blue-600 ring-4 ring-blue-200 flex items-center justify-center shadow-lg">
            <Shield size={20} className="text-white" />
          </div>
          <p className="text-center text-[10px] font-semibold text-blue-600 mt-1.5">AI-SPM</p>
        </div>

        {/* Risk nodes */}
        {ringNodes.map(({ label, count, ring, bg, cx, cy }) => (
          <div
            key={label}
            className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-1 z-10"
            style={{ left: cx, top: cy }}
          >
            <div className={cn('w-10 h-10 rounded-full ring-2 flex items-center justify-center shadow', bg, ring)}>
              <span className="text-white text-[11px] font-bold">{count}</span>
            </div>
            <span className="text-[9px] font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{label}</span>
          </div>
        ))}
      </div>

      {/* Caption + legend */}
      <div className="flex flex-col items-center gap-3">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gray-100 border border-gray-200">
          <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
          <span className="text-[11px] font-semibold text-gray-500 tracking-wide">Graph View — Coming Soon</span>
        </div>
        <p className="text-[12px] text-gray-400 text-center max-w-sm leading-relaxed">
          Interactive blast-radius graph with risk propagation, policy coverage, and asset dependency edges.
        </p>

        {/* Mini legend */}
        <div className="flex items-center gap-4 mt-1">
          {ringNodes.map(({ label, bg, lightBg, text }) => (
            <div key={label} className={cn('flex items-center gap-1.5 px-2 py-0.5 rounded-md', lightBg)}>
              <span className={cn('w-1.5 h-1.5 rounded-full', bg)} />
              <span className={cn('text-[10px] font-semibold', text)}>{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Quick preview panel ────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return (
    <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 mb-2">
      {children}
    </p>
  )
}

function MetaRow({ icon: Icon, label, value }) {
  return (
    <div className="grid grid-cols-[72px_1fr] items-baseline gap-1">
      <span className="flex items-center gap-1.5 text-[11px] text-gray-400">
        <Icon size={11} className="shrink-0" />
        {label}
      </span>
      <span className="text-[12px] text-gray-700 font-medium truncate">{value}</span>
    </div>
  )
}

function PreviewPanel({ asset, onClose }) {
  if (!asset) return null

  const riskBg = {
    Critical: 'bg-red-50',
    High:     'bg-orange-50',
    Medium:   'bg-yellow-50',
    Low:      'bg-emerald-50',
  }[asset.risk] ?? 'bg-gray-50'

  return (
    <div className="w-[300px] shrink-0 flex flex-col h-full">

      {/* Header — risk-tinted */}
      <div className={cn('px-4 py-3.5 border-b border-gray-100 flex items-start justify-between gap-2', riskBg)}>
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-gray-900 leading-snug truncate">{asset.name}</p>
          <p className="text-[11px] text-gray-500 mt-0.5">{asset.type}</p>
        </div>
        <button
          onClick={onClose}
          className="w-6 h-6 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-black/5 transition-colors shrink-0 mt-0.5"
        >
          <X size={13} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100">

        {/* Risk + policy */}
        <div className="px-4 py-3 flex items-center gap-2 flex-wrap">
          <RiskChip risk={asset.risk} />
          <div className="flex items-center gap-1.5">
            <PolicyIcon status={asset.policyStatus} />
            <Badge variant={POLICY_VARIANT[asset.policyStatus]} className="text-[10px]">
              {POLICY_LABEL[asset.policyStatus]}
            </Badge>
          </div>
        </div>

        {/* Meta */}
        <div className="px-4 py-3 space-y-2">
          <MetaRow icon={User}  label="Owner"    value={asset.owner ?? <span className="text-orange-500 font-medium not-italic">Unowned</span>} />
          <MetaRow icon={Cloud} label="Provider" value={asset.provider} />
          <MetaRow icon={Clock} label="Last Seen" value={asset.lastSeen} />
        </div>

        {/* Description */}
        <div className="px-4 py-3">
          <SectionLabel>Description</SectionLabel>
          <p className="text-[12px] text-gray-600 leading-relaxed">{asset.description}</p>
        </div>

        {/* Linked policies */}
        <div className="px-4 py-3">
          <SectionLabel>Linked Policies</SectionLabel>
          {asset.linkedPolicies.length > 0
            ? <div className="flex flex-wrap gap-1.5">
                {asset.linkedPolicies.map(p => (
                  <Badge key={p} variant="info" className="text-[10px]">{p}</Badge>
                ))}
              </div>
            : <p className="text-[12px] text-orange-500 font-medium">No policies applied</p>}
        </div>

        {/* Active alerts */}
        <div className="px-4 py-3">
          <SectionLabel>Active Alerts</SectionLabel>
          {asset.linkedAlerts > 0
            ? <div className="flex items-center gap-1.5">
                <AlertTriangle size={12} className="text-red-500 shrink-0" />
                <span className="text-[12px] font-semibold text-red-600">
                  {asset.linkedAlerts} active alert{asset.linkedAlerts !== 1 ? 's' : ''}
                </span>
              </div>
            : <div className="flex items-center gap-1.5">
                <ShieldCheck size={12} className="text-emerald-500 shrink-0" />
                <span className="text-[12px] text-gray-500">No active alerts</span>
              </div>}
        </div>

      </div>

      {/* Actions */}
      <div className="px-4 py-3 border-t border-gray-100 space-y-2 shrink-0">
        <Button variant="outline" size="sm" className="w-full h-8 gap-1.5 text-[12px] justify-center">
          <ExternalLink size={12} />
          View Detail
        </Button>
        <Button size="sm" className="w-full h-8 gap-1.5 text-[12px] justify-center">
          <Shield size={12} />
          Apply Policy
        </Button>
      </div>

    </div>
  )
}

// ── Inventory page ─────────────────────────────────────────────────────────────

export default function Inventory() {
  const [activeTab, setActiveTab] = useState('agents')
  const [view,      setView]      = useState('table')
  const [search,    setSearch]    = useState('')
  const [provider,  setProvider]  = useState('All Providers')
  const [risk,      setRisk]      = useState('All Risk')
  const [policy,    setPolicy]    = useState('All Coverage')
  const [selected,  setSelected]  = useState(null)

  const handleTabChange = (tab) => {
    setActiveTab(tab)
    setSelected(null)
  }

  const rawAssets = ASSETS[activeTab] ?? []

  const filtered = rawAssets.filter(a => {
    if (search   && !a.name.toLowerCase().includes(search.toLowerCase()) && !a.type.toLowerCase().includes(search.toLowerCase())) return false
    if (provider !== 'All Providers' && a.provider     !== provider) return false
    if (risk     !== 'All Risk'      && a.risk         !== risk)     return false
    if (policy   !== 'All Coverage'  && a.policyStatus !== policy)   return false
    return true
  })

  return (
    <PageContainer>

      <PageHeader
        title="Inventory"
        subtitle="Discover and inspect AI assets, tools, and context sources across all environments"
        actions={
          <>
            <Button variant="outline" size="sm">Export</Button>
            <Button size="sm">+ Register Asset</Button>
          </>
        }
      />

      {/* Summary strip */}
      <SummaryStrip assets={rawAssets} />

      {/* Main panel */}
      <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">

        {/* Tabs + filter bar in one flush zone */}
        <div className="px-5 pt-3 pb-0">
          <TabStrip activeTab={activeTab} setActiveTab={handleTabChange} />
        </div>

        <div className="px-5 py-2.5 border-b border-gray-100">
          <FilterBar
            search={search}     setSearch={setSearch}
            provider={provider} setProvider={setProvider}
            risk={risk}         setRisk={setRisk}
            policy={policy}     setPolicy={setPolicy}
            view={view}         setView={setView}
          />
        </div>

        {/* Table + preview side panel */}
        <div className="flex items-stretch divide-x divide-gray-100">

          <div className="flex-1 min-w-0 overflow-x-auto">
            {view === 'table'
              ? <AssetTable
                  assets={filtered}
                  selectedId={selected?.id}
                  onSelect={setSelected}
                />
              : <GraphView assets={filtered} />
            }
          </div>

          {selected && <PreviewPanel asset={selected} onClose={() => setSelected(null)} />}

        </div>

        {/* Footer */}
        {view === 'table' && (
          <div className="px-5 py-2.5 border-t border-gray-100 flex items-center justify-between bg-gray-50/40">
            <span className="text-[11px] text-gray-400">
              {filtered.length} of {rawAssets.length} asset{rawAssets.length !== 1 ? 's' : ''}
            </span>
            <button className="text-[11px] font-semibold text-blue-600 hover:text-blue-700 transition-colors">
              View all in {TABS.find(t => t.key === activeTab)?.label} →
            </button>
          </div>
        )}

      </div>

    </PageContainer>
  )
}
