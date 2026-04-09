import { useState } from 'react'
import {
  Search, X, Plus, Download, Bookmark,
  User, Bot, KeyRound, ShieldCheck, ShieldAlert,
  Fingerprint, Link, Activity, AlertTriangle, CheckCircle2,
  Filter, ChevronDown, ChevronRight,
  Clock, Eye, Ban, Zap, Database, Cpu, Lock,
  ArrowUpRight, ArrowDownRight, Minus,
  RefreshCw, ExternalLink, GitBranch,
  Wrench, Network, Shield, RotateCcw,
  FileText, Layers, Settings,
  TrendingDown, TrendingUp,
  Users, Info, ShieldOff, Siren,
  ArrowRight,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'

// ── Design tokens ──────────────────────────────────────────────────────────────

const ID_TYPE_CFG = {
  'Human User':           { icon: User,    color: 'text-blue-600',   bg: 'bg-blue-50',    border: 'border-blue-200',   bdr: 'border-l-blue-400'    },
  'Agent':                { icon: Bot,     color: 'text-violet-600', bg: 'bg-violet-50',  border: 'border-violet-200', bdr: 'border-l-violet-400'  },
  'Service Account':      { icon: Shield,  color: 'text-cyan-600',   bg: 'bg-cyan-50',    border: 'border-cyan-200',   bdr: 'border-l-cyan-400'    },
  'API Key':              { icon: KeyRound,color: 'text-amber-600',  bg: 'bg-amber-50',   border: 'border-amber-200',  bdr: 'border-l-amber-400'   },
  'Tool Principal':       { icon: Wrench,  color: 'text-emerald-600',bg: 'bg-emerald-50', border: 'border-emerald-200',bdr: 'border-l-emerald-400' },
  'Integration Identity': { icon: Network, color: 'text-indigo-600', bg: 'bg-indigo-50',  border: 'border-indigo-200', bdr: 'border-l-indigo-400'  },
}

const ID_STATUS_CFG = {
  Active:      { dot: 'bg-emerald-400', text: 'text-emerald-700', bg: 'bg-emerald-50',  border: 'border-emerald-200', bdr: 'border-l-emerald-400' },
  Suspicious:  { dot: 'bg-orange-500',  text: 'text-orange-700',  bg: 'bg-orange-50',   border: 'border-orange-200',  bdr: 'border-l-orange-400'  },
  Disabled:    { dot: 'bg-gray-300',    text: 'text-gray-500',    bg: 'bg-gray-100',    border: 'border-gray-200',    bdr: 'border-l-gray-200'    },
  Expired:     { dot: 'bg-gray-400',    text: 'text-gray-500',    bg: 'bg-gray-100',    border: 'border-gray-200',    bdr: 'border-l-gray-300'    },
  Quarantined: { dot: 'bg-red-500',     text: 'text-red-700',     bg: 'bg-red-50',      border: 'border-red-200',     bdr: 'border-l-red-500'     },
}

const FLAG_CFG = {
  'Elevated Access':     { color: 'text-orange-700', bg: 'bg-orange-50',  border: 'border-orange-200' },
  'Delegated':           { color: 'text-blue-700',   bg: 'bg-blue-50',    border: 'border-blue-200'   },
  'Unused Credential':   { color: 'text-gray-600',   bg: 'bg-gray-100',   border: 'border-gray-200'   },
  'Risk Spike':          { color: 'text-red-700',    bg: 'bg-red-50',     border: 'border-red-200'    },
  'Cross-Tenant Access': { color: 'text-violet-700', bg: 'bg-violet-50',  border: 'border-violet-200' },
  'Policy Violation':    { color: 'text-red-700',    bg: 'bg-red-50',     border: 'border-red-200'    },
  'Expired':             { color: 'text-gray-500',   bg: 'bg-gray-100',   border: 'border-gray-200'   },
}

const TRUST_CFG = {
  Trusted: { label: 'Trusted', color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', bar: 'bg-emerald-400', bdr: 'border-l-emerald-400' },
  Watch:   { label: 'Watch',   color: 'text-yellow-600',  bg: 'bg-yellow-50',  border: 'border-yellow-200',  bar: 'bg-yellow-400',  bdr: 'border-l-yellow-400'  },
  Risky:   { label: 'Risky',   color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200',     bar: 'bg-red-500',     bdr: 'border-l-red-500'     },
}

const SIGNAL_CFG = {
  High:   { dot: 'bg-red-500',     pill: 'text-red-700 bg-red-50 border-red-100',         bdr: 'border-l-red-500',     dotBg: 'bg-red-100'     },
  Medium: { dot: 'bg-yellow-400',  pill: 'text-yellow-700 bg-yellow-50 border-yellow-100', bdr: 'border-l-yellow-400',  dotBg: 'bg-yellow-100'  },
  Low:    { dot: 'bg-blue-400',    pill: 'text-blue-700 bg-blue-50 border-blue-100',       bdr: 'border-l-blue-400',    dotBg: 'bg-blue-100'    },
  Ok:     { dot: 'bg-emerald-400', pill: 'text-emerald-700 bg-emerald-50 border-emerald-100', bdr: 'border-l-emerald-400', dotBg: 'bg-emerald-100' },
}

const SESSION_OUTCOME_CFG = {
  Success: { dot: 'bg-emerald-400', text: 'text-emerald-700 bg-emerald-50 border-emerald-100', bdrL: 'border-l-emerald-400' },
  Blocked: { dot: 'bg-red-500',     text: 'text-red-700 bg-red-50 border-red-100',             bdrL: 'border-l-red-500'     },
  Warning: { dot: 'bg-yellow-400',  text: 'text-yellow-700 bg-yellow-50 border-yellow-100',    bdrL: 'border-l-yellow-400'  },
}

const EVENT_IMPACT_CFG = {
  High:   { dot: 'bg-red-500',     pill: 'text-red-700 bg-red-50 border-red-100',         bdr: 'border-l-red-500'    },
  Medium: { dot: 'bg-yellow-400',  pill: 'text-yellow-700 bg-yellow-50 border-yellow-100', bdr: 'border-l-yellow-400' },
  Low:    { dot: 'bg-blue-400',    pill: 'text-blue-700 bg-blue-50 border-blue-100',       bdr: 'border-l-blue-400'   },
}

const EVENT_RESULT_CFG = {
  Detected: 'text-red-600 bg-red-50 border-red-100',
  Warning:  'text-yellow-700 bg-yellow-50 border-yellow-100',
  Info:     'text-blue-700 bg-blue-50 border-blue-100',
  Resolved: 'text-emerald-700 bg-emerald-50 border-emerald-100',
}

const CHAIN_NODE_TYPE = {
  'Human User':           { color: 'text-blue-600',    bg: 'bg-blue-50',    border: 'border-blue-200',    icon: User    },
  'Agent':                { color: 'text-violet-600',  bg: 'bg-violet-50',  border: 'border-violet-200',  icon: Bot     },
  'Service Account':      { color: 'text-cyan-600',    bg: 'bg-cyan-50',    border: 'border-cyan-200',    icon: Shield  },
  'API Key':              { color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200',   icon: KeyRound},
  'Tool Principal':       { color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', icon: Wrench  },
  'Integration Identity': { color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200',  icon: Network },
  'Data Source':          { color: 'text-gray-600',    bg: 'bg-gray-100',   border: 'border-gray-200',    icon: Database},
  'Model':                { color: 'text-violet-600',  bg: 'bg-violet-50',  border: 'border-violet-200',  icon: Cpu     },
}

function getTrustTier(score) {
  if (score >= 80) return 'Trusted'
  if (score >= 60) return 'Watch'
  return 'Risky'
}

// ── Mock data ──────────────────────────────────────────────────────────────────

const MOCK_IDENTITIES = [
  // ── Human Users ──
  {
    id: 'id-005', name: 'sarah.chen', displayName: 'Sarah Chen',
    type: 'Human User', trustScore: 94, trustTrend: 'stable', status: 'Active', flags: [],
    owner: 'sarah.chen', ownerDisplay: 'Sarah Chen',
    environment: 'Production', tenant: 'core-platform', authMethod: 'SSO + MFA',
    createdAt: 'Sep 1, 2025', lastActivity: '5m ago', lastActivityFull: 'Apr 8 · 14:27 UTC',
    description: 'Senior Security Engineer. Manages threat-hunter-agent, Splunk and Sentinel integrations, and case escalation workflows. Fully MFA-enrolled with clean access history.',
    scopes: ['agents:manage', 'alerts:admin', 'integrations:manage', 'cases:admin'],
    elevatedRoles: ['security-engineer'], linkedTools: [], linkedModels: [],
    linkedDataSources: [], delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 96, accessHygiene: 94, anomaly: 95, policyAdherence: 92 },
    trustSignals: [
      { ts: 'Apr 8 · 08:00 UTC', signal: 'Login from new device — MacBook Pro M3', severity: 'Low', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7822', action: 'integrations:manage Splunk', ts: 'Apr 8 · 14:27', outcome: 'Success' },
      { id: 'SID-7817', action: 'cases:admin CASE-1051', ts: 'Apr 8 · 11:00', outcome: 'Success' },
    ],
    linkedAlerts: 0, linkedCases: 0,
    delegationChain: [{ label: 'sarah.chen', type: 'Human User' }],
    credential: { type: 'SSO (Okta)', age: 'N/A', lastRotated: 'Apr 1, 2026', expires: 'Session-based', mfa: 'TOTP + Hardware key', approvalPath: 'Manager approval for elevated ops' },
    recommendedActions: [],
  },
  {
    id: 'id-009', name: 'raj.patel', displayName: 'Raj Patel',
    type: 'Human User', trustScore: 87, trustTrend: 'stable', status: 'Active', flags: ['Delegated'],
    owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Production', tenant: 'core-platform', authMethod: 'SSO + MFA',
    createdAt: 'Aug 15, 2025', lastActivity: '18m ago', lastActivityFull: 'Apr 8 · 14:14 UTC',
    description: 'Principal ML Engineer. Manages AI provider integrations, agent lifecycle, and model governance. Has delegated model:admin to lim-agent-prod for operational automation.',
    scopes: ['agents:admin', 'models:admin', 'integrations:manage', 'policies:read'],
    elevatedRoles: ['ml-engineer', 'model-admin'], linkedTools: [],
    linkedModels: ['gpt-4o', 'claude-3-5-sonnet', 'amazon-bedrock'],
    linkedDataSources: [], delegatedFrom: null,
    delegatedPermissions: ['model:admin → lim-agent-prod'],
    trustBreakdown: { behavior: 88, accessHygiene: 87, anomaly: 86, policyAdherence: 88 },
    trustSignals: [
      { ts: 'Apr 8 · 10:00 UTC', signal: 'Delegated model:admin permission to lim-agent-prod', severity: 'Medium', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7813', action: 'models:admin config update', ts: 'Apr 8 · 14:14', outcome: 'Success' },
      { id: 'SID-7809', action: 'integrations:manage OpenAI', ts: 'Apr 8 · 10:00', outcome: 'Success' },
    ],
    linkedAlerts: 0, linkedCases: 0,
    delegationChain: [
      { label: 'raj.patel', type: 'Human User' },
      { label: 'lim-agent-prod', type: 'Agent' },
      { label: 'code-exec-tool', type: 'Tool Principal' },
    ],
    credential: { type: 'SSO (Okta)', age: 'N/A', lastRotated: 'Apr 1, 2026', expires: 'Session-based', mfa: 'TOTP enrolled', approvalPath: 'Director approval for model:admin' },
    recommendedActions: ['Review delegation to lim-agent-prod — elevated scope'],
  },
  // ── Agents ──
  {
    id: 'id-001', name: 'lim-agent-prod', displayName: 'LIM Agent (Production)',
    type: 'Agent', trustScore: 71, trustTrend: 'down', status: 'Active', flags: ['Delegated', 'Elevated Access'],
    owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Production', tenant: 'core-platform', authMethod: 'Service Token',
    createdAt: 'Jan 15, 2026', lastActivity: '3m ago', lastActivityFull: 'Apr 8 · 14:29 UTC',
    description: 'Production LLM inference management agent. Handles model routing, rate limiting, and session context. Elevated access granted for cross-tenant model switching.',
    scopes: ['model:invoke', 'session:read', 'session:write', 'config:read'],
    elevatedRoles: ['cross-tenant-model-router'],
    linkedTools: ['code-exec-tool', 'rag-retrieval-tool'],
    linkedModels: ['gpt-4o', 'claude-3-5-sonnet', 'amazon-bedrock'],
    linkedDataSources: ['customer-knowledge-base', 'policy-store'],
    delegatedFrom: 'raj.patel', delegatedPermissions: ['model:admin', 'session:delete'],
    trustBreakdown: { behavior: 74, accessHygiene: 65, anomaly: 72, policyAdherence: 70 },
    trustSignals: [
      { ts: 'Apr 8 · 14:10 UTC', signal: 'New tool invocation pattern — code-exec-tool called 12x in 5m', severity: 'Medium', resolved: false },
      { ts: 'Apr 7 · 22:00 UTC', signal: 'Cross-tenant model switch detected — staging → production', severity: 'High', resolved: false },
      { ts: 'Apr 6 · 18:00 UTC', signal: 'Delegated permission used — session:delete', severity: 'Medium', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7821', action: 'model:invoke gpt-4o', ts: 'Apr 8 · 14:29', outcome: 'Success' },
      { id: 'SID-7820', action: 'tool:invoke code-exec-tool', ts: 'Apr 8 · 14:28', outcome: 'Success' },
      { id: 'SID-7815', action: 'model:invoke claude-3-5-sonnet', ts: 'Apr 8 · 14:10', outcome: 'Blocked' },
      { id: 'SID-7811', action: 'session:delete (delegated)', ts: 'Apr 7 · 22:00', outcome: 'Success' },
    ],
    linkedAlerts: 3, linkedCases: 1,
    delegationChain: [
      { label: 'raj.patel', type: 'Human User' },
      { label: 'lim-agent-prod', type: 'Agent' },
      { label: 'code-exec-tool', type: 'Tool Principal' },
      { label: 'customer-knowledge-base', type: 'Data Source' },
    ],
    credential: { type: 'Service Token', age: '48d', lastRotated: 'Feb 20, 2026', expires: 'Jun 20, 2026', mfa: null, approvalPath: 'Auto-approved by policy' },
    recommendedActions: ['Reduce tool invocation rate limit', 'Review cross-tenant model access', 'Rotate service token (48d old)'],
  },
  {
    id: 'id-002', name: 'threat-hunter-agent', displayName: 'Threat Hunter Agent',
    type: 'Agent', trustScore: 88, trustTrend: 'up', status: 'Active', flags: [],
    owner: 'sarah.chen', ownerDisplay: 'Sarah Chen',
    environment: 'Production', tenant: 'security-ops', authMethod: 'OAuth',
    createdAt: 'Feb 1, 2026', lastActivity: '12m ago', lastActivityFull: 'Apr 8 · 14:20 UTC',
    description: 'Security analysis agent for threat hunting across logs, alerts, and behavioral data. Runs on isolated compute with restricted data access.',
    scopes: ['alerts:read', 'logs:read', 'cases:write', 'runtime:read'],
    elevatedRoles: [], linkedTools: ['rag-retrieval-tool'],
    linkedModels: ['claude-3-5-sonnet'],
    linkedDataSources: ['splunk-log-store', 'alert-index'],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 90, accessHygiene: 88, anomaly: 85, policyAdherence: 91 },
    trustSignals: [
      { ts: 'Apr 8 · 08:00 UTC', signal: 'Daily health check passed — no anomalies', severity: 'Ok', resolved: true },
      { ts: 'Apr 6 · 14:00 UTC', signal: 'New alert pattern processed successfully', severity: 'Ok', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7819', action: 'logs:read (Splunk query)', ts: 'Apr 8 · 14:20', outcome: 'Success' },
      { id: 'SID-7812', action: 'cases:write CASE-1051', ts: 'Apr 8 · 10:00', outcome: 'Success' },
    ],
    linkedAlerts: 0, linkedCases: 2,
    delegationChain: [
      { label: 'sarah.chen', type: 'Human User' },
      { label: 'threat-hunter-agent', type: 'Agent' },
      { label: 'rag-retrieval-tool', type: 'Tool Principal' },
      { label: 'splunk-log-store', type: 'Data Source' },
    ],
    credential: { type: 'OAuth Token', age: '8d', lastRotated: 'Mar 31, 2026', expires: 'Auto-renews', mfa: null, approvalPath: 'Security team approval required' },
    recommendedActions: [],
  },
  {
    id: 'id-010', name: 'compliance-agent', displayName: 'Compliance Agent',
    type: 'Agent', trustScore: 62, trustTrend: 'down', status: 'Active', flags: ['Policy Violation'],
    owner: 'sarah.chen', ownerDisplay: 'Sarah Chen',
    environment: 'Production', tenant: 'compliance', authMethod: 'Service Token',
    createdAt: 'Mar 10, 2026', lastActivity: '45m ago', lastActivityFull: 'Apr 8 · 13:47 UTC',
    description: 'Automated compliance checking agent. Reviews policy adherence for runtime agents and generates audit reports. Recently violated output-filtering policy on 3 consecutive sessions.',
    scopes: ['policies:read', 'reports:write', 'runtime:read', 'audit:write'],
    elevatedRoles: [], linkedTools: [], linkedModels: ['claude-3-5-sonnet'],
    linkedDataSources: ['audit-store', 'policy-store'],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 58, accessHygiene: 72, anomaly: 60, policyAdherence: 52 },
    trustSignals: [
      { ts: 'Apr 8 · 13:47 UTC', signal: 'Output-filter policy violation — 3rd consecutive session', severity: 'High', resolved: false },
      { ts: 'Apr 8 · 11:00 UTC', signal: 'Policy violation — unauthorized audit:write path', severity: 'Medium', resolved: false },
      { ts: 'Apr 7 · 18:00 UTC', signal: 'Trust score declined 12 points over 7 days', severity: 'Medium', resolved: false },
    ],
    recentSessions: [
      { id: 'SID-7806', action: 'runtime:read (compliance scan)', ts: 'Apr 8 · 13:47', outcome: 'Blocked' },
      { id: 'SID-7805', action: 'audit:write (policy report)', ts: 'Apr 8 · 11:00', outcome: 'Blocked' },
      { id: 'SID-7801', action: 'policies:read (config fetch)', ts: 'Apr 8 · 09:00', outcome: 'Success' },
    ],
    linkedAlerts: 3, linkedCases: 1,
    delegationChain: [
      { label: 'sarah.chen', type: 'Human User' },
      { label: 'compliance-agent', type: 'Agent' },
      { label: 'policy-store', type: 'Data Source' },
    ],
    credential: { type: 'Service Token', age: '29d', lastRotated: 'Mar 10, 2026', expires: 'Jun 10, 2026', mfa: null, approvalPath: 'Security team approval' },
    recommendedActions: ['Investigate output-filter bypass attempts', 'Restrict audit:write path', 'Increase monitoring frequency'],
  },
  {
    id: 'id-007', name: 'data-pipeline-agent', displayName: 'Data Pipeline Agent',
    type: 'Agent', trustScore: 76, trustTrend: 'stable', status: 'Active', flags: ['Cross-Tenant Access'],
    owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', tenant: 'data-platform', authMethod: 'IAM Role',
    createdAt: 'Feb 15, 2026', lastActivity: '21m ago', lastActivityFull: 'Apr 8 · 14:11 UTC',
    description: 'Orchestration agent for AI data pipelines. Reads from S3, writes to vector store, and syncs with Confluence knowledge base. Cross-tenant access is intentional but flagged for review.',
    scopes: ['s3:read', 'vectorstore:write', 'confluence:read', 'pipeline:manage'],
    elevatedRoles: [], linkedTools: ['rag-retrieval-tool'],
    linkedModels: ['amazon-bedrock'],
    linkedDataSources: ['s3-evidence-bucket', 'confluence-kb', 'vector-store'],
    delegatedFrom: 'mike.torres', delegatedPermissions: ['cross-tenant:data-platform→finance'],
    trustBreakdown: { behavior: 78, accessHygiene: 75, anomaly: 76, policyAdherence: 74 },
    trustSignals: [
      { ts: 'Apr 8 · 12:00 UTC', signal: 'Cross-tenant read — data-platform → finance namespace', severity: 'Medium', resolved: false },
      { ts: 'Apr 7 · 18:00 UTC', signal: 'Vector store write volume 2x baseline', severity: 'Low', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7816', action: 's3:read evidence archive', ts: 'Apr 8 · 14:11', outcome: 'Success' },
      { id: 'SID-7814', action: 'confluence:read page sync', ts: 'Apr 8 · 12:00', outcome: 'Success' },
    ],
    linkedAlerts: 1, linkedCases: 0,
    delegationChain: [
      { label: 'mike.torres', type: 'Human User' },
      { label: 'data-pipeline-agent', type: 'Agent' },
      { label: 'rag-retrieval-tool', type: 'Tool Principal' },
      { label: 'vector-store', type: 'Data Source' },
    ],
    credential: { type: 'IAM Role', age: 'N/A', lastRotated: 'Auto-rotated', expires: 'Auto-renews', mfa: null, approvalPath: 'IAM policy — auto-approved' },
    recommendedActions: ['Review cross-tenant delegation scope', 'Add audit logging for cross-tenant reads'],
  },
  // ── Service Accounts ──
  {
    id: 'id-003', name: 'finance-ops-service', displayName: 'Finance Ops Service Account',
    type: 'Service Account', trustScore: 42, trustTrend: 'down', status: 'Suspicious', flags: ['Elevated Access', 'Unused Credential', 'Risk Spike'],
    owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', tenant: 'finance', authMethod: 'API Key',
    createdAt: 'Nov 5, 2025', lastActivity: '6h ago', lastActivityFull: 'Apr 8 · 08:15 UTC',
    description: 'Finance data pipeline service account. Granted elevated database read access for reporting. Credential has not been rotated in 152 days. Recent spike in unusual query patterns flagged.',
    scopes: ['db:read', 'db:admin', 'reports:write', 'export:all'],
    elevatedRoles: ['db-admin-readonly', 'finance-exporter'], linkedTools: [], linkedModels: [],
    linkedDataSources: ['finance-db', 'audit-store'],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 38, accessHygiene: 22, anomaly: 55, policyAdherence: 48 },
    trustSignals: [
      { ts: 'Apr 8 · 08:15 UTC', signal: 'Unusual export volume — 14x baseline in 1h', severity: 'High', resolved: false },
      { ts: 'Apr 7 · 23:00 UTC', signal: 'Credential not rotated — 152 days old', severity: 'High', resolved: false },
      { ts: 'Apr 7 · 12:00 UTC', signal: 'db:admin scope used — not in approved workflow', severity: 'High', resolved: false },
      { ts: 'Apr 5 · 10:00 UTC', signal: 'Access from new IP range — 203.0.113.0/24', severity: 'Medium', resolved: false },
    ],
    recentSessions: [
      { id: 'SID-7810', action: 'db:read (bulk export)', ts: 'Apr 8 · 08:15', outcome: 'Success' },
      { id: 'SID-7800', action: 'db:admin (schema query)', ts: 'Apr 8 · 07:00', outcome: 'Success' },
      { id: 'SID-7795', action: 'export:all (finance-db)', ts: 'Apr 7 · 23:00', outcome: 'Blocked' },
    ],
    linkedAlerts: 5, linkedCases: 2,
    delegationChain: [
      { label: 'finance-ops-service', type: 'Service Account' },
      { label: 'finance-db', type: 'Data Source' },
    ],
    credential: { type: 'API Key', age: '152d', lastRotated: 'Nov 7, 2025', expires: 'Never', mfa: null, approvalPath: 'None configured' },
    recommendedActions: ['Rotate API key immediately', 'Revoke db:admin scope', 'Enable approval path for exports', 'Add IP allowlist'],
  },
  {
    id: 'id-012', name: 'sentinel-sync-svc', displayName: 'Sentinel Sync Service',
    type: 'Service Account', trustScore: 78, trustTrend: 'stable', status: 'Active', flags: ['Cross-Tenant Access'],
    owner: 'sarah.chen', ownerDisplay: 'Sarah Chen',
    environment: 'Production', tenant: 'security-ops', authMethod: 'Service Account',
    createdAt: 'Feb 10, 2026', lastActivity: '18m ago', lastActivityFull: 'Apr 8 · 14:14 UTC',
    description: 'Microsoft Sentinel sync service. Forwards AI security events to the Sentinel SIEM workspace. Cross-tenant read access required for multi-tenant alert ingestion.',
    scopes: ['SecurityInsights/alertRules/write', 'SecurityInsights/incidents/read'],
    elevatedRoles: [], linkedTools: [], linkedModels: [],
    linkedDataSources: ['sentinel-workspace'],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 80, accessHygiene: 78, anomaly: 79, policyAdherence: 76 },
    trustSignals: [
      { ts: 'Apr 7 · 22:15 UTC', signal: 'Cross-tenant alert ingestion from compliance tenant', severity: 'Low', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7811', action: 'SecurityInsights/incidents:read', ts: 'Apr 8 · 14:14', outcome: 'Success' },
    ],
    linkedAlerts: 0, linkedCases: 0,
    delegationChain: [
      { label: 'sentinel-sync-svc', type: 'Service Account' },
      { label: 'sentinel-workspace', type: 'Data Source' },
    ],
    credential: { type: 'Service Principal', age: '57d', lastRotated: 'Auto-renewed', expires: 'Auto-renews', mfa: null, approvalPath: 'Security team approval' },
    recommendedActions: [],
  },
  {
    id: 'id-014', name: 'bedrock-runtime-svc', displayName: 'Bedrock Runtime Service',
    type: 'Service Account', trustScore: 90, trustTrend: 'stable', status: 'Active', flags: [],
    owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', tenant: 'core-platform', authMethod: 'IAM Role',
    createdAt: 'Jan 20, 2026', lastActivity: '6m ago', lastActivityFull: 'Apr 8 · 14:26 UTC',
    description: 'AWS Bedrock inference service account. Operates under least-privilege IAM policy with SCP guardrails. Handles Titan Embeddings and Claude 3 invocations for the platform.',
    scopes: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream', 'bedrock:ListFoundationModels'],
    elevatedRoles: [], linkedTools: [],
    linkedModels: ['claude-bedrock', 'titan-embeddings'], linkedDataSources: [],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 92, accessHygiene: 91, anomaly: 88, policyAdherence: 90 },
    trustSignals: [
      { ts: 'Apr 8 · 14:00 UTC', signal: 'IAM health check passed', severity: 'Ok', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7824', action: 'bedrock:InvokeModel claude-3', ts: 'Apr 8 · 14:26', outcome: 'Success' },
    ],
    linkedAlerts: 0, linkedCases: 0,
    delegationChain: [
      { label: 'bedrock-runtime-svc', type: 'Service Account' },
      { label: 'claude-bedrock', type: 'Model' },
    ],
    credential: { type: 'IAM Role', age: 'N/A', lastRotated: 'Auto-rotated', expires: 'Auto-renews', mfa: null, approvalPath: 'AWS SCP policy' },
    recommendedActions: [],
  },
  // ── API Keys ──
  {
    id: 'id-006', name: 'customer-analytics-key', displayName: 'Customer Analytics API Key',
    type: 'API Key', trustScore: 55, trustTrend: 'down', status: 'Suspicious', flags: ['Unused Credential', 'Risk Spike'],
    owner: 'alex.kim', ownerDisplay: 'Alex Kim',
    environment: 'Production', tenant: 'analytics', authMethod: 'API Key',
    createdAt: 'Oct 12, 2025', lastActivity: '14d ago', lastActivityFull: 'Mar 25 · 09:00 UTC',
    description: 'API key for customer analytics pipeline. Unused for 14 days. Sudden burst of 340 requests from an unrecognized IP on Mar 25, then complete silence.',
    scopes: ['analytics:read', 'analytics:write', 'export:customers'],
    elevatedRoles: [], linkedTools: [], linkedModels: [],
    linkedDataSources: ['customer-db', 'analytics-store'],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 48, accessHygiene: 35, anomaly: 62, policyAdherence: 70 },
    trustSignals: [
      { ts: 'Mar 25 · 09:00 UTC', signal: 'Burst of 340 requests from unrecognized IP 198.51.100.14', severity: 'High', resolved: false },
      { ts: 'Mar 20 · 00:00 UTC', signal: 'Credential unused for 30+ consecutive days', severity: 'Medium', resolved: false },
      { ts: 'Nov 1 · 00:00 UTC', signal: 'Credential not rotated — 178 days old', severity: 'High', resolved: false },
    ],
    recentSessions: [
      { id: 'SID-7640', action: 'analytics:read (bulk — 340 requests)', ts: 'Mar 25 · 09:00', outcome: 'Success' },
      { id: 'SID-7639', action: 'export:customers', ts: 'Mar 25 · 09:01', outcome: 'Blocked' },
    ],
    linkedAlerts: 4, linkedCases: 1,
    delegationChain: [
      { label: 'alex.kim', type: 'Human User' },
      { label: 'customer-analytics-key', type: 'API Key' },
      { label: 'customer-db', type: 'Data Source' },
    ],
    credential: { type: 'API Key', age: '178d', lastRotated: 'Oct 13, 2025', expires: 'Never', mfa: null, approvalPath: 'None configured' },
    recommendedActions: ['Revoke key — suspicious activity detected', 'Issue new key with stricter scope', 'Add IP allowlist', 'Configure approval path'],
  },
  {
    id: 'id-011', name: 'prod-api-key-01', displayName: 'Production API Key #01',
    type: 'API Key', trustScore: 38, trustTrend: 'down', status: 'Expired', flags: ['Unused Credential', 'Expired'],
    owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', tenant: 'core-platform', authMethod: 'API Key',
    createdAt: 'Jul 1, 2025', lastActivity: '32d ago', lastActivityFull: 'Mar 7 · 00:00 UTC',
    description: 'Legacy production API key from the initial platform deployment. Expired Mar 8. Used for external webhook callbacks, now superseded by service account tokens.',
    scopes: ['webhooks:receive', 'events:write'],
    elevatedRoles: [], linkedTools: [], linkedModels: [], linkedDataSources: [],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 40, accessHygiene: 15, anomaly: 50, policyAdherence: 42 },
    trustSignals: [
      { ts: 'Mar 8 · 00:00 UTC', signal: 'API key expired — no rotation scheduled', severity: 'High', resolved: false },
      { ts: 'Feb 15 · 00:00 UTC', signal: 'Credential unused for 30 days prior to expiry', severity: 'Medium', resolved: false },
    ],
    recentSessions: [
      { id: 'SID-7640', action: 'webhooks:receive (last use)', ts: 'Mar 7 · 00:00', outcome: 'Success' },
    ],
    linkedAlerts: 2, linkedCases: 0,
    delegationChain: [{ label: 'prod-api-key-01', type: 'API Key' }],
    credential: { type: 'API Key', age: '281d', lastRotated: 'Never', expires: 'Expired Mar 8, 2026', mfa: null, approvalPath: 'None configured' },
    recommendedActions: ['Delete expired credential immediately', 'Audit all references to this key', 'Document replacement (service account token)'],
  },
  // ── Tool Principals ──
  {
    id: 'id-008', name: 'rag-retrieval-tool', displayName: 'RAG Retrieval Tool',
    type: 'Tool Principal', trustScore: 89, trustTrend: 'stable', status: 'Active', flags: [],
    owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Production', tenant: 'core-platform', authMethod: 'Service Token',
    createdAt: 'Jan 20, 2026', lastActivity: '2m ago', lastActivityFull: 'Apr 8 · 14:30 UTC',
    description: 'Vector search and retrieval tool. Invoked by multiple agents for knowledge base lookups. Access is strictly read-only across all configured data sources.',
    scopes: ['vectorstore:read', 'confluence:read', 's3:read'],
    elevatedRoles: [], linkedTools: [],
    linkedModels: ['amazon-bedrock', 'openai-embeddings'],
    linkedDataSources: ['vector-store', 'confluence-kb', 's3-evidence-bucket'],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 91, accessHygiene: 88, anomaly: 90, policyAdherence: 87 },
    trustSignals: [
      { ts: 'Apr 8 · 14:00 UTC', signal: 'Health check passed — all data sources reachable', severity: 'Ok', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7823', action: 'vectorstore:read (lim-agent-prod)', ts: 'Apr 8 · 14:30', outcome: 'Success' },
      { id: 'SID-7820', action: 'vectorstore:read (threat-hunter)', ts: 'Apr 8 · 14:28', outcome: 'Success' },
    ],
    linkedAlerts: 0, linkedCases: 0,
    delegationChain: [
      { label: 'rag-retrieval-tool', type: 'Tool Principal' },
      { label: 'vector-store', type: 'Data Source' },
    ],
    credential: { type: 'Service Token', age: '25d', lastRotated: 'Mar 14, 2026', expires: 'Jun 14, 2026', mfa: null, approvalPath: 'Auto-approved by policy' },
    recommendedActions: [],
  },
  {
    id: 'id-013', name: 'code-exec-tool', displayName: 'Code Execution Tool',
    type: 'Tool Principal', trustScore: 51, trustTrend: 'down', status: 'Suspicious', flags: ['Elevated Access', 'Risk Spike'],
    owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Production', tenant: 'core-platform', authMethod: 'Service Token',
    createdAt: 'Mar 5, 2026', lastActivity: '3m ago', lastActivityFull: 'Apr 8 · 14:29 UTC',
    description: 'Code execution sandbox tool. Invoked by lim-agent-prod for dynamic code evaluation. Spike of 12 invocations in 5 minutes triggered a risk alert. Elevated network access not in original scope.',
    scopes: ['exec:code', 'network:egress', 'fs:read', 'fs:write'],
    elevatedRoles: ['network-egress-allowed'], linkedTools: [], linkedModels: [], linkedDataSources: [],
    delegatedFrom: 'lim-agent-prod', delegatedPermissions: ['network:egress'],
    trustBreakdown: { behavior: 44, accessHygiene: 52, anomaly: 58, policyAdherence: 48 },
    trustSignals: [
      { ts: 'Apr 8 · 14:10 UTC', signal: '12 invocations in 5 minutes — rate limit exceeded', severity: 'High', resolved: false },
      { ts: 'Apr 8 · 13:00 UTC', signal: 'Network egress to unrecognized endpoint 93.184.216.34', severity: 'High', resolved: false },
      { ts: 'Apr 7 · 10:00 UTC', signal: 'fs:write outside approved sandbox path', severity: 'Medium', resolved: false },
    ],
    recentSessions: [
      { id: 'SID-7821', action: 'exec:code (from lim-agent-prod)', ts: 'Apr 8 · 14:29', outcome: 'Success' },
      { id: 'SID-7819', action: 'network:egress (outbound HTTP)', ts: 'Apr 8 · 14:28', outcome: 'Blocked' },
      { id: 'SID-7818', action: 'fs:write (outside sandbox)', ts: 'Apr 7 · 10:00', outcome: 'Blocked' },
    ],
    linkedAlerts: 4, linkedCases: 2,
    delegationChain: [
      { label: 'lim-agent-prod', type: 'Agent' },
      { label: 'code-exec-tool', type: 'Tool Principal' },
    ],
    credential: { type: 'Service Token', age: '34d', lastRotated: 'Mar 5, 2026', expires: 'Jun 5, 2026', mfa: null, approvalPath: 'Agent delegation — auto-approved' },
    recommendedActions: ['Quarantine pending investigation', 'Revoke network:egress scope', 'Add strict rate limits', 'Audit delegation from lim-agent-prod'],
  },
  // ── Integration Identities ──
  {
    id: 'id-004', name: 'jira-sync-bot', displayName: 'Jira Sync Bot',
    type: 'Integration Identity', trustScore: 83, trustTrend: 'stable', status: 'Active', flags: [],
    owner: 'alex.kim', ownerDisplay: 'Alex Kim',
    environment: 'Production', tenant: 'core-platform', authMethod: 'API Key',
    createdAt: 'Jan 15, 2026', lastActivity: '8m ago', lastActivityFull: 'Apr 8 · 14:24 UTC',
    description: 'Atlassian Jira integration bot for bi-directional case sync. Operates within strict scope — ticket creation, status updates, and user assignment only.',
    scopes: ['read:jira-work', 'write:jira-work', 'read:jira-user'],
    elevatedRoles: [], linkedTools: [], linkedModels: [],
    linkedDataSources: ['jira-cloud'],
    delegatedFrom: 'alex.kim', delegatedPermissions: ['jira:admin-read'],
    trustBreakdown: { behavior: 85, accessHygiene: 82, anomaly: 88, policyAdherence: 84 },
    trustSignals: [
      { ts: 'Apr 8 · 08:00 UTC', signal: 'Daily sync completed — 3 cases updated', severity: 'Ok', resolved: true },
    ],
    recentSessions: [
      { id: 'SID-7818', action: 'write:jira-work AISPM-892', ts: 'Apr 8 · 14:24', outcome: 'Success' },
      { id: 'SID-7808', action: 'read:jira-user assignment', ts: 'Apr 8 · 08:00', outcome: 'Success' },
    ],
    linkedAlerts: 0, linkedCases: 3,
    delegationChain: [
      { label: 'alex.kim', type: 'Human User' },
      { label: 'jira-sync-bot', type: 'Integration Identity' },
      { label: 'jira-cloud', type: 'Data Source' },
    ],
    credential: { type: 'API Key', age: '15d', lastRotated: 'Mar 24, 2026', expires: 'Never', mfa: null, approvalPath: 'Team approval' },
    recommendedActions: [],
  },
  {
    id: 'id-015', name: 'okta-sync-user', displayName: 'Okta Sync Service User',
    type: 'Integration Identity', trustScore: 74, trustTrend: 'down', status: 'Active', flags: ['Cross-Tenant Access'],
    owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', tenant: 'identity', authMethod: 'OAuth',
    createdAt: 'Feb 20, 2026', lastActivity: '11m ago', lastActivityFull: 'Apr 8 · 14:21 UTC',
    description: 'Okta identity sync integration. Reads user profiles and group memberships for trust scoring. Missing groups:read scope causing partial sync failures and degraded trust data quality.',
    scopes: ['openid', 'profile', 'email', 'okta.users.read'],
    elevatedRoles: [], linkedTools: [], linkedModels: [],
    linkedDataSources: ['okta-directory'],
    delegatedFrom: null, delegatedPermissions: [],
    trustBreakdown: { behavior: 75, accessHygiene: 70, anomaly: 76, policyAdherence: 72 },
    trustSignals: [
      { ts: 'Apr 8 · 14:21 UTC', signal: 'Partial sync — groups:read scope missing', severity: 'Medium', resolved: false },
      { ts: 'Apr 6 · 10:00 UTC', signal: 'Trust score declined — degraded identity data', severity: 'Medium', resolved: false },
    ],
    recentSessions: [
      { id: 'SID-7815', action: 'okta.users.read (profile sync)', ts: 'Apr 8 · 14:21', outcome: 'Success' },
      { id: 'SID-7807', action: 'okta.groups.read (failed — 403)', ts: 'Apr 8 · 11:15', outcome: 'Blocked' },
    ],
    linkedAlerts: 1, linkedCases: 0,
    delegationChain: [
      { label: 'okta-sync-user', type: 'Integration Identity' },
      { label: 'okta-directory', type: 'Data Source' },
    ],
    credential: { type: 'OAuth Token', age: '47d', lastRotated: 'Feb 20, 2026', expires: 'Auto-refresh', mfa: null, approvalPath: 'Identity team approval' },
    recommendedActions: ['Grant groups:read scope', 'Review partial sync impact on trust scoring'],
  },
]

const MOCK_TRUST_EVENTS = [
  { id:1,  ts:'Apr 8 · 14:10 UTC', identity:'lim-agent-prod',       event:'Rate limit exceeded — code-exec-tool 12x in 5m',     impact:'High',   result:'Detected'  },
  { id:2,  ts:'Apr 8 · 13:47 UTC', identity:'compliance-agent',     event:'Output-filter policy violation — 3rd consecutive',   impact:'High',   result:'Detected'  },
  { id:3,  ts:'Apr 8 · 13:01 UTC', identity:'finance-ops-service',  event:'Unusual export volume — 14x baseline detected',      impact:'High',   result:'Detected'  },
  { id:4,  ts:'Apr 8 · 12:00 UTC', identity:'data-pipeline-agent',  event:'Cross-tenant read — data-platform → finance',        impact:'Medium', result:'Warning'   },
  { id:5,  ts:'Apr 8 · 11:15 UTC', identity:'okta-sync-user',       event:'groups:read scope missing — partial sync failed',    impact:'Medium', result:'Warning'   },
  { id:6,  ts:'Apr 8 · 08:00 UTC', identity:'bedrock-runtime-svc',  event:'IAM role validation passed — daily health check',    impact:'Low',    result:'Resolved'  },
  { id:7,  ts:'Apr 7 · 22:00 UTC', identity:'lim-agent-prod',       event:'Cross-tenant model switch — staging → production',   impact:'High',   result:'Detected'  },
  { id:8,  ts:'Apr 7 · 18:44 UTC', identity:'code-exec-tool',       event:'Network egress to unrecognized endpoint — blocked',  impact:'High',   result:'Detected'  },
  { id:9,  ts:'Apr 7 · 16:00 UTC', identity:'raj.patel',            event:'Delegated model:admin permission to lim-agent-prod', impact:'Medium', result:'Info'      },
  { id:10, ts:'Mar 25 · 09:00 UTC',identity:'customer-analytics-key',event:'Request burst — 340 calls from unrecognized IP',    impact:'High',   result:'Detected'  },
]

// ── Small primitives ───────────────────────────────────────────────────────────

function FilterSelect({ value, onChange, options }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className={cn(
          'h-8 pl-3 pr-8 text-[12px] font-medium text-gray-600 bg-white',
          'border border-gray-200 rounded-lg appearance-none cursor-pointer',
          'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400',
          'hover:border-gray-300 transition-colors',
        )}
      >
        {options.map(o => <option key={o}>{o}</option>)}
      </select>
      <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
    </div>
  )
}

function Toggle({ checked, onChange }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex w-9 h-5 rounded-full transition-colors duration-200 focus:outline-none shrink-0',
        'focus:ring-2 focus:ring-offset-1',
        checked
          ? 'bg-emerald-500 focus:ring-emerald-400/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]'
          : 'bg-gray-200 focus:ring-gray-300/40 shadow-[inset_0_1px_2px_rgba(0,0,0,0.10)]',
      )}
    >
      <span className={cn(
        'absolute top-[3px] left-[3px] w-[14px] h-[14px] rounded-full bg-white shadow-sm transition-transform duration-200',
        checked ? 'translate-x-[16px]' : 'translate-x-0',
      )} />
    </button>
  )
}

function OwnerAvatar({ name, size = 'sm' }) {
  const parts   = name.split('.')
  const initials = parts.map(p => p[0]?.toUpperCase() ?? '').join('').slice(0, 2)
  const colors  = ['bg-blue-500','bg-violet-500','bg-emerald-500','bg-amber-500','bg-rose-500','bg-cyan-500']
  const color   = colors[name.charCodeAt(0) % colors.length]
  const sz      = size === 'sm' ? 'w-6 h-6 text-[9px]' : 'w-7 h-7 text-[10px]'
  return (
    <div className={cn('rounded-full flex items-center justify-center text-white font-bold shrink-0', sz, color)}>
      {initials}
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <div className="flex items-center gap-2 mb-2.5">
      <p className="text-[10px] font-black uppercase tracking-[0.1em] text-gray-400 whitespace-nowrap">{children}</p>
      <div className="flex-1 h-px bg-gray-100" />
    </div>
  )
}

function MetaRow({ label, value, mono = false, highlight }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-gray-100 last:border-0">
      <span className="text-[10.5px] font-semibold text-gray-400 shrink-0 uppercase tracking-[0.04em]">{label}</span>
      <span className={cn(
        'text-[11.5px] text-right font-medium leading-snug',
        mono ? 'font-mono text-[11px]' : '',
        highlight === 'danger' ? 'text-red-600 font-semibold' :
        highlight === 'warn'   ? 'text-yellow-600 font-semibold' :
        highlight === 'good'   ? 'text-emerald-600 font-semibold' :
        'text-gray-700',
      )}>{value}</span>
    </div>
  )
}

// Trust score bar + label
function TrustMeter({ score, size = 'sm' }) {
  const tier = getTrustTier(score)
  const cfg  = TRUST_CFG[tier]
  const pct  = `${score}%`
  if (size === 'lg') {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-end gap-2">
          <span className={cn('text-[36px] font-black tabular-nums leading-none', cfg.color)}>{score}</span>
          <span className="text-[13px] text-gray-400 font-medium mb-1">/ 100</span>
          <span className={cn('text-[11px] font-black px-2 py-0.5 rounded-full border mb-1 tracking-wide', cfg.color, cfg.bg, cfg.border)}>{cfg.label}</span>
        </div>
        <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
          <div className={cn('h-full rounded-full transition-all duration-500', cfg.bar)} style={{ width: pct }} />
        </div>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-0.5 min-w-[54px]">
      <div className="flex items-center gap-1">
        <span className={cn('text-[15px] font-black tabular-nums leading-none', cfg.color)}>{score}</span>
        <span className="text-[9px] text-gray-400 font-medium">/100</span>
      </div>
      <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', cfg.bar)} style={{ width: pct }} />
      </div>
    </div>
  )
}

function TrustTierBadge({ score }) {
  const tier = getTrustTier(score)
  const cfg  = TRUST_CFG[tier]
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black border', cfg.color, cfg.bg, cfg.border)}>
      <span className={cn('w-1.5 h-1.5 rounded-full', cfg.bar)} />
      {cfg.label}
    </span>
  )
}

function TrendIcon({ trend }) {
  if (trend === 'up')     return <TrendingUp   size={11} className="text-emerald-500" />
  if (trend === 'down')   return <TrendingDown  size={11} className="text-red-400" />
  return                         <Minus         size={11} className="text-gray-300" />
}

function StatusPip({ status }) {
  const cfg = ID_STATUS_CFG[status] || ID_STATUS_CFG['Active']
  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold border', cfg.text, cfg.bg, cfg.border)}>
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', cfg.dot, status === 'Active' ? 'animate-pulse' : '')} />
      {status}
    </span>
  )
}

function TypeChip({ type, compact = false }) {
  const cfg  = ID_TYPE_CFG[type] || ID_TYPE_CFG['Human User']
  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1 rounded border text-[10px] font-semibold', cfg.color, cfg.bg, cfg.border, compact ? 'px-1 py-px' : 'px-1.5 py-0.5')}>
      <Icon size={9} />
      {type}
    </span>
  )
}

function FlagChip({ flag }) {
  const cfg     = FLAG_CFG[flag] || { color: 'text-gray-600', bg: 'bg-gray-100', border: 'border-gray-200' }
  const isAlert = flag === 'Risk Spike' || flag === 'Policy Violation'
  return (
    <span className={cn('inline-flex items-center gap-1 px-1.5 py-px rounded border text-[9.5px] font-semibold', cfg.color, cfg.bg, cfg.border)}>
      {isAlert && <Siren size={8} className="shrink-0" />}
      {flag}
    </span>
  )
}

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, icon: Icon, iconBg, valueTint, stripColor }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm hover:border-gray-300 transition-colors overflow-hidden">
      {stripColor && <div className={cn('h-[3px] w-full', stripColor)} />}
      <div className="px-5 py-4 flex items-center gap-4">
        <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm', iconBg)}>
          <Icon size={17} className="text-white" strokeWidth={1.75} />
        </div>
        <div className="min-w-0">
          <p className={cn('text-[22px] font-black tabular-nums leading-none', valueTint ?? 'text-gray-900')}>{value}</p>
          <p className="text-[11px] font-semibold text-gray-500 mt-0.5">{label}</p>
          {sub && <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>}
        </div>
      </div>
    </div>
  )
}

// ── Identity list ──────────────────────────────────────────────────────────────

const TYPE_ORDER = ['Human User', 'Agent', 'Service Account', 'API Key', 'Tool Principal', 'Integration Identity']

function IdentityRow({ identity: id, isSelected, onSelect }) {
  const typCfg = ID_TYPE_CFG[id.type] || ID_TYPE_CFG['Human User']
  const stCfg  = ID_STATUS_CFG[id.status] || ID_STATUS_CFG['Active']
  const TypeIcon = typCfg.icon
  return (
    <tr
      onClick={() => onSelect(id.id)}
      className={cn(
        'cursor-pointer transition-colors duration-100 group border-l-[3px]',
        stCfg.bdr,
        isSelected ? 'bg-blue-50/60' : 'hover:bg-gray-50/40',
      )}
    >
      <td className="w-0 p-0" />
      {/* Identity */}
      <td className="px-3.5 py-2.5">
        <div className="flex items-center gap-2.5">
          <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center border shrink-0 shadow-sm', typCfg.bg, typCfg.border)}>
            <TypeIcon size={14} className={typCfg.color} />
          </div>
          <div className="min-w-0">
            <p className={cn('text-[12.5px] font-semibold font-mono leading-snug truncate', isSelected ? 'text-blue-700' : 'text-gray-800')}>
              {id.name}
            </p>
            <p className="text-[10px] text-gray-400 font-medium truncate leading-tight">{id.tenant}</p>
          </div>
        </div>
      </td>
      {/* Type */}
      <td className="px-3.5 py-2.5"><TypeChip type={id.type} compact /></td>
      {/* Trust score */}
      <td className="px-3.5 py-2.5">
        <div className="flex items-center gap-1.5">
          <TrustMeter score={id.trustScore} />
          <TrendIcon trend={id.trustTrend} />
        </div>
      </td>
      {/* Last activity */}
      <td className="px-3.5 py-2.5">
        <span className={cn(
          'text-[11px] font-mono',
          id.lastActivity.includes('d ago') ? 'text-red-500' :
          id.lastActivity.includes('h ago') ? 'text-yellow-600' :
          'text-gray-500',
        )}>{id.lastActivity}</span>
      </td>
      {/* Status */}
      <td className="px-3.5 py-2.5"><StatusPip status={id.status} /></td>
      {/* Flags */}
      <td className="px-3.5 py-2.5">
        <div className="flex flex-wrap gap-1">
          {id.flags.slice(0, 2).map(f => <FlagChip key={f} flag={f} />)}
        </div>
      </td>
    </tr>
  )
}

function IdentityList({ identities, selectedId, onSelect }) {
  const groups = {}
  const orderedTypes = []
  TYPE_ORDER.forEach(t => {
    const rows = identities.filter(i => i.type === t)
    if (rows.length > 0) {
      groups[t] = rows
      orderedTypes.push(t)
    }
  })

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      {/* Table header */}
      <div className="border-b border-gray-150 bg-gray-50">
        <table className="w-full">
          <thead>
            <tr>
              <th className="w-0 p-0" />
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[200px] min-w-[160px]">Identity</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[140px]">Type</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[110px]">Trust Score</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[90px]">Last Active</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[110px]">Status</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400">Flags</th>
            </tr>
          </thead>
        </table>
      </div>

      <div className="divide-y divide-gray-100">
        {orderedTypes.map(type => {
          const cfg  = ID_TYPE_CFG[type]
          const Icon = cfg.icon
          const rows = groups[type]
          return (
            <div key={type}>
              {/* Group header */}
              <div className="px-4 py-2 flex items-center gap-2.5 bg-gray-50 border-b border-gray-100">
                <div className={cn('w-5 h-5 rounded-md flex items-center justify-center border shrink-0', cfg.bg, cfg.border)}>
                  <Icon size={10} className={cfg.color} />
                </div>
                <span className="text-[10px] font-black uppercase tracking-[0.08em] text-gray-500">{type}</span>
                <span className="ml-auto text-[9.5px] font-semibold text-gray-300 tabular-nums">
                  {rows.length} {rows.length === 1 ? 'identity' : 'identities'}
                </span>
              </div>

              <table className="w-full border-collapse">
                <tbody className="divide-y divide-gray-50">
                  {rows.map(id => (
                    <IdentityRow
                      key={id.id}
                      identity={id}
                      isSelected={id.id === selectedId}
                      onSelect={onSelect}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Detail panel sub-components ───────────────────────────────────────────────

function TrustBreakdown({ scores }) {
  const dims = [
    { label: 'Behavior',         value: scores.behavior,        color: 'bg-violet-400' },
    { label: 'Access Hygiene',   value: scores.accessHygiene,   color: 'bg-blue-400'   },
    { label: 'Anomaly Score',    value: scores.anomaly,         color: 'bg-amber-400'  },
    { label: 'Policy Adherence', value: scores.policyAdherence, color: 'bg-emerald-400'},
  ]
  return (
    <div className="space-y-2.5">
      {dims.map(d => (
        <div key={d.label}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] font-medium text-gray-600">{d.label}</span>
            <span className={cn(
              'text-[11px] font-bold tabular-nums',
              d.value >= 80 ? 'text-emerald-600' : d.value >= 60 ? 'text-yellow-600' : 'text-red-600',
            )}>{d.value}</span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all duration-500', d.color)}
              style={{ width: `${d.value}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function DelegationChain({ chain }) {
  return (
    <div className="flex items-center flex-wrap gap-1">
      {chain.map((node, idx) => {
        const cfg  = CHAIN_NODE_TYPE[node.type] || CHAIN_NODE_TYPE['Human User']
        const Icon = cfg.icon
        const isLast = idx === chain.length - 1
        return (
          <div key={idx} className="flex items-center gap-1">
            <div className={cn('inline-flex items-center gap-1 px-2 py-1 rounded-lg border text-[10.5px] font-semibold shadow-sm', cfg.color, cfg.bg, cfg.border)}>
              <Icon size={10} />
              <span className="font-mono">{node.label}</span>
            </div>
            {!isLast && <ArrowRight size={11} className="text-gray-400 shrink-0" />}
          </div>
        )
      })}
    </div>
  )
}

function CredentialPosture({ credential }) {
  const isExpired  = credential.expires?.toLowerCase().includes('expired')
  const isOldKey   = parseInt(credential.age) > 90
  const noApproval = credential.approvalPath === 'None configured'
  return (
    <div className="space-y-0 bg-gray-50 rounded-xl border border-gray-100 px-4 py-1">
      <MetaRow label="Type"          value={credential.type} />
      <MetaRow label="Key Age"       value={credential.age}           highlight={isOldKey ? 'danger' : undefined} />
      <MetaRow label="Last Rotated"  value={credential.lastRotated} />
      <MetaRow label="Expires"       value={credential.expires}       highlight={isExpired ? 'danger' : undefined} />
      <MetaRow label="MFA"           value={credential.mfa || 'Not applicable'} highlight={!credential.mfa ? undefined : 'good'} />
      <MetaRow label="Approval Path" value={credential.approvalPath}  highlight={noApproval ? 'warn' : 'good'} />
    </div>
  )
}

function RecommendedActions({ actions }) {
  if (!actions || actions.length === 0) return (
    <div className="flex items-center gap-2 px-3 py-2.5 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-xl">
      <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />
      <p className="text-[11.5px] font-medium text-emerald-700">No recommended actions — posture looks good.</p>
    </div>
  )
  return (
    <div className="space-y-1.5">
      {actions.map((action, idx) => (
        <div key={idx} className="flex items-start gap-2 px-3 py-2 bg-white border border-gray-150 border-l-[3px] border-l-orange-400 rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <AlertTriangle size={11} className="text-orange-500 mt-0.5 shrink-0" />
          <p className="text-[11.5px] font-medium text-gray-700 leading-snug">{action}</p>
        </div>
      ))}
    </div>
  )
}

// ── Identity detail panel ─────────────────────────────────────────────────────

const DETAIL_TABS = ['Overview', 'Access', 'Trust Signals', 'Sessions', 'Alerts & Cases', 'Delegation']

function IdentityDetailPanel({ identity: id, onClose }) {
  const [activeTab, setActiveTab] = useState('Overview')

  if (!id) return null

  const typCfg = ID_TYPE_CFG[id.type] || ID_TYPE_CFG['Human User']
  const stCfg  = ID_STATUS_CFG[id.status] || ID_STATUS_CFG['Active']
  const tier   = getTrustTier(id.trustScore)
  const trCfg  = TRUST_CFG[tier]
  const TypeIcon = typCfg.icon

  const HDR_STRIP =
    id.status === 'Suspicious' || id.status === 'Quarantined' ? 'bg-red-500' :
    id.status === 'Expired'    || id.status === 'Disabled'    ? 'bg-gray-300' :
    tier === 'Risky'  ? 'bg-red-500' :
    tier === 'Watch'  ? 'bg-yellow-400' : 'bg-emerald-500'

  const HDR_BG =
    id.status === 'Suspicious' ? 'bg-orange-50/40 border-b-orange-100' :
    tier === 'Risky'   ? 'bg-red-50/30 border-b-red-100' :
    tier === 'Watch'   ? 'bg-yellow-50/30 border-b-yellow-100' :
    'bg-emerald-50/20 border-b-emerald-100'

  return (
    <div className="w-[460px] shrink-0 bg-white border border-gray-200 rounded-xl shadow-sm flex flex-col overflow-hidden">
      {/* Accent strip */}
      <div className={cn('h-[3px] w-full shrink-0', HDR_STRIP)} />

      {/* Header */}
      <div className={cn('px-5 py-4 border-b shrink-0', HDR_BG)}>
        {/* Row 1: icon + name + close */}
        <div className="flex items-start justify-between gap-2 mb-2.5">
          <div className="flex items-center gap-2.5">
            <div className={cn('w-9 h-9 rounded-xl flex items-center justify-center border-2 border-white shadow-sm', typCfg.bg)}>
              <TypeIcon size={16} className={typCfg.color} />
            </div>
            <div>
              <h2 className="text-[14px] font-bold text-gray-900 leading-tight font-mono">{id.name}</h2>
              <p className="text-[10.5px] text-gray-400 font-medium mt-px">{id.displayName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded-md hover:bg-black/[0.06] text-gray-400 hover:text-gray-600 transition-colors shrink-0 mt-0.5"
          >
            <X size={13} />
          </button>
        </div>

        {/* Row 2: chips */}
        <div className="flex items-center gap-1.5 flex-wrap mb-2.5">
          <StatusPip status={id.status} />
          <TypeChip type={id.type} />
          <TrustTierBadge score={id.trustScore} />
          {id.flags.slice(0, 2).map(f => <FlagChip key={f} flag={f} />)}
        </div>

        {/* Row 3: owner + env + last active */}
        <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-3">
          <OwnerAvatar name={id.owner} size="sm" />
          <span className="font-semibold text-gray-600">{id.ownerDisplay}</span>
          <span className="text-gray-300">·</span>
          <span className={cn(
            'text-[10px] font-semibold px-1 py-px rounded-sm border',
            id.environment === 'Production' ? 'text-gray-400 border-gray-200 bg-gray-50' : 'text-amber-600 border-amber-200 bg-amber-50',
          )}>{id.environment}</span>
          <span className="text-gray-300">·</span>
          <Clock size={10} className="text-gray-300" />
          <span className="font-mono text-gray-400">{id.lastActivity}</span>
        </div>

        {/* Row 4: trust meter */}
        <div className="mb-3.5">
          <TrustMeter score={id.trustScore} size="lg" />
        </div>

        {/* Row 5: actions */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <Eye size={11} /> Review Access
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-blue-600 border-blue-200 hover:bg-blue-50">
            <Activity size={11} /> Sessions
          </Button>
          <div className="w-px h-5 bg-gray-200 mx-0.5" />
          {id.status === 'Active' && (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-orange-600 border-orange-200 hover:bg-orange-50">
              <Ban size={11} /> Suspend
            </Button>
          )}
          {(id.status === 'Suspicious' || id.linkedAlerts > 0) && (
            <Button size="sm" variant="destructive" className="h-7 gap-1 text-[11px]">
              <ShieldAlert size={11} /> View Alerts
            </Button>
          )}
          <Button size="sm" variant="ghost" className="h-7 gap-1 text-[11px] ml-auto text-gray-400 hover:text-gray-600">
            <Settings size={11} />
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-100 bg-white shrink-0 px-2 overflow-x-auto">
        {DETAIL_TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-2.5 py-2.5 text-[11px] font-semibold whitespace-nowrap border-b-2 transition-colors',
              activeTab === tab
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700',
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">

        {/* ── Overview ── */}
        {activeTab === 'Overview' && (
          <div className="p-5 space-y-5">
            {/* Status banner */}
            {(id.status === 'Suspicious' || id.status === 'Quarantined') && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-xl">
                <ShieldAlert size={13} className="text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-red-700">
                    {id.status === 'Quarantined' ? 'Identity Quarantined' : 'Suspicious Behavior Detected'}
                  </p>
                  <p className="text-[11px] text-red-600 mt-0.5 leading-snug">
                    {id.trustSignals.filter(s => !s.resolved)[0]?.signal || 'Review trust signals for details.'}
                  </p>
                </div>
              </div>
            )}
            {id.status === 'Expired' && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-gray-50 border border-gray-200 border-l-[3px] border-l-gray-400 rounded-xl">
                <Clock size={13} className="text-gray-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-gray-600">Credential Expired</p>
                  <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">This identity's credential has expired. Clean up or rotate to restore access.</p>
                </div>
              </div>
            )}

            {/* Description */}
            <div>
              <SectionLabel>Description</SectionLabel>
              <p className="text-[12.5px] text-gray-700 leading-relaxed">{id.description}</p>
            </div>

            {/* Metadata */}
            <div>
              <SectionLabel>Identity Details</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-1">
                <MetaRow label="Owner"         value={id.ownerDisplay} />
                <MetaRow label="Auth Method"   value={id.authMethod} />
                <MetaRow label="Environment"   value={id.environment} />
                <MetaRow label="Tenant"        value={id.tenant}     mono />
                <MetaRow label="Created"       value={id.createdAt} />
                <MetaRow label="Last Active"   value={id.lastActivityFull} mono />
              </div>
            </div>

            {/* Trust breakdown */}
            <div>
              <SectionLabel>Trust Breakdown</SectionLabel>
              <TrustBreakdown scores={id.trustBreakdown} />
            </div>

            {/* Recommended actions */}
            <div>
              <SectionLabel>Recommended Actions</SectionLabel>
              <RecommendedActions actions={id.recommendedActions} />
            </div>
          </div>
        )}

        {/* ── Access ── */}
        {activeTab === 'Access' && (
          <div className="p-5 space-y-5">
            {/* Granted scopes */}
            {id.scopes.length > 0 && (
              <div>
                <SectionLabel>Granted Scopes</SectionLabel>
                <div className="space-y-1.5">
                  {id.scopes.map(s => (
                    <div key={s} className="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-lg">
                      <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
                      <span className="text-[11px] font-mono text-emerald-800 leading-snug">{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Elevated roles */}
            {id.elevatedRoles.length > 0 && (
              <div>
                <SectionLabel>Elevated Roles</SectionLabel>
                <div className="space-y-1.5">
                  {id.elevatedRoles.map(r => (
                    <div key={r} className="flex items-center gap-2 px-3 py-1.5 bg-orange-50 border border-orange-100 border-l-[3px] border-l-orange-400 rounded-lg">
                      <ShieldAlert size={11} className="text-orange-500 shrink-0" />
                      <span className="text-[11px] font-mono text-orange-800 leading-snug">{r}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Delegated permissions */}
            {id.delegatedPermissions.length > 0 && (
              <div>
                <SectionLabel>Delegated Permissions</SectionLabel>
                <div className="space-y-1.5">
                  {id.delegatedPermissions.map(p => (
                    <div key={p} className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border border-blue-100 border-l-[3px] border-l-blue-400 rounded-lg">
                      <Link size={11} className="text-blue-500 shrink-0" />
                      <span className="text-[11px] font-mono text-blue-800 leading-snug">{p}</span>
                    </div>
                  ))}
                </div>
                {id.delegatedFrom && (
                  <p className="text-[10.5px] text-gray-400 mt-1.5">Delegated from <span className="font-semibold text-gray-600 font-mono">{id.delegatedFrom}</span></p>
                )}
              </div>
            )}

            {/* Linked resources */}
            {(id.linkedTools.length + id.linkedModels.length + id.linkedDataSources.length) > 0 && (
              <div>
                <SectionLabel>Linked Resources</SectionLabel>
                <div className="space-y-1.5">
                  {id.linkedTools.map(t => (
                    <div key={t} className="flex items-center gap-2 px-3 py-1.5 bg-white border border-gray-150 rounded-lg shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <Wrench size={10} className="text-emerald-500 shrink-0" />
                      <span className="text-[11.5px] font-medium text-gray-700 font-mono">{t}</span>
                      <span className="ml-auto text-[9.5px] text-gray-300 font-semibold">Tool</span>
                    </div>
                  ))}
                  {id.linkedModels.map(m => (
                    <div key={m} className="flex items-center gap-2 px-3 py-1.5 bg-white border border-gray-150 rounded-lg shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <Cpu size={10} className="text-violet-500 shrink-0" />
                      <span className="text-[11.5px] font-medium text-gray-700 font-mono">{m}</span>
                      <span className="ml-auto text-[9.5px] text-gray-300 font-semibold">Model</span>
                    </div>
                  ))}
                  {id.linkedDataSources.map(d => (
                    <div key={d} className="flex items-center gap-2 px-3 py-1.5 bg-white border border-gray-150 rounded-lg shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <Database size={10} className="text-cyan-500 shrink-0" />
                      <span className="text-[11.5px] font-medium text-gray-700 font-mono">{d}</span>
                      <span className="ml-auto text-[9.5px] text-gray-300 font-semibold">Data</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Credential posture */}
            <div>
              <SectionLabel>Credential Posture</SectionLabel>
              <CredentialPosture credential={id.credential} />
            </div>
          </div>
        )}

        {/* ── Trust Signals ── */}
        {activeTab === 'Trust Signals' && (
          <div className="p-5 space-y-4">
            <SectionLabel>Trust Signals ({id.trustSignals.length})</SectionLabel>
            {id.trustSignals.length === 0 ? (
              <div className="py-8 flex flex-col items-center gap-2 text-center">
                <ShieldCheck size={20} className="text-gray-300" />
                <p className="text-[12px] text-gray-400 font-medium">No trust signals — posture is clean</p>
              </div>
            ) : (
              <div className="flex flex-col">
                {id.trustSignals.map((signal, idx) => {
                  const cfg    = SIGNAL_CFG[signal.severity] || SIGNAL_CFG['Low']
                  const isLast = idx === id.trustSignals.length - 1
                  return (
                    <div key={idx} className="flex gap-3 items-start">
                      <div className="flex flex-col items-center shrink-0 pt-3">
                        <div className={cn('w-5 h-5 rounded-full flex items-center justify-center border-2 border-white shadow-sm', cfg.dotBg)}>
                          <span className={cn('w-2 h-2 rounded-full', cfg.dot)} />
                        </div>
                        {!isLast && <div className="flex-1 mt-1 mb-1 w-px border-l border-dashed border-gray-200 min-h-[16px]" />}
                      </div>
                      <div className="flex-1 min-w-0 mb-2.5">
                        <div className={cn('bg-white rounded-xl border border-gray-150 border-l-[3px] px-3.5 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]', cfg.bdr)}>
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-[12px] font-medium text-gray-700 leading-snug">{signal.signal}</p>
                            <span className="text-[9.5px] font-mono text-gray-400 shrink-0 mt-0.5 whitespace-nowrap">{signal.ts}</span>
                          </div>
                          <div className="flex items-center gap-2 mt-1.5">
                            <span className={cn('inline-flex items-center gap-1 text-[9.5px] font-semibold px-1.5 py-px rounded-full border', cfg.pill)}>
                              <span className={cn('w-1 h-1 rounded-full', cfg.dot)} />
                              {signal.severity}
                            </span>
                            {signal.resolved && (
                              <span className="text-[9.5px] font-semibold text-emerald-600 bg-emerald-50 border border-emerald-100 px-1.5 py-px rounded-full">Resolved</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            <div>
              <SectionLabel>Trust Breakdown</SectionLabel>
              <TrustBreakdown scores={id.trustBreakdown} />
            </div>
          </div>
        )}

        {/* ── Sessions ── */}
        {activeTab === 'Sessions' && (
          <div className="p-5 space-y-4">
            <SectionLabel>Recent Sessions</SectionLabel>
            {id.recentSessions.length === 0 ? (
              <p className="text-[12px] text-gray-400 italic">No recent session data.</p>
            ) : (
              <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                {id.recentSessions.map((sess, idx) => {
                  const cfg = SESSION_OUTCOME_CFG[sess.outcome] || SESSION_OUTCOME_CFG['Success']
                  return (
                    <div key={idx} className={cn('flex items-center gap-3 px-3.5 py-2.5 border-b border-gray-75 last:border-0 hover:bg-gray-50/50 transition-colors border-l-[3px]', cfg.bdrL)}>
                      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', cfg.dot)} />
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-mono text-gray-700 truncate">{sess.action}</p>
                        <p className="text-[9.5px] font-semibold text-gray-400">{sess.id}</p>
                      </div>
                      <span className="text-[10px] font-mono text-gray-400 whitespace-nowrap">{sess.ts}</span>
                      <span className={cn('text-[9.5px] font-semibold px-1.5 py-px rounded-full border', cfg.text)}>{sess.outcome}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* ── Alerts & Cases ── */}
        {activeTab === 'Alerts & Cases' && (
          <div className="p-5 space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <div className={cn(
                'rounded-xl border border-l-[3px] px-4 py-3.5',
                id.linkedAlerts > 0 ? 'bg-red-50 border-red-100 border-l-red-500' : 'bg-gray-50 border-gray-100 border-l-gray-200',
              )}>
                <p className={cn('text-[26px] font-black tabular-nums leading-none', id.linkedAlerts > 0 ? 'text-red-600' : 'text-gray-400')}>
                  {id.linkedAlerts}
                </p>
                <p className="text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 mt-1">Linked Alerts</p>
                {id.linkedAlerts > 0 && (
                  <button className="mt-2 text-[10.5px] font-semibold text-red-600 flex items-center gap-1 hover:underline">
                    View alerts <ExternalLink size={10} />
                  </button>
                )}
              </div>
              <div className={cn(
                'rounded-xl border border-l-[3px] px-4 py-3.5',
                id.linkedCases > 0 ? 'bg-violet-50 border-violet-100 border-l-violet-500' : 'bg-gray-50 border-gray-100 border-l-gray-200',
              )}>
                <p className={cn('text-[26px] font-black tabular-nums leading-none', id.linkedCases > 0 ? 'text-violet-600' : 'text-gray-400')}>
                  {id.linkedCases}
                </p>
                <p className="text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 mt-1">Linked Cases</p>
                {id.linkedCases > 0 && (
                  <button className="mt-2 text-[10.5px] font-semibold text-violet-600 flex items-center gap-1 hover:underline">
                    View cases <ExternalLink size={10} />
                  </button>
                )}
              </div>
            </div>

            {id.linkedAlerts === 0 && id.linkedCases === 0 && (
              <div className="flex items-center gap-2.5 px-3.5 py-3 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-xl">
                <ShieldCheck size={13} className="text-emerald-500 shrink-0" />
                <p className="text-[12px] font-medium text-emerald-700">No linked alerts or cases — identity posture is clean.</p>
              </div>
            )}

            <div>
              <SectionLabel>Recommended Actions</SectionLabel>
              <RecommendedActions actions={id.recommendedActions} />
            </div>
          </div>
        )}

        {/* ── Delegation ── */}
        {activeTab === 'Delegation' && (
          <div className="p-5 space-y-5">
            <div>
              <SectionLabel>Access Chain</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-4">
                <DelegationChain chain={id.delegationChain} />
              </div>
              <p className="text-[10.5px] text-gray-400 mt-2 leading-snug">
                This chain shows how access flows from the principal identity through linked tools and data sources.
              </p>
            </div>

            {id.delegatedFrom && (
              <div>
                <SectionLabel>Delegated From</SectionLabel>
                <div className="flex items-center gap-2 px-3.5 py-3 bg-blue-50 border border-blue-100 border-l-[3px] border-l-blue-400 rounded-xl">
                  <User size={12} className="text-blue-500 shrink-0" />
                  <div>
                    <p className="text-[12px] font-semibold text-blue-800 font-mono">{id.delegatedFrom}</p>
                    <p className="text-[10.5px] text-blue-600 mt-0.5">Delegation grants elevated permissions to this identity</p>
                  </div>
                </div>
              </div>
            )}

            {id.delegatedPermissions.length > 0 && (
              <div>
                <SectionLabel>Delegated Permissions</SectionLabel>
                <div className="space-y-1.5">
                  {id.delegatedPermissions.map((p, idx) => (
                    <div key={idx} className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border border-blue-100 border-l-[3px] border-l-blue-400 rounded-lg">
                      <Link size={11} className="text-blue-500 shrink-0" />
                      <span className="text-[11px] font-mono text-blue-800">{p}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <SectionLabel>Credential Posture</SectionLabel>
              <CredentialPosture credential={id.credential} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Trust events table ─────────────────────────────────────────────────────────

function TrustEventsTable({ events }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between bg-white">
        <div className="flex items-center gap-3">
          <p className="text-[13px] font-bold text-gray-900">Trust Events</p>
          <span className="text-[10px] font-black uppercase tracking-[0.06em] text-gray-400 bg-gray-100 rounded-full px-2 py-0.5">{events.length} events</span>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <RefreshCw size={11} /> Refresh
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <ExternalLink size={11} /> Full Log
          </Button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="w-0 p-0" />
              {['Timestamp', 'Identity', 'Event', 'Risk Impact', 'Result'].map(col => (
                <th key={col} className="px-3.5 py-2.5 text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-75">
            {events.map(ev => {
              const impCfg = EVENT_IMPACT_CFG[ev.impact] || EVENT_IMPACT_CFG['Low']
              const resCls = EVENT_RESULT_CFG[ev.result] || EVENT_RESULT_CFG['Info']
              return (
                <tr key={ev.id} className={cn('hover:bg-gray-50/50 transition-colors border-l-[3px]', impCfg.bdr)}>
                  <td className="w-0 p-0" />
                  <td className="px-3.5 py-2.5 whitespace-nowrap">
                    <span className="text-[10.5px] font-mono text-gray-400">{ev.ts}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="inline-flex items-center text-[11px] font-semibold font-mono text-gray-600 bg-gray-50 border border-gray-200 rounded-md px-1.5 py-0.5 whitespace-nowrap">{ev.identity}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="text-[11.5px] font-medium text-gray-700">{ev.event}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold border', impCfg.pill)}>
                      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', impCfg.dot)} />
                      {ev.impact}
                    </span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className={cn('inline-flex items-center text-[10.5px] font-semibold px-2 py-0.5 rounded-full border', resCls)}>
                      {ev.result}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Identity() {
  const [identities, setIdentities] = useState(MOCK_IDENTITIES)
  const [selectedId, setSelectedId] = useState('id-003')
  const [search, setSearch]         = useState('')
  const [filterType, setFilterType] = useState('All Types')
  const [filterTrust, setFilterTrust] = useState('All Trust Levels')
  const [filterStatus, setFilterStatus] = useState('All Statuses')
  const [filterEnv, setFilterEnv]   = useState('All Environments')
  const [onlySuspicious, setOnlySuspicious] = useState(false)

  const selectedIdentity = identities.find(i => i.id === selectedId) || null

  const typeOpts   = ['All Types',         ...Array.from(new Set(MOCK_IDENTITIES.map(i => i.type)))]
  const trustOpts  = ['All Trust Levels',  'Trusted (80–100)', 'Watch (60–79)', 'Risky (0–59)']
  const statusOpts = ['All Statuses',      ...Array.from(new Set(MOCK_IDENTITIES.map(i => i.status)))]
  const envOpts    = ['All Environments',  ...Array.from(new Set(MOCK_IDENTITIES.map(i => i.environment)))]

  const filtered = identities.filter(id => {
    const q = search.toLowerCase()
    if (q && !id.name.toLowerCase().includes(q) && !id.type.toLowerCase().includes(q) && !id.tenant.toLowerCase().includes(q)) return false
    if (filterType !== 'All Types' && id.type !== filterType) return false
    if (filterStatus !== 'All Statuses' && id.status !== filterStatus) return false
    if (filterEnv !== 'All Environments' && id.environment !== filterEnv) return false
    if (filterTrust !== 'All Trust Levels') {
      const tier = getTrustTier(id.trustScore)
      if (filterTrust === 'Trusted (80–100)' && tier !== 'Trusted') return false
      if (filterTrust === 'Watch (60–79)'     && tier !== 'Watch')   return false
      if (filterTrust === 'Risky (0–59)'      && tier !== 'Risky')   return false
    }
    if (onlySuspicious && id.status !== 'Suspicious' && id.status !== 'Quarantined' && id.flags.length === 0) return false
    return true
  })

  // KPI values
  const totalIdentities    = identities.length
  const highRisk           = identities.filter(i => getTrustTier(i.trustScore) === 'Risky').length
  const lowTrust           = identities.filter(i => getTrustTier(i.trustScore) === 'Watch').length
  const delegatedChains    = identities.filter(i => i.delegatedFrom || i.delegatedPermissions.length > 0).length

  return (
    <PageContainer>
      {/* Page header */}
      <PageHeader
        title="Identity & Trust"
        subtitle="Review access posture, delegated permissions, and trust signals across users, agents, and services"
        actions={
          <>
            <Button size="sm" variant="outline" className="gap-1.5">
              <Bookmark size={13} /> Saved Views
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5">
              <Download size={13} /> Export
            </Button>
            <Button size="sm" className="gap-1.5">
              <Plus size={13} /> Add Identity
            </Button>
          </>
        }
      />

      {/* KPI strip */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="Total Identities"      value={totalIdentities} sub="Across all types"          icon={Fingerprint}  iconBg="bg-blue-500"    valueTint="text-blue-600"    stripColor="bg-blue-500"    />
        <KpiCard label="High Risk Identities"  value={highRisk}        sub="Trust score 0–59"          icon={ShieldAlert}  iconBg="bg-red-500"     valueTint={highRisk > 0 ? 'text-red-600' : 'text-gray-900'}     stripColor={highRisk > 0 ? 'bg-red-500' : 'bg-gray-200'}     />
        <KpiCard label="Low Trust Entities"    value={lowTrust}        sub="Trust score 60–79"         icon={AlertTriangle}iconBg="bg-yellow-500"  valueTint={lowTrust > 0 ? 'text-yellow-600' : 'text-gray-900'}  stripColor={lowTrust > 0 ? 'bg-yellow-400' : 'bg-gray-200'}  />
        <KpiCard label="Delegated Access"      value={delegatedChains} sub="With active delegations"   icon={GitBranch}    iconBg="bg-violet-500"  valueTint="text-violet-600"  stripColor="bg-violet-500"  />
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-[280px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search identities…"
            className={cn(
              'w-full h-8 pl-8 pr-3 text-[12px] text-gray-700 bg-white',
              'border border-gray-200 rounded-lg',
              'focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400',
              'placeholder:text-gray-400',
            )}
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500">
              <X size={12} />
            </button>
          )}
        </div>

        <FilterSelect value={filterType}   onChange={setFilterType}   options={typeOpts}   />
        <FilterSelect value={filterTrust}  onChange={setFilterTrust}  options={trustOpts}  />
        <FilterSelect value={filterStatus} onChange={setFilterStatus} options={statusOpts} />
        <FilterSelect value={filterEnv}    onChange={setFilterEnv}    options={envOpts}    />

        {/* Suspicious toggle */}
        <div className="flex items-center gap-2 ml-auto">
          <Toggle checked={onlySuspicious} onChange={setOnlySuspicious} />
          <span className="text-[12px] font-medium text-gray-500">Only suspicious</span>
        </div>
      </div>

      {/* Main area: list + detail */}
      <div className="flex gap-4 items-start">
        {/* Identity list */}
        <div className="flex-1 min-w-0">
          {filtered.length === 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm py-16 flex flex-col items-center gap-2 text-center">
              <Filter size={20} className="text-gray-300" />
              <p className="text-[12.5px] text-gray-400 font-medium">No identities match your filters</p>
              <p className="text-[11px] text-gray-300">Try adjusting the search or filter criteria</p>
            </div>
          ) : (
            <IdentityList
              identities={filtered}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedIdentity && (
          <IdentityDetailPanel
            identity={selectedIdentity}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>

      {/* Trust events table */}
      <TrustEventsTable events={MOCK_TRUST_EVENTS} />
    </PageContainer>
  )
}
