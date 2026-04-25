import { useMemo, useState } from 'react'
import {
  Search, X, Plus, Upload, Download, RefreshCw,
  Cloud, Shield, Database, Bell, Workflow,
  KeyRound, CheckCircle2, AlertTriangle, XCircle,
  Link, Settings, Eye, RotateCcw, ChevronDown,
  Lock, Cpu, User, Activity, Clock, Zap,
  GitBranch, Layers, Webhook, Filter,
  Network, FlaskConical, ExternalLink,
  Server, ShieldCheck, FileText, Plug,
  Loader2,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'
import { useIntegrations, useIntegration } from '../../hooks/useIntegrations.js'
import {
  enableIntegration,
  disableIntegration,
  syncIntegration,
  testIntegration,
  createIntegration,
  listIntegrations,
} from '../api/integrationsApi.js'
import { summaryToListRow, detailToViewModel } from './integrationsViewModel.js'
import { IntegrationConfigureModal }           from './IntegrationConfigureModal.jsx'
import { IntegrationCreateModal }              from './IntegrationCreateModal.jsx'

// ── Design tokens ──────────────────────────────────────────────────────────────

const INT_STATUS = {
  Healthy:          { dot: 'bg-emerald-400', text: 'text-emerald-700', bg: 'bg-emerald-50',  bdr: 'border-l-emerald-400', badge: 'success'  },
  Warning:          { dot: 'bg-yellow-400',  text: 'text-yellow-700',  bg: 'bg-yellow-50',   bdr: 'border-l-yellow-400',  badge: 'medium'   },
  Error:            { dot: 'bg-red-500',     text: 'text-red-700',     bg: 'bg-red-50',      bdr: 'border-l-red-500',     badge: 'critical' },
  'Not Configured': { dot: 'bg-gray-300',    text: 'text-gray-500',    bg: 'bg-gray-100',    bdr: 'border-l-gray-200',    badge: 'neutral'  },
  Disabled:         { dot: 'bg-gray-300',    text: 'text-gray-400',    bg: 'bg-gray-100',    bdr: 'border-l-gray-200',    badge: 'neutral'  },
  Partial:          { dot: 'bg-blue-400',    text: 'text-blue-700',    bg: 'bg-blue-50',     bdr: 'border-l-blue-400',    badge: 'info'     },
}

const CATEGORY_CFG = {
  'AI Providers':         { color: 'text-violet-600', bg: 'bg-violet-50',  border: 'border-violet-200', icon: Cpu      },
  'Security / SIEM':      { color: 'text-red-600',    bg: 'bg-red-50',     border: 'border-red-200',    icon: Shield   },
  'Ticketing / Workflow': { color: 'text-blue-600',   bg: 'bg-blue-50',    border: 'border-blue-200',   icon: Workflow },
  'Identity / Access':    { color: 'text-orange-600', bg: 'bg-orange-50',  border: 'border-orange-200', icon: Lock     },
  'Data / Storage':       { color: 'text-cyan-600',   bg: 'bg-cyan-50',    border: 'border-cyan-200',   icon: Database },
  'Messaging / Collab':   { color: 'text-emerald-600',bg: 'bg-emerald-50', border: 'border-emerald-200',icon: Bell     },
}

const AUTH_CFG = {
  'API Key':         { icon: KeyRound, color: 'text-blue-600',   bg: 'bg-blue-50',   border: 'border-blue-100'   },
  'OAuth':           { icon: Link,     color: 'text-violet-600', bg: 'bg-violet-50', border: 'border-violet-100' },
  'IAM Role':        { icon: Shield,   color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-100' },
  'Service Account': { icon: User,     color: 'text-cyan-600',   bg: 'bg-cyan-50',   border: 'border-cyan-100'   },
}

const ACT_RESULT_CFG = {
  Success: { dot: 'bg-emerald-400', pill: 'text-emerald-700 bg-emerald-50 border-emerald-100', bdr: 'border-l-emerald-400' },
  Warning: { dot: 'bg-yellow-400',  pill: 'text-yellow-700 bg-yellow-50 border-yellow-100',   bdr: 'border-l-yellow-400'  },
  Error:   { dot: 'bg-red-500',     pill: 'text-red-700 bg-red-50 border-red-100',             bdr: 'border-l-red-500'     },
  Info:    { dot: 'bg-blue-400',    pill: 'text-blue-700 bg-blue-50 border-blue-100',          bdr: 'border-l-blue-400'    },
}

// Spine dot container bg per result
const SPINE_DOT_BG = {
  Success: 'bg-emerald-100',
  Warning: 'bg-yellow-100',
  Error:   'bg-red-100',
  Info:    'bg-blue-100',
}

// Left-border per auth method (Auth tab card)
const AUTH_LEFT_BDR = {
  'API Key':         'border-l-blue-400',
  'OAuth':           'border-l-violet-400',
  'IAM Role':        'border-l-orange-400',
  'Service Account': 'border-l-cyan-400',
}

// ── Mock data ──────────────────────────────────────────────────────────────────

const MOCK_INTEGRATIONS = [
  // ── AI Providers ──
  {
    id: 'int-001', name: 'OpenAI', abbrev: 'OA', category: 'AI Providers',
    status: 'Healthy', authMethod: 'API Key', owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Production', enabled: true,
    description: 'Direct API integration with OpenAI for GPT-4 and GPT-3.5 model families. Supports completions, embeddings, and function calling for production agents.',
    vendor: 'OpenAI, Inc.', createdAt: 'Jan 12, 2026', lastModified: 'Apr 1, 2026',
    lastSync: '4m ago', lastSyncFull: 'Apr 8 · 14:28 UTC', lastFailedSync: null,
    avgLatency: '218ms', uptime: '99.98%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'Never (static key)',
    scopes: ['completions:write', 'models:read', 'embeddings:write', 'usage:read'],
    missingScopes: [],
    capabilities: [
      { label: 'Execute model completions', enabled: true  },
      { label: 'Generate embeddings',       enabled: true  },
      { label: 'Read model metadata',       enabled: true  },
      { label: 'Ingest runtime events',     enabled: true  },
      { label: 'Send notifications',        enabled: false },
      { label: 'Execute ticket actions',    enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 14:28 UTC', event: 'API key validated',             result: 'Success' },
      { ts: 'Apr 8 · 08:00 UTC', event: 'Daily health check passed',     result: 'Success' },
      { ts: 'Apr 7 · 14:28 UTC', event: 'API key validated',             result: 'Success' },
      { ts: 'Apr 5 · 11:00 UTC', event: 'Rate limit warning — 85% quota',result: 'Warning' },
      { ts: 'Apr 3 · 14:28 UTC', event: 'API key validated',             result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: ['Prompt Injection Auto-Response', 'Model Drift Auto-Containment'],
      alerts:    ['Model Rate Limit', 'API Error Spike'],
      policies:  ['Prompt-Guard v3', 'Output-Guard v2'],
      cases:     ['CASE-1042', 'CASE-1051'],
    },
    setupProgress: null, tags: ['gpt-4o', 'embeddings'],
  },
  {
    id: 'int-002', name: 'Azure OpenAI', abbrev: 'Az', category: 'AI Providers',
    status: 'Healthy', authMethod: 'API Key', owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Production', enabled: true,
    description: 'Azure-hosted OpenAI deployment for enterprise compliance. Supports GPT-4 Turbo within the EU data boundary.',
    vendor: 'Microsoft Azure', createdAt: 'Feb 3, 2026', lastModified: 'Mar 15, 2026',
    lastSync: '12m ago', lastSyncFull: 'Apr 8 · 14:20 UTC', lastFailedSync: null,
    avgLatency: '312ms', uptime: '99.94%',
    healthHistory: ['ok','ok','ok','ok','ok','warn','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'Never (static key)',
    scopes: ['completions:write', 'models:read', 'embeddings:write'],
    missingScopes: ['fine-tune:read'],
    capabilities: [
      { label: 'Execute model completions',  enabled: true  },
      { label: 'Generate embeddings',        enabled: true  },
      { label: 'EU data boundary compliance',enabled: true  },
      { label: 'Fine-tune model access',     enabled: false },
      { label: 'Send notifications',         enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 14:20 UTC', event: 'Health check passed',           result: 'Success' },
      { ts: 'Apr 6 · 09:00 UTC', event: 'Endpoint latency spike — 890ms',result: 'Warning' },
      { ts: 'Apr 5 · 14:20 UTC', event: 'API key validated',             result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: ['Daily Security Posture Digest'],
      alerts:    ['API Error Spike'], policies: ['EU-Compliance-Guard'], cases: [],
    },
    setupProgress: null, tags: ['gpt-4-turbo', 'eu-boundary'],
  },
  {
    id: 'int-003', name: 'Anthropic', abbrev: 'An', category: 'AI Providers',
    status: 'Healthy', authMethod: 'API Key', owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Production', enabled: true,
    description: 'Claude model family API for analysis agents and content safety evaluation. Used as secondary safety layer on high-risk user segments.',
    vendor: 'Anthropic, PBC', createdAt: 'Mar 1, 2026', lastModified: 'Mar 20, 2026',
    lastSync: '8m ago', lastSyncFull: 'Apr 8 · 14:24 UTC', lastFailedSync: null,
    avgLatency: '245ms', uptime: '99.99%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'Never (static key)',
    scopes: ['messages:write', 'models:read'],
    missingScopes: [],
    capabilities: [
      { label: 'Execute model completions', enabled: true  },
      { label: 'Content safety evaluation', enabled: true  },
      { label: 'Ingest runtime events',     enabled: true  },
      { label: 'Generate embeddings',       enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 14:24 UTC', event: 'Health check passed',   result: 'Success' },
      { ts: 'Apr 7 · 14:24 UTC', event: 'API key validated',     result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: [], alerts: ['Safety Eval Failed'], policies: ['Content-Safety-Guard'], cases: [],
    },
    setupProgress: null, tags: ['claude', 'safety-eval'],
  },
  {
    id: 'int-004', name: 'Amazon Bedrock', abbrev: 'Bk', category: 'AI Providers',
    status: 'Healthy', authMethod: 'IAM Role', owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', enabled: true,
    description: 'AWS Bedrock via IAM role for multi-model inference including Titan Embeddings and Claude 3 on-demand. Governed by AWS SCP policies.',
    vendor: 'Amazon Web Services', createdAt: 'Jan 20, 2026', lastModified: 'Feb 28, 2026',
    lastSync: '6m ago', lastSyncFull: 'Apr 8 · 14:26 UTC', lastFailedSync: null,
    avgLatency: '198ms', uptime: '99.96%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'IAM — no expiry',
    scopes: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream', 'bedrock:ListFoundationModels'],
    missingScopes: [],
    capabilities: [
      { label: 'Execute model completions', enabled: true  },
      { label: 'Generate embeddings',       enabled: true  },
      { label: 'Stream responses',          enabled: true  },
      { label: 'List available models',     enabled: true  },
      { label: 'Send notifications',        enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 14:26 UTC', event: 'IAM role validation passed',  result: 'Success' },
      { ts: 'Apr 8 · 09:30 UTC', event: 'Daily health check passed',   result: 'Success' },
      { ts: 'Apr 7 · 14:26 UTC', event: 'IAM role validation passed',  result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: ['Model Drift Auto-Containment'], alerts: [], policies: ['AWS-Governance-Guard'], cases: [],
    },
    setupProgress: null, tags: ['titan', 'claude-bedrock', 'iam'],
  },
  {
    id: 'int-005', name: 'Google Vertex AI', abbrev: 'GV', category: 'AI Providers',
    status: 'Warning', authMethod: 'Service Account', owner: 'raj.patel', ownerDisplay: 'Raj Patel',
    environment: 'Staging', enabled: true,
    description: 'Google Cloud Vertex AI service account integration for Gemini models. Currently in staging — service account key rotation is overdue (expires in 7 days).',
    vendor: 'Google Cloud', createdAt: 'Mar 15, 2026', lastModified: 'Apr 2, 2026',
    lastSync: '2h ago', lastSyncFull: 'Apr 8 · 12:30 UTC', lastFailedSync: 'Apr 7 · 09:00 UTC',
    avgLatency: '380ms', uptime: '97.20%',
    healthHistory: ['ok','ok','ok','warn','ok','ok','err','ok','warn','ok','ok','ok','warn','ok'],
    tokenExpiry: 'Expires Apr 15, 2026 — 7 days',
    scopes: ['aiplatform.endpoints.predict', 'aiplatform.models.list'],
    missingScopes: ['aiplatform.models.delete', 'logging.logEntries.create'],
    capabilities: [
      { label: 'Execute model completions', enabled: true  },
      { label: 'List available models',     enabled: true  },
      { label: 'Generate embeddings',       enabled: false },
      { label: 'Write audit logs',          enabled: false },
      { label: 'Ingest runtime events',     enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 12:30 UTC', event: 'Health check — elevated latency 380ms', result: 'Warning' },
      { ts: 'Apr 7 · 09:00 UTC', event: 'Service account key expiry warning',    result: 'Warning' },
      { ts: 'Apr 6 · 12:30 UTC', event: 'Health check passed',                   result: 'Success' },
      { ts: 'Apr 5 · 08:00 UTC', event: 'Token rotation recommended',            result: 'Warning' },
    ],
    linkedWorkflows: {
      playbooks: [], alerts: ['Credential Expiry Warning'], policies: [], cases: [],
    },
    setupProgress: null, tags: ['gemini', 'vertex', 'staging'],
  },

  // ── Security / SIEM ──
  {
    id: 'int-006', name: 'Splunk', abbrev: 'Sp', category: 'Security / SIEM',
    status: 'Error', authMethod: 'API Key', owner: 'sarah.chen', ownerDisplay: 'Sarah Chen',
    environment: 'Production', enabled: true,
    description: 'Splunk SIEM integration for forwarding AI security events, policy violations, and audit logs via HEC endpoint. Failing due to expired token.',
    vendor: 'Splunk Inc.', createdAt: 'Dec 5, 2025', lastModified: 'Apr 6, 2026',
    lastSync: '1h ago', lastSyncFull: 'Apr 8 · 13:00 UTC', lastFailedSync: 'Apr 8 · 13:01 UTC',
    avgLatency: null, uptime: '91.20%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','err','ok','ok','err','err','err','err'],
    tokenExpiry: 'Expired Apr 7, 2026',
    scopes: ['hec:write'],
    missingScopes: ['search:read', 'indexes:list'],
    capabilities: [
      { label: 'Forward security events',    enabled: true  },
      { label: 'Write audit logs',           enabled: true  },
      { label: 'Forward policy violations',  enabled: true  },
      { label: 'Query log indexes',          enabled: false },
      { label: 'Run saved searches',         enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 13:01 UTC', event: 'HEC write failed — token expired',   result: 'Error'   },
      { ts: 'Apr 8 · 13:00 UTC', event: 'Connection attempt failed',          result: 'Error'   },
      { ts: 'Apr 7 · 16:44 UTC', event: 'Token rotation failed — 401',        result: 'Error'   },
      { ts: 'Apr 6 · 18:00 UTC', event: 'Last successful event forward',      result: 'Success' },
      { ts: 'Apr 6 · 11:00 UTC', event: 'Admin updated HEC endpoint URL',     result: 'Info'    },
    ],
    linkedWorkflows: {
      playbooks: ['Prompt Injection Auto-Response', 'PII Exfiltration Escalation', 'Daily Security Posture Digest'],
      alerts: [], policies: [], cases: ['CASE-1042'],
    },
    setupProgress: null, tags: ['hec', 'siem', 'audit'],
  },
  {
    id: 'int-007', name: 'Microsoft Sentinel', abbrev: 'MS', category: 'Security / SIEM',
    status: 'Healthy', authMethod: 'Service Account', owner: 'sarah.chen', ownerDisplay: 'Sarah Chen',
    environment: 'Production', enabled: true,
    description: 'Microsoft Sentinel workspace for AI threat intelligence ingestion and SOAR playbook triggers, connected via service principal.',
    vendor: 'Microsoft Azure', createdAt: 'Feb 10, 2026', lastModified: 'Mar 30, 2026',
    lastSync: '18m ago', lastSyncFull: 'Apr 8 · 14:14 UTC', lastFailedSync: null,
    avgLatency: '290ms', uptime: '99.90%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'Service principal — auto-renewed',
    scopes: ['SecurityInsights/alertRules/write', 'SecurityInsights/incidents/read', 'SecurityInsights/watchlists/read'],
    missingScopes: [],
    capabilities: [
      { label: 'Ingest AI security incidents', enabled: true  },
      { label: 'Trigger SOAR playbooks',       enabled: true  },
      { label: 'Read threat intelligence',     enabled: true  },
      { label: 'Write custom analytics rules', enabled: true  },
      { label: 'Forward raw events',           enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 7 · 22:15 UTC', event: 'Alert ingestion reconnected', result: 'Success' },
      { ts: 'Apr 7 · 14:14 UTC', event: 'Health check passed',        result: 'Success' },
      { ts: 'Apr 6 · 14:14 UTC', event: 'Health check passed',        result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: [], alerts: ['SIEM Alert Forwarding'], policies: [], cases: [],
    },
    setupProgress: null, tags: ['sentinel', 'soar', 'azure'],
  },

  // ── Ticketing / Workflow ──
  {
    id: 'int-008', name: 'Jira', abbrev: 'Ji', category: 'Ticketing / Workflow',
    status: 'Healthy', authMethod: 'API Key', owner: 'alex.kim', ownerDisplay: 'Alex Kim',
    environment: 'Production', enabled: true,
    description: 'Atlassian Jira for automatic ticket creation from security cases with bi-directional status sync.',
    vendor: 'Atlassian', createdAt: 'Jan 15, 2026', lastModified: 'Mar 5, 2026',
    lastSync: '8m ago', lastSyncFull: 'Apr 8 · 08:00 UTC', lastFailedSync: null,
    avgLatency: '175ms', uptime: '99.95%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'Never (API token)',
    scopes: ['read:jira-work', 'write:jira-work', 'read:jira-user'],
    missingScopes: [],
    capabilities: [
      { label: 'Create security tickets', enabled: true  },
      { label: 'Update ticket status',    enabled: true  },
      { label: 'Read assignee info',      enabled: true  },
      { label: 'Attach evidence files',   enabled: true  },
      { label: 'Delete tickets',          enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 08:00 UTC', event: 'Daily sync — 3 tickets updated', result: 'Success' },
      { ts: 'Apr 7 · 15:30 UTC', event: 'CASE-1042 → AISPM-891 created', result: 'Success' },
      { ts: 'Apr 7 · 08:00 UTC', event: 'Daily sync completed',           result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: ['PII Exfiltration Escalation'], alerts: [], policies: [], cases: ['CASE-1042', 'CASE-1049'],
    },
    setupProgress: null, tags: ['jira', 'ticketing'],
  },
  {
    id: 'int-009', name: 'ServiceNow', abbrev: 'SN', category: 'Ticketing / Workflow',
    status: 'Not Configured', authMethod: 'OAuth', owner: 'alex.kim', ownerDisplay: 'Alex Kim',
    environment: 'Production', enabled: false,
    description: 'ServiceNow ITSM integration for enterprise incident management. OAuth app registered — redirect URI and scopes pending.',
    vendor: 'ServiceNow', createdAt: 'Apr 1, 2026', lastModified: 'Apr 5, 2026',
    lastSync: 'Never', lastSyncFull: null, lastFailedSync: null,
    avgLatency: null, uptime: null,
    healthHistory: null,
    tokenExpiry: 'Not authenticated',
    scopes: [],
    missingScopes: ['incident:create', 'incident:read', 'incident:update', 'user:read'],
    capabilities: [
      { label: 'Create ITSM incidents',  enabled: false },
      { label: 'Update incident status', enabled: false },
      { label: 'Attach evidence files',  enabled: false },
      { label: 'Read CMDB assets',       enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 5 · 10:00 UTC', event: 'OAuth app registered — redirect pending', result: 'Info' },
      { ts: 'Apr 1 · 09:30 UTC', event: 'Integration added by alex.kim',           result: 'Info' },
    ],
    linkedWorkflows: { playbooks: [], alerts: [], policies: [], cases: [] },
    setupProgress: [
      { step: 1, label: 'Register OAuth application', status: 'done'    },
      { step: 2, label: 'Configure redirect URI',      status: 'pending' },
      { step: 3, label: 'Grant required scopes',       status: 'pending' },
      { step: 4, label: 'Test connection',             status: 'pending' },
    ],
    tags: ['servicenow', 'itsm'],
  },

  // ── Messaging / Collab ──
  {
    id: 'int-010', name: 'Slack', abbrev: 'Sl', category: 'Messaging / Collab',
    status: 'Warning', authMethod: 'OAuth', owner: 'sarah.chen', ownerDisplay: 'Sarah Chen',
    environment: 'Production', enabled: true,
    description: 'Slack workspace integration for security alert notifications and daily posture digest delivery. Webhook delivery intermittently timing out.',
    vendor: 'Salesforce / Slack', createdAt: 'Dec 1, 2025', lastModified: 'Apr 3, 2026',
    lastSync: '15m ago', lastSyncFull: 'Apr 8 · 14:17 UTC', lastFailedSync: 'Apr 8 · 13:00 UTC',
    avgLatency: '145ms', uptime: '96.80%',
    healthHistory: ['ok','ok','ok','ok','warn','ok','ok','warn','ok','ok','err','ok','ok','warn'],
    tokenExpiry: 'OAuth token — auto-refresh',
    scopes: ['chat:write', 'channels:read', 'incoming-webhook'],
    missingScopes: ['files:write'],
    capabilities: [
      { label: 'Send channel notifications', enabled: true  },
      { label: 'Post incident updates',      enabled: true  },
      { label: 'Deliver daily digest',       enabled: true  },
      { label: 'Attach report files',        enabled: false },
      { label: 'Read channel history',       enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 14:17 UTC', event: 'Webhook delivery — success',                     result: 'Success' },
      { ts: 'Apr 8 · 13:00 UTC', event: 'Webhook delivery timeout #security-incidents',   result: 'Warning' },
      { ts: 'Apr 8 · 11:15 UTC', event: 'PII escalation alert sent',                      result: 'Success' },
      { ts: 'Apr 8 · 08:00 UTC', event: 'Daily posture digest delivered',                 result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: ['Prompt Injection Auto-Response', 'PII Exfiltration Escalation', 'Daily Security Posture Digest', 'Model Drift Auto-Containment'],
      alerts: ['Webhook Failure'], policies: [], cases: [],
    },
    setupProgress: null, tags: ['slack', 'notifications', 'webhook'],
  },

  // ── Identity / Access ──
  {
    id: 'int-011', name: 'Okta', abbrev: 'Ok', category: 'Identity / Access',
    status: 'Partial', authMethod: 'OAuth', owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', enabled: true,
    description: 'Okta identity provider for user identity validation, trust scoring, and session risk classification. Scope sync is partially configured — missing groups:read.',
    vendor: 'Okta, Inc.', createdAt: 'Feb 20, 2026', lastModified: 'Apr 8, 2026',
    lastSync: '11m ago', lastSyncFull: 'Apr 8 · 14:21 UTC', lastFailedSync: 'Apr 8 · 11:15 UTC',
    avgLatency: '135ms', uptime: '98.40%',
    healthHistory: ['ok','ok','ok','ok','warn','ok','ok','ok','warn','warn','ok','ok','ok','ok'],
    tokenExpiry: 'Refreshed 11m ago — 59m remaining',
    scopes: ['openid', 'profile', 'email', 'okta.users.read'],
    missingScopes: ['okta.groups.read', 'okta.logs.read'],
    capabilities: [
      { label: 'Validate user identity',  enabled: true  },
      { label: 'Read user profiles',      enabled: true  },
      { label: 'Classify session risk',   enabled: true  },
      { label: 'Read group memberships',  enabled: false },
      { label: 'Read audit logs',         enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 14:21 UTC', event: 'OAuth token refreshed',             result: 'Success' },
      { ts: 'Apr 8 · 11:15 UTC', event: 'Scope sync — groups:read missing',  result: 'Warning' },
      { ts: 'Apr 7 · 14:21 UTC', event: 'OAuth token refreshed',             result: 'Success' },
      { ts: 'Apr 6 · 10:00 UTC', event: 'Scope update by mike.torres',       result: 'Info'    },
    ],
    linkedWorkflows: {
      playbooks: [], alerts: ['Identity Risk Score Alert'], policies: ['Identity-Trust-Guard'], cases: [],
    },
    setupProgress: [
      { step: 1, label: 'Register OAuth application', status: 'done'  },
      { step: 2, label: 'Configure redirect URI',      status: 'done'  },
      { step: 3, label: 'Grant required scopes',       status: 'error' },
      { step: 4, label: 'Test connection',             status: 'pending'},
    ],
    tags: ['okta', 'identity', 'oauth'],
  },
  {
    id: 'int-012', name: 'Entra ID', abbrev: 'En', category: 'Identity / Access',
    status: 'Healthy', authMethod: 'OAuth', owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', enabled: true,
    description: 'Microsoft Entra ID (Azure AD) for enterprise SSO, group-based access control, and conditional access policy enforcement.',
    vendor: 'Microsoft', createdAt: 'Jan 5, 2026', lastModified: 'Mar 10, 2026',
    lastSync: '9m ago', lastSyncFull: 'Apr 8 · 14:23 UTC', lastFailedSync: null,
    avgLatency: '168ms', uptime: '99.97%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'Auto-renewed — enterprise tenant',
    scopes: ['User.Read', 'Group.Read.All', 'Directory.Read.All', 'AuditLog.Read.All'],
    missingScopes: [],
    capabilities: [
      { label: 'SSO user authentication',    enabled: true  },
      { label: 'Read group memberships',     enabled: true  },
      { label: 'Enforce conditional access', enabled: true  },
      { label: 'Read audit logs',            enabled: true  },
      { label: 'Write directory objects',    enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 7 · 14:30 UTC', event: 'OAuth token refreshed',            result: 'Success' },
      { ts: 'Apr 7 · 08:00 UTC', event: 'Group sync — 148 users',           result: 'Success' },
      { ts: 'Apr 6 · 14:30 UTC', event: 'OAuth token refreshed',            result: 'Success' },
    ],
    linkedWorkflows: {
      playbooks: [], alerts: [], policies: ['Identity-Trust-Guard', 'Conditional-Access-Policy'], cases: [],
    },
    setupProgress: null, tags: ['azure-ad', 'entra', 'sso'],
  },

  // ── Data / Storage ──
  {
    id: 'int-013', name: 'Amazon S3', abbrev: 'S3', category: 'Data / Storage',
    status: 'Healthy', authMethod: 'IAM Role', owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', enabled: true,
    description: 'S3 bucket integration for evidence artifact storage, audit log export, and RAG document ingestion. Least-privilege IAM policy enforced.',
    vendor: 'Amazon Web Services', createdAt: 'Jan 10, 2026', lastModified: 'Feb 15, 2026',
    lastSync: '30m ago', lastSyncFull: 'Apr 8 · 14:02 UTC', lastFailedSync: null,
    avgLatency: '82ms', uptime: '100%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'IAM — no expiry',
    scopes: ['s3:GetObject', 's3:PutObject', 's3:ListBucket', 's3:DeleteObject'],
    missingScopes: [],
    capabilities: [
      { label: 'Store evidence artifacts', enabled: true  },
      { label: 'Export audit logs',        enabled: true  },
      { label: 'Fetch RAG documents',      enabled: true  },
      { label: 'Manage bucket policies',   enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 14:02 UTC', event: 'Evidence archive written — CASE-1042', result: 'Success' },
      { ts: 'Apr 8 · 08:00 UTC', event: 'Daily log export completed',            result: 'Success' },
      { ts: 'Apr 7 · 14:02 UTC', event: 'IAM role validation passed',           result: 'Success' },
    ],
    linkedWorkflows: { playbooks: [], alerts: [], policies: [], cases: ['CASE-1042', 'CASE-1049'] },
    setupProgress: null, tags: ['s3', 'storage', 'iam'],
  },
  {
    id: 'int-014', name: 'Confluence', abbrev: 'Cf', category: 'Data / Storage',
    status: 'Healthy', authMethod: 'API Key', owner: 'alex.kim', ownerDisplay: 'Alex Kim',
    environment: 'Production', enabled: true,
    description: 'Atlassian Confluence for RAG document ingestion. Security runbooks and knowledge base content indexed for AI agents.',
    vendor: 'Atlassian', createdAt: 'Feb 1, 2026', lastModified: 'Mar 20, 2026',
    lastSync: '1h ago', lastSyncFull: 'Apr 8 · 13:30 UTC', lastFailedSync: null,
    avgLatency: '210ms', uptime: '99.88%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok','ok'],
    tokenExpiry: 'Never (API token)',
    scopes: ['read:page:confluence', 'read:space:confluence', 'read:attachment:confluence'],
    missingScopes: [],
    capabilities: [
      { label: 'Fetch RAG documents',  enabled: true  },
      { label: 'Read page content',    enabled: true  },
      { label: 'List spaces',          enabled: true  },
      { label: 'Read attachments',     enabled: true  },
      { label: 'Write pages',          enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 8 · 13:30 UTC', event: 'Sync completed — 14 pages indexed', result: 'Success' },
      { ts: 'Apr 7 · 13:30 UTC', event: 'Sync completed — 2 pages updated',  result: 'Success' },
    ],
    linkedWorkflows: { playbooks: [], alerts: [], policies: [], cases: [] },
    setupProgress: null, tags: ['confluence', 'rag', 'knowledge-base'],
  },
  {
    id: 'int-015', name: 'Kafka', abbrev: 'Kf', category: 'Data / Storage',
    status: 'Error', authMethod: 'Service Account', owner: 'mike.torres', ownerDisplay: 'Mike Torres',
    environment: 'Production', enabled: true,
    description: 'Apache Kafka for real-time AI event stream ingestion. Consumer group disconnected after broker certificate renewal.',
    vendor: 'Confluent / Apache', createdAt: 'Mar 10, 2026', lastModified: 'Apr 7, 2026',
    lastSync: '2d ago', lastSyncFull: 'Apr 6 · 22:00 UTC', lastFailedSync: 'Apr 7 · 00:00 UTC',
    avgLatency: null, uptime: '82.50%',
    healthHistory: ['ok','ok','ok','ok','ok','ok','ok','ok','ok','err','err','err','err','err'],
    tokenExpiry: 'Service account cert expired',
    scopes: ['kafka:consumer:read', 'kafka:topics:list'],
    missingScopes: ['kafka:producer:write'],
    capabilities: [
      { label: 'Ingest real-time AI events', enabled: true  },
      { label: 'Read event streams',         enabled: true  },
      { label: 'List topics',               enabled: true  },
      { label: 'Publish events',            enabled: false },
    ],
    recentActivity: [
      { ts: 'Apr 7 · 18:44 UTC', event: 'Consumer group disconnected — cert error',        result: 'Error'   },
      { ts: 'Apr 7 · 00:00 UTC', event: 'Broker TLS cert renewed — reconnect required',    result: 'Error'   },
      { ts: 'Apr 6 · 22:00 UTC', event: 'Last successful consumer group event',            result: 'Success' },
    ],
    linkedWorkflows: { playbooks: [], alerts: ['Kafka Consumer Down'], policies: [], cases: [] },
    setupProgress: null, tags: ['kafka', 'streaming', 'events'],
  },
]

const MOCK_ACTIVITY = [
  { id:1,  ts:'Apr 8 · 14:32 UTC', integration:'OpenAI',           event:'API key validated',                   result:'Success', actor:'System'      },
  { id:2,  ts:'Apr 8 · 14:28 UTC', integration:'Splunk',           event:'Event forwarding failed — HEC 401',   result:'Error',   actor:'System'      },
  { id:3,  ts:'Apr 8 · 13:00 UTC', integration:'Slack',            event:'Webhook delivery timeout',            result:'Warning', actor:'System'      },
  { id:4,  ts:'Apr 8 · 11:15 UTC', integration:'Okta',             event:'Scope sync — groups:read missing',    result:'Warning', actor:'sarah.chen'  },
  { id:5,  ts:'Apr 8 · 09:30 UTC', integration:'Amazon Bedrock',   event:'IAM role validation passed',          result:'Success', actor:'System'      },
  { id:6,  ts:'Apr 8 · 08:00 UTC', integration:'Jira',             event:'Daily sync completed — 3 tickets',    result:'Success', actor:'System'      },
  { id:7,  ts:'Apr 7 · 22:15 UTC', integration:'Microsoft Sentinel',event:'Alert ingestion reconnected',        result:'Success', actor:'System'      },
  { id:8,  ts:'Apr 7 · 18:44 UTC', integration:'Kafka',            event:'Consumer group disconnected',         result:'Error',   actor:'System'      },
  { id:9,  ts:'Apr 7 · 16:00 UTC', integration:'Entra ID',         event:'OAuth token refreshed',               result:'Success', actor:'System'      },
  { id:10, ts:'Apr 7 · 14:30 UTC', integration:'Google Vertex AI', event:'Service account key expiry warning',  result:'Warning', actor:'System'      },
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

function Toggle({ checked, onChange, showLabel = false }) {
  return (
    <div className="flex items-center gap-2">
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
      {showLabel && (
        <span className={cn('text-[10.5px] font-semibold w-5', checked ? 'text-emerald-600' : 'text-gray-400')}>
          {checked ? 'On' : 'Off'}
        </span>
      )}
    </div>
  )
}

function OwnerAvatar({ name, size = 'sm' }) {
  // Defensive: a freshly-created integration may not have an owner.name
  // yet (the create modal doesn't ask for it). Without this guard the
  // page blanks out with "Cannot read properties of null (reading 'split')".
  const safeName = (typeof name === 'string' && name.trim()) ? name.trim() : '—'
  const parts    = safeName.split('.')
  const initials = parts.map(p => (p && p[0] ? p[0].toUpperCase() : '')).join('') || '?'
  const colors = ['bg-blue-500','bg-violet-500','bg-emerald-500','bg-amber-500','bg-rose-500','bg-cyan-500']
  const color  = colors[(safeName.charCodeAt(0) || 0) % colors.length]
  const sz     = size === 'sm' ? 'w-6 h-6 text-[9px]' : 'w-7 h-7 text-[10px]'
  return (
    <div className={cn('rounded-full flex items-center justify-center text-white font-bold shrink-0', sz, color)}>
      {initials}
    </div>
  )
}

const STATUS_PIP_BDR = {
  Healthy:          'border-emerald-200',
  Warning:          'border-yellow-200',
  Error:            'border-red-200',
  'Not Configured': 'border-gray-200',
  Disabled:         'border-gray-200',
  Partial:          'border-blue-200',
}

function StatusPip({ status }) {
  const cfg = INT_STATUS[status] || INT_STATUS['Not Configured']
  const bdr = STATUS_PIP_BDR[status] || 'border-gray-200'
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold border',
      cfg.text, cfg.bg, bdr,
    )}>
      <span className={cn(
        'w-1.5 h-1.5 rounded-full shrink-0', cfg.dot,
        status === 'Healthy' ? 'animate-pulse' : '',
      )} />
      {status}
    </span>
  )
}

function CategoryChip({ category }) {
  const cfg  = CATEGORY_CFG[category] || { color: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200', icon: Plug }
  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10.5px] font-medium', cfg.color, cfg.bg, cfg.border)}>
      <Icon size={10} />
      {category}
    </span>
  )
}

function AuthChip({ authMethod }) {
  const cfg  = AUTH_CFG[authMethod] || AUTH_CFG['API Key']
  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium', cfg.color, cfg.bg, cfg.border)}>
      <Icon size={10} />
      {authMethod}
    </span>
  )
}

function IntegrationLogo({ name, abbrev, category, size = 'md' }) {
  const cfg = CATEGORY_CFG[category] || { color: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200' }
  const sz  = size === 'sm' ? 'w-7 h-7 text-[10px]' : size === 'lg' ? 'w-10 h-10 text-[14px]' : 'w-8 h-8 text-[11px]'
  return (
    <div className={cn('rounded-xl flex items-center justify-center font-black border-2 shrink-0', sz, cfg.bg, cfg.color, cfg.border)}>
      {abbrev}
    </div>
  )
}

// Mini 14-day uptime timeline
function UptimeTimeline({ history }) {
  if (!history) return <p className="text-[11px] text-gray-400 italic">No data</p>
  const labels = ['M','T','W','T','F','S','S','M','T','W','T','F','S','S']
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-end gap-0.5 h-5">
        {history.map((s, i) => (
          <div
            key={i}
            title={labels[i]}
            className={cn(
              'flex-1 rounded-sm min-w-[3px]',
              s === 'ok'   ? 'bg-emerald-400 h-full' :
              s === 'warn' ? 'bg-yellow-400 h-[65%]' :
              'bg-red-500 h-[40%]',
            )}
          />
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[9px] text-gray-400 font-mono">14 days ago</span>
        <span className="text-[9px] text-gray-400 font-mono">today</span>
      </div>
    </div>
  )
}

// Setup progress stepper
function SetupProgress({ steps }) {
  if (!steps) return null
  return (
    <div className="space-y-0">
      {steps.map((step, idx) => {
        const isLast = idx === steps.length - 1
        return (
          <div key={step.step} className="flex gap-3">
            <div className="flex flex-col items-center shrink-0">
              <div className={cn(
                'w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-1 border-2 border-white shadow-sm',
                step.status === 'done'    ? 'bg-emerald-500' :
                step.status === 'error'   ? 'bg-red-500' :
                'bg-gray-200',
              )}>
                {step.status === 'done'  && <CheckCircle2 size={10} className="text-white" />}
                {step.status === 'error' && <XCircle      size={10} className="text-white" />}
                {step.status === 'pending' && <span className="text-[8px] font-black text-gray-400">{step.step}</span>}
              </div>
              {!isLast && <div className="flex-1 mt-0.5 mb-0.5 w-px border-l border-dashed border-gray-200 min-h-[12px]" />}
            </div>
            <div className="flex-1 pb-2">
              <p className={cn(
                'text-[11.5px] font-medium mt-0.5',
                step.status === 'done'    ? 'text-gray-600 line-through decoration-gray-300' :
                step.status === 'error'   ? 'text-red-600' :
                'text-gray-500',
              )}>
                {step.label}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── KPI card ──────────────────────────────────────────────────────────────────

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

// ── Integration list ───────────────────────────────────────────────────────────

function IntegrationRow({ integration: int, isSelected, onSelect, onToggle }) {
  const stCfg = INT_STATUS[int.status] || INT_STATUS['Not Configured']
  // Stale sync coloring
  const syncColor =
    int.lastSync === 'Never'                                        ? 'text-gray-300' :
    int.lastSync.includes('2d') || int.lastSync.includes('1d')     ? 'text-red-500 font-semibold' :
    int.lastSync.includes('2h') || int.lastSync.includes('1h')     ? 'text-yellow-600' :
    'text-gray-500'
  return (
    <tr
      onClick={() => onSelect(int.id)}
      className={cn(
        'cursor-pointer transition-colors duration-100 group border-l-[3px]',
        stCfg.bdr,
        isSelected ? 'bg-blue-50/60' : 'hover:bg-gray-50/40',
      )}
    >
      <td className="w-0 p-0" />
      {/* Logo + Name */}
      <td className="px-3.5 py-2.5">
        <div className="flex items-center gap-2.5">
          <IntegrationLogo name={int.name} abbrev={int.abbrev} category={int.category} size="sm" />
          <div className="min-w-0">
            <p className={cn('text-[12.5px] font-semibold leading-snug', isSelected ? 'text-blue-700' : 'text-gray-800 group-hover:text-gray-900')}>
              {int.name}
            </p>
            <div className="flex items-center gap-1 mt-0.5">
              <span className={cn(
                'text-[9px] font-semibold px-1 py-px rounded-sm border leading-tight',
                int.environment === 'Production'
                  ? 'text-gray-400 border-gray-200 bg-gray-50'
                  : 'text-amber-600 border-amber-200 bg-amber-50',
              )}>{int.environment}</span>
              {int.tags.slice(0, 1).map(t => (
                <span key={t} className="text-[9px] font-medium text-gray-400 border border-gray-200 rounded px-1 py-px bg-white leading-tight">{t}</span>
              ))}
            </div>
          </div>
        </div>
      </td>
      {/* Auth */}
      <td className="px-3.5 py-2.5"><AuthChip authMethod={int.authMethod} /></td>
      {/* Status */}
      <td className="px-3.5 py-2.5"><StatusPip status={int.status} /></td>
      {/* Last sync */}
      <td className="px-3.5 py-2.5">
        <span className={cn('text-[11px] font-mono', syncColor)}>{int.lastSync}</span>
      </td>
      {/* Toggle */}
      <td className="px-3.5 py-2.5" onClick={e => e.stopPropagation()}>
        <Toggle checked={int.enabled} onChange={v => onToggle(int.id, v)} showLabel />
      </td>
    </tr>
  )
}

function IntegrationList({ integrations, selectedId, onSelect, onToggle }) {
  // Group by category preserving order
  const categories = []
  const grouped = {}
  integrations.forEach(int => {
    if (!grouped[int.category]) {
      grouped[int.category] = []
      categories.push(int.category)
    }
    grouped[int.category].push(int)
  })

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      {/* Table header */}
      <div className="border-b border-gray-150 bg-gray-50">
        <table className="w-full">
          <thead>
            <tr>
              <th className="w-0 p-0" />
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[240px] min-w-[200px]">Integration</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[130px]">Auth</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[130px]">Status</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[90px]">Last Sync</th>
              <th className="px-3.5 py-2.5 text-left text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 w-[80px]">Active</th>
            </tr>
          </thead>
        </table>
      </div>

      {/* Grouped rows */}
      <div className="divide-y divide-gray-100">
        {categories.map(cat => {
          const cfg  = CATEGORY_CFG[cat] || {}
          const Icon = cfg.icon || Plug
          const rows = grouped[cat]
          return (
            <div key={cat}>
              {/* Category header */}
              <div className="px-4 py-2 flex items-center gap-2.5 bg-gray-50 border-b border-gray-100">
                <div className={cn('w-5 h-5 rounded-md flex items-center justify-center border shrink-0', cfg.bg, cfg.border)}>
                  <Icon size={10} className={cfg.color} />
                </div>
                <span className="text-[10px] font-black uppercase tracking-[0.08em] text-gray-500">{cat}</span>
                <span className="ml-auto text-[9.5px] font-semibold text-gray-300 tabular-nums">
                  {rows.length} integration{rows.length !== 1 ? 's' : ''}
                </span>
              </div>

              {/* Integration rows */}
              <table className="w-full border-collapse">
                <tbody className="divide-y divide-gray-50">
                  {rows.map(int => (
                    <IntegrationRow
                      key={int.id}
                      integration={int}
                      isSelected={int.id === selectedId}
                      onSelect={onSelect}
                      onToggle={onToggle}
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

// ── Integration detail panel ───────────────────────────────────────────────────

const DETAIL_TABS = ['Overview', 'Connection', 'Auth', 'Coverage', 'Activity', 'Workflows']

function SectionLabel({ children }) {
  return (
    <div className="flex items-center gap-2 mb-2.5">
      <p className="text-[10px] font-black uppercase tracking-[0.1em] text-gray-400 whitespace-nowrap">{children}</p>
      <div className="flex-1 h-px bg-gray-100" />
    </div>
  )
}

function MetaRow({ label, value, mono = false }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-gray-100 last:border-0">
      <span className="text-[10.5px] font-semibold text-gray-400 shrink-0 uppercase tracking-[0.04em]">{label}</span>
      <span className={cn('text-[11.5px] text-gray-700 text-right font-medium leading-snug', mono && 'font-mono text-[11px]')}>{value}</span>
    </div>
  )
}

function IntegrationDetailPanel({
  integration: int,
  detailLoading = false,
  onClose,
  onConfigure,
  onTest,
  testBusy = false,
  onEnable,
  onDisable,
  onSync,
}) {
  const [activeTab, setActiveTab] = useState('Overview')
  if (!int) return null

  const stCfg  = INT_STATUS[int.status] || INT_STATUS['Not Configured']
  const HDR_STRIP = int.status === 'Error'   ? 'bg-red-500' :
                    int.status === 'Healthy' ? 'bg-emerald-500' :
                    int.status === 'Warning' ? 'bg-yellow-400' :
                    int.status === 'Partial' ? 'bg-blue-400' : 'bg-gray-300'
  const HDR_BG    = int.status === 'Error'   ? 'bg-red-50/50 border-b-red-100' :
                    int.status === 'Healthy' ? 'bg-emerald-50/30 border-b-emerald-100' :
                    int.status === 'Warning' ? 'bg-yellow-50/40 border-b-yellow-100' :
                    int.status === 'Partial' ? 'bg-blue-50/40 border-b-blue-100' :
                    'bg-gray-50/60 border-b-gray-100'

  return (
    <div className="w-[440px] shrink-0 bg-white border border-gray-200 rounded-xl shadow-sm flex flex-col overflow-hidden">
      {/* Accent strip */}
      <div className={cn('h-[3px] w-full shrink-0', HDR_STRIP)} />

      {/* Header */}
      <div className={cn('px-5 py-4 border-b shrink-0', HDR_BG)}>
        {/* Row 1: logo + close */}
        <div className="flex items-start justify-between gap-2 mb-2.5">
          <div className="flex items-center gap-2.5">
            <IntegrationLogo name={int.name} abbrev={int.abbrev} category={int.category} size="md" />
            <div>
              <h2 className="text-[15px] font-bold text-gray-900 leading-tight">{int.name}</h2>
              <p className="text-[10.5px] text-gray-400 font-medium">{int.vendor}</p>
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
          <StatusPip status={int.status} />
          <CategoryChip category={int.category} />
          <AuthChip authMethod={int.authMethod} />
        </div>

        {/* Row 3: owner + env */}
        <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-3">
          <OwnerAvatar name={int.owner} size="sm" />
          <span className="font-semibold text-gray-600">{int.ownerDisplay}</span>
          <span className="text-gray-300">·</span>
          <span className={cn(
            'text-[10px] font-semibold px-1 py-px rounded-sm border',
            int.environment === 'Production' ? 'text-gray-400 border-gray-200 bg-gray-50' : 'text-amber-600 border-amber-200 bg-amber-50',
          )}>{int.environment}</span>
          <span className="text-gray-300">·</span>
          <span className="font-mono text-gray-400">{int.lastSync}</span>
        </div>

        {/* Row 4: actions */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]" onClick={onConfigure}>
            <Settings size={11} /> Configure
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1 text-[11px] text-blue-600 border-blue-200 hover:bg-blue-50"
            onClick={onTest}
            disabled={testBusy}
          >
            {testBusy
              ? <Loader2 size={11} className="animate-spin" />
              : <Activity size={11} />}
            {testBusy ? 'Testing…' : 'Test'}
          </Button>
          <div className="w-px h-5 bg-gray-200 mx-0.5" />
          {int.status === 'Error' && (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-emerald-600 border-emerald-200 hover:bg-emerald-50 font-semibold" onClick={onConfigure}>
              <RotateCcw size={11} /> Reconnect
            </Button>
          )}
          {int.enabled ? (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-orange-600 border-orange-200 hover:bg-orange-50" onClick={onDisable}>
              <XCircle size={11} /> Disable
            </Button>
          ) : (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-emerald-600 border-emerald-200 hover:bg-emerald-50" onClick={onEnable}>
              <CheckCircle2 size={11} /> Enable
            </Button>
          )}
          {/* Logs — jumps to the Activity tab, which already renders the
              recent-activity table for this integration.  Previously this
              button was a visual stub with no onClick. */}
          <Button
            size="sm"
            variant="ghost"
            className="h-7 gap-1 text-[11px] ml-auto text-gray-400 hover:text-gray-600"
            onClick={() => setActiveTab('Activity')}
          >
            <Eye size={11} /> Logs
          </Button>
        </div>
      </div>

      {/* Tabs
       * ─────────────────────────────────────────────────────────────
       * Pixel-perfect structure:
       *   outer  – horizontal scroll container, reserves an 8px gutter
       *            (pb-2) below the inner row so the 6px scrollbar
       *            sits in its own lane and never touches tab text
       *            or the active-tab indicator.
       *   inner  – flex row that owns the full-width `border-b` gray
       *            line.  Keeping the border on this inner row means
       *            the active tab's blue border-b-2 indicator butts
       *            directly against the gray line with zero gap. */}
      <div className="bg-white shrink-0 px-4 pb-2 overflow-x-auto">
        <div className="flex border-b border-gray-100 min-w-max">
          {DETAIL_TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                'px-3 py-3 text-[11.5px] font-semibold whitespace-nowrap border-b-2 -mb-px transition-colors',
                activeTab === tab
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700',
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">

        {/* ── Overview ── */}
        {activeTab === 'Overview' && (
          <div className="p-5 space-y-5">
            {/* Error / warning banner */}
            {int.status === 'Error' && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-xl">
                <XCircle size={13} className="text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-red-700">Integration Error</p>
                  <p className="text-[11px] text-red-600 mt-0.5 leading-snug">
                    {int.name === 'Splunk' ? 'HEC token expired Apr 7. Rotate credentials to restore event forwarding.' :
                     int.name === 'Kafka'  ? 'Service account certificate expired. Reconnect after cert rotation.' :
                     'Connection failed. Check credentials and endpoint configuration.'}
                  </p>
                </div>
              </div>
            )}
            {int.status === 'Warning' && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-yellow-50 border border-yellow-200 border-l-[3px] border-l-yellow-400 rounded-xl">
                <AlertTriangle size={13} className="text-yellow-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-yellow-700">Attention Required</p>
                  <p className="text-[11px] text-yellow-700 mt-0.5 leading-snug">
                    {int.tokenExpiry.includes('Expires') ? `Credential expiry: ${int.tokenExpiry}. Rotate before deadline.` :
                     'Intermittent delivery failures detected. Review recent activity.'}
                  </p>
                </div>
              </div>
            )}
            {int.setupProgress && int.status !== 'Healthy' && (
              <div className="bg-blue-50 border border-blue-200 border-l-[3px] border-l-blue-400 rounded-xl px-3.5 py-3">
                <p className="text-[11.5px] font-semibold text-blue-700 mb-2.5">Setup Progress</p>
                <SetupProgress steps={int.setupProgress} />
              </div>
            )}

            {/* Description */}
            <div>
              <SectionLabel>Description</SectionLabel>
              <p className="text-[12.5px] text-gray-700 leading-relaxed">{int.description}</p>
            </div>

            {/* Metadata */}
            <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-1">
              <MetaRow label="Vendor"        value={int.vendor} />
              <MetaRow label="Environment"   value={int.environment} />
              <MetaRow label="Owner"         value={int.ownerDisplay} />
              <MetaRow label="Created"       value={int.createdAt} />
              <MetaRow label="Last Modified" value={int.lastModified} />
              <MetaRow label="Last Sync"     value={int.lastSyncFull || '—'} mono />
            </div>

            {/* Tags */}
            <div>
              <SectionLabel>Tags</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {int.tags.map(t => (
                  <span key={t} className="text-[11px] font-medium text-gray-500 border border-gray-200 rounded-md px-2 py-0.5 bg-white">{t}</span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Connection ── */}
        {activeTab === 'Connection' && (
          <div className="p-5 space-y-5">
            {/* Status grid */}
            <div className="grid grid-cols-2 gap-2">
              {[
                {
                  label: 'Uptime (30d)', value: int.uptime || '—',
                  tint: !int.uptime ? 'text-gray-400' :
                        parseFloat(int.uptime) >= 99 ? 'text-emerald-600' :
                        parseFloat(int.uptime) >= 95 ? 'text-yellow-600' : 'text-red-600',
                },
                {
                  label: 'Avg Latency', value: int.avgLatency || '—',
                  tint: !int.avgLatency ? 'text-gray-400' :
                        parseInt(int.avgLatency) <= 200 ? 'text-emerald-600' :
                        parseInt(int.avgLatency) <= 350 ? 'text-gray-800' : 'text-yellow-600',
                },
                { label: 'Last Sync',    value: int.lastSync,                   tint: 'text-gray-800' },
                {
                  label: 'Last Failure', value: int.lastFailedSync || 'None',
                  tint: int.lastFailedSync ? 'text-red-500' : 'text-emerald-600',
                },
              ].map(s => (
                <div key={s.label} className="bg-gray-50 rounded-xl border border-gray-100 px-3.5 py-3">
                  <p className={cn('text-[18px] font-black tabular-nums leading-none', s.tint)}>{s.value}</p>
                  <p className="text-[9.5px] font-black uppercase tracking-[0.08em] text-gray-400 mt-1">{s.label}</p>
                </div>
              ))}
            </div>

            {/* 14-day health timeline */}
            <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-3">
              <SectionLabel>14-Day Health History</SectionLabel>
              <UptimeTimeline history={int.healthHistory} />
              <div className="flex items-center gap-3 mt-3">
                {[['ok','bg-emerald-400','Healthy'],['warn','bg-yellow-400','Degraded'],['err','bg-red-500','Error']].map(([k,c,l]) => (
                  <div key={k} className="flex items-center gap-1.5">
                    <div className={cn('w-2 h-2 rounded-sm', c)} />
                    <span className="text-[9.5px] text-gray-400 font-medium">{l}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Quick actions */}
            <div>
              <SectionLabel>Quick Actions</SectionLabel>
              <div className="grid grid-cols-2 gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1.5 text-[11.5px] justify-start"
                  onClick={onTest}
                  disabled={testBusy}
                >
                  {testBusy
                    ? <Loader2 size={12} className="animate-spin" />
                    : <Activity size={12} />}
                  {testBusy ? 'Testing…' : 'Test Connection'}
                </Button>
                <Button variant="outline" size="sm" className="h-8 gap-1.5 text-[11.5px] justify-start" onClick={onConfigure}>
                  <RotateCcw size={12} /> Rotate Credentials
                </Button>
                <Button variant="outline" size="sm" className="h-8 gap-1.5 text-[11.5px] justify-start" onClick={onSync}>
                  <RefreshCw size={12} /> Force Sync
                </Button>
                <Button variant="outline" size="sm" className="h-8 gap-1.5 text-[11.5px] justify-start">
                  <ExternalLink size={12} /> Open Docs
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* ── Auth ── */}
        {activeTab === 'Auth' && (
          <div className="p-5 space-y-5">
            {/* Auth method card */}
            {(() => {
              const cfg  = AUTH_CFG[int.authMethod] || AUTH_CFG['API Key']
              const lbr  = AUTH_LEFT_BDR[int.authMethod] || 'border-l-gray-300'
              const Icon = cfg.icon
              const expiryTint =
                int.tokenExpiry.includes('Expired') ? 'text-red-600 font-semibold' :
                int.tokenExpiry.includes('Expires') ? 'text-yellow-600 font-semibold' :
                'text-gray-500'
              return (
                <div className={cn('flex items-center gap-3 px-4 py-3.5 rounded-xl border border-l-[3px] shadow-[0_1px_3px_rgba(0,0,0,0.04)]', cfg.bg, cfg.border, lbr)}>
                  <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center border shadow-sm', cfg.bg, cfg.border)}>
                    <Icon size={16} className={cfg.color} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[12.5px] font-semibold text-gray-800">{int.authMethod}</p>
                    <p className={cn('text-[11px] font-mono mt-0.5 leading-snug', expiryTint)}>{int.tokenExpiry}</p>
                  </div>
                </div>
              )
            })()}

            {/* Granted scopes */}
            {int.scopes.length > 0 && (
              <div>
                <SectionLabel>Granted Permissions</SectionLabel>
                <div className="space-y-1.5">
                  {int.scopes.map(s => (
                    <div key={s} className="flex items-center gap-2 px-3 py-1.5 bg-emerald-50 border border-emerald-100 border-l-[3px] border-l-emerald-400 rounded-lg">
                      <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
                      <span className="text-[11px] font-mono text-emerald-800 leading-snug">{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Missing scopes */}
            {int.missingScopes.length > 0 && (
              <div>
                <SectionLabel>Missing Permissions</SectionLabel>
                <div className="space-y-1.5">
                  {int.missingScopes.map(s => (
                    <div key={s} className="flex items-center gap-2 px-3 py-1.5 bg-red-50 border border-red-100 border-l-[3px] border-l-red-400 rounded-lg">
                      <XCircle size={11} className="text-red-400 shrink-0" />
                      <span className="text-[11px] font-mono text-red-700 leading-snug">{s}</span>
                    </div>
                  ))}
                </div>
                <p className="text-[10.5px] text-gray-400 mt-2 leading-snug">
                  Grant missing permissions in your provider console to unlock full coverage.
                </p>
              </div>
            )}

            {int.scopes.length === 0 && int.missingScopes.length === 0 && (
              <p className="text-[12px] text-gray-400 italic">No scope information available — complete setup to configure permissions.</p>
            )}
          </div>
        )}

        {/* ── Coverage ── */}
        {activeTab === 'Coverage' && (
          <div className="p-5 space-y-4">
            <SectionLabel>Capabilities</SectionLabel>
            <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
              {int.capabilities.map((cap, idx) => (
                <div
                  key={cap.label}
                  className={cn(
                    'flex items-center gap-3 px-3.5 py-2.5 border-b border-gray-75 last:border-0 transition-opacity',
                    cap.enabled ? '' : 'opacity-50',
                  )}
                >
                  <div className={cn(
                    'w-5 h-5 rounded-full flex items-center justify-center shrink-0 border-2 border-white shadow-sm',
                    cap.enabled ? 'bg-emerald-100' : 'bg-gray-100',
                  )}>
                    {cap.enabled
                      ? <CheckCircle2 size={10} className="text-emerald-600" />
                      : <XCircle      size={10} className="text-gray-400" />}
                  </div>
                  <span className={cn(
                    'text-[12px] font-medium leading-snug flex-1',
                    cap.enabled ? 'text-gray-700' : 'text-gray-500',
                  )}>
                    {cap.label}
                  </span>
                  <span className={cn(
                    'text-[9.5px] font-semibold px-1.5 py-0.5 rounded-full border',
                    cap.enabled
                      ? 'text-emerald-600 bg-emerald-50 border-emerald-100'
                      : 'text-gray-400 bg-gray-50 border-gray-150',
                  )}>
                    {cap.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Activity ── */}
        {activeTab === 'Activity' && (
          <div className="p-5 space-y-3">
            <SectionLabel>Recent Events</SectionLabel>
            <div className="flex flex-col">
              {int.recentActivity.map((event, idx) => {
                const cfg    = ACT_RESULT_CFG[event.result] || ACT_RESULT_CFG['Info']
                const dotBg  = SPINE_DOT_BG[event.result] || 'bg-gray-100'
                const isLast = idx === int.recentActivity.length - 1
                return (
                  <div key={idx} className="flex gap-3 items-start">
                    <div className="flex flex-col items-center shrink-0 pt-3">
                      <div className={cn('w-5 h-5 rounded-full flex items-center justify-center shrink-0 border-2 border-white shadow-sm', dotBg)}>
                        <span className={cn('w-2 h-2 rounded-full', cfg.dot)} />
                      </div>
                      {!isLast && <div className="flex-1 mt-1 mb-1 w-px border-l border-dashed border-gray-200 min-h-[16px]" />}
                    </div>
                    <div className="flex-1 min-w-0 mb-2.5">
                      <div className={cn('bg-white rounded-xl border border-gray-150 border-l-[3px] px-3.5 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]', cfg.bdr)}>
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-[12px] font-medium text-gray-700 leading-snug">{event.event}</p>
                          <span className="text-[9.5px] font-mono text-gray-400 shrink-0 mt-0.5 whitespace-nowrap">{event.ts}</span>
                        </div>
                        <span className={cn('inline-flex items-center gap-1 mt-1.5 text-[9.5px] font-semibold px-1.5 py-px rounded-full border', cfg.pill)}>
                          <span className={cn('w-1 h-1 rounded-full', cfg.dot)} />
                          {event.result}
                        </span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── Workflows ── */}
        {activeTab === 'Workflows' && (() => {
          const wf = int.linkedWorkflows
          const hasAny = wf.playbooks.length + wf.alerts.length + wf.policies.length + wf.cases.length > 0
          return (
            <div className="p-5 space-y-4">
              {!hasAny && (
                <div className="py-8 flex flex-col items-center gap-2 text-center">
                  <GitBranch size={20} className="text-gray-300" />
                  <p className="text-[12px] text-gray-400 font-medium">No linked workflows yet</p>
                  <p className="text-[10.5px] text-gray-300">Link playbooks, alerts, and policies to track coverage.</p>
                </div>
              )}
              {[
                { label: 'Playbooks', items: wf.playbooks, icon: Zap,        color: 'text-emerald-600', bg: 'bg-emerald-50',  bdr: 'border-l-emerald-400' },
                { label: 'Alerts',    items: wf.alerts,    icon: AlertTriangle,color:'text-orange-500', bg: 'bg-orange-50',   bdr: 'border-l-orange-400' },
                { label: 'Policies',  items: wf.policies,  icon: Shield,      color: 'text-blue-600',   bg: 'bg-blue-50',     bdr: 'border-l-blue-400'   },
                { label: 'Cases',     items: wf.cases,     icon: Layers,      color: 'text-violet-600', bg: 'bg-violet-50',   bdr: 'border-l-violet-400' },
              ].filter(g => g.items.length > 0).map(group => {
                const Icon = group.icon
                return (
                  <div key={group.label}>
                    <SectionLabel>{group.label}</SectionLabel>
                    <div className="space-y-1.5">
                      {group.items.map(item => (
                        <div key={item} className={cn('flex items-center gap-2.5 px-3 py-2 rounded-xl border border-l-[3px] bg-white', group.bdr, 'border-gray-150 shadow-[0_1px_2px_rgba(0,0,0,0.04)]')}>
                          <div className={cn('w-5 h-5 rounded-md flex items-center justify-center shrink-0', group.bg)}>
                            <Icon size={10} className={group.color} />
                          </div>
                          <span className="text-[12px] font-medium text-gray-700">{item}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })()}
      </div>
    </div>
  )
}

// ── Recent activity table ──────────────────────────────────────────────────────

const ACT_ROW_BDR = {
  Success: 'border-l-emerald-400',
  Warning: 'border-l-yellow-400',
  Error:   'border-l-red-500',
  Info:    'border-l-blue-400',
}

function RecentActivityTable({ events }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between bg-white">
        <div className="flex items-center gap-3">
          <p className="text-[13px] font-bold text-gray-900">Recent Activity</p>
          <span className="text-[10.5px] font-medium text-gray-400 bg-gray-100 rounded-full px-2 py-0.5">{events.length} events</span>
        </div>
        <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
          <RefreshCw size={11} /> Refresh
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="w-0 p-0" />
              {['Timestamp', 'Integration', 'Event', 'Result', 'Actor'].map(col => (
                <th key={col} className="px-3.5 py-2.5 text-[10px] font-black uppercase tracking-[0.08em] text-gray-400 whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-75">
            {events.map(ev => {
              const cfg = ACT_RESULT_CFG[ev.result] || ACT_RESULT_CFG['Info']
              const bdr = ACT_ROW_BDR[ev.result] || 'border-l-gray-200'
              return (
                <tr key={ev.id} className={cn('hover:bg-gray-50/50 transition-colors group border-l-[3px]', bdr)}>
                  <td className="w-0 p-0" />
                  <td className="px-3.5 py-2.5 whitespace-nowrap">
                    <span className="text-[10.5px] font-mono text-gray-400">{ev.ts}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="inline-flex items-center text-[11px] font-semibold text-gray-600 bg-gray-50 border border-gray-200 rounded-md px-1.5 py-0.5 whitespace-nowrap">{ev.integration}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="text-[12px] font-medium text-gray-700">{ev.event}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold border', cfg.pill)}>
                      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', cfg.dot)} />
                      {ev.result}
                    </span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className={cn(
                      'text-[11px]',
                      ev.actor === 'System'
                        ? 'font-mono text-gray-300'
                        : 'font-semibold text-gray-500 group-hover:text-gray-700 transition-colors',
                    )}>{ev.actor}</span>
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

export default function Integrations() {
  // ── Filters ────────────────────────────────────────────────────────────────
  // Backend does server-side filtering on category/status/q; auth-method and
  // "only unhealthy" are client-side, because the list endpoint doesn't take
  // those and they're cheap to apply to the returned array (we never have
  // more than ~50 rows).
  const [search,         setSearch]         = useState('')
  const [filterCategory, setFilterCategory] = useState('All Categories')
  const [filterStatus,   setFilterStatus]   = useState('All Statuses')
  const [filterAuth,     setFilterAuth]     = useState('All Auth Types')
  const [onlyUnhealthy,  setOnlyUnhealthy]  = useState(false)

  // Live list + metrics — the hook reacts to filter changes automatically
  // and drops stale responses via its seq counter, so there's no extra work
  // to do here when the user flips a filter mid-request.
  const { integrations: rawList, metrics, loading, error, refresh } =
    useIntegrations({ category: filterCategory, status: filterStatus, q: search })

  // Normalize server rows to the flat view-model the renderers were built
  // against.  Memoized so IntegrationRow's identity checks don't re-mount
  // every render.
  const integrations = useMemo(
    () => (rawList || []).map(summaryToListRow),
    [rawList],
  )

  // Selection: default to the first integration once the list lands, and
  // clear the selection if the selected row disappears after a refresh.
  const [selectedId, setSelectedId] = useState(null)
  const resolvedSelectedId =
    selectedId && integrations.some(i => i.id === selectedId)
      ? selectedId
      : integrations[0]?.id ?? null

  // Full detail (credentials/connection/auth/coverage/activity/workflows)
  // — fetched lazily per-selection.  The list row already has enough to
  // render the header chips while we wait for the detail to arrive.
  const { integration: rawDetail, loading: detailLoading, refresh: refreshDetail } =
    useIntegration(resolvedSelectedId)
  const selectedDetail = useMemo(() => detailToViewModel(rawDetail), [rawDetail])
  const selectedListRow = integrations.find(i => i.id === resolvedSelectedId) || null
  // Prefer the full detail view-model; fall back to the summary row so the
  // panel can render its header immediately on selection while the detail
  // request is in flight.
  const selectedInt = selectedDetail || selectedListRow

  // ── Configure modal ────────────────────────────────────────────────────────
  const [configureOpen, setConfigureOpen] = useState(false)

  // ── Create modal + Import/Export state ─────────────────────────────────────
  const [createOpen,     setCreateOpen]     = useState(false)
  const [importBusy,     setImportBusy]     = useState(false)
  const [exportBusy,     setExportBusy]     = useState(false)
  const [importSummary,  setImportSummary]  = useState(null)   // { ok, failed, total }

  // ── Mutations (optimistic; revert + surface error on failure) ──────────────
  const [mutationError, setMutationError] = useState(null)
  // Test-button state — structured result + loading flag so the Test
  // button can show a spinner, and we can render a green/red banner with
  // the probe's message + latency when the call completes.
  const [testResult,    setTestResult]    = useState(null)
  const [testBusy,      setTestBusy]      = useState(false)
  async function runMutation(fn) {
    setMutationError(null)
    try {
      await fn()
      // Refresh list + detail so the KPI strip and chips reflect the new
      // state.  We could be more surgical (swap in the returned row), but
      // mutation rates on this surface are low enough that an extra GET
      // is a fine tradeoff for guaranteed correctness.
      await Promise.all([refresh(), refreshDetail()])
    } catch (err) {
      setMutationError(err)
    }
  }

  async function handleToggle(id, enabled) {
    await runMutation(() => (enabled ? enableIntegration(id) : disableIntegration(id)))
  }
  async function handleEnable()  { if (selectedInt) await runMutation(() => enableIntegration(selectedInt.id)) }
  async function handleDisable() { if (selectedInt) await runMutation(() => disableIntegration(selectedInt.id)) }

  // Test — unlike the other mutations, we want to show the probe's
  // structured response ({ ok, message, latency_ms }) to the user, not
  // just flip the row status silently.  The backend always returns 200
  // whether the probe passed or failed, so we capture the body into
  // `testResult` and render a green/red banner.  The network-level
  // errors (500, etc.) still fall through to mutationError.
  async function handleTest() {
    if (!selectedInt) return
    setMutationError(null)
    setTestResult(null)
    setTestBusy(true)
    try {
      const res = await testIntegration(selectedInt.id)
      setTestResult({ ...res, integrationName: selectedInt.name })
      // Refresh so the row's Healthy/Error chip matches the probe result.
      await Promise.all([refresh(), refreshDetail()])
    } catch (err) {
      setMutationError(err)
    } finally {
      setTestBusy(false)
    }
  }

  async function handleSync()    { if (selectedInt) await runMutation(() => syncIntegration(selectedInt.id))    }
  async function handleSaved()   { await Promise.all([refresh(), refreshDetail()]) }

  // ── Create handler ─────────────────────────────────────────────────────────
  // On successful create, refresh the list so the new row renders, then
  // auto-select it so the detail panel opens on the thing the user just made.
  async function handleCreated(created) {
    setMutationError(null)
    setImportSummary(null)
    await refresh()
    if (created?.id) setSelectedId(created.id)
  }

  // ── Export handler ─────────────────────────────────────────────────────────
  // Server returns IntegrationSummary (no credentials), but we still defensively
  // strip any credential-shaped fields in case the server payload evolves.  The
  // JSON is round-trippable through the Import handler below.
  async function handleExport() {
    setMutationError(null)
    setImportSummary(null)
    setExportBusy(true)
    try {
      const rows = await listIntegrations()
      const safe = (rows || []).map(r => {
        const {
          // secrets / runtime-only fields we never want in a portable config
          credentials:   _creds,     // eslint-disable-line no-unused-vars
          api_key:       _apiKey,    // eslint-disable-line no-unused-vars
          value_hint:    _hint,      // eslint-disable-line no-unused-vars
          last_sync:     _ls1,       // eslint-disable-line no-unused-vars
          lastSync:      _ls2,       // eslint-disable-line no-unused-vars
          avg_latency:   _al1,       // eslint-disable-line no-unused-vars
          avgLatency:    _al2,       // eslint-disable-line no-unused-vars
          health_history:_hh1,       // eslint-disable-line no-unused-vars
          healthHistory: _hh2,       // eslint-disable-line no-unused-vars
          uptime:        _up,        // eslint-disable-line no-unused-vars
          status:        _st,        // reset to Not Configured on re-import
          id:            _id,        // eslint-disable-line no-unused-vars
          ...rest
        } = r
        return rest
      })
      const payload = {
        version:      1,
        exported_at:  new Date().toISOString(),
        integrations: safe,
      }
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `integrations-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setMutationError(err)
    } finally {
      setExportBusy(false)
    }
  }

  // ── Import handler ─────────────────────────────────────────────────────────
  // Opens a transient <input type=file>.  Accepts either the export shape
  // ({ version, integrations: [...] }) or a bare array of integration objects.
  // Creates each row via POST /integrations and tallies success/failure;
  // duplicates surface as per-row errors without aborting the batch.
  function handleImport() {
    setMutationError(null)
    setImportSummary(null)
    const input = document.createElement('input')
    input.type   = 'file'
    input.accept = 'application/json,.json'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      setImportBusy(true)
      try {
        const text  = await file.text()
        const json  = JSON.parse(text)
        const rows  = Array.isArray(json)
          ? json
          : Array.isArray(json?.integrations)
            ? json.integrations
            : null
        if (!rows) {
          throw new Error('File must be a JSON array or { integrations: [...] }.')
        }
        let ok = 0
        let failed = 0
        for (const row of rows) {
          if (!row || !row.name || !row.category) { failed += 1; continue }
          try {
            await createIntegration({
              name:        row.name,
              category:    row.category,
              auth_method: row.auth_method || row.authMethod || 'API Key',
              environment: row.environment || 'Production',
              ...(row.vendor      ? { vendor:      row.vendor      } : {}),
              ...(row.description ? { description: row.description } : {}),
              ...(Array.isArray(row.tags) && row.tags.length
                ? { tags: row.tags }
                : {}),
              ...(row.config && typeof row.config === 'object'
                ? { config: row.config }
                : {}),
              ...(row.external_id ? { external_id: row.external_id } : {}),
            })
            ok += 1
          } catch {
            failed += 1
          }
        }
        setImportSummary({ ok, failed, total: rows.length })
        await refresh()
      } catch (err) {
        setMutationError(err)
      } finally {
        setImportBusy(false)
      }
    }
    // Firefox won't fire change if the element isn't in the DOM briefly.
    document.body.appendChild(input)
    input.click()
    setTimeout(() => input.remove(), 1000)
  }

  // ── Filter options ─────────────────────────────────────────────────────────
  // Pull options from the (already-filtered) live list.  This intentionally
  // re-uses whatever the server just returned, so categories/statuses that
  // aren't present are hidden from the dropdown rather than showing as
  // empty picks.
  const categoryOpts = ['All Categories', ...Array.from(new Set(integrations.map(i => i.category)))]
  const statusOpts   = ['All Statuses',   ...Array.from(new Set(integrations.map(i => i.status)))]
  const authOpts     = ['All Auth Types', ...Array.from(new Set(integrations.map(i => i.authMethod)))]

  // Client-side only for auth + unhealthy flag; the rest is already server-side.
  const filtered = integrations.filter(i => {
    if (filterAuth     !== 'All Auth Types' && i.authMethod !== filterAuth) return false
    if (onlyUnhealthy && (i.status === 'Healthy' || i.status === 'Disabled')) return false
    return true
  })

  // ── KPIs — prefer server metrics when present, fall back to derived ────────
  const totalConnected = metrics?.connected        ?? integrations.filter(i => i.status !== 'Not Configured' && i.status !== 'Disabled').length
  const healthy        = metrics?.healthy          ?? integrations.filter(i => i.status === 'Healthy').length
  const needsAttention = metrics?.needs_attention  ?? integrations.filter(i => i.status === 'Warning' || i.status === 'Partial').length
  const failedSyncs    = metrics?.failed_syncs_24h ?? 0

  return (
    <PageContainer>
      {/* Page header */}
      <PageHeader
        title="Integrations"
        subtitle="Connect AI providers, security systems, and operational tools to extend platform coverage"
        actions={
          <>
            <Button size="sm" variant="outline" className="gap-1.5" onClick={refresh} disabled={loading}>
              {loading
                ? <Loader2 size={13} className="animate-spin" />
                : <RefreshCw size={13} />}
              Sync
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={handleImport}
              disabled={importBusy}
            >
              {importBusy
                ? <Loader2 size={13} className="animate-spin" />
                : <Upload size={13} />}
              Import Config
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={handleExport}
              disabled={exportBusy}
            >
              {exportBusy
                ? <Loader2 size={13} className="animate-spin" />
                : <Download size={13} />}
              Export
            </Button>
            <Button
              size="sm"
              className="gap-1.5"
              onClick={() => setCreateOpen(true)}
            >
              <Plus size={13} /> Add Integration
            </Button>
          </>
        }
      />

      {/* Error banners (list load + mutation) */}
      {error && (
        <div className="flex items-start gap-2.5 px-3.5 py-3 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-xl">
          <AlertTriangle size={13} className="text-red-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-[11.5px] font-semibold text-red-700">Couldn't load integrations</p>
            <p className="text-[11px] text-red-600 mt-0.5 leading-snug">
              {error.message || 'Request failed.'} Try the Sync button to retry.
            </p>
          </div>
        </div>
      )}
      {mutationError && (
        <div className="flex items-start gap-2.5 px-3.5 py-3 bg-red-50 border border-red-200 border-l-[3px] border-l-red-500 rounded-xl">
          <AlertTriangle size={13} className="text-red-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-[11.5px] font-semibold text-red-700">Action failed</p>
            <p className="text-[11px] text-red-600 mt-0.5 leading-snug">
              {mutationError.message || 'Request failed.'}
            </p>
          </div>
        </div>
      )}
      {/* Test-probe result — green on ok, red on failure.  Dismissible
          via the X so it doesn't hang around after the user's seen it. */}
      {testResult && (
        <div
          className={cn(
            'flex items-start gap-2.5 px-3.5 py-3 border border-l-[3px] rounded-xl',
            testResult.ok
              ? 'bg-emerald-50 border-emerald-200 border-l-emerald-500'
              : 'bg-red-50 border-red-200 border-l-red-500',
          )}
        >
          {testResult.ok
            ? <CheckCircle2 size={13} className="text-emerald-600 mt-0.5 shrink-0" />
            : <XCircle size={13} className="text-red-500 mt-0.5 shrink-0" />}
          <div className="flex-1 min-w-0">
            <p className={cn(
              'text-[11.5px] font-semibold',
              testResult.ok ? 'text-emerald-700' : 'text-red-700',
            )}>
              {testResult.ok
                ? `${testResult.integrationName || 'Integration'} is alive`
                : `${testResult.integrationName || 'Integration'} test failed`}
              {testResult.latency_ms != null && (
                <span className="ml-1.5 font-mono text-[10.5px] opacity-70">
                  ({testResult.latency_ms}ms)
                </span>
              )}
            </p>
            <p className={cn(
              'text-[11px] mt-0.5 leading-snug',
              testResult.ok ? 'text-emerald-700/80' : 'text-red-600',
            )}>
              {testResult.message || (testResult.ok ? 'Probe succeeded.' : 'Probe failed.')}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setTestResult(null)}
            className="w-5 h-5 flex items-center justify-center rounded-md hover:bg-black/[0.06] text-gray-400 hover:text-gray-600 transition-colors shrink-0"
            aria-label="Dismiss"
          >
            <X size={11} />
          </button>
        </div>
      )}
      {importSummary && (
        <div
          className={cn(
            'flex items-start gap-2.5 px-3.5 py-3 border border-l-[3px] rounded-xl',
            importSummary.failed === 0
              ? 'bg-emerald-50 border-emerald-200 border-l-emerald-500'
              : 'bg-yellow-50 border-yellow-200 border-l-yellow-500',
          )}
        >
          {importSummary.failed === 0
            ? <CheckCircle2 size={13} className="text-emerald-600 mt-0.5 shrink-0" />
            : <AlertTriangle size={13} className="text-yellow-600 mt-0.5 shrink-0" />}
          <div className="flex-1">
            <p className={cn(
              'text-[11.5px] font-semibold',
              importSummary.failed === 0 ? 'text-emerald-700' : 'text-yellow-800',
            )}>
              Import complete
            </p>
            <p className={cn(
              'text-[11px] mt-0.5 leading-snug',
              importSummary.failed === 0 ? 'text-emerald-700' : 'text-yellow-700',
            )}>
              {importSummary.ok} of {importSummary.total} integrations imported
              {importSummary.failed > 0 && ` · ${importSummary.failed} failed (likely duplicates or missing required fields)`}
              .
            </p>
          </div>
          <button
            onClick={() => setImportSummary(null)}
            className="w-5 h-5 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-black/[0.04] shrink-0"
            aria-label="Dismiss"
          >
            <X size={11} />
          </button>
        </div>
      )}

      {/* KPI strip */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="Connected"          value={totalConnected} sub="Active connections" icon={Plug}          iconBg="bg-blue-500"    valueTint="text-blue-600"    stripColor="bg-blue-500"    />
        <KpiCard label="Healthy"            value={healthy}        sub="No issues detected" icon={CheckCircle2}  iconBg="bg-emerald-500" valueTint="text-emerald-600" stripColor="bg-emerald-500" />
        <KpiCard label="Needs Attention"    value={needsAttention} sub="Warning or partial" icon={AlertTriangle} iconBg="bg-yellow-500"  valueTint={needsAttention > 0 ? 'text-yellow-600' : 'text-gray-900'} stripColor={needsAttention > 0 ? 'bg-yellow-400' : 'bg-gray-200'} />
        <KpiCard label="Failed Syncs (24h)" value={failedSyncs}   sub="In last 24 hours"   icon={XCircle}       iconBg="bg-red-500"     valueTint={failedSyncs > 0 ? 'text-red-600' : 'text-gray-900'}      stripColor={failedSyncs > 0 ? 'bg-red-500' : 'bg-gray-200'} />
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
            placeholder="Search integrations…"
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

        <FilterSelect value={filterCategory} onChange={setFilterCategory} options={categoryOpts} />
        <FilterSelect value={filterStatus}   onChange={setFilterStatus}   options={statusOpts}   />
        <FilterSelect value={filterAuth}     onChange={setFilterAuth}     options={authOpts}     />

        {/* Unhealthy toggle */}
        <div className="flex items-center gap-2 ml-auto">
          <Toggle checked={onlyUnhealthy} onChange={setOnlyUnhealthy} />
          <span className="text-[12px] font-medium text-gray-500">Only unhealthy</span>
        </div>
      </div>

      {/* Main area: list + detail */}
      <div className="flex gap-4 items-start">
        {/* Integration list */}
        <div className="flex-1 min-w-0">
          {loading && integrations.length === 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm py-16 flex flex-col items-center gap-2 text-center">
              <Loader2 size={20} className="text-gray-300 animate-spin" />
              <p className="text-[12.5px] text-gray-400 font-medium">Loading integrations…</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl shadow-sm py-16 flex flex-col items-center gap-2 text-center">
              <Filter size={20} className="text-gray-300" />
              <p className="text-[12.5px] text-gray-400 font-medium">No integrations match your filters</p>
              <p className="text-[11px] text-gray-300">Try adjusting the search or filter criteria</p>
            </div>
          ) : (
            <IntegrationList
              integrations={filtered}
              selectedId={resolvedSelectedId}
              onSelect={setSelectedId}
              onToggle={handleToggle}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedInt && (
          <IntegrationDetailPanel
            integration={selectedInt}
            detailLoading={detailLoading && !selectedDetail}
            onClose={() => setSelectedId(null)}
            onConfigure={() => setConfigureOpen(true)}
            onTest={handleTest}
            testBusy={testBusy}
            onEnable={handleEnable}
            onDisable={handleDisable}
            onSync={handleSync}
          />
        )}
      </div>

      {/* Recent activity */}
      <RecentActivityTable events={MOCK_ACTIVITY} />

      {/* Configure modal — admin-only on the server; dev token has the role. */}
      <IntegrationConfigureModal
        integration={selectedInt}
        open={configureOpen}
        onClose={() => setConfigureOpen(false)}
        onSaved={handleSaved}
      />

      {/* Create modal — POSTs to /integrations; on success auto-selects the new row. */}
      <IntegrationCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleCreated}
      />
    </PageContainer>
  )
}
