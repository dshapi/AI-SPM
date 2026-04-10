import { useState } from 'react'
import {
  Search, X, Plus, Download, Bookmark,
  Database, FileText, BookOpen, HardDrive, FolderKanban,
  Layers, Cpu, Network, Server,
  ShieldCheck, ShieldAlert,
  AlertTriangle, CheckCircle2,
  Clock, ChevronDown,
  RefreshCw, ExternalLink,
  Link, Eye, Pause,
  ArrowRight, TrendingDown, TrendingUp, Minus,
  Lock, Siren,
  Settings, Activity, Filter,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'

// ── Design tokens ─────────────────────────────────────────────────────────────

const SOURCE_TYPE_CFG = {
  'Vector Database':      { icon: Database,     color: 'text-violet-600', bg: 'bg-violet-50',  border: 'border-violet-200', bdr: 'border-l-violet-400'  },
  'Document Repository':  { icon: FileText,     color: 'text-blue-600',   bg: 'bg-blue-50',    border: 'border-blue-200',   bdr: 'border-l-blue-400'    },
  'Confluence / Wiki':    { icon: BookOpen,     color: 'text-cyan-600',   bg: 'bg-cyan-50',    border: 'border-cyan-200',   bdr: 'border-l-cyan-400'    },
  'S3 / Object Storage':  { icon: HardDrive,   color: 'text-amber-600',  bg: 'bg-amber-50',   border: 'border-amber-200',  bdr: 'border-l-amber-400'   },
  'SharePoint / Drive':   { icon: FolderKanban,color: 'text-indigo-600', bg: 'bg-indigo-50',  border: 'border-indigo-200', bdr: 'border-l-indigo-400'  },
  'SQL / Structured Data':{ icon: Server,       color: 'text-emerald-600',bg: 'bg-emerald-50', border: 'border-emerald-200',bdr: 'border-l-emerald-400' },
  'Prompt Library':       { icon: Layers,       color: 'text-rose-600',   bg: 'bg-rose-50',    border: 'border-rose-200',   bdr: 'border-l-rose-400'    },
  'Memory Store':         { icon: Cpu,          color: 'text-pink-600',   bg: 'bg-pink-50',    border: 'border-pink-200',   bdr: 'border-l-pink-400'    },
  'API Knowledge Source': { icon: Network,      color: 'text-orange-600', bg: 'bg-orange-50',  border: 'border-orange-200', bdr: 'border-l-orange-400'  },
}

const SENSITIVITY_CFG = {
  'Public':       { color: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-200', dot: 'bg-emerald-400', bdr: 'border-l-emerald-400', level: 0 },
  'Internal':     { color: 'text-blue-700',    bg: 'bg-blue-50',    border: 'border-blue-200',    dot: 'bg-blue-400',    bdr: 'border-l-blue-400',    level: 1 },
  'Confidential': { color: 'text-orange-700',  bg: 'bg-orange-50',  border: 'border-orange-200',  dot: 'bg-orange-500',  bdr: 'border-l-orange-400',  level: 2 },
  'Restricted':   { color: 'text-red-700',     bg: 'bg-red-50',     border: 'border-red-200',     dot: 'bg-red-500',     bdr: 'border-l-red-500',     level: 3 },
}

const TRUST_CFG = {
  Trusted: { label: 'Trusted', color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', bar: 'bg-emerald-400', bdr: 'border-l-emerald-400', headerBg: 'bg-emerald-50/30', strip: 'bg-emerald-500' },
  Review:  { label: 'Review',  color: 'text-yellow-600',  bg: 'bg-yellow-50',  border: 'border-yellow-200',  bar: 'bg-yellow-400',  bdr: 'border-l-yellow-400',  headerBg: 'bg-yellow-50/30',  strip: 'bg-yellow-500'  },
  Risky:   { label: 'Risky',   color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200',     bar: 'bg-red-500',     bdr: 'border-l-red-500',     headerBg: 'bg-red-50/20',     strip: 'bg-red-500'     },
}

const SOURCE_STATUS_CFG = {
  Healthy:     { dot: 'bg-emerald-400', text: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-200', bdr: 'border-l-emerald-400', pulse: true  },
  Syncing:     { dot: 'bg-blue-400',    text: 'text-blue-700',    bg: 'bg-blue-50',    border: 'border-blue-200',    bdr: 'border-l-blue-400',    pulse: true  },
  Warning:     { dot: 'bg-yellow-400',  text: 'text-yellow-700',  bg: 'bg-yellow-50',  border: 'border-yellow-200',  bdr: 'border-l-yellow-400',  pulse: false },
  Failed:      { dot: 'bg-red-500',     text: 'text-red-700',     bg: 'bg-red-50',     border: 'border-red-200',     bdr: 'border-l-red-500',     pulse: false },
  Stale:       { dot: 'bg-amber-400',   text: 'text-amber-700',   bg: 'bg-amber-50',   border: 'border-amber-200',   bdr: 'border-l-amber-400',   pulse: false },
  Quarantined: { dot: 'bg-red-600',     text: 'text-red-800',     bg: 'bg-red-100',    border: 'border-red-300',     bdr: 'border-l-red-600',     pulse: false },
}

const SIGNAL_CFG = {
  High:   { dot: 'bg-red-500',     pill: 'text-red-700 bg-red-50 border-red-100',             bdr: 'border-l-red-500',     dotBg: 'bg-red-100'     },
  Medium: { dot: 'bg-yellow-400',  pill: 'text-yellow-700 bg-yellow-50 border-yellow-100',    bdr: 'border-l-yellow-400',  dotBg: 'bg-yellow-100'  },
  Low:    { dot: 'bg-blue-400',    pill: 'text-blue-700 bg-blue-50 border-blue-100',           bdr: 'border-l-blue-400',    dotBg: 'bg-blue-100'    },
  Ok:     { dot: 'bg-emerald-400', pill: 'text-emerald-700 bg-emerald-50 border-emerald-100', bdr: 'border-l-emerald-400', dotBg: 'bg-emerald-100' },
}

const EVENT_IMPACT_CFG = {
  High:   { dot: 'bg-red-500',     pill: 'text-red-700 bg-red-50 border-red-100',          bdr: 'border-l-red-500'    },
  Medium: { dot: 'bg-yellow-400',  pill: 'text-yellow-700 bg-yellow-50 border-yellow-100', bdr: 'border-l-yellow-400' },
  Low:    { dot: 'bg-blue-400',    pill: 'text-blue-700 bg-blue-50 border-blue-100',        bdr: 'border-l-blue-400'   },
}

const EVENT_RESULT_CFG = {
  Detected: 'text-red-600 bg-red-50 border-red-100',
  Warning:  'text-yellow-700 bg-yellow-50 border-yellow-100',
  Resolved: 'text-emerald-700 bg-emerald-50 border-emerald-100',
  Info:     'text-blue-700 bg-blue-50 border-blue-100',
}

const RISK_LEVEL_CFG = {
  Low:    { color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-100', bar: 'bg-emerald-400', width: '22%'  },
  Medium: { color: 'text-yellow-600',  bg: 'bg-yellow-50',  border: 'border-yellow-100',  bar: 'bg-yellow-400',  width: '58%'  },
  High:   { color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-100',     bar: 'bg-red-500',     width: '90%'  },
}

const HEALTH_DOT_CFG = {
  ok:    { bg: 'bg-emerald-400', ring: 'ring-emerald-100' },
  warn:  { bg: 'bg-yellow-400',  ring: 'ring-yellow-100'  },
  fail:  { bg: 'bg-red-500',     ring: 'ring-red-100'     },
  stale: { bg: 'bg-amber-400',   ring: 'ring-amber-100'   },
  sync:  { bg: 'bg-blue-400',    ring: 'ring-blue-100'    },
}

const SENSITIVITY_ORDER = ['Restricted', 'Confidential', 'Internal', 'Public']
const DETAIL_TABS = ['Overview', 'Trust & Security', 'Dependencies', 'Content', 'Sync History', 'Alerts & Cases']

function getTrustTier(score) {
  if (score >= 80) return 'Trusted'
  if (score >= 60) return 'Review'
  return 'Risky'
}

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_SOURCES = [
  {
    id: 'src-001',
    name: 'prod-vector-index',
    displayName: 'Production Vector Index',
    type: 'Vector Database',
    sensitivity: 'Confidential',
    trustScore: 85,
    trustTrend: 'stable',
    status: 'Healthy',
    coverage: 94,
    lastSync: '4m ago',
    lastSyncFull: 'Apr 8 · 14:28 UTC',
    owner: 'raj.patel',
    ownerDisplay: 'Raj Patel',
    team: 'ML Platform',
    environment: 'Production',
    connector: 'Pinecone (v2.1)',
    location: 'pinecone://prod-vector-index',
    createdAt: 'Jan 10, 2026',
    lastUpdated: 'Apr 8, 2026',
    description: 'Primary production vector index for RAG-based query resolution. Indexes customer knowledge, policy documents, and product documentation. Feeds lim-agent-prod and threat-hunter-agent.',
    documentCount: 142850,
    chunkCount: 1284200,
    embeddingStatus: 'Current',
    freshnessWindow: '24h',
    piiPresent: true,
    piiTypes: ['email', 'name', 'org'],
    contentTypes: ['PDF', 'Markdown', 'JSON'],
    poisoningRisk: 'Low',
    stalenessRisk: 'Low',
    exposureRisk: 'Medium',
    dataQuality: 94,
    trustBreakdown: { freshness: 90, integrity: 88, accessControl: 84, validationScore: 79 },
    linkedAgents: ['lim-agent-prod', 'threat-hunter-agent'],
    linkedModels: ['gpt-4o', 'claude-3-5-sonnet'],
    linkedTools: ['rag-retrieval-tool', 'semantic-search-tool'],
    linkedPolicies: ['data-access-policy-v2', 'retention-policy'],
    linkedSessions: 2840,
    linkedAlerts: 0,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 14:28 UTC', event: 'Nightly sync completed — 142,850 docs verified', severity: 'Ok', resolved: true },
      { ts: 'Apr 7 · 14:25 UTC', event: 'Nightly sync completed', severity: 'Ok', resolved: true },
      { ts: 'Apr 6 · 14:22 UTC', event: 'Chunk count increased 2.1% — new docs indexed', severity: 'Low', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','ok','ok','ok'],
    recommendedActions: [],
    credential: { type: 'API Key (Pinecone)', age: '22d', expires: 'Jul 8, 2026', lastRotated: 'Mar 17, 2026' },
    poisoningDetails: null,
  },
  {
    id: 'src-002',
    name: 'finance-rag-bucket',
    displayName: 'Finance RAG Bucket',
    type: 'S3 / Object Storage',
    sensitivity: 'Restricted',
    trustScore: 38,
    trustTrend: 'down',
    status: 'Warning',
    coverage: 51,
    lastSync: '2d ago',
    lastSyncFull: 'Apr 6 · 08:00 UTC',
    owner: 'sarah.chen',
    ownerDisplay: 'Sarah Chen',
    team: 'Finance Ops',
    environment: 'Production',
    connector: 'AWS S3 (us-east-1)',
    location: 's3://finance-rag-bucket-prod',
    createdAt: 'Oct 3, 2025',
    lastUpdated: 'Apr 6, 2026',
    description: 'Restricted S3 bucket containing financial reports, earnings documents, and M&A data for RAG-based financial analysis. Stale content threshold exceeded. Unusual source drift detected.',
    documentCount: 38210,
    chunkCount: 412000,
    embeddingStatus: 'Stale',
    freshnessWindow: '6h',
    piiPresent: true,
    piiTypes: ['financial records', 'employee compensation', 'contract terms'],
    contentTypes: ['PDF', 'XLSX', 'CSV'],
    poisoningRisk: 'High',
    stalenessRisk: 'High',
    exposureRisk: 'High',
    dataQuality: 41,
    trustBreakdown: { freshness: 28, integrity: 45, accessControl: 38, validationScore: 42 },
    linkedAgents: ['finance-ops-service'],
    linkedModels: ['gpt-4o'],
    linkedTools: ['rag-retrieval-tool'],
    linkedPolicies: ['finance-data-policy', 'pii-handling-policy'],
    linkedSessions: 112,
    linkedAlerts: 4,
    linkedCases: 2,
    syncHistory: [
      { ts: 'Apr 7 · 12:00 UTC', event: 'Stale content threshold exceeded — 2d without sync', severity: 'High', resolved: false },
      { ts: 'Apr 6 · 08:00 UTC', event: 'Sync completed with 3 validation warnings', severity: 'Medium', resolved: false },
      { ts: 'Apr 5 · 09:00 UTC', event: 'Unusual source drift detected — 14% document mutation', severity: 'High', resolved: false },
      { ts: 'Apr 4 · 08:30 UTC', event: 'Sync completed successfully', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','warn','warn','fail','stale','stale'],
    recommendedActions: ['Trigger emergency sync immediately', 'Review document mutation (14% drift)', 'Isolate from low-trust agents', 'Rotate S3 connector credentials (87d old)'],
    credential: { type: 'IAM Role (arn:aws:iam::...)', age: '87d', expires: 'Never (IAM)', lastRotated: 'Jan 11, 2026' },
    poisoningDetails: { suspiciousUpdates: 3, unusualDrift: '14%', lastValidated: 'Apr 6 · 08:00 UTC', verdict: 'Under Review' },
  },
  {
    id: 'src-003',
    name: 'customer-docs-repo',
    displayName: 'Customer Docs Repository',
    type: 'Document Repository',
    sensitivity: 'Confidential',
    trustScore: 67,
    trustTrend: 'down',
    status: 'Stale',
    coverage: 72,
    lastSync: '1d ago',
    lastSyncFull: 'Apr 7 · 06:00 UTC',
    owner: 'raj.patel',
    ownerDisplay: 'Raj Patel',
    team: 'ML Platform',
    environment: 'Production',
    connector: 'GitHub Connector (v3)',
    location: 'github://acme-org/customer-docs',
    createdAt: 'Nov 20, 2025',
    lastUpdated: 'Apr 7, 2026',
    description: 'Customer-facing documentation repository indexed for support and resolution AI workflows. Freshness window is 12h — last sync is 1d behind schedule due to GitHub rate limiting.',
    documentCount: 24700,
    chunkCount: 198500,
    embeddingStatus: 'Stale',
    freshnessWindow: '12h',
    piiPresent: false,
    piiTypes: [],
    contentTypes: ['Markdown', 'HTML'],
    poisoningRisk: 'Low',
    stalenessRisk: 'High',
    exposureRisk: 'Low',
    dataQuality: 72,
    trustBreakdown: { freshness: 42, integrity: 81, accessControl: 75, validationScore: 70 },
    linkedAgents: ['support-resolution-agent'],
    linkedModels: ['claude-3-5-sonnet'],
    linkedTools: ['rag-retrieval-tool'],
    linkedPolicies: ['content-freshness-policy'],
    linkedSessions: 574,
    linkedAlerts: 1,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 08:00 UTC', event: 'Sync failed — GitHub API rate limit exceeded', severity: 'Medium', resolved: false },
      { ts: 'Apr 7 · 06:00 UTC', event: 'Sync completed — 45 new docs indexed', severity: 'Ok', resolved: true },
      { ts: 'Apr 6 · 06:00 UTC', event: 'Sync completed', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','ok','ok','stale'],
    recommendedActions: ['Resolve GitHub rate limit — increase API quota', 'Trigger manual sync'],
    credential: { type: 'GitHub OAuth Token', age: '31d', expires: 'May 8, 2026', lastRotated: 'Mar 8, 2026' },
    poisoningDetails: null,
  },
  {
    id: 'src-004',
    name: 'policy-memory-store',
    displayName: 'Policy Memory Store',
    type: 'Memory Store',
    sensitivity: 'Restricted',
    trustScore: 91,
    trustTrend: 'stable',
    status: 'Healthy',
    coverage: 99,
    lastSync: '8m ago',
    lastSyncFull: 'Apr 8 · 14:24 UTC',
    owner: 'sarah.chen',
    ownerDisplay: 'Sarah Chen',
    team: 'Security Ops',
    environment: 'Production',
    connector: 'Redis Enterprise (v7.2)',
    location: 'redis://policy-memory-prod.internal:6379',
    createdAt: 'Jan 5, 2026',
    lastUpdated: 'Apr 8, 2026',
    description: 'In-memory policy and rule store for real-time agent decision enforcement. Restricted access — only security ops agents may read or write. Continuously synced with integrity verification.',
    documentCount: 8440,
    chunkCount: 8440,
    embeddingStatus: 'N/A (key-value)',
    freshnessWindow: '15m',
    piiPresent: false,
    piiTypes: [],
    contentTypes: ['JSON', 'YAML'],
    poisoningRisk: 'Low',
    stalenessRisk: 'Low',
    exposureRisk: 'Low',
    dataQuality: 98,
    trustBreakdown: { freshness: 97, integrity: 94, accessControl: 90, validationScore: 88 },
    linkedAgents: ['threat-hunter-agent', 'policy-enforcement-agent'],
    linkedModels: [],
    linkedTools: ['policy-lookup-tool'],
    linkedPolicies: ['access-control-policy-v3', 'agent-enforcement-policy'],
    linkedSessions: 12200,
    linkedAlerts: 0,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 14:24 UTC', event: 'Policy update synced — 3 rules modified', severity: 'Ok', resolved: true },
      { ts: 'Apr 8 · 12:00 UTC', event: 'Validation passed — 8,440 rules healthy', severity: 'Ok', resolved: true },
      { ts: 'Apr 7 · 14:24 UTC', event: 'Policy update synced', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','ok','ok','ok'],
    recommendedActions: [],
    credential: { type: 'TLS Cert + Redis Auth', age: '5d', expires: 'Oct 8, 2026', lastRotated: 'Apr 3, 2026' },
    poisoningDetails: null,
  },
  {
    id: 'src-005',
    name: 'secops-confluence',
    displayName: 'SecOps Confluence Space',
    type: 'Confluence / Wiki',
    sensitivity: 'Internal',
    trustScore: 72,
    trustTrend: 'stable',
    status: 'Healthy',
    coverage: 85,
    lastSync: '2h ago',
    lastSyncFull: 'Apr 8 · 12:32 UTC',
    owner: 'sarah.chen',
    ownerDisplay: 'Sarah Chen',
    team: 'Security Ops',
    environment: 'Production',
    connector: 'Confluence Cloud (REST v2)',
    location: 'confluence://acme.atlassian.net/secops',
    createdAt: 'Feb 14, 2026',
    lastUpdated: 'Apr 8, 2026',
    description: 'Security operations Confluence space containing runbooks, incident playbooks, threat intel notes, and escalation procedures. Indexed for threat-hunter-agent enrichment.',
    documentCount: 1840,
    chunkCount: 31200,
    embeddingStatus: 'Current',
    freshnessWindow: '4h',
    piiPresent: false,
    piiTypes: [],
    contentTypes: ['Confluence Pages', 'Attachments'],
    poisoningRisk: 'Medium',
    stalenessRisk: 'Low',
    exposureRisk: 'Medium',
    dataQuality: 79,
    trustBreakdown: { freshness: 82, integrity: 71, accessControl: 68, validationScore: 66 },
    linkedAgents: ['threat-hunter-agent'],
    linkedModels: ['claude-3-5-sonnet'],
    linkedTools: ['rag-retrieval-tool', 'playbook-lookup-tool'],
    linkedPolicies: ['internal-content-policy'],
    linkedSessions: 398,
    linkedAlerts: 1,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 12:32 UTC', event: 'Sync completed — 12 pages updated', severity: 'Ok', resolved: true },
      { ts: 'Apr 8 · 08:30 UTC', event: 'Sensitivity upgrade — 2 pages reclassified to Confidential', severity: 'Medium', resolved: true },
      { ts: 'Apr 7 · 12:30 UTC', event: 'Sync completed', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','warn','ok','ok'],
    recommendedActions: ['Review 2 reclassified pages for appropriate access controls'],
    credential: { type: 'Confluence OAuth 2.0', age: '14d', expires: 'Jul 8, 2026', lastRotated: 'Mar 25, 2026' },
    poisoningDetails: { suspiciousUpdates: 1, unusualDrift: '2%', lastValidated: 'Apr 8 · 12:32 UTC', verdict: 'Monitoring' },
  },
  {
    id: 'src-006',
    name: 'external-knowledge-api',
    displayName: 'External Knowledge API',
    type: 'API Knowledge Source',
    sensitivity: 'Public',
    trustScore: 61,
    trustTrend: 'down',
    status: 'Warning',
    coverage: 63,
    lastSync: '45m ago',
    lastSyncFull: 'Apr 8 · 13:47 UTC',
    owner: 'raj.patel',
    ownerDisplay: 'Raj Patel',
    team: 'ML Platform',
    environment: 'Production',
    connector: 'REST Webhook (v1)',
    location: 'https://api.external-knowledge.io/v2/query',
    createdAt: 'Mar 1, 2026',
    lastUpdated: 'Apr 8, 2026',
    description: 'External third-party knowledge API providing public industry intelligence and market data. Intermittent latency and partial response failures observed in the last 6h.',
    documentCount: 0,
    chunkCount: 0,
    embeddingStatus: 'N/A (live API)',
    freshnessWindow: '1h',
    piiPresent: false,
    piiTypes: [],
    contentTypes: ['JSON REST'],
    poisoningRisk: 'Medium',
    stalenessRisk: 'Medium',
    exposureRisk: 'Low',
    dataQuality: 63,
    trustBreakdown: { freshness: 70, integrity: 55, accessControl: 72, validationScore: 58 },
    linkedAgents: ['lim-agent-prod'],
    linkedModels: ['gpt-4o'],
    linkedTools: ['api-fetch-tool'],
    linkedPolicies: ['external-source-policy'],
    linkedSessions: 211,
    linkedAlerts: 2,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 13:47 UTC', event: 'API response — 38% request timeout', severity: 'Medium', resolved: false },
      { ts: 'Apr 8 · 12:47 UTC', event: 'API response — degraded (latency 8.4s)', severity: 'Medium', resolved: false },
      { ts: 'Apr 8 · 11:47 UTC', event: 'API response — healthy', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','ok','warn','warn'],
    recommendedActions: ['Check external API provider status page', 'Add circuit breaker for timeout handling', 'Consider response caching fallback'],
    credential: { type: 'API Key (Bearer)', age: '38d', expires: 'Jun 1, 2026', lastRotated: 'Mar 1, 2026' },
    poisoningDetails: null,
  },
  {
    id: 'src-007',
    name: 'hr-sharepoint-drive',
    displayName: 'HR SharePoint Drive',
    type: 'SharePoint / Drive',
    sensitivity: 'Restricted',
    trustScore: 44,
    trustTrend: 'down',
    status: 'Failed',
    coverage: 0,
    lastSync: '3d ago',
    lastSyncFull: 'Apr 5 · 10:00 UTC',
    owner: 'admin',
    ownerDisplay: 'Platform Admin',
    team: 'HR / People Ops',
    environment: 'Production',
    connector: 'Microsoft Graph API (v1.0)',
    location: 'sharepoint://acme.sharepoint.com/sites/hr-docs',
    createdAt: 'Sep 15, 2025',
    lastUpdated: 'Apr 5, 2026',
    description: 'HR and People Ops SharePoint drive containing employee records, compensation data, and org structure documents. Connector authentication expired — all syncs failing for 3 days.',
    documentCount: 19800,
    chunkCount: 144000,
    embeddingStatus: 'Stale',
    freshnessWindow: '12h',
    piiPresent: true,
    piiTypes: ['SSN', 'compensation', 'performance reviews', 'personal data'],
    contentTypes: ['Word', 'Excel', 'PDF'],
    poisoningRisk: 'Medium',
    stalenessRisk: 'High',
    exposureRisk: 'High',
    dataQuality: 44,
    trustBreakdown: { freshness: 12, integrity: 55, accessControl: 48, validationScore: 60 },
    linkedAgents: [],
    linkedModels: [],
    linkedTools: [],
    linkedPolicies: ['pii-handling-policy', 'hr-data-policy'],
    linkedSessions: 0,
    linkedAlerts: 3,
    linkedCases: 1,
    syncHistory: [
      { ts: 'Apr 8 · 08:00 UTC', event: 'Sync failed — OAuth token expired', severity: 'High', resolved: false },
      { ts: 'Apr 7 · 08:00 UTC', event: 'Sync failed — OAuth token expired', severity: 'High', resolved: false },
      { ts: 'Apr 6 · 08:00 UTC', event: 'Sync failed — OAuth token expired', severity: 'High', resolved: false },
      { ts: 'Apr 5 · 10:00 UTC', event: 'Last successful sync before connector failure', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','fail','fail','fail'],
    recommendedActions: ['Re-authenticate Microsoft Graph OAuth immediately', 'Review PII exposure during outage window', 'Consider quarantine until auth restored'],
    credential: { type: 'Microsoft OAuth 2.0', age: '182d', expires: 'EXPIRED', lastRotated: 'Oct 8, 2025' },
    poisoningDetails: null,
  },
  {
    id: 'src-008',
    name: 'core-prompt-library',
    displayName: 'Core Prompt Library',
    type: 'Prompt Library',
    sensitivity: 'Internal',
    trustScore: 88,
    trustTrend: 'up',
    status: 'Healthy',
    coverage: 100,
    lastSync: '1h ago',
    lastSyncFull: 'Apr 8 · 13:30 UTC',
    owner: 'raj.patel',
    ownerDisplay: 'Raj Patel',
    team: 'ML Platform',
    environment: 'Production',
    connector: 'Internal Git (main)',
    location: 'git://core-platform/prompt-registry',
    createdAt: 'Dec 1, 2025',
    lastUpdated: 'Apr 8, 2026',
    description: 'Versioned prompt library used across all production agents. Contains system prompts, few-shot templates, and safety instructions. Integrity-checked on every sync.',
    documentCount: 220,
    chunkCount: 220,
    embeddingStatus: 'N/A (template store)',
    freshnessWindow: '1h',
    piiPresent: false,
    piiTypes: [],
    contentTypes: ['YAML', 'JSON', 'Jinja2'],
    poisoningRisk: 'Low',
    stalenessRisk: 'Low',
    exposureRisk: 'Low',
    dataQuality: 96,
    trustBreakdown: { freshness: 91, integrity: 92, accessControl: 88, validationScore: 84 },
    linkedAgents: ['lim-agent-prod', 'threat-hunter-agent', 'finance-ops-service', 'policy-enforcement-agent'],
    linkedModels: ['gpt-4o', 'claude-3-5-sonnet', 'amazon-bedrock'],
    linkedTools: ['prompt-fetch-tool'],
    linkedPolicies: ['prompt-governance-policy'],
    linkedSessions: 18400,
    linkedAlerts: 0,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 13:30 UTC', event: 'Sync + integrity check passed — 220 prompts verified', severity: 'Ok', resolved: true },
      { ts: 'Apr 8 · 12:30 UTC', event: 'New prompt version committed — v2.14.1', severity: 'Low', resolved: true },
      { ts: 'Apr 7 · 13:30 UTC', event: 'Sync + integrity check passed', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','ok','ok','ok'],
    recommendedActions: [],
    credential: { type: 'SSH Deploy Key', age: '10d', expires: 'Never', lastRotated: 'Mar 29, 2026' },
    poisoningDetails: null,
  },
  {
    id: 'src-009',
    name: 'billing-sql-db',
    displayName: 'Billing SQL Database',
    type: 'SQL / Structured Data',
    sensitivity: 'Confidential',
    trustScore: 65,
    trustTrend: 'stable',
    status: 'Syncing',
    coverage: 88,
    lastSync: '12m ago',
    lastSyncFull: 'Apr 8 · 14:20 UTC',
    owner: 'admin',
    ownerDisplay: 'Platform Admin',
    team: 'Billing Platform',
    environment: 'Production',
    connector: 'PostgreSQL (v15.2)',
    location: 'postgres://billing-prod.internal:5432/billing',
    createdAt: 'Nov 5, 2025',
    lastUpdated: 'Apr 8, 2026',
    description: 'Billing and subscription data structured source. Indexed for billing analytics and anomaly detection. Currently syncing — schema drift detected in the last run.',
    documentCount: 4210000,
    chunkCount: 0,
    embeddingStatus: 'N/A (structured)',
    freshnessWindow: '1h',
    piiPresent: true,
    piiTypes: ['payment method', 'billing address', 'invoice data'],
    contentTypes: ['SQL Tables', 'Views'],
    poisoningRisk: 'Low',
    stalenessRisk: 'Low',
    exposureRisk: 'Medium',
    dataQuality: 81,
    trustBreakdown: { freshness: 78, integrity: 72, accessControl: 64, validationScore: 67 },
    linkedAgents: ['billing-anomaly-agent'],
    linkedModels: ['gpt-4o'],
    linkedTools: ['sql-query-tool'],
    linkedPolicies: ['financial-data-policy', 'pii-handling-policy'],
    linkedSessions: 880,
    linkedAlerts: 1,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 14:20 UTC', event: 'Sync in progress — schema drift detected (2 columns)', severity: 'Medium', resolved: false },
      { ts: 'Apr 8 · 13:20 UTC', event: 'Sync completed — 4.2M rows updated', severity: 'Ok', resolved: true },
      { ts: 'Apr 7 · 13:20 UTC', event: 'Sync completed', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','ok','ok','warn'],
    recommendedActions: ['Review schema drift — 2 column type changes detected'],
    credential: { type: 'Service Account (pg_read)', age: '44d', expires: 'Never', lastRotated: 'Feb 23, 2026' },
    poisoningDetails: null,
  },
  {
    id: 'src-010',
    name: 'threat-intel-feed',
    displayName: 'Threat Intelligence Feed',
    type: 'API Knowledge Source',
    sensitivity: 'Internal',
    trustScore: 82,
    trustTrend: 'up',
    status: 'Healthy',
    coverage: 91,
    lastSync: '22m ago',
    lastSyncFull: 'Apr 8 · 14:10 UTC',
    owner: 'sarah.chen',
    ownerDisplay: 'Sarah Chen',
    team: 'Security Ops',
    environment: 'Production',
    connector: 'STIX/TAXII 2.1 Feed',
    location: 'taxii://threat-intel.internal/feeds/v2',
    createdAt: 'Feb 28, 2026',
    lastUpdated: 'Apr 8, 2026',
    description: 'Live threat intelligence feed providing IOCs, TTPs, and threat actor profiles. Ingested continuously by threat-hunter-agent for enrichment and real-time triage.',
    documentCount: 0,
    chunkCount: 0,
    embeddingStatus: 'N/A (streaming)',
    freshnessWindow: '30m',
    piiPresent: false,
    piiTypes: [],
    contentTypes: ['STIX 2.1', 'JSON'],
    poisoningRisk: 'Low',
    stalenessRisk: 'Low',
    exposureRisk: 'Low',
    dataQuality: 89,
    trustBreakdown: { freshness: 90, integrity: 84, accessControl: 79, validationScore: 76 },
    linkedAgents: ['threat-hunter-agent'],
    linkedModels: ['claude-3-5-sonnet'],
    linkedTools: ['threat-lookup-tool', 'ioc-enrichment-tool'],
    linkedPolicies: ['external-source-policy', 'threat-intel-policy'],
    linkedSessions: 3210,
    linkedAlerts: 0,
    linkedCases: 0,
    syncHistory: [
      { ts: 'Apr 8 · 14:10 UTC', event: 'Feed updated — 142 new IOCs ingested', severity: 'Ok', resolved: true },
      { ts: 'Apr 8 · 13:40 UTC', event: 'Feed updated — 78 IOCs ingested', severity: 'Ok', resolved: true },
      { ts: 'Apr 8 · 13:10 UTC', event: 'Feed updated', severity: 'Ok', resolved: true },
    ],
    healthTimeline: ['ok','ok','ok','ok','ok','ok','ok'],
    recommendedActions: [],
    credential: { type: 'TAXII Bearer Token', age: '8d', expires: 'May 8, 2026', lastRotated: 'Mar 31, 2026' },
    poisoningDetails: null,
  },
]

// ── Mock sync events ───────────────────────────────────────────────────────────

const SYNC_EVENTS = [
  { id: 'se-001', ts: 'Apr 8 · 14:20 UTC', source: 'billing-sql-db',       event: 'Schema drift detected — 2 column type changes',     impact: 'Medium', result: 'Warning'  },
  { id: 'se-002', ts: 'Apr 8 · 13:47 UTC', source: 'external-knowledge-api',event: 'API response — 38% request timeout rate',            impact: 'Medium', result: 'Warning'  },
  { id: 'se-003', ts: 'Apr 8 · 12:32 UTC', source: 'secops-confluence',     event: 'Sensitivity upgrade — 2 pages reclassified',         impact: 'Medium', result: 'Detected' },
  { id: 'se-004', ts: 'Apr 8 · 08:00 UTC', source: 'hr-sharepoint-drive',   event: 'OAuth token expired — connector sync failure',        impact: 'High',   result: 'Detected' },
  { id: 'se-005', ts: 'Apr 7 · 12:00 UTC', source: 'finance-rag-bucket',    event: 'Stale content threshold exceeded — 2d without sync', impact: 'High',   result: 'Detected' },
  { id: 'se-006', ts: 'Apr 7 · 14:25 UTC', source: 'prod-vector-index',     event: 'Nightly sync completed — 142,850 docs verified',     impact: 'Low',    result: 'Resolved' },
  { id: 'se-007', ts: 'Apr 5 · 09:00 UTC', source: 'finance-rag-bucket',    event: 'Unusual source drift — 14% document mutation',       impact: 'High',   result: 'Detected' },
  { id: 'se-008', ts: 'Apr 4 · 08:00 UTC', source: 'customer-docs-repo',    event: 'Sync failed — GitHub rate limit exceeded',           impact: 'Medium', result: 'Detected' },
  { id: 'se-009', ts: 'Apr 5 · 10:00 UTC', source: 'hr-sharepoint-drive',   event: 'Last successful sync before connector failure',       impact: 'Low',    result: 'Resolved' },
  { id: 'se-010', ts: 'Apr 8 · 13:30 UTC', source: 'core-prompt-library',   event: 'Integrity check passed — 220 prompts verified',      impact: 'Low',    result: 'Resolved' },
]

// ── Primitive components ───────────────────────────────────────────────────────

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

function OwnerAvatar({ name }) {
  const parts   = name.split('.')
  const initials = parts.map(p => p[0]?.toUpperCase() ?? '').join('').slice(0, 2)
  const colors  = ['bg-blue-500','bg-violet-500','bg-emerald-500','bg-amber-500','bg-rose-500','bg-cyan-500']
  const color   = colors[name.charCodeAt(0) % colors.length]
  return (
    <div className={cn('w-6 h-6 rounded-full flex items-center justify-center text-white font-bold text-[9px] shrink-0', color)}>
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

function CoverageBar({ pct }) {
  const color = pct >= 90 ? 'bg-emerald-400' : pct >= 70 ? 'bg-yellow-400' : pct >= 50 ? 'bg-orange-400' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2 min-w-[72px]">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn('text-[10.5px] font-mono tabular-nums font-black',
        pct >= 90 ? 'text-emerald-600' : pct >= 70 ? 'text-yellow-600' : pct >= 50 ? 'text-orange-600' : 'text-red-600',
      )}>{pct}%</span>
    </div>
  )
}

function RiskBar({ label, level }) {
  const cfg = RISK_LEVEL_CFG[level] || RISK_LEVEL_CFG.Low
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] font-semibold text-gray-600">{label}</span>
        <span className={cn('text-[10px] font-black px-2 py-0.5 rounded-full border', cfg.color, cfg.bg, cfg.border)}>{level}</span>
      </div>
      <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full transition-all duration-500', cfg.bar)} style={{ width: cfg.width }} />
      </div>
    </div>
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

// ── Trust / score components ───────────────────────────────────────────────────

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
  if (trend === 'up')   return <TrendingUp   size={11} className="text-emerald-500" />
  if (trend === 'down') return <TrendingDown  size={11} className="text-red-400" />
  return                       <Minus         size={11} className="text-gray-300" />
}

function StatusPip({ status }) {
  const cfg = SOURCE_STATUS_CFG[status] || SOURCE_STATUS_CFG['Healthy']
  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold border', cfg.text, cfg.bg, cfg.border)}>
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', cfg.dot, cfg.pulse ? 'animate-pulse' : '')} />
      {status}
    </span>
  )
}

function TypeChip({ type, compact = false }) {
  const cfg  = SOURCE_TYPE_CFG[type] || SOURCE_TYPE_CFG['Document Repository']
  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1 rounded border text-[10px] font-semibold', cfg.color, cfg.bg, cfg.border, compact ? 'px-1 py-px' : 'px-1.5 py-0.5')}>
      <Icon size={9} />
      {type}
    </span>
  )
}

function SensitivityBadge({ sensitivity }) {
  const cfg = SENSITIVITY_CFG[sensitivity] || SENSITIVITY_CFG['Internal']
  return (
    <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-black', cfg.color, cfg.bg, cfg.border)}>
      <Lock size={8} className="shrink-0" />
      {sensitivity}
    </span>
  )
}

function HealthTimeline({ history }) {
  const labels = ['7d ago', '6d', '5d', '4d', '3d', '2d', 'Today']
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        {history.map((state, idx) => {
          const cfg = HEALTH_DOT_CFG[state] || HEALTH_DOT_CFG.ok
          return (
            <div key={idx} className="flex-1 flex flex-col items-center gap-1">
              <div className={cn('w-4 h-4 rounded-full ring-2 ring-white shadow-sm', cfg.bg)} title={labels[idx]} />
              <span className="text-[8px] text-gray-400 font-medium whitespace-nowrap">{labels[idx]}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Source row ────────────────────────────────────────────────────────────────

function SourceRow({ source: src, isSelected, onSelect }) {
  const typCfg = SOURCE_TYPE_CFG[src.type] || SOURCE_TYPE_CFG['Document Repository']
  const stCfg  = SOURCE_STATUS_CFG[src.status] || SOURCE_STATUS_CFG['Healthy']
  const TypeIcon = typCfg.icon
  const syncColor =
    src.lastSync === 'Never'                                      ? 'text-gray-300' :
    src.lastSync.includes('3d') || src.lastSync.includes('2d')   ? 'text-red-500 font-semibold' :
    src.lastSync.includes('1d')                                   ? 'text-orange-500 font-semibold' :
    src.lastSync.includes('h ago') && !src.lastSync.includes('1h') ? 'text-gray-500' :
    'text-gray-500'

  return (
    <tr
      onClick={() => onSelect(src.id)}
      className={cn(
        'cursor-pointer transition-colors duration-100 group border-l-[3px]',
        stCfg.bdr,
        isSelected ? 'bg-blue-50/60' : 'hover:bg-gray-50/40',
      )}
    >
      <td className="w-0 p-0" />
      {/* Name */}
      <td className="px-3.5 py-2.5">
        <div className="flex items-center gap-2.5">
          <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center border shrink-0 shadow-sm', typCfg.bg, typCfg.border)}>
            <TypeIcon size={14} className={typCfg.color} />
          </div>
          <div className="min-w-0">
            <p className={cn('text-[12.5px] font-semibold font-mono leading-snug truncate', isSelected ? 'text-blue-700' : 'text-gray-800')}>
              {src.name}
            </p>
            <p className="text-[10px] font-medium truncate leading-tight flex items-center gap-1">
                {src.piiPresent && <span className="text-red-500 font-black">· PII</span>}
            </p>
          </div>
        </div>
      </td>
      {/* Type */}
      <td className="px-3.5 py-2.5"><TypeChip type={src.type} compact /></td>
      {/* Sensitivity */}
      <td className="px-3.5 py-2.5"><SensitivityBadge sensitivity={src.sensitivity} /></td>
      {/* Trust */}
      <td className="px-3.5 py-2.5">
        <div className="flex items-center gap-1.5">
          <TrustMeter score={src.trustScore} />
          <TrendIcon trend={src.trustTrend} />
        </div>
      </td>
      {/* Coverage */}
      <td className="px-3.5 py-2.5"><CoverageBar pct={src.coverage} /></td>
      {/* Last Sync */}
      <td className="px-3.5 py-2.5">
        <span className={cn('text-[11px] font-mono', syncColor)}>{src.lastSync}</span>
      </td>
      {/* Status */}
      <td className="px-3.5 py-2.5"><StatusPip status={src.status} /></td>
    </tr>
  )
}

// ── Source list (grouped by sensitivity) ──────────────────────────────────────

function SourceList({ sources, selectedId, onSelect }) {
  const groups = {}
  const orderedSens = []
  SENSITIVITY_ORDER.forEach(s => {
    const rows = sources.filter(src => src.sensitivity === s)
    if (rows.length > 0) {
      groups[s] = rows
      orderedSens.push(s)
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
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[200px] min-w-[160px]">Source</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[160px]">Type</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[110px]">Sensitivity</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[110px]">Trust</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[100px]">Coverage</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[80px]">Last Sync</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[110px]">Status</th>
            </tr>
          </thead>
        </table>
      </div>

      <div className="divide-y divide-gray-100">
        {orderedSens.map(sens => {
          const cfg  = SENSITIVITY_CFG[sens]
          const rows = groups[sens]
          return (
            <div key={sens}>
              {/* Sensitivity group header */}
              <div className="px-4 py-2 flex items-center gap-2.5 bg-gray-50 border-b border-gray-100">
                <div className={cn('w-5 h-5 rounded-md flex items-center justify-center border shrink-0', cfg.bg, cfg.border)}>
                  <Lock size={9} className={cfg.color} />
                </div>
                <span className={cn('text-[10px] font-black uppercase tracking-[0.08em]', cfg.color)}>{sens}</span>
                <span className="ml-auto text-[9.5px] font-semibold text-gray-300 tabular-nums">
                  {rows.length} {rows.length === 1 ? 'source' : 'sources'}
                </span>
              </div>

              <table className="w-full border-collapse">
                <tbody className="divide-y divide-gray-50">
                  {rows.map(src => (
                    <SourceRow
                      key={src.id}
                      source={src}
                      isSelected={src.id === selectedId}
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
    { label: 'Freshness',        value: scores.freshness,       color: 'bg-blue-400'    },
    { label: 'Integrity',        value: scores.integrity,       color: 'bg-violet-400'  },
    { label: 'Access Control',   value: scores.accessControl,   color: 'bg-amber-400'   },
    { label: 'Validation Score', value: scores.validationScore, color: 'bg-emerald-400' },
  ]
  return (
    <div className="space-y-2.5">
      {dims.map(d => (
        <div key={d.label}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] font-medium text-gray-600">{d.label}</span>
            <span className={cn('text-[11px] font-bold tabular-nums',
              d.value >= 80 ? 'text-emerald-600' : d.value >= 60 ? 'text-yellow-600' : 'text-red-600',
            )}>{d.value}</span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <div className={cn('h-full rounded-full transition-all duration-500', d.color)} style={{ width: `${d.value}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function DependencyChip({ label, icon: Icon, color, bg, border }) {
  return (
    <div className={cn('inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-[10.5px] font-semibold shadow-sm', color, bg, border)}>
      {Icon && <Icon size={10} />}
      <span className="font-mono">{label}</span>
    </div>
  )
}

function RecommendedActions({ actions }) {
  if (!actions || actions.length === 0) return (
    <div className="flex items-center gap-2 px-3.5 py-3 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-xl">
      <ShieldCheck size={13} className="text-emerald-500 shrink-0" />
      <p className="text-[12px] font-medium text-emerald-700">No recommended actions — posture is clean.</p>
    </div>
  )
  return (
    <div className="space-y-1.5">
      {actions.map((action, idx) => (
        <div key={idx} className="flex items-center gap-2.5 px-3.5 py-2.5 bg-white border border-gray-150 rounded-xl hover:border-gray-200 hover:bg-gray-50/40 transition-colors cursor-pointer group shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <ArrowRight size={11} className="text-gray-400 shrink-0 group-hover:text-blue-500 transition-colors" />
          <span className="text-[12px] font-medium text-gray-700 group-hover:text-gray-900 transition-colors">{action}</span>
        </div>
      ))}
    </div>
  )
}

// ── Source detail panel ───────────────────────────────────────────────────────

function SourceDetailPanel({ source: src, onClose }) {
  const [activeTab, setActiveTab] = useState('Overview')
  const tier    = getTrustTier(src.trustScore)
  const trustCfg = TRUST_CFG[tier]
  const typCfg  = SOURCE_TYPE_CFG[src.type] || SOURCE_TYPE_CFG['Document Repository']
  const TypeIcon = typCfg.icon
  const stCfg   = SOURCE_STATUS_CFG[src.status] || SOURCE_STATUS_CFG['Healthy']

  const credExpired = src.credential.expires === 'EXPIRED'

  return (
    <div className="w-[460px] shrink-0 bg-white border border-gray-200 rounded-xl shadow-sm flex flex-col overflow-hidden self-start sticky top-0 max-h-[calc(100vh-140px)]">
      {/* Accent strip */}
      <div className={cn('h-[3px] w-full shrink-0', trustCfg.strip)} />

      {/* Header */}
      <div className={cn('px-5 pt-4 pb-3.5 border-b border-gray-100 shrink-0', trustCfg.headerBg)}>
        {/* Row 1: icon + name + close */}
        <div className="flex items-start gap-3 mb-2.5">
          <div className={cn('w-9 h-9 rounded-xl flex items-center justify-center border shadow-sm shrink-0', typCfg.bg, typCfg.border)}>
            <TypeIcon size={16} className={typCfg.color} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[13.5px] font-black font-mono text-gray-900 leading-snug truncate">{src.name}</p>
            <p className="text-[11px] text-gray-500 font-medium leading-tight truncate">{src.displayName}</p>
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
          <StatusPip status={src.status} />
          <TypeChip type={src.type} />
          <SensitivityBadge sensitivity={src.sensitivity} />
          <TrustTierBadge score={src.trustScore} />
        </div>

        {/* Row 3: owner + env + last sync */}
        <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-3">
          <OwnerAvatar name={src.owner} />
          <span className="font-semibold text-gray-600">{src.ownerDisplay}</span>
          <span className="text-gray-300">·</span>
          <span className={cn(
            'text-[10px] font-semibold px-1 py-px rounded-sm border',
            src.environment === 'Production' ? 'text-gray-400 border-gray-200 bg-gray-50' : 'text-amber-600 border-amber-200 bg-amber-50',
          )}>{src.environment}</span>
          <span className="text-gray-300">·</span>
          <Clock size={10} className="text-gray-300" />
          <span className="font-mono text-gray-400">{src.lastSync}</span>
        </div>

        {/* Row 4: trust meter */}
        <div className="mb-3.5">
          <TrustMeter score={src.trustScore} size="lg" />
        </div>

        {/* Row 5: actions */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <Link size={11} /> View Dependencies
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-blue-600 border-blue-200 hover:bg-blue-50">
            <Activity size={11} /> Run Validation
          </Button>
          <div className="w-px h-5 bg-gray-200 mx-0.5" />
          {src.status !== 'Failed' && src.status !== 'Quarantined' && (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-orange-600 border-orange-200 hover:bg-orange-50">
              <Pause size={11} /> Pause Sync
            </Button>
          )}
          {(src.linkedAlerts > 0 || src.status === 'Failed' || src.status === 'Quarantined') && (
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
            {/* Status banners */}
            {(src.status === 'Failed' || src.status === 'Quarantined') && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-xl">
                <ShieldAlert size={13} className="text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-red-700">
                    {src.status === 'Quarantined' ? 'Source Quarantined' : 'Sync Connector Failed'}
                  </p>
                  <p className="text-[11px] text-red-600 mt-0.5 leading-snug">
                    {src.syncHistory[0]?.event || 'Review sync history for details.'}
                  </p>
                </div>
              </div>
            )}
            {src.status === 'Stale' && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-amber-50 border border-amber-200 border-l-[3px] border-l-amber-500 rounded-xl">
                <Clock size={13} className="text-amber-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-amber-700">Stale Content Detected</p>
                  <p className="text-[11px] text-amber-600 mt-0.5 leading-snug">Source has exceeded its freshness window. Last sync: {src.lastSyncFull}.</p>
                </div>
              </div>
            )}
            {src.poisoningDetails && getTrustTier(src.trustScore) === 'Risky' && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-orange-50 border border-orange-200 border-l-[3px] border-l-orange-500 rounded-xl">
                <Siren size={13} className="text-orange-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-orange-700">Poisoning Risk — {src.poisoningDetails.verdict}</p>
                  <p className="text-[11px] text-orange-600 mt-0.5 leading-snug">
                    {src.poisoningDetails.suspiciousUpdates} suspicious updates detected. Source drift: {src.poisoningDetails.unusualDrift}.
                  </p>
                </div>
              </div>
            )}

            {/* Description */}
            <div>
              <SectionLabel>Description</SectionLabel>
              <p className="text-[12.5px] text-gray-700 leading-relaxed">{src.description}</p>
            </div>

            {/* Source details */}
            <div>
              <SectionLabel>Source Details</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-1">
                <MetaRow label="Owner"       value={src.ownerDisplay} />
                <MetaRow label="Team"        value={src.team} />
                <MetaRow label="Environment" value={src.environment} />
                <MetaRow label="Connector"   value={src.connector} />
                <MetaRow label="Location"    value={src.location}   mono />
                <MetaRow label="Created"     value={src.createdAt} />
                <MetaRow label="Last Sync"   value={src.lastSyncFull} mono />
              </div>
            </div>

            {/* Connector credential */}
            <div>
              <SectionLabel>Connector Credential</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-1">
                <MetaRow label="Type"          value={src.credential.type} />
                <MetaRow label="Credential Age" value={src.credential.age}
                  highlight={parseInt(src.credential.age) > 90 ? 'danger' : parseInt(src.credential.age) > 30 ? 'warn' : undefined} />
                <MetaRow label="Expires"       value={src.credential.expires}
                  highlight={credExpired ? 'danger' : undefined} />
                <MetaRow label="Last Rotated"  value={src.credential.lastRotated}
                  highlight={credExpired ? 'danger' : undefined} />
              </div>
            </div>

            {/* Recommended actions */}
            <div>
              <SectionLabel>Recommended Actions</SectionLabel>
              <RecommendedActions actions={src.recommendedActions} />
            </div>
          </div>
        )}

        {/* ── Trust & Security ── */}
        {activeTab === 'Trust & Security' && (
          <div className="p-5 space-y-5">
            {/* Trust score */}
            <div>
              <SectionLabel>Trust Score</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-3.5">
                <TrustMeter score={src.trustScore} size="lg" />
              </div>
            </div>

            {/* Risk assessment */}
            <div>
              <SectionLabel>Risk Assessment</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-3.5 space-y-3">
                <RiskBar label="Poisoning Risk"    level={src.poisoningRisk} />
                <RiskBar label="Staleness Risk"    level={src.stalenessRisk} />
                <RiskBar label="Exposure Risk"     level={src.exposureRisk} />
              </div>
            </div>

            {/* Poisoning details card */}
            {src.poisoningDetails && (
              <div>
                <SectionLabel>Poisoning Risk Details</SectionLabel>
                <div className="flex items-start gap-2.5 px-3.5 py-3 bg-orange-50 border border-orange-200 border-l-[3px] border-l-orange-500 rounded-xl">
                  <Siren size={13} className="text-orange-500 mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[11.5px] font-semibold text-orange-700 mb-2">Verdict: {src.poisoningDetails.verdict}</p>
                    <div className="bg-white/60 rounded-lg border border-orange-100 px-3 py-1">
                      <MetaRow label="Suspicious Updates" value={`${src.poisoningDetails.suspiciousUpdates} events`} highlight="danger" />
                      <MetaRow label="Source Drift"       value={src.poisoningDetails.unusualDrift} highlight="warn" />
                      <MetaRow label="Last Validated"     value={src.poisoningDetails.lastValidated} mono />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Trust breakdown */}
            <div>
              <SectionLabel>Trust Breakdown</SectionLabel>
              <TrustBreakdown scores={src.trustBreakdown} />
            </div>

            {/* Freshness health timeline */}
            <div>
              <SectionLabel>Sync Health — Last 7 Days</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-3.5">
                <HealthTimeline history={src.healthTimeline} />
                <div className="flex items-center gap-4 mt-3 pt-2.5 border-t border-gray-100">
                  {[
                    { state: 'ok',    label: 'Healthy', dotBg: 'bg-emerald-400' },
                    { state: 'warn',  label: 'Warning', dotBg: 'bg-yellow-400'  },
                    { state: 'fail',  label: 'Failed',  dotBg: 'bg-red-500'     },
                    { state: 'stale', label: 'Stale',   dotBg: 'bg-amber-400'   },
                  ].map(({ state, label, dotBg }) => (
                    <div key={state} className="flex items-center gap-1">
                      <span className={cn('w-2.5 h-2.5 rounded-full', dotBg)} />
                      <span className="text-[9.5px] font-medium text-gray-400">{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Dependencies ── */}
        {activeTab === 'Dependencies' && (
          <div className="p-5 space-y-5">
            {/* Dependency flow */}
            <div>
              <SectionLabel>Dependency Chain</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-4">
                <div className="flex items-center flex-wrap gap-1.5">
                  {/* Source */}
                  <DependencyChip
                    label={src.name}
                    icon={SOURCE_TYPE_CFG[src.type]?.icon}
                    color={SOURCE_TYPE_CFG[src.type]?.color || 'text-gray-600'}
                    bg={SOURCE_TYPE_CFG[src.type]?.bg || 'bg-gray-100'}
                    border={SOURCE_TYPE_CFG[src.type]?.border || 'border-gray-200'}
                  />
                  {src.linkedAgents.length > 0 && (
                    <>
                      <ArrowRight size={11} className="text-gray-400 shrink-0" />
                      <div className="flex flex-wrap gap-1">
                        {src.linkedAgents.slice(0, 2).map(a => (
                          <DependencyChip key={a} label={a} color="text-violet-600" bg="bg-violet-50" border="border-violet-200" />
                        ))}
                        {src.linkedAgents.length > 2 && (
                          <span className="text-[10px] font-semibold text-gray-400 self-center">+{src.linkedAgents.length - 2}</span>
                        )}
                      </div>
                    </>
                  )}
                  {src.linkedTools.length > 0 && (
                    <>
                      <ArrowRight size={11} className="text-gray-400 shrink-0" />
                      <div className="flex flex-wrap gap-1">
                        {src.linkedTools.slice(0, 2).map(t => (
                          <DependencyChip key={t} label={t} color="text-emerald-600" bg="bg-emerald-50" border="border-emerald-200" />
                        ))}
                      </div>
                    </>
                  )}
                  {src.linkedSessions > 0 && (
                    <>
                      <ArrowRight size={11} className="text-gray-400 shrink-0" />
                      <span className="text-[10.5px] font-semibold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-1 rounded-lg">
                        {src.linkedSessions.toLocaleString()} sessions
                      </span>
                    </>
                  )}
                </div>
                <p className="text-[10.5px] text-gray-400 mt-3 leading-snug">
                  Access flows from this source through linked agents and tools into active sessions.
                </p>
              </div>
            </div>

            {/* Linked agents */}
            {src.linkedAgents.length > 0 && (
              <div>
                <SectionLabel>Linked Agents ({src.linkedAgents.length})</SectionLabel>
                <div className="space-y-1.5">
                  {src.linkedAgents.map(a => (
                    <div key={a} className="flex items-center gap-2 px-3 py-1.5 bg-violet-50 border border-violet-100 border-l-[3px] border-l-violet-400 rounded-lg shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <CheckCircle2 size={11} className="text-violet-500 shrink-0" />
                      <span className="text-[11px] font-mono text-violet-800 leading-snug">{a}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {src.linkedAgents.length === 0 && (
              <div className="flex items-center gap-2 px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl">
                <Activity size={12} className="text-gray-300 shrink-0" />
                <p className="text-[11.5px] text-gray-400">No agents currently linked to this source.</p>
              </div>
            )}

            {/* Linked models */}
            {src.linkedModels.length > 0 && (
              <div>
                <SectionLabel>Linked Models ({src.linkedModels.length})</SectionLabel>
                <div className="space-y-1.5">
                  {src.linkedModels.map(m => (
                    <div key={m} className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border border-blue-100 border-l-[3px] border-l-blue-400 rounded-lg shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <Cpu size={11} className="text-blue-500 shrink-0" />
                      <span className="text-[11px] font-mono text-blue-800 leading-snug">{m}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Linked tools */}
            {src.linkedTools.length > 0 && (
              <div>
                <SectionLabel>Linked Tools ({src.linkedTools.length})</SectionLabel>
                <div className="space-y-1.5">
                  {src.linkedTools.map(t => (
                    <div key={t} className="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-lg shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <Link size={11} className="text-emerald-500 shrink-0" />
                      <span className="text-[11px] font-mono text-emerald-800 leading-snug">{t}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Linked policies */}
            {src.linkedPolicies.length > 0 && (
              <div>
                <SectionLabel>Linked Policies</SectionLabel>
                <div className="space-y-1.5">
                  {src.linkedPolicies.map(p => (
                    <div key={p} className="flex items-center gap-2 px-3 py-1.5 bg-white border border-gray-150 rounded-lg shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <ShieldCheck size={11} className="text-gray-400 shrink-0" />
                      <span className="text-[11px] font-mono text-gray-700">{p}</span>
                      <span className="ml-auto text-[9.5px] text-gray-300 font-semibold">Policy</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Sessions count */}
            <div>
              <SectionLabel>Active Sessions</SectionLabel>
              <div className="flex items-center gap-3 px-4 py-3.5 bg-gray-50 border border-gray-100 rounded-xl">
                <div>
                  <p className={cn('text-[26px] font-black tabular-nums leading-none', src.linkedSessions > 0 ? 'text-blue-600' : 'text-gray-400')}>
                    {src.linkedSessions.toLocaleString()}
                  </p>
                  <p className="text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 mt-1">Sessions using this source</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Content ── */}
        {activeTab === 'Content' && (
          <div className="p-5 space-y-5">
            {/* Source statistics */}
            <div>
              <SectionLabel>Source Statistics</SectionLabel>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-1">
                <MetaRow
                  label="Documents / Records"
                  value={src.documentCount > 0 ? src.documentCount.toLocaleString() : 'N/A (streaming)'}
                  mono
                />
                <MetaRow
                  label="Indexed Chunks"
                  value={src.chunkCount > 0 ? src.chunkCount.toLocaleString() : src.embeddingStatus}
                  mono
                />
                <MetaRow label="Embedding Status" value={src.embeddingStatus}
                  highlight={src.embeddingStatus === 'Stale' ? 'danger' : src.embeddingStatus === 'Current' ? 'good' : undefined} />
                <MetaRow label="Freshness Window" value={src.freshnessWindow} />
                <MetaRow label="Coverage"         value={`${src.coverage}%`}
                  highlight={src.coverage < 50 ? 'danger' : src.coverage < 80 ? 'warn' : 'good'} />
                <MetaRow label="Data Quality"     value={`${src.dataQuality}/100`}
                  highlight={src.dataQuality < 50 ? 'danger' : src.dataQuality < 70 ? 'warn' : 'good'} />
              </div>
            </div>

            {/* Content types */}
            <div>
              <SectionLabel>Content Types</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {src.contentTypes.map(ct => (
                  <span key={ct} className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 border border-gray-200 rounded-lg text-[10.5px] font-semibold text-gray-600">
                    <FileText size={9} className="text-gray-400" />
                    {ct}
                  </span>
                ))}
              </div>
            </div>

            {/* PII presence */}
            <div>
              <SectionLabel>PII Presence</SectionLabel>
              {src.piiPresent ? (
                <div>
                  <div className="flex items-center gap-2 px-3.5 py-2.5 bg-red-50 border border-red-100 border-l-[3px] border-l-red-400 rounded-xl mb-2">
                    <AlertTriangle size={12} className="text-red-500 shrink-0" />
                    <p className="text-[12px] font-semibold text-red-700">PII detected in this source</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {src.piiTypes.map(pt => (
                      <span key={pt} className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-50 border border-red-100 rounded-full text-[10px] font-semibold text-red-700">
                        <Lock size={8} className="text-red-400" />
                        {pt}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2 px-3.5 py-2.5 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-xl">
                  <ShieldCheck size={12} className="text-emerald-500 shrink-0" />
                  <p className="text-[12px] font-medium text-emerald-700">No PII detected in this source.</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Sync History ── */}
        {activeTab === 'Sync History' && (
          <div className="p-5 space-y-4">
            <SectionLabel>Recent Sync Events ({src.syncHistory.length})</SectionLabel>
            {src.syncHistory.length === 0 ? (
              <div className="py-8 flex flex-col items-center gap-2 text-center">
                <RefreshCw size={20} className="text-gray-300" />
                <p className="text-[12px] text-gray-400 font-medium">No sync history available</p>
              </div>
            ) : (
              <div className="flex flex-col">
                {src.syncHistory.map((ev, idx) => {
                  const cfg    = SIGNAL_CFG[ev.severity] || SIGNAL_CFG['Low']
                  const isLast = idx === src.syncHistory.length - 1
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
                            <p className="text-[12px] font-medium text-gray-700 leading-snug">{ev.event}</p>
                            <span className="text-[9.5px] font-mono text-gray-400 shrink-0 mt-0.5 whitespace-nowrap">{ev.ts}</span>
                          </div>
                          <div className="flex items-center gap-2 mt-1.5">
                            <span className={cn('inline-flex items-center gap-1 text-[9.5px] font-semibold px-1.5 py-px rounded-full border', cfg.pill)}>
                              <span className={cn('w-1 h-1 rounded-full', cfg.dot)} />
                              {ev.severity}
                            </span>
                            {ev.resolved && (
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
          </div>
        )}

        {/* ── Alerts & Cases ── */}
        {activeTab === 'Alerts & Cases' && (
          <div className="p-5 space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <div className={cn(
                'rounded-xl border border-l-[3px] px-4 py-3.5',
                src.linkedAlerts > 0 ? 'bg-red-50 border-red-100 border-l-red-500' : 'bg-gray-50 border-gray-100 border-l-gray-200',
              )}>
                <p className={cn('text-[26px] font-black tabular-nums leading-none', src.linkedAlerts > 0 ? 'text-red-600' : 'text-gray-400')}>
                  {src.linkedAlerts}
                </p>
                <p className="text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 mt-1">Linked Alerts</p>
                {src.linkedAlerts > 0 && (
                  <button className="mt-2 text-[10.5px] font-semibold text-red-600 flex items-center gap-1 hover:underline">
                    View alerts <ExternalLink size={10} />
                  </button>
                )}
              </div>
              <div className={cn(
                'rounded-xl border border-l-[3px] px-4 py-3.5',
                src.linkedCases > 0 ? 'bg-violet-50 border-violet-100 border-l-violet-500' : 'bg-gray-50 border-gray-100 border-l-gray-200',
              )}>
                <p className={cn('text-[26px] font-black tabular-nums leading-none', src.linkedCases > 0 ? 'text-violet-600' : 'text-gray-400')}>
                  {src.linkedCases}
                </p>
                <p className="text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 mt-1">Linked Cases</p>
                {src.linkedCases > 0 && (
                  <button className="mt-2 text-[10.5px] font-semibold text-violet-600 flex items-center gap-1 hover:underline">
                    View cases <ExternalLink size={10} />
                  </button>
                )}
              </div>
            </div>

            {src.linkedAlerts === 0 && src.linkedCases === 0 && (
              <div className="flex items-center gap-2.5 px-3.5 py-3 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-xl">
                <ShieldCheck size={13} className="text-emerald-500 shrink-0" />
                <p className="text-[12px] font-medium text-emerald-700">No linked alerts or cases — source posture is clean.</p>
              </div>
            )}

            <div>
              <SectionLabel>Recommended Actions</SectionLabel>
              <RecommendedActions actions={src.recommendedActions} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Sync events table ─────────────────────────────────────────────────────────

function SyncEventsTable({ events }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between bg-white">
        <div className="flex items-center gap-3">
          <p className="text-[13px] font-bold text-gray-900">Sync & Trust Events</p>
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
              {['Timestamp', 'Source', 'Event', 'Risk Impact', 'Result'].map(col => (
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
                <tr key={ev.id} className={cn('hover:bg-gray-50/50 transition-colors border-l-[3px] group', impCfg.bdr)}>
                  <td className="w-0 p-0" />
                  <td className="px-3.5 py-2.5 whitespace-nowrap">
                    <span className="text-[10.5px] font-mono text-gray-400">{ev.ts}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="inline-flex items-center text-[11px] font-semibold font-mono text-gray-600 bg-gray-50 border border-gray-200 rounded-md px-1.5 py-0.5 whitespace-nowrap">{ev.source}</span>
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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Data() {
  const [sources, setSources]         = useState(MOCK_SOURCES)
  const [selectedId, setSelectedId]   = useState('src-002')
  const [search, setSearch]           = useState('')
  const [filterType, setFilterType]   = useState('All Types')
  const [filterSens, setFilterSens]   = useState('All Sensitivity')
  const [filterTrust, setFilterTrust] = useState('All Trust Levels')
  const [filterStatus, setFilterStatus] = useState('All Statuses')
  const [filterEnv, setFilterEnv]     = useState('All Environments')
  const [onlyUnhealthy, setOnlyUnhealthy] = useState(false)

  const selectedSource = sources.find(s => s.id === selectedId) || null

  const typeOpts   = ['All Types',        ...Array.from(new Set(MOCK_SOURCES.map(s => s.type)))]
  const sensOpts   = ['All Sensitivity',  'Restricted', 'Confidential', 'Internal', 'Public']
  const trustOpts  = ['All Trust Levels', 'Trusted (80–100)', 'Review (60–79)', 'Risky (0–59)']
  const statusOpts = ['All Statuses',     ...Array.from(new Set(MOCK_SOURCES.map(s => s.status)))]
  const envOpts    = ['All Environments', ...Array.from(new Set(MOCK_SOURCES.map(s => s.environment)))]

  const filtered = sources.filter(src => {
    const q = search.toLowerCase()
    if (q && !src.name.toLowerCase().includes(q) && !src.type.toLowerCase().includes(q)) return false
    if (filterType   !== 'All Types'        && src.type        !== filterType)   return false
    if (filterSens   !== 'All Sensitivity'  && src.sensitivity !== filterSens)   return false
    if (filterStatus !== 'All Statuses'     && src.status      !== filterStatus) return false
    if (filterEnv    !== 'All Environments' && src.environment !== filterEnv)    return false
    if (filterTrust  !== 'All Trust Levels') {
      const tier = getTrustTier(src.trustScore)
      if (filterTrust === 'Trusted (80–100)' && tier !== 'Trusted') return false
      if (filterTrust === 'Review (60–79)'   && tier !== 'Review')  return false
      if (filterTrust === 'Risky (0–59)'     && tier !== 'Risky')   return false
    }
    if (onlyUnhealthy && src.status === 'Healthy' && src.status !== 'Syncing') return false
    return true
  })

  // KPI values
  const totalSources    = sources.length
  const sensitiveSources = sources.filter(s => s.sensitivity === 'Confidential' || s.sensitivity === 'Restricted').length
  const needsReview     = sources.filter(s => getTrustTier(s.trustScore) === 'Review' || getTrustTier(s.trustScore) === 'Risky').length
  const failedSyncs     = sources.filter(s => s.status === 'Failed' || s.status === 'Stale' || s.status === 'Warning').length

  return (
    <PageContainer>
      {/* Page header */}
      <PageHeader
        title="Data & Knowledge"
        subtitle="Inspect context sources, data trust posture, and knowledge dependencies across AI workflows"
        actions={
          <>
            <Button size="sm" variant="outline" className="gap-1.5">
              <Bookmark size={13} /> Import Catalog
            </Button>
            <Button size="sm" variant="outline" className="gap-1.5">
              <Download size={13} /> Export
            </Button>
            <Button size="sm" className="gap-1.5">
              <Plus size={13} /> Add Source
            </Button>
          </>
        }
      />

      {/* KPI strip */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="Total Sources"      value={totalSources}     sub="Across all types"             icon={Database}      iconBg="bg-blue-500"    valueTint="text-blue-600"    stripColor="bg-blue-500"    />
        <KpiCard label="Sensitive Sources"  value={sensitiveSources} sub="Confidential + Restricted"    icon={Lock}          iconBg="bg-orange-500"  valueTint={sensitiveSources > 0 ? 'text-orange-600' : 'text-gray-900'}  stripColor={sensitiveSources > 0 ? 'bg-orange-500' : 'bg-gray-200'}  />
        <KpiCard label="Needs Review"       value={needsReview}      sub="Trust score below 80"         icon={AlertTriangle} iconBg="bg-yellow-500"  valueTint={needsReview > 0 ? 'text-yellow-600' : 'text-gray-900'}      stripColor={needsReview > 0 ? 'bg-yellow-400' : 'bg-gray-200'}      />
        <KpiCard label="Failed Syncs"       value={failedSyncs}      sub="Failed, Stale, or Warning"   icon={ShieldAlert}   iconBg="bg-red-500"     valueTint={failedSyncs > 0 ? 'text-red-600' : 'text-gray-900'}        stripColor={failedSyncs > 0 ? 'bg-red-500' : 'bg-gray-200'}        />
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
            placeholder="Search sources…"
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
        <FilterSelect value={filterSens}   onChange={setFilterSens}   options={sensOpts}   />
        <FilterSelect value={filterTrust}  onChange={setFilterTrust}  options={trustOpts}  />
        <FilterSelect value={filterStatus} onChange={setFilterStatus} options={statusOpts} />
        <FilterSelect value={filterEnv}    onChange={setFilterEnv}    options={envOpts}    />

        {/* Unhealthy toggle */}
        <div className="flex items-center gap-2 ml-auto">
          <Toggle checked={onlyUnhealthy} onChange={setOnlyUnhealthy} />
          <span className="text-[12px] font-medium text-gray-500">Only stale or unhealthy</span>
        </div>
      </div>

      {/* Main area: list + detail */}
      <div className="flex gap-4 items-start">
        {/* Source list */}
        <div className="flex-1 min-w-0">
          {filtered.length === 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm py-16 flex flex-col items-center gap-2 text-center">
              <Filter size={20} className="text-gray-300" />
              <p className="text-[12.5px] text-gray-400 font-medium">No sources match your filters</p>
              <p className="text-[11px] text-gray-300">Try adjusting the search or filter criteria</p>
            </div>
          ) : (
            <SourceList
              sources={filtered}
              selectedId={selectedId}
              onSelect={id => setSelectedId(prev => prev === id ? null : id)}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedSource && (
          <SourceDetailPanel
            source={selectedSource}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>

      {/* Sync & trust events table */}
      <SyncEventsTable events={SYNC_EVENTS} />
    </PageContainer>
  )
}
