import { useEffect, useState, useMemo, useRef } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import {
  Search, SlidersHorizontal, LayoutGrid, List,
  ChevronRight, X, ExternalLink, AlertTriangle,
  Bot, Cpu, Wrench, Database, Activity,
  Shield, ShieldAlert, ShieldCheck, ShieldOff,
  User, Cloud, Clock, ArrowUpRight,
  CheckCircle2, XCircle, AlertCircle, Share2,
  Upload, FileUp, Loader2,
  MessageSquare,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { useFilterParams } from '../../hooks/useFilterParams.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { fetchModels, registerModelWithFile, fetchPolicies } from '../api/spm.js'

// ── Phase 3 — agent runtime control plane wiring ──────────────────────────
import { useAgentList, mergeAgents } from '../agents/hooks/useAgentList.js'
import { deleteAgent } from '../api/agents.js'
import AgentChatPanel       from '../agents/AgentChatPanel.jsx'
import AgentRunStopToggle   from '../agents/AgentRunStopToggle.jsx'
import PolicySelector       from '../agents/PolicySelector.jsx'
import RegisterAgentPanel   from '../agents/RegisterAgentPanel.jsx'

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
    { id: 'ag-005', name: 'ThreatHunter-AI',           type: 'LangChain Agent',    risk: 'High',     owner: 'security-ops',   provider: 'Internal', policyStatus: 'partial', lastSeen: 'live', description: 'Real-time threat hunting agent. Consumes Kafka events across all tenants, correlates AI-layer and infrastructure signals, and opens findings for human investigation. Powered by Groq llama-3.3-70b-versatile.', linkedPolicies: ['Audit-Log v1', 'OPA-Policy v1'], linkedAlerts: 0 },
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

const allAssets = Object.values(ASSETS).flat()

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

// Delete-agent confirmation modal — same visual language as
// EscalateConfirmModal in Runtime.jsx, just retitled and red-tinted
// to signal a destructive action. Kept inline here because PreviewPanel
// is the only consumer; promote to a shared component when a second
// destructive flow needs it.
function DeleteAgentConfirmModal({ open, agentName, loading, onConfirm, onCancel }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-[2px]"
        onClick={onCancel}
      />
      {/* Dialog */}
      <div className="relative z-10 bg-white rounded-xl shadow-xl border border-gray-200 w-[360px] p-5">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-9 h-9 rounded-lg bg-red-50 border border-red-200 flex items-center justify-center shrink-0">
            <AlertCircle size={16} className="text-red-600" strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-gray-900">Delete Agent</p>
            <p className="text-[12px] text-gray-500 mt-0.5 leading-relaxed">
              Are you sure you want to delete <span className="font-medium text-gray-700">{agentName}</span>?
              This stops the container, deletes its Kafka topics, and drops the row.
              This cannot be undone.
            </p>
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          <Button
            variant="outline"
            size="sm"
            className="text-[12px] h-8 px-3"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            className="text-[12px] h-8 px-3 bg-red-600 hover:bg-red-700 text-white border-0"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? 'Deleting…' : 'Yes, Delete'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function PreviewPanel({ asset, onClose, onOpenChat, onDeleted }) {
  if (!asset) return null

  const riskBg = {
    Critical: 'bg-red-50',
    High:     'bg-orange-50',
    Medium:   'bg-yellow-50',
    Low:      'bg-emerald-50',
  }[asset.risk] ?? 'bg-gray-50'

  // Phase 3 — live agents get an extra "Open Chat" + run/stop +
  // Delete control appended to the action footer. Mocks and other
  // asset types render the panel exactly as before.
  const isLiveAgent = asset.kind === 'agent' && asset._live === true

  // Delete (retire) state for the live-agent footer.
  const [deleting, setDeleting] = useState(false)
  const [deleteErr, setDeleteErr] = useState(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  async function _runDelete() {
    setDeleting(true); setDeleteErr(null)
    try {
      await deleteAgent(asset._backendId)
      setConfirmingDelete(false)
      if (onDeleted) onDeleted(asset)
    } catch (e) {
      setDeleteErr(e.message || 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="w-[300px] shrink-0 flex flex-col h-full" data-testid="asset-preview-panel">

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
          {isLiveAgent
            ? <PolicySelector agent={asset} />
            : asset.linkedPolicies.length > 0
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
        {/* Live-agent only: runtime status + Open Chat. Stays above
            the existing actions so it's the first thing the operator
            sees when they open an agent row. */}
        {isLiveAgent && (
          <>
            <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
              <span>Runtime status</span>
              <span className="font-medium text-gray-800">
                {asset.runtime_state || 'stopped'}
              </span>
            </div>
            <AgentRunStopToggle
              agent={{ id: asset._backendId, runtime_state: asset.runtime_state }}
              size="sm"
              className="w-full justify-center"
            />
            <Button
              variant="outline" size="sm"
              onClick={() => onOpenChat && onOpenChat(asset)}
              className="w-full h-8 gap-1.5 text-[12px] justify-center"
            >
              <MessageSquare size={12} />
              Open Chat
            </Button>
            <Button
              variant="outline" size="sm"
              onClick={() => setConfirmingDelete(true)}
              disabled={deleting}
              className="w-full h-8 gap-1.5 text-[12px] justify-center text-red-600 border-red-200 hover:bg-red-50"
            >
              <X size={12} />
              Delete asset
            </Button>
            {deleteErr && (
              <p className="text-[11px] text-red-600 text-center" role="alert">
                ⚠ {deleteErr}
              </p>
            )}
            <DeleteAgentConfirmModal
              open={confirmingDelete}
              agentName={asset.name}
              loading={deleting}
              onConfirm={_runDelete}
              onCancel={() => { if (!deleting) setConfirmingDelete(false) }}
            />
          </>
        )}
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

// ── Register Asset side panel ──────────────────────────────────────────────────

// Mirrors PreviewPanel's shell (300px right-side drawer, header + scrollable
// body + footer) so the two panels visually swap in the same slot. No new
// reusable component — kept inline here the same way PreviewPanel is.

const MODEL_TYPE_OPTIONS = [
  { value: 'llm',             label: 'LLM' },
  { value: 'open_source_llm', label: 'Open Source LLM' },
  { value: 'embedding_model', label: 'Embedding Model' },
  { value: 'audio_model',     label: 'Audio Model' },
  { value: 'vision_model',    label: 'Vision Model' },
  { value: 'multimodal',      label: 'Multimodal' },
  { value: 'other',           label: 'Other' },
]

const PROVIDER_OPTIONS = [
  'aws', 'azure', 'gcp', 'internal',
  'local', 'openai', 'anthropic', 'other',
]

// Risk ladder mirrors backend: 0=Low, 1-2=Medium, 3-5=High, 6+=Critical
function riskFromAlerts(n) {
  const a = Number(n) || 0
  if (a <= 0) return 'Low'
  if (a <= 2) return 'Medium'
  if (a <= 5) return 'High'
  return 'Critical'
}

function policyCoverageFromLinks(count) {
  if (!count)        return 'none'
  if (count >= 3)    return 'full'
  return 'partial'
}

// Reuse the same input/select styles as FilterBar so the panel visually
// matches the rest of the page.
const FIELD_CLS = cn(
  'w-full h-8 px-2.5 rounded-lg border border-gray-200 bg-white',
  'text-[12px] text-gray-700 placeholder:text-gray-400',
  'hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400',
  'transition-colors duration-150',
)
const SELECT_CLS = cn(
  FIELD_CLS, 'pr-7 font-medium appearance-none cursor-pointer',
  'bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'10\' height=\'10\' viewBox=\'0 0 24 24\'%3E%3Cpath d=\'M6 9l6 6 6-6\' stroke=\'%239ca3af\' stroke-width=\'2.5\' fill=\'none\' stroke-linecap=\'round\'/%3E%3C/svg%3E")]',
  'bg-no-repeat bg-[right_0.5rem_center]',
)

function FieldLabel({ children, required }) {
  return (
    <label className="block text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 mb-1.5">
      {children}
      {required && <span className="text-red-400 ml-0.5">*</span>}
    </label>
  )
}

function FieldError({ msg }) {
  if (!msg) return null
  return <p className="mt-1 text-[11px] text-red-500 font-medium">{msg}</p>
}

function RegisterAssetPanel({ onClose, onRegistered }) {
  // Form state
  const [name,        setName]        = useState('')
  const [version,     setVersion]     = useState('1.0.0')
  const [modelType,   setModelType]   = useState('llm')
  const [owner,       setOwner]       = useState('')
  const [provider,    setProvider]    = useState('')
  const [description, setDescription] = useState('')
  const [notes,       setNotes]       = useState('')
  const [file,        setFile]        = useState(null)
  const [linkedPols,  setLinkedPols]  = useState([])       // array of policy ids
  const [policies,    setPolicies]    = useState([])       // [{id, name, ...}]

  // Dynamic owner dropdown — populated from the merged asset list above
  const ownerOptions = onRegistered?.ownerOptions ?? []

  // Derived, not editable
  const alertsCount = 0                                   // new asset has no alerts yet
  const risk        = riskFromAlerts(alertsCount)
  const coverage    = policyCoverageFromLinks(linkedPols.length)

  // UX state
  const [errors,   setErrors]   = useState({})           // field → message
  const [progress, setProgress] = useState(0)            // 0..100
  const [busy,     setBusy]     = useState(false)
  const [apiError, setApiError] = useState(null)
  const [dupe,     setDupe]     = useState(null)         // {name, version} when 409
  const abortRef = useRef(null)

  const fileInputRef = useRef(null)

  // Load policies from CPM once
  useEffect(() => {
    fetchPolicies().then(setPolicies).catch(() => setPolicies([]))
  }, [])

  // Esc closes (only when not uploading), Enter submits
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { if (!busy) cancelAndClose() }
      else if (e.key === 'Enter' && !e.shiftKey) {
        // Avoid stealing Enter inside the textarea
        if (document.activeElement?.tagName !== 'TEXTAREA') {
          e.preventDefault()
          handleApply()
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, version, modelType, owner, provider, description, file, linkedPols, busy])

  // Cancel in-flight upload if the panel unmounts (e.g. user navigates away)
  useEffect(() => () => { try { abortRef.current?.abort() } catch {} }, [])

  function cancelAndClose() {
    try { abortRef.current?.abort() } catch {}
    onClose?.()
  }

  function validate() {
    const e = {}
    if (!name.trim())       e.name      = 'Name is required'
    if (!version.trim())    e.version   = 'Version is required'
    if (!modelType)         e.modelType = 'Type is required'
    if (!owner)             e.owner     = 'Owner is required'
    if (!provider)          e.provider  = 'Provider is required'
    if (!description.trim())e.description = 'Description is required'
    if (!file)              e.file      = 'Please select a model file'
    return e
  }

  async function handleApply() {
    if (busy) return
    setApiError(null)
    setDupe(null)
    const e = validate()
    setErrors(e)
    if (Object.keys(e).length > 0) return

    const fd = new FormData()
    fd.set('name',        name.trim())
    fd.set('version',     version.trim())
    fd.set('model_type',  modelType)
    fd.set('owner',       owner)
    fd.set('provider',    provider)
    fd.set('purpose',     description.trim())           // description → purpose column
    if (notes.trim())     fd.set('notes', notes.trim())
    fd.set('alerts_count', '0')
    fd.set('policy_status', policyCoverageFromLinks(linkedPols.length))
    fd.set('linked_policies', JSON.stringify(linkedPols))
    fd.set('file', file)

    const ctrl = new AbortController()
    abortRef.current = ctrl
    setBusy(true); setProgress(0)
    try {
      const row = await registerModelWithFile(fd, {
        onProgress: setProgress,
        signal:     ctrl.signal,
      })
      onRegistered?.onCreated?.(row)
      onClose?.()
    } catch (err) {
      if (err?.aborted) return                          // silent — panel is closing
      if (err?.status === 409) {
        setDupe({ name: name.trim(), version: version.trim() })
      } else {
        setApiError(err?.message || 'Registration failed')
      }
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }

  function togglePolicy(id) {
    setLinkedPols(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  function onPickFile(f) {
    if (!f) return
    setFile(f)
    if (errors.file) setErrors(p => ({ ...p, file: undefined }))
  }

  // Header styling mirrors PreviewPanel (risk-tinted)
  const riskBg = { Critical: 'bg-red-50', High: 'bg-orange-50', Medium: 'bg-yellow-50', Low: 'bg-emerald-50' }[risk]

  return (
    <div className="w-[300px] shrink-0 flex flex-col h-full" data-testid="register-asset-panel">

      {/* Header */}
      <div className={cn('px-4 py-3.5 border-b border-gray-100 flex items-start justify-between gap-2', riskBg)}>
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-gray-900 leading-snug truncate">
            {name.trim() || 'Register Asset'}
          </p>
          <p className="text-[11px] text-gray-500 mt-0.5">
            {MODEL_TYPE_OPTIONS.find(o => o.value === modelType)?.label ?? 'Model'}
          </p>
        </div>
        <button
          onClick={cancelAndClose}
          disabled={busy}
          className="w-6 h-6 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-black/5 transition-colors shrink-0 mt-0.5 disabled:opacity-40"
        >
          <X size={13} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100">

        {/* Derived risk + policy badges (read-only) */}
        <div className="px-4 py-3 flex items-center gap-2 flex-wrap">
          <RiskChip risk={risk} />
          <div className="flex items-center gap-1.5">
            <PolicyIcon status={coverage} />
            <Badge variant={POLICY_VARIANT[coverage]} className="text-[10px]">
              {POLICY_LABEL[coverage]}
            </Badge>
          </div>
        </div>

        {/* Core fields */}
        <div className="px-4 py-3 space-y-3">

          {/* Name */}
          <div>
            <FieldLabel required>Name</FieldLabel>
            <input
              type="text" className={FIELD_CLS} placeholder="gpt-4-turbo"
              value={name}
              onChange={e => { setName(e.target.value); if (errors.name) setErrors(p => ({...p, name: undefined})) }}
              disabled={busy}
            />
            <FieldError msg={errors.name} />
          </div>

          {/* Version */}
          <div>
            <FieldLabel required>Version</FieldLabel>
            <input
              type="text" className={FIELD_CLS} placeholder="1.0.0"
              value={version}
              onChange={e => { setVersion(e.target.value); if (errors.version) setErrors(p => ({...p, version: undefined})) }}
              disabled={busy}
            />
            <FieldError msg={errors.version} />
          </div>

          {/* Type */}
          <div>
            <FieldLabel required>Type</FieldLabel>
            <select
              className={SELECT_CLS} value={modelType}
              onChange={e => setModelType(e.target.value)}
              disabled={busy}
            >
              {MODEL_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <FieldError msg={errors.modelType} />
          </div>

          {/* Owner */}
          <div>
            <FieldLabel required>Owner</FieldLabel>
            <select
              className={SELECT_CLS} value={owner}
              onChange={e => { setOwner(e.target.value); if (errors.owner) setErrors(p => ({...p, owner: undefined})) }}
              disabled={busy}
            >
              <option value="">enter the owner of the model…</option>
              {ownerOptions.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
            <FieldError msg={errors.owner} />
          </div>

          {/* Provider */}
          <div>
            <FieldLabel required>Provider</FieldLabel>
            <select
              className={SELECT_CLS} value={provider}
              onChange={e => { setProvider(e.target.value); if (errors.provider) setErrors(p => ({...p, provider: undefined})) }}
              disabled={busy}
            >
              <option value="">enter the provider…</option>
              {PROVIDER_OPTIONS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <FieldError msg={errors.provider} />
          </div>

          {/* Last Seen — read only ("now", will update via updated_at) */}
          <div className="grid grid-cols-[72px_1fr] items-baseline gap-1">
            <span className="flex items-center gap-1.5 text-[11px] text-gray-400">
              <Clock size={11} className="shrink-0" />
              Last Seen
            </span>
            <span className="text-[12px] text-gray-400 italic">set on apply</span>
          </div>
        </div>

        {/* Description */}
        <div className="px-4 py-3">
          <FieldLabel required>Description</FieldLabel>
          <textarea
            rows={3}
            className={cn(FIELD_CLS, 'h-auto py-2 resize-none leading-snug')}
            placeholder="please provide a description for the model"
            value={description}
            onChange={e => { setDescription(e.target.value); if (errors.description) setErrors(p => ({...p, description: undefined})) }}
            disabled={busy}
          />
          <FieldError msg={errors.description} />
        </div>

        {/* Notes / Tags */}
        <div className="px-4 py-3">
          <FieldLabel>Tags / Notes</FieldLabel>
          <input
            type="text" className={FIELD_CLS}
            placeholder="optional — comma-separated tags or free-text"
            value={notes} onChange={e => setNotes(e.target.value)}
            disabled={busy}
          />
        </div>

        {/* Linked Policies */}
        <div className="px-4 py-3">
          <SectionLabel>Linked Policies</SectionLabel>
          {policies.length === 0
            ? <p className="text-[12px] text-gray-400 italic">No policies available</p>
            : (
              <div className="max-h-32 overflow-y-auto rounded-lg border border-gray-200 divide-y divide-gray-100">
                {policies.map(p => {
                  const checked = linkedPols.includes(p.id)
                  return (
                    <label
                      key={p.id}
                      className={cn(
                        'flex items-center gap-2 px-2.5 py-1.5 text-[12px] cursor-pointer',
                        checked ? 'bg-blue-50/60' : 'hover:bg-gray-50',
                      )}
                    >
                      <input
                        type="checkbox" checked={checked}
                        onChange={() => togglePolicy(p.id)}
                        disabled={busy}
                        className="accent-blue-600 shrink-0"
                      />
                      <span className="text-gray-700 truncate">{p.name}</span>
                      {p.is_active && (
                        <span className="ml-auto text-[10px] font-semibold text-emerald-600 uppercase tracking-wider shrink-0">Active</span>
                      )}
                    </label>
                  )
                })}
              </div>
            )}
          {linkedPols.length > 0 && (
            <p className="mt-1.5 text-[10px] text-gray-400">{linkedPols.length} selected</p>
          )}
        </div>

        {/* Active alerts — read only */}
        <div className="px-4 py-3">
          <SectionLabel>Active Alerts</SectionLabel>
          <div className="flex items-center gap-1.5">
            <ShieldCheck size={12} className="text-gray-300 shrink-0" />
            <span className="text-[12px] text-gray-400">none — populated when alerts start flowing</span>
          </div>
        </div>

      </div>

      {/* Footer: file + actions */}
      <div className="px-4 py-3 border-t border-gray-100 space-y-2 shrink-0">

        {/* File picker */}
        <input
          ref={fileInputRef} type="file" className="hidden"
          onChange={e => onPickFile(e.target.files?.[0])}
        />
        {file ? (
          <div className="flex items-center gap-1.5 px-2.5 h-8 rounded-lg bg-gray-50 border border-gray-200">
            <FileUp size={12} className="text-gray-500 shrink-0" />
            <span className="text-[11px] text-gray-700 truncate flex-1">{file.name}</span>
            <span className="text-[10px] text-gray-400 shrink-0 tabular-nums">
              {(file.size / (1024 * 1024)).toFixed(1)} MB
            </span>
            {!busy && (
              <button
                onClick={() => setFile(null)}
                className="w-4 h-4 flex items-center justify-center rounded text-gray-400 hover:text-red-500 hover:bg-red-50 shrink-0"
                aria-label="Remove file"
              >
                <X size={11} />
              </button>
            )}
          </div>
        ) : (
          <Button
            variant="outline" size="sm"
            className="w-full h-8 gap-1.5 text-[12px] justify-center"
            onClick={() => fileInputRef.current?.click()}
            disabled={busy}
          >
            <Upload size={12} />
            Browse…
          </Button>
        )}
        <FieldError msg={errors.file} />

        {/* Progress */}
        {busy && (
          <div className="space-y-1">
            <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all duration-150"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-[10px] text-gray-400 text-center tabular-nums">
              Uploading… {progress}%
            </p>
          </div>
        )}

        {/* API error */}
        {apiError && (
          <p className="text-[11px] text-red-500 font-medium">{apiError}</p>
        )}

        {/* Apply */}
        <Button
          size="sm"
          className="w-full h-8 gap-1.5 text-[12px] justify-center"
          onClick={handleApply}
          disabled={busy}
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Shield size={12} />}
          {busy ? 'Uploading…' : 'Apply'}
        </Button>
      </div>

      {/* Duplicate-model confirm dialog */}
      {dupe && (
        <div className="absolute inset-0 bg-black/30 flex items-center justify-center z-20">
          <div className="bg-white rounded-xl shadow-xl w-72 p-4 space-y-3 mx-3">
            <p className="text-[13px] font-semibold text-gray-900">Model already exists</p>
            <p className="text-[12px] text-gray-600 leading-relaxed">
              <span className="font-mono">{dupe.name}</span> version{' '}
              <span className="font-mono">{dupe.version}</span> is already registered.
              Bump the version and try again.
            </p>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" onClick={() => setDupe(null)}>OK</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Inventory page ─────────────────────────────────────────────────────────────

// ── Live model adapter: spm_api row → table-row shape ─────────────────────────

const PROVIDER_DISPLAY = {
  aws: 'AWS', azure: 'Azure', gcp: 'GCP', internal: 'Internal',
  local: 'Local', openai: 'OpenAI', anthropic: 'Anthropic', other: 'Other',
}

const TYPE_DISPLAY = {
  llm: 'LLM', open_source_llm: 'Open Source LLM',
  embedding_model: 'Embedding Model', audio_model: 'Audio Model',
  vision_model: 'Vision Model', multimodal: 'Multimodal', other: 'Other',
}

function formatAgo(iso) {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Math.max(0, Date.now() - then)
  const mins = Math.floor(diff / 60000)
  if (mins < 1)       return 'just now'
  if (mins < 60)      return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)       return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function riskDisplayFromBackend(r) {
  if (!r) return 'Low'
  const s = String(r).toLowerCase()
  if (s === 'critical' || s === 'unacceptable') return 'Critical'
  if (s === 'high')                             return 'High'
  if (s === 'medium' || s === 'limited')        return 'Medium'
  return 'Low'
}

function adaptLiveModel(m) {
  return {
    id:            `live-${m.model_id}`,
    name:          m.name,
    type:          TYPE_DISPLAY[m.model_type] ?? 'LLM',
    risk:          riskDisplayFromBackend(m.risk_tier),
    owner:         m.owner || undefined,
    provider:      PROVIDER_DISPLAY[m.provider] ?? (m.provider || '—'),
    policyStatus:  m.policy_status || 'none',
    lastSeen:      formatAgo(m.last_seen_at || m.updated_at),
    description:   m.purpose || 'Registered via Inventory.',
    linkedPolicies: (m.ai_sbom?.linked_policies ?? []).map(String),
    linkedAlerts:  m.alerts_count || 0,
    _live: true,
  }
}

// ── Phase 3 — adapt /api/spm/agents row to the Inventory UI shape ─────────

const AGENT_TYPE_LABEL = {
  langchain:        'LangChain Agent',
  llamaindex:       'LlamaIndex Agent',
  autogpt:          'AutoGPT',
  openai_assistant: 'OpenAI Assistant',
  custom:           'Custom Agent',
}

// The backend uses lowercase risk + a different policy_status vocabulary
// than the Inventory mocks. Translate so the existing filter chips +
// PolicyIcon + RiskChip render the live rows the same way as mocks.
const POLICY_FROM_BACKEND = { covered: 'full', partial: 'partial', none: 'none' }

function adaptLiveAgent(a) {
  return {
    // Prefix so the URL-param selector can't accidentally match a mock row.
    id:            `live-${a.id}`,
    _backendId:    a.id,
    kind:          'agent',
    name:          a.name,
    type:          AGENT_TYPE_LABEL[a.agent_type] || (a.agent_type || 'Agent'),
    risk:          riskDisplayFromBackend(a.risk),
    owner:         a.owner || undefined,
    provider:      PROVIDER_DISPLAY[a.provider] ?? (a.provider || '—'),
    policyStatus:  POLICY_FROM_BACKEND[a.policy_status] || 'none',
    lastSeen:      a.last_seen_at ? formatAgo(a.last_seen_at) : '—',
    description:   a.description || 'Uploaded via Inventory.',
    linkedPolicies: [],
    linkedAlerts:   0,
    // Pass-throughs the AgentDetailDrawer / chat panel need:
    runtime_state:  a.runtime_state,
    version:        a.version,
    agent_type:     a.agent_type,
    code_path:      a.code_path,
    code_sha256:    a.code_sha256,
    policy_status:  a.policy_status,  // backend value for the drawer's Configure tab
    _live: true,
  }
}

// ── Inventory page ────────────────────────────────────────────────────────────

export default function Inventory() {
  const { assetId } = useParams()
  const navigate    = useNavigate()

  const { values, setters } = useFilterParams({
    tab:      'agents',
    view:     'table',
    search:   '',
    provider: 'All Providers',
    risk:     'All Risk',
    policy:   'All Coverage',
  })
  const { tab: activeTab, view, search, provider, risk, policy } = values
  const { setTab, setView, setSearch, setProvider, setRisk, setPolicy } = setters

  // Live models fetched from spm_api — prepended to the Models tab. Mocks kept.
  const [liveModels, setLiveModels] = useState([])
  const [showRegister, setShowRegister] = useState(false)

  // Phase 3 — live agents from /api/spm/agents. Polled every 5s; same
  // offline-friendly fall-through as models (errors get swallowed by
  // the hook so we just see no live rows).
  const { live: liveAgentsRaw, refresh: refreshAgents } =
    useAgentList({ pollMs: 5000 })
  const liveAgents = useMemo(
    () => (liveAgentsRaw || []).map(adaptLiveAgent),
    [liveAgentsRaw],
  )

  // Chat-panel state. Floats over the page; opens from the Open Chat
  // button on PreviewPanel for live agents.
  const [chatAgent, setChatAgent] = useState(null)

  async function reloadLiveModels() {
    try {
      const rows = await fetchModels()
      setLiveModels(rows.map(adaptLiveModel))
    } catch {
      // Offline / backend down → just show mocks
      setLiveModels([])
    }
  }

  useEffect(() => { reloadLiveModels() }, [])

  // Merged view per tab — live models prepend to the Models list, and
  // live agents merge with mock agents (live wins on name collision so
  // a live "CustomerSupport-GPT" replaces the mock of the same name).
  const mergedAssets = useMemo(() => {
    const next = { ...ASSETS }
    next.models = [...liveModels, ...ASSETS.models]
    // Tag the mock agent rows so the row click dispatcher below can
    // route both mock + live agents to the new drawer (mocks open the
    // same UI in read-only mode — no live API actions fire).
    const taggedMockAgents = ASSETS.agents.map(a => ({ ...a, kind: 'agent' }))
    next.agents = mergeAgents(taggedMockAgents, liveAgents)
    return next
  }, [liveModels, liveAgents])

  const mergedAllAssets = useMemo(() => Object.values(mergedAssets).flat(), [mergedAssets])

  // Selection derived from URL param — now searches the merged list so live rows work
  const selected = mergedAllAssets.find(a => a.id === assetId) ?? null

  // Owners seen across all merged assets, for the Register panel's Owner dropdown
  const ownerOptions = useMemo(() => {
    const set = new Set()
    for (const a of mergedAllAssets) if (a.owner) set.add(a.owner)
    return Array.from(set).sort()
  }, [mergedAllAssets])

  // ── Redirect ?asset=<name> → /:assetId (runs once on mount) ──────────────
  const location  = useLocation()
  const assetNameParam = new URLSearchParams(location.search).get('asset')

  useEffect(() => {
    if (!assetNameParam || assetId) return            // already a path param, or no query param
    const match = mergedAllAssets.find(
      a => a.name.toLowerCase() === assetNameParam.toLowerCase()
    )
    if (match) navigate(`/admin/inventory/${match.id}`, { replace: true })
  }, [assetNameParam, assetId, navigate, mergedAllAssets])

  const handleTabChange = (tab) => {
    setTab(tab)
    setShowRegister(false)                            // close panel on tab change
    if (assetId) navigate('/admin/inventory', { replace: true })
  }

  const rawAssets = mergedAssets[activeTab] ?? []

  const filtered = rawAssets.filter(a => {
    if (search   && !a.name.toLowerCase().includes(search.toLowerCase()) && !a.type.toLowerCase().includes(search.toLowerCase())) return false
    if (provider !== 'All Providers' && a.provider     !== provider) return false
    if (risk     !== 'All Risk'      && a.risk         !== risk)     return false
    if (policy   !== 'All Coverage'  && a.policyStatus !== policy)   return false
    return true
  })

  // Phase 3 — Register Asset is now available on the agents tab too
  // (agents go through their own RegisterAgentPanel). The button gates
  // a separate panel per asset kind so the model + agent flows don't
  // bleed into each other.
  const canRegister = activeTab === 'models' || activeTab === 'agents'

  return (
    <PageContainer>

      <PageHeader
        title="Inventory"
        subtitle="Discover and inspect AI assets, tools, and context sources across all environments"
        actions={
          <>
            <Button variant="outline" size="sm">Export</Button>
            <Button
              size="sm"
              onClick={() => canRegister && setShowRegister(v => !v)}
              disabled={!canRegister}
              title={
                canRegister
                  ? (activeTab === 'agents' ? 'Register a new agent (upload agent.py)' : 'Register a new model')
                  : 'Register Asset is only available on the Models and Agents tabs'
              }
            >
              + Register Asset
            </Button>
          </>
        }
      />

      {/* Summary strip — reflects whatever the Models tab currently shows (live + mock) */}
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

        {/* Table + (preview | register) side panel */}
        <div className="relative flex items-stretch divide-x divide-gray-100">

          <div className="flex-1 min-w-0 overflow-x-auto">
            {view === 'table'
              ? <AssetTable
                  assets={filtered}
                  selectedId={selected?.id}
                  onSelect={(asset) => {
                    // Reverted to the original behaviour for ALL asset
                    // types: single-click toggles the inline
                    // PreviewPanel via URL state. The AgentDetailDrawer
                    // built in Phase 3 is left in the codebase but no
                    // longer triggered from row clicks — bring it back
                    // selectively (e.g. via a "View details" right-
                    // click item) when the design lands.
                    if (asset?.id === assetId) {
                      navigate('/admin/inventory', { replace: true })
                    } else {
                      navigate(`/admin/inventory/${asset.id}`, { replace: true })
                    }
                  }}
                />
              : <GraphView assets={filtered} />
            }
          </div>

          {/* Right-hand slot priority — only one panel renders at a
              time, all share the same 300px column dimensions:
                1. AgentChatPanel — if chat is open
                2. Register panel — agents (RegisterAgentPanel) or
                   models (RegisterAssetPanel)
                3. PreviewPanel — selected asset */}
          {chatAgent
            ? <AgentChatPanel
                open
                agent={{
                  // Map the inventory-shape row onto the fields the
                  // chat panel expects — id is the real backend id.
                  id:            chatAgent._backendId || chatAgent.id,
                  name:          chatAgent.name,
                  risk:          chatAgent.risk,
                  runtime_state: chatAgent.runtime_state || 'stopped',
                }}
                onClose={() => setChatAgent(null)}
              />
            : showRegister && canRegister && activeTab === 'agents'
              ? <RegisterAgentPanel
                  onClose={() => setShowRegister(false)}
                  ownerOptions={ownerOptions}
                  onRegistered={async () => {
                    // Pull the live agents poll forward so the new row
                    // shows up immediately instead of waiting 5s.
                    if (refreshAgents) await refreshAgents()
                    setShowRegister(false)
                  }}
                />
              : showRegister && canRegister && activeTab === 'models'
                ? <RegisterAssetPanel
                    onClose={() => setShowRegister(false)}
                    onRegistered={{
                      ownerOptions,
                      onCreated: async () => {
                        // Refresh live list so the new row appears at the top
                        await reloadLiveModels()
                      },
                    }}
                  />
                : selected && (
                    <PreviewPanel
                      asset={selected}
                      onClose={() => navigate('/admin/inventory', { replace: true })}
                      onOpenChat={(agent) => setChatAgent(agent)}
                      onDeleted={async () => {
                        try {
                          if (refreshAgents) await refreshAgents()
                        } catch { /* swallow — navigate anyway */ }
                        navigate('/admin/inventory', { replace: true })
                      }}
                    />
                  )
          }

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
