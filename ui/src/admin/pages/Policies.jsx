import { useState } from 'react'
import {
  ShieldCheck, ScrollText, FileCode2, SlidersHorizontal,
  History, Sparkles, Play, Copy, Archive,
  Search, Download, Plus, Upload,
  CheckCircle2, Clock, AlertTriangle, Users,
  ChevronRight, X, Wrench, Database, Bot,
  Globe, Lock, TriangleAlert, TestTube2,
  Save, Pencil, Eye, RotateCcw, Zap,
  Tag, Building2,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'

// ── Design tokens ──────────────────────────────────────────────────────────────

const MODE_CFG = {
  Enforce:  { badge: 'success',  dot: 'bg-emerald-500',              label: 'Enforce'  },
  Monitor:  { badge: 'medium',   dot: 'bg-yellow-400',               label: 'Monitor'  },
  Disabled: { badge: 'neutral',  dot: 'bg-gray-300',                 label: 'Disabled' },
}

const TYPE_CFG = {
  'prompt-safety':     { label: 'Prompt Safety',     color: 'text-violet-600', bg: 'bg-violet-50', border: 'border-violet-200', icon: ShieldCheck  },
  'tool-access':       { label: 'Tool Access',        color: 'text-blue-600',   bg: 'bg-blue-50',   border: 'border-blue-200',   icon: Wrench       },
  'data-access':       { label: 'Data Access',        color: 'text-cyan-600',   bg: 'bg-cyan-50',   border: 'border-cyan-200',   icon: Database     },
  'output-validation': { label: 'Output Validation',  color: 'text-emerald-600',bg: 'bg-emerald-50',border: 'border-emerald-200',icon: CheckCircle2 },
  'privacy':           { label: 'Privacy / Redaction',color: 'text-pink-600',   bg: 'bg-pink-50',   border: 'border-pink-200',   icon: Lock         },
  'tenant-isolation':  { label: 'Tenant Isolation',   color: 'text-indigo-600', bg: 'bg-indigo-50', border: 'border-indigo-200', icon: Building2    },
  'rate-limit':        { label: 'Budget / Rate Limits',color: 'text-amber-600', bg: 'bg-amber-50',  border: 'border-amber-200',  icon: Zap          },
}

const TABS = ['Overview', 'Logic', 'Scope', 'History']

// ── Mock data ──────────────────────────────────────────────────────────────────

const POLICIES = [
  {
    id: 'pg-v3',
    name: 'Prompt-Guard',
    version: 'v3',
    type: 'prompt-safety',
    mode: 'Enforce',
    status: 'Active',
    scope: 'All Production Agents',
    owner: 'security-ops',
    createdBy: 'admin@orbyx.ai',
    created: 'Mar 12, 2026',
    updated: '2d ago',
    updatedFull: 'Apr 7, 2026 · 09:14 UTC',
    description: 'Detects and blocks adversarial prompt patterns including jailbreaks, role-play overrides, and Base64-encoded bypass attempts before they reach any production model invocation.',
    affectedAssets: 8,
    relatedAlerts: 4,
    linkedSimulations: 2,
    agents: ['CustomerSupport-GPT', 'ThreatHunter-AI', 'DataPipeline-Orchestrator'],
    tools: [],
    dataSources: [],
    environments: ['Production'],
    exceptions: ['staging-test-agent-01'],
    impact: { blocked: 4, flagged: 11, unchanged: 105, total: 120 },
    history: [
      { version: 'v3', by: 'admin@orbyx.ai',        when: 'Apr 7, 2026 · 09:14', change: 'Added Base64 payload detection. Confidence threshold raised to 0.92.' },
      { version: 'v2', by: 'sec-eng@orbyx.ai',      when: 'Mar 28, 2026 · 14:02', change: 'Expanded jailbreak signature library. Added roleplay framing detection.' },
      { version: 'v1', by: 'admin@orbyx.ai',        when: 'Mar 12, 2026 · 10:30', change: 'Initial policy created. Basic injection pattern matching.' },
    ],
    logic: [
      { t: 'kw',  v: 'package' }, { t: 'tx', v: ' ai.security.prompt_guard\n\n' },
      { t: 'kw',  v: 'import'  }, { t: 'tx', v: ' future.keywords.if\n' },
      { t: 'kw',  v: 'import'  }, { t: 'tx', v: ' future.keywords.in\n\n' },
      { t: 'kw',  v: 'default' }, { t: 'tx', v: ' allow := ' }, { t: 'bl', v: 'false\n\n' },
      { t: 'fn',  v: 'allow'   }, { t: 'tx', v: ' ' }, { t: 'kw', v: 'if' }, { t: 'tx', v: ' {\n' },
      { t: 'tx',  v: '    not ' }, { t: 'fn', v: 'injection_detected\n' },
      { t: 'tx',  v: '    not ' }, { t: 'fn', v: 'jailbreak_pattern_matched\n' },
      { t: 'tx',  v: '}\n\n' },
      { t: 'fn',  v: 'injection_detected' }, { t: 'tx', v: ' ' }, { t: 'kw', v: 'if' }, { t: 'tx', v: ' {\n' },
      { t: 'tx',  v: '    patterns := [\n' },
      { t: 'str', v: '        "ignore all previous instructions"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '        "forget your system prompt"'        }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '        "you are now"'                      }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '        "act as if you have no"'           }, { t: 'tx', v: ',\n' },
      { t: 'tx',  v: '    ]\n' },
      { t: 'tx',  v: '    some pattern ' }, { t: 'kw', v: 'in' }, { t: 'tx', v: ' patterns\n' },
      { t: 'fn',  v: '    contains' }, { t: 'tx', v: '(' }, { t: 'fn', v: 'lower' }, { t: 'tx', v: '(input.prompt), pattern)\n' },
      { t: 'tx',  v: '}\n\n' },
      { t: 'fn',  v: 'jailbreak_pattern_matched' }, { t: 'tx', v: ' ' }, { t: 'kw', v: 'if' }, { t: 'tx', v: ' {\n' },
      { t: 'tx',  v: '    input.threat_score > ' }, { t: 'num', v: '0.85\n' },
      { t: 'tx',  v: '    input.pattern_type == ' }, { t: 'str', v: '"adversarial"\n' },
      { t: 'tx',  v: '}\n' },
    ],
  },
  {
    id: 'ts-v2',
    name: 'Tool-Scope',
    version: 'v2',
    type: 'tool-access',
    mode: 'Enforce',
    status: 'Active',
    scope: 'Finance Tools',
    owner: 'data-eng',
    createdBy: 'data-eng@orbyx.ai',
    created: 'Feb 18, 2026',
    updated: '5d ago',
    updatedFull: 'Apr 4, 2026 · 16:45 UTC',
    description: 'Restricts SQL tool invocations to SELECT-only queries for all non-privileged agents. Blocks INSERT, UPDATE, DELETE, DROP, and TRUNCATE statements in production database tools.',
    affectedAssets: 5,
    relatedAlerts: 2,
    linkedSimulations: 1,
    agents: ['DataPipeline-Orchestrator'],
    tools: ['SQL-Query-Runner', 'BigQuery-Connector'],
    dataSources: ['Customer-Records-DB'],
    environments: ['Production', 'Staging'],
    exceptions: [],
    impact: { blocked: 2, flagged: 6, unchanged: 112, total: 120 },
    history: [
      { version: 'v2', by: 'data-eng@orbyx.ai',   when: 'Apr 4, 2026 · 16:45', change: 'Extended allowlist enforcement to BigQuery connector. Added TRUNCATE to blocklist.' },
      { version: 'v1', by: 'admin@orbyx.ai',       when: 'Feb 18, 2026 · 11:00', change: 'Initial scope policy. SELECT-only allowlist for SQL-Query-Runner.' },
    ],
    logic: [
      { t: 'cm', v: '// Tool-Scope v2 — Query allowlist enforcement\n\n' },
      { t: 'tx', v: '{\n' },
      { t: 'pr', v: '  "policy"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"tool-scope-v2"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "version"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"2.0.1"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "tools"' }, { t: 'tx', v: ': [' }, { t: 'str', v: '"SQL-Query-Runner"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"BigQuery-Connector"' }, { t: 'tx', v: '],\n' },
      { t: 'pr', v: '  "allowed_operations"' }, { t: 'tx', v: ': [\n' },
      { t: 'str', v: '    "SELECT"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"SHOW"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"DESCRIBE"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"EXPLAIN"\n' },
      { t: 'tx', v: '  ],\n' },
      { t: 'pr', v: '  "blocked_operations"' }, { t: 'tx', v: ': [\n' },
      { t: 'str', v: '    "INSERT"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"UPDATE"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"DELETE"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "DROP"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"TRUNCATE"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"ALTER"\n' },
      { t: 'tx', v: '  ],\n' },
      { t: 'pr', v: '  "on_violation"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"block_and_alert"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "privileged_agents"' }, { t: 'tx', v: ': [' }, { t: 'str', v: '"dba-agent-01"' }, { t: 'tx', v: ']\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'pm-v2',
    name: 'PII-Mask',
    version: 'v2',
    type: 'privacy',
    mode: 'Enforce',
    status: 'Active',
    scope: 'Customer-Docs RAG',
    owner: 'ml-platform',
    createdBy: 'privacy-eng@orbyx.ai',
    created: 'Jan 30, 2026',
    updated: '1w ago',
    updatedFull: 'Apr 2, 2026 · 10:05 UTC',
    description: 'Masks or redacts personally identifiable information from model inputs and outputs, and from RAG retrieval context before passing to any LLM invocation.',
    affectedAssets: 11,
    relatedAlerts: 1,
    linkedSimulations: 3,
    agents: ['CustomerSupport-GPT', 'HRIntake-Bot'],
    tools: [],
    dataSources: ['Customer-Records-DB', 'HR-Knowledge-Base'],
    environments: ['Production'],
    exceptions: ['pii-audit-agent'],
    impact: { blocked: 0, flagged: 17, unchanged: 103, total: 120 },
    history: [
      { version: 'v2', by: 'privacy-eng@orbyx.ai', when: 'Apr 2, 2026 · 10:05', change: 'Added ADDRESS and DOB to entity types. Confidence threshold lowered to 0.72.' },
      { version: 'v1', by: 'admin@orbyx.ai',        when: 'Jan 30, 2026 · 09:00', change: 'Initial PII masking policy. EMAIL, PHONE, SSN, CREDIT_CARD.' },
    ],
    logic: [
      { t: 'cm', v: '// PII-Mask v2 — Entity detection and redaction\n\n' },
      { t: 'tx', v: '{\n' },
      { t: 'pr', v: '  "policy"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"pii-mask-v2"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "version"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"2.1.0"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "confidence_threshold"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '0.72' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "rules"' }, { t: 'tx', v: ': [\n' },
      { t: 'tx', v: '    {\n' },
      { t: 'pr', v: '      "entity_types"' }, { t: 'tx', v: ': [' }, { t: 'str', v: '"EMAIL"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"PHONE"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"SSN"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"CREDIT_CARD"' }, { t: 'tx', v: '],\n' },
      { t: 'pr', v: '      "action"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"MASK"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '      "mask_char"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"*"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '      "preserve_length"' }, { t: 'tx', v: ': ' }, { t: 'bl', v: 'true' }, { t: 'tx', v: '\n    },\n' },
      { t: 'tx', v: '    {\n' },
      { t: 'pr', v: '      "entity_types"' }, { t: 'tx', v: ': [' }, { t: 'str', v: '"NAME"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"ADDRESS"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"DOB"' }, { t: 'tx', v: '],\n' },
      { t: 'pr', v: '      "action"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"REDACT"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '      "replacement"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"[REDACTED]"' }, { t: 'tx', v: '\n    }\n' },
      { t: 'tx', v: '  ],\n' },
      { t: 'pr', v: '  "apply_to"' }, { t: 'tx', v: ': [' }, { t: 'str', v: '"model_input"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"model_output"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"rag_context"' }, { t: 'tx', v: ']\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'ti-v1',
    name: 'Tenant-Isolate',
    version: 'v1',
    type: 'tenant-isolation',
    mode: 'Enforce',
    status: 'Active',
    scope: 'All Tenants',
    owner: 'platform-eng',
    createdBy: 'platform-eng@orbyx.ai',
    created: 'Feb 1, 2026',
    updated: '2w ago',
    updatedFull: 'Mar 26, 2026 · 14:30 UTC',
    description: 'Prevents cross-tenant data access during RAG retrieval and model context injection. Validates tenant boundary on every knowledge-base query.',
    affectedAssets: 19,
    relatedAlerts: 0,
    linkedSimulations: 1,
    agents: ['CustomerSupport-GPT', 'HRIntake-Bot', 'DataPipeline-Orchestrator'],
    tools: [],
    dataSources: ['Customer-Records-DB', 'HR-Knowledge-Base', 'SIEM-Event-Stream'],
    environments: ['Production', 'Staging'],
    exceptions: [],
    impact: { blocked: 0, flagged: 2, unchanged: 118, total: 120 },
    history: [
      { version: 'v1', by: 'platform-eng@orbyx.ai', when: 'Mar 26, 2026 · 14:30', change: 'Added SIEM-Event-Stream to covered data sources.' },
      { version: 'v1', by: 'admin@orbyx.ai',         when: 'Feb 1, 2026 · 08:45',  change: 'Initial tenant isolation policy.' },
    ],
    logic: [
      { t: 'kw', v: 'package' }, { t: 'tx', v: ' ai.security.tenant_isolation\n\n' },
      { t: 'kw', v: 'default' }, { t: 'tx', v: ' allow := ' }, { t: 'bl', v: 'false\n\n' },
      { t: 'fn', v: 'allow' }, { t: 'tx', v: ' ' }, { t: 'kw', v: 'if' }, { t: 'tx', v: ' {\n' },
      { t: 'tx', v: '    input.session.tenant_id == input.resource.tenant_id\n' },
      { t: 'tx', v: '    input.session.tenant_id != ' }, { t: 'str', v: '""' }, { t: 'tx', v: '\n' },
      { t: 'tx', v: '}\n\n' },
      { t: 'fn', v: 'allow' }, { t: 'tx', v: ' ' }, { t: 'kw', v: 'if' }, { t: 'tx', v: ' {\n' },
      { t: 'cm', v: '    # Super-admin bypass with audit log\n' },
      { t: 'tx', v: '    input.session.role == ' }, { t: 'str', v: '"platform-admin"\n' },
      { t: 'fn', v: '    audit_log' }, { t: 'tx', v: '(input.session, input.resource)\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'wa-v1',
    name: 'Write-Approval',
    version: 'v1',
    type: 'tool-access',
    mode: 'Monitor',
    status: 'Active',
    scope: 'Write-Capable Tools',
    owner: 'security-ops',
    createdBy: 'sec-eng@orbyx.ai',
    created: 'Mar 5, 2026',
    updated: '3d ago',
    updatedFull: 'Apr 6, 2026 · 11:20 UTC',
    description: 'Requires human-in-the-loop approval before any agent may invoke a write-capable tool in production. Currently in monitor mode — logging without blocking.',
    affectedAssets: 4,
    relatedAlerts: 1,
    linkedSimulations: 0,
    agents: ['DataPipeline-Orchestrator'],
    tools: ['SQL-Query-Runner', 'GitHub-PR-Creator', 'Email-Sender'],
    dataSources: [],
    environments: ['Production'],
    exceptions: ['auto-approved-pipeline-01'],
    impact: { blocked: 0, flagged: 8, unchanged: 112, total: 120 },
    history: [
      { version: 'v1', by: 'sec-eng@orbyx.ai',   when: 'Apr 6, 2026 · 11:20', change: 'Extended monitoring to Email-Sender tool.' },
      { version: 'v1', by: 'admin@orbyx.ai',      when: 'Mar 5, 2026 · 15:00', change: 'Initial write-approval policy in monitor mode.' },
    ],
    logic: [
      { t: 'cm', v: '// Write-Approval v1 — Human approval gate\n\n' },
      { t: 'tx', v: '{\n' },
      { t: 'pr', v: '  "policy"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"write-approval-v1"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "mode"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"monitor"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "write_capable_tools"' }, { t: 'tx', v: ': [\n' },
      { t: 'str', v: '    "SQL-Query-Runner"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"GitHub-PR-Creator"' }, { t: 'tx', v: ', ' }, { t: 'str', v: '"Email-Sender"\n' },
      { t: 'tx', v: '  ],\n' },
      { t: 'pr', v: '  "approval_required"' }, { t: 'tx', v: ': ' }, { t: 'bl', v: 'true' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "approval_timeout_sec"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '300' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "approved_agents"' }, { t: 'tx', v: ': [' }, { t: 'str', v: '"auto-approved-pipeline-01"' }, { t: 'tx', v: ']\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'tb-v1',
    name: 'Token-Budget',
    version: 'v1',
    type: 'rate-limit',
    mode: 'Enforce',
    status: 'Active',
    scope: 'Suspicious Sessions',
    owner: 'ml-platform',
    createdBy: 'ml-platform@orbyx.ai',
    created: 'Mar 20, 2026',
    updated: '6d ago',
    updatedFull: 'Apr 3, 2026 · 09:55 UTC',
    description: 'Caps maximum token budget per session for any session flagged with a risk score above 0.7. Prevents runaway cost and limits blast radius of compromised sessions.',
    affectedAssets: 6,
    relatedAlerts: 0,
    linkedSimulations: 1,
    agents: ['CustomerSupport-GPT', 'DataPipeline-Orchestrator', 'ThreatHunter-AI'],
    tools: [],
    dataSources: [],
    environments: ['Production'],
    exceptions: [],
    impact: { blocked: 1, flagged: 3, unchanged: 116, total: 120 },
    history: [
      { version: 'v1', by: 'ml-platform@orbyx.ai', when: 'Apr 3, 2026 · 09:55', change: 'Risk score threshold lowered from 0.85 to 0.70.' },
      { version: 'v1', by: 'admin@orbyx.ai',        when: 'Mar 20, 2026 · 13:00', change: 'Initial token budget policy.' },
    ],
    logic: [
      { t: 'cm', v: '// Token-Budget v1 — Per-session token cap\n\n' },
      { t: 'tx', v: '{\n' },
      { t: 'pr', v: '  "policy"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"token-budget-v1"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "trigger_condition"' }, { t: 'tx', v: ': {\n' },
      { t: 'pr', v: '    "risk_score_gt"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '0.70\n' },
      { t: 'tx', v: '  },\n' },
      { t: 'pr', v: '  "limits"' }, { t: 'tx', v: ': {\n' },
      { t: 'pr', v: '    "max_input_tokens"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '4096' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '    "max_output_tokens"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '1024' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '    "max_total_session_tokens"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '16000\n' },
      { t: 'tx', v: '  },\n' },
      { t: 'pr', v: '  "on_exceed"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"terminate_session"' }, { t: 'tx', v: '\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'of-v1',
    name: 'Output-Filter',
    version: 'v1',
    type: 'output-validation',
    mode: 'Monitor',
    status: 'Active',
    scope: 'All Models',
    owner: 'ml-platform',
    createdBy: 'ml-platform@orbyx.ai',
    created: 'Feb 25, 2026',
    updated: '1w ago',
    updatedFull: 'Apr 2, 2026 · 08:30 UTC',
    description: 'Scans all model outputs for harmful content, credential leakage, and PII before delivery to end users or downstream agents. Currently monitoring — enforcement pending review.',
    affectedAssets: 6,
    relatedAlerts: 1,
    linkedSimulations: 2,
    agents: [],
    tools: [],
    dataSources: [],
    environments: ['Production', 'Staging'],
    exceptions: [],
    impact: { blocked: 0, flagged: 14, unchanged: 106, total: 120 },
    history: [
      { version: 'v1', by: 'ml-platform@orbyx.ai', when: 'Apr 2, 2026 · 08:30', change: 'Added credential pattern detection (API keys, tokens).' },
      { version: 'v1', by: 'admin@orbyx.ai',        when: 'Feb 25, 2026 · 12:00', change: 'Initial output validation policy.' },
    ],
    logic: [
      { t: 'cm', v: '// Output-Filter v1 — Post-generation scan\n\n' },
      { t: 'tx', v: '{\n' },
      { t: 'pr', v: '  "policy"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"output-filter-v1"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "checks"' }, { t: 'tx', v: ': [\n' },
      { t: 'str', v: '    "pii_detection"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "credential_leak"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "harmful_content"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "toxic_language"\n' },
      { t: 'tx', v: '  ],\n' },
      { t: 'pr', v: '  "harmful_content_threshold"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '0.80' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "credential_patterns"' }, { t: 'tx', v: ': [\n' },
      { t: 'str', v: '    "sk-[a-zA-Z0-9]{48}"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "ghp_[a-zA-Z0-9]{36}"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "AKIA[0-9A-Z]{16}"\n' },
      { t: 'tx', v: '  ],\n' },
      { t: 'pr', v: '  "on_detect"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"log_and_redact"\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'ec-v2',
    name: 'Egress-Control',
    version: 'v2',
    type: 'tool-access',
    mode: 'Enforce',
    status: 'Active',
    scope: 'External Connectors',
    owner: 'security-ops',
    createdBy: 'sec-eng@orbyx.ai',
    created: 'Mar 1, 2026',
    updated: '4d ago',
    updatedFull: 'Apr 5, 2026 · 17:10 UTC',
    description: 'Maintains an allowlist of approved external domains for all outbound HTTP tool calls. Blocks navigation to unapproved domains and follows redirect chains before permitting requests.',
    affectedAssets: 3,
    relatedAlerts: 1,
    linkedSimulations: 1,
    agents: [],
    tools: ['BrowserScraper', 'HTTP-Client', 'Slack-Notifier'],
    dataSources: [],
    environments: ['Production'],
    exceptions: [],
    impact: { blocked: 3, flagged: 5, unchanged: 112, total: 120 },
    history: [
      { version: 'v2', by: 'sec-eng@orbyx.ai',  when: 'Apr 5, 2026 · 17:10', change: 'Added redirect chain validation. Max 2 hops before re-evaluation.' },
      { version: 'v1', by: 'admin@orbyx.ai',     when: 'Mar 1, 2026 · 10:00', change: 'Initial egress control with domain allowlist.' },
    ],
    logic: [
      { t: 'cm', v: '// Egress-Control v2 — Domain allowlist + redirect chain\n\n' },
      { t: 'tx', v: '{\n' },
      { t: 'pr', v: '  "policy"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"egress-control-v2"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "allowed_domains"' }, { t: 'tx', v: ': [\n' },
      { t: 'str', v: '    "*.anthropic.com"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "api.openai.com"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "hooks.slack.com"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "github.com"' }, { t: 'tx', v: ',\n' },
      { t: 'str', v: '    "*.internal.orbyx.ai"\n' },
      { t: 'tx', v: '  ],\n' },
      { t: 'pr', v: '  "max_redirect_hops"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '2' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "validate_redirects"' }, { t: 'tx', v: ': ' }, { t: 'bl', v: 'true' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "on_violation"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"block_and_alert"\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'rl-v1',
    name: 'RAG-Retrieval-Limit',
    version: 'v1',
    type: 'data-access',
    mode: 'Monitor',
    status: 'Active',
    scope: 'Vector Stores',
    owner: 'data-platform',
    createdBy: 'data-platform@orbyx.ai',
    created: 'Mar 15, 2026',
    updated: '1w ago',
    updatedFull: 'Apr 2, 2026 · 14:00 UTC',
    description: 'Limits the number of records returned per RAG query to prevent bulk data extraction. Triggers alerts when retrieval volume significantly exceeds per-session baseline.',
    affectedAssets: 4,
    relatedAlerts: 1,
    linkedSimulations: 1,
    agents: ['CustomerSupport-GPT', 'HRIntake-Bot'],
    tools: [],
    dataSources: ['Customer-Records-DB', 'HR-Knowledge-Base'],
    environments: ['Production'],
    exceptions: [],
    impact: { blocked: 0, flagged: 4, unchanged: 116, total: 120 },
    history: [
      { version: 'v1', by: 'data-platform@orbyx.ai', when: 'Apr 2, 2026 · 14:00', change: 'Baseline updated from 12 to 20 records/session.' },
      { version: 'v1', by: 'admin@orbyx.ai',          when: 'Mar 15, 2026 · 09:30', change: 'Initial retrieval limit policy.' },
    ],
    logic: [
      { t: 'cm', v: '// RAG-Retrieval-Limit v1 — Bulk retrieval detection\n\n' },
      { t: 'tx', v: '{\n' },
      { t: 'pr', v: '  "policy"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"rag-retrieval-limit-v1"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "max_records_per_query"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '50' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "baseline_records_per_session"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '20' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "anomaly_multiplier"' }, { t: 'tx', v: ': ' }, { t: 'num', v: '5.0' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "on_exceed_limit"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"truncate_and_flag"' }, { t: 'tx', v: ',\n' },
      { t: 'pr', v: '  "on_anomaly_detected"' }, { t: 'tx', v: ': ' }, { t: 'str', v: '"alert_and_log"\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
  {
    id: 'jd-v1',
    name: 'Jailbreak-Detect',
    version: 'v1',
    type: 'prompt-safety',
    mode: 'Enforce',
    status: 'Active',
    scope: 'All Agents',
    owner: 'security-ops',
    createdBy: 'sec-eng@orbyx.ai',
    created: 'Feb 10, 2026',
    updated: '3w ago',
    updatedFull: 'Mar 19, 2026 · 16:00 UTC',
    description: 'Maintains a continuously updated library of known jailbreak signatures, DAN variants, roleplay override patterns, and multi-hop obfuscation techniques.',
    affectedAssets: 12,
    relatedAlerts: 3,
    linkedSimulations: 4,
    agents: ['CustomerSupport-GPT', 'ThreatHunter-AI', 'CodeReview-Assistant', 'DataPipeline-Orchestrator'],
    tools: [],
    dataSources: [],
    environments: ['Production', 'Staging'],
    exceptions: [],
    impact: { blocked: 6, flagged: 9, unchanged: 105, total: 120 },
    history: [
      { version: 'v1.4', by: 'sec-eng@orbyx.ai',  when: 'Mar 19, 2026 · 16:00', change: 'Signature library updated: +14 new DAN variants, +7 roleplay patterns.' },
      { version: 'v1.3', by: 'sec-eng@orbyx.ai',  when: 'Mar 5, 2026 · 10:30',  change: 'Added multi-hop obfuscation detection (Base64 chains, Unicode escaping).' },
      { version: 'v1.0', by: 'admin@orbyx.ai',     when: 'Feb 10, 2026 · 11:00', change: 'Initial jailbreak detection policy.' },
    ],
    logic: [
      { t: 'kw', v: 'package' }, { t: 'tx', v: ' ai.security.jailbreak_detect\n\n' },
      { t: 'kw', v: 'import' }, { t: 'tx', v: ' future.keywords.if\n' },
      { t: 'kw', v: 'import' }, { t: 'tx', v: ' data.signatures.jailbreak as jb_sigs\n\n' },
      { t: 'kw', v: 'default' }, { t: 'tx', v: ' blocked := ' }, { t: 'bl', v: 'false\n\n' },
      { t: 'fn', v: 'blocked' }, { t: 'tx', v: ' ' }, { t: 'kw', v: 'if' }, { t: 'tx', v: ' {\n' },
      { t: 'tx', v: '    some sig ' }, { t: 'kw', v: 'in' }, { t: 'tx', v: ' jb_sigs\n' },
      { t: 'fn', v: '    regex.match' }, { t: 'tx', v: '(sig.pattern, ' }, { t: 'fn', v: 'lower' }, { t: 'tx', v: '(input.prompt))\n' },
      { t: 'tx', v: '    sig.confidence >= input.threshold\n' },
      { t: 'tx', v: '}\n\n' },
      { t: 'fn', v: 'blocked' }, { t: 'tx', v: ' ' }, { t: 'kw', v: 'if' }, { t: 'tx', v: ' {\n' },
      { t: 'cm', v: '    # Base64 decode and re-check\n' },
      { t: 'fn', v: '    decoded' }, { t: 'tx', v: ' := ' }, { t: 'fn', v: 'base64.decode' }, { t: 'tx', v: '(input.prompt)\n' },
      { t: 'fn', v: '    blocked' }, { t: 'tx', v: ' with input.prompt as decoded\n' },
      { t: 'tx', v: '}\n' },
    ],
  },
]

// ── Helpers ────────────────────────────────────────────────────────────────────

function TypeBadge({ type, size = 'sm' }) {
  const cfg = TYPE_CFG[type] ?? TYPE_CFG['prompt-safety']
  const Icon = cfg.icon
  return (
    <span className={cn(
      'inline-flex items-center rounded-md border font-semibold tracking-wide whitespace-nowrap',
      cfg.color, cfg.bg, cfg.border,
      size === 'xs' ? 'gap-1 px-1.5 py-0.5 text-[9px]' : 'gap-1.5 px-2 py-0.5 text-[11px]',
    )}>
      <Icon size={size === 'xs' ? 9 : 11} strokeWidth={2} />
      {cfg.label}
    </span>
  )
}

function ModeBadge({ mode, size = 'sm' }) {
  const cfg = MODE_CFG[mode] ?? MODE_CFG.Monitor
  const dotSz = size === 'xs' ? 'w-1 h-1' : 'w-1.5 h-1.5'
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 rounded-md border font-semibold tracking-wide whitespace-nowrap',
      size === 'xs' ? 'px-1.5 py-0.5 text-[9px]' : 'px-2 py-0.5 text-[11px]',
      mode === 'Enforce'  && 'bg-emerald-50 text-emerald-700 border-emerald-200',
      mode === 'Monitor'  && 'bg-yellow-50  text-yellow-700  border-yellow-200',
      mode === 'Disabled' && 'bg-gray-100   text-gray-500    border-gray-200',
    )}>
      <span className={cn('rounded-full shrink-0', dotSz, cfg.dot)} />
      {mode}
    </span>
  )
}

// Syntax-token renderer
const TOKEN_CLS = {
  kw:  'text-violet-400 font-semibold',
  fn:  'text-sky-300',
  str: 'text-amber-300',
  num: 'text-blue-300',
  bl:  'text-orange-400 font-semibold',
  pr:  'text-sky-200',
  cm:  'text-gray-500 italic',
  tx:  'text-gray-300',
}

function CodeBlock({ tokens }) {
  const lines = []
  let cur = []
  tokens.forEach(tok => {
    const parts = tok.v.split('\n')
    parts.forEach((part, i) => {
      if (part) cur.push({ t: tok.t, v: part })
      if (i < parts.length - 1) { lines.push(cur); cur = [] }
    })
  })
  if (cur.length) lines.push(cur)

  return (
    <div className="flex text-[12px] font-mono leading-[1.75] select-text">
      {/* Gutter */}
      <div className="shrink-0 select-none w-10 text-right pr-3 text-gray-600 border-r border-gray-700/50 bg-gray-900/40">
        {lines.map((_, i) => <div key={i}>{i + 1}</div>)}
      </div>
      {/* Code */}
      <div className="pl-5 flex-1 overflow-x-auto">
        {lines.map((lineTokens, i) => (
          <div key={i} className="hover:bg-white/[0.03] pr-4">
            {lineTokens.length === 0
              ? <span className="text-transparent">·</span>
              : lineTokens.map((tok, j) => (
                  <span key={j} className={TOKEN_CLS[tok.t] ?? TOKEN_CLS.tx}>{tok.v}</span>
                ))
            }
          </div>
        ))}
      </div>
    </div>
  )
}

// ── KPI strip ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, accentClass }) {
  return (
    <div className={cn(
      'bg-white rounded-xl border border-gray-200 border-l-[3px] px-4 py-3 flex items-center gap-3',
      accentClass,
    )}>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.08em] leading-none mb-1.5">{label}</p>
        <p className="text-[22px] font-bold text-gray-900 leading-none tabular-nums">{value}</p>
        {sub && <p className="text-[10px] text-gray-400 mt-1 leading-none">{sub}</p>}
      </div>
    </div>
  )
}

// ── Policy row ─────────────────────────────────────────────────────────────────

function PolicyRow({ policy, selected, onClick }) {
  const typeCfg = TYPE_CFG[policy.type] ?? TYPE_CFG['prompt-safety']
  const TypeIcon = typeCfg.icon
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full text-left px-3 py-2.5 border-l-[3px] transition-colors duration-100',
        selected
          ? 'bg-blue-50/60 border-l-blue-500'
          : 'bg-white border-l-transparent hover:bg-gray-50 hover:border-l-gray-200',
      )}
    >
      <div className="flex items-center gap-2.5">
        {/* Type icon — smaller, tighter */}
        <div className={cn(
          'w-7 h-7 rounded-lg flex items-center justify-center shrink-0 border',
          typeCfg.bg, typeCfg.border,
        )}>
          <TypeIcon size={12} className={typeCfg.color} strokeWidth={2} />
        </div>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          {/* Type label row */}
          <div className="flex items-center gap-1.5 mb-[3px]">
            <span className={cn('text-[9.5px] font-bold uppercase tracking-[0.07em] leading-none', typeCfg.color)}>
              {typeCfg.label}
            </span>
            {policy.relatedAlerts > 0 && (
              <span className="shrink-0 inline-flex items-center gap-0.5 text-[9px] font-bold bg-red-50 text-red-600 border border-red-200 px-1.5 py-px rounded-full tabular-nums leading-none">
                {policy.relatedAlerts} alert{policy.relatedAlerts > 1 ? 's' : ''}
              </span>
            )}
          </div>
          {/* Name + version */}
          <div className="flex items-baseline gap-1.5 mb-[3px]">
            <span className={cn(
              'text-[13px] font-semibold leading-none',
              selected ? 'text-blue-700' : 'text-gray-900',
            )}>
              {policy.name}
            </span>
            <span className="text-[11px] text-gray-400 font-normal leading-none shrink-0">{policy.version}</span>
          </div>
          {/* Scope · owner · updated — all on one line */}
          <div className="flex items-center gap-1 text-[10px] text-gray-400 leading-none">
            <span className="truncate max-w-[90px]">{policy.scope}</span>
            <span className="shrink-0 text-gray-200">·</span>
            <span className="shrink-0">{policy.owner}</span>
            <span className="shrink-0 text-gray-200">·</span>
            <span className="shrink-0 tabular-nums">{policy.updated}</span>
          </div>
        </div>

        {/* Mode badge — xs, right-aligned */}
        <div className="shrink-0">
          <ModeBadge mode={policy.mode} size="xs" />
        </div>
      </div>
    </button>
  )
}

// ── Impact bar ─────────────────────────────────────────────────────────────────

function ImpactBar({ impact }) {
  const { blocked, flagged, unchanged, total } = impact
  const pBlocked = (blocked  / total) * 100
  const pFlagged = (flagged  / total) * 100
  const pPass    = (unchanged / total) * 100
  return (
    <div className="space-y-2.5">
      {/* Segmented bar */}
      <div className="flex rounded-full overflow-hidden h-2 bg-gray-100">
        {blocked  > 0 && <div className="bg-red-500    transition-all" style={{ width: `${pBlocked}%` }} />}
        {flagged  > 0 && <div className="bg-amber-400  transition-all" style={{ width: `${pFlagged}%` }} />}
        {unchanged > 0 && <div className="bg-emerald-400 transition-all" style={{ width: `${pPass}%`    }} />}
      </div>
      {/* Legend */}
      <div className="flex items-center gap-5 text-[11px]">
        <span className="flex items-center gap-1.5 font-medium text-red-600">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />{blocked} blocked
        </span>
        <span className="flex items-center gap-1.5 font-medium text-amber-600">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />{flagged} flagged
        </span>
        <span className="flex items-center gap-1.5 font-medium text-emerald-600">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />{unchanged} unchanged
        </span>
        <span className="ml-auto text-gray-400 tabular-nums">{total} sessions evaluated</span>
      </div>
    </div>
  )
}

// ── Scope chip ─────────────────────────────────────────────────────────────────

function Chip({ label, icon: Icon, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1.5 bg-white text-gray-700 border border-gray-200 rounded-full px-2.5 py-0.5 text-[11px] font-medium hover:border-gray-300 transition-colors">
      {Icon && <Icon size={10} strokeWidth={2} className="text-gray-400 shrink-0" />}
      {label}
      {onRemove && (
        <button onClick={onRemove} className="ml-0.5 text-gray-400 hover:text-gray-700 transition-colors">
          <X size={10} strokeWidth={2} />
        </button>
      )}
    </span>
  )
}

// ── Section label ──────────────────────────────────────────────────────────────

function SectionLabel({ children }) {
  return <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400 leading-none">{children}</p>
}

// ── Divider ────────────────────────────────────────────────────────────────────

function Divider() {
  return <div className="border-t border-gray-100" />
}

// ── Tab config ─────────────────────────────────────────────────────────────────

const TABS_CFG = [
  { key: 'Overview', icon: Eye         },
  { key: 'Logic',    icon: FileCode2   },
  { key: 'Scope',    icon: SlidersHorizontal },
  { key: 'History',  icon: History     },
]

// ── Detail panel ───────────────────────────────────────────────────────────────

function DetailPanel({ policy }) {
  const [tab, setTab] = useState('Overview')

  if (!policy) return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center mb-3">
        <ScrollText size={18} className="text-gray-400" />
      </div>
      <p className="text-[13px] font-medium text-gray-500">No policy selected</p>
      <p className="text-[11px] text-gray-400 mt-1">Select a policy to inspect or edit</p>
    </div>
  )

  const typeCfg = TYPE_CFG[policy.type] ?? TYPE_CFG['prompt-safety']
  const TypeIcon = typeCfg.icon
  const isRego = policy.type === 'prompt-safety' || policy.type === 'tenant-isolation'

  return (
    <div className="flex flex-col h-full">

      {/* ── TYPE ACCENT STRIP ── */}
      <div className={cn('h-[3px] shrink-0 rounded-t-xl', typeCfg.bg.replace('bg-', 'bg-').replace('-50', '-400').replace('50', '400'))}
        style={{ background: typeCfg.color.replace('text-', '').includes('violet') ? '#7c3aed'
          : typeCfg.color.includes('blue')    ? '#2563eb'
          : typeCfg.color.includes('cyan')    ? '#0891b2'
          : typeCfg.color.includes('emerald') ? '#059669'
          : typeCfg.color.includes('pink')    ? '#db2777'
          : typeCfg.color.includes('indigo')  ? '#4338ca'
          : typeCfg.color.includes('amber')   ? '#d97706'
          : '#6b7280'
        }}
      />

      {/* ── IDENTITY ROW ── */}
      <div className="px-5 py-3.5 border-b border-gray-100 shrink-0">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className={cn(
              'w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border',
              typeCfg.bg, typeCfg.border,
            )}>
              <TypeIcon size={16} className={typeCfg.color} strokeWidth={1.75} />
            </div>
            <div className="min-w-0">
              <div className="flex items-baseline gap-2 mb-1">
                <h2 className="text-[15px] font-bold text-gray-900 leading-none">{policy.name}</h2>
                <span className="text-[11px] text-gray-400 font-normal leading-none">{policy.version}</span>
              </div>
              <div className="flex items-center gap-2">
                <TypeBadge type={policy.type} size="xs" />
                <span className="text-[10px] text-gray-400 leading-none truncate">{policy.scope}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <ModeBadge mode={policy.mode} />
            <Badge variant={policy.status === 'Active' ? 'success' : 'neutral'}>{policy.status}</Badge>
          </div>
        </div>
      </div>

      {/* ── TOOLBAR ROW ── */}
      <div className="px-4 py-1.5 bg-gray-50/70 border-b border-gray-100 flex items-center gap-1 shrink-0">
        {/* Group A — edit actions */}
        <div className="flex items-center gap-1">
          <Button variant="default" size="sm" className="gap-1.5 h-7 text-[11.5px] px-3">
            <Pencil size={10.5} strokeWidth={2} /> Edit
          </Button>
          <Button variant="outline" size="sm" className="gap-1.5 h-7 text-[11.5px] px-3">
            <Save size={10.5} strokeWidth={2} /> Draft
          </Button>
        </div>

        <div className="w-px h-3.5 bg-gray-200 mx-1.5 shrink-0" />

        {/* Group B — enforcement actions */}
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm" className="gap-1.5 h-7 text-[11.5px] px-3">
            <TestTube2 size={10.5} strokeWidth={2} /> Simulate
          </Button>
          {policy.mode === 'Monitor' && (
            <Button variant="outline" size="sm" className="gap-1.5 h-7 text-[11.5px] px-3 text-emerald-600 border-emerald-200 hover:bg-emerald-50">
              <ShieldCheck size={10.5} strokeWidth={2} /> Enforce
            </Button>
          )}
          {policy.mode === 'Enforce' && (
            <Button variant="outline" size="sm" className="gap-1.5 h-7 text-[11.5px] px-3 text-amber-600 border-amber-200 hover:bg-amber-50">
              <Eye size={10.5} strokeWidth={2} /> Monitor
            </Button>
          )}
        </div>

        <div className="flex-1" />

        {/* Group C — utility (icon-only) */}
        <div className="flex items-center gap-0.5">
          <button title="Duplicate" className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
            <Copy size={13} strokeWidth={1.75} />
          </button>
          <button title="Archive" className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
            <Archive size={13} strokeWidth={1.75} />
          </button>
          <button title="Download" className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors">
            <Download size={13} strokeWidth={1.75} />
          </button>
        </div>
      </div>

      {/* ── TAB BAR ── */}
      <div className="flex items-center px-4 border-b border-gray-100 shrink-0 gap-0.5">
        {TABS_CFG.map(({ key, icon: TabIcon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-2.5 text-[12px] border-b-2 transition-colors duration-100 whitespace-nowrap',
              tab === key
                ? 'border-blue-600 text-blue-600 font-semibold'
                : 'border-transparent text-gray-500 hover:text-gray-700 font-medium',
            )}
          >
            <TabIcon size={12} strokeWidth={tab === key ? 2.5 : 1.75} />
            {key}
          </button>
        ))}
      </div>

      {/* ── TAB CONTENT ── */}
      <div className="flex-1 overflow-y-auto">

        {/* ── OVERVIEW ── */}
        {tab === 'Overview' && (
          <div className="divide-y divide-gray-100">

            {/* Description */}
            <div className="px-5 py-4">
              <SectionLabel>Description</SectionLabel>
              <p className={cn(
                'text-[12.5px] text-gray-700 leading-relaxed mt-2.5 pl-3 border-l-2',
                typeCfg.border,
              )}>{policy.description}</p>
            </div>

            {/* Metadata grid */}
            <div className="px-5 py-4">
              <SectionLabel>Details</SectionLabel>
              <div className="mt-3 divide-y divide-gray-50">
                {[
                  { label: 'Owner',        val: policy.owner      },
                  { label: 'Created by',   val: policy.createdBy  },
                  { label: 'Created',      val: policy.created    },
                  { label: 'Last updated', val: policy.updatedFull},
                ].map(({ label, val }) => (
                  <div key={label} className="flex items-baseline justify-between py-1.5 gap-4">
                    <span className="text-[10px] font-bold uppercase tracking-[0.07em] text-gray-400 shrink-0">{label}</span>
                    <span className="text-[12px] text-gray-800 font-medium text-right truncate">{val}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Stats */}
            <div className="px-5 py-4">
              <SectionLabel>Coverage</SectionLabel>
              <div className="grid grid-cols-3 gap-2 mt-3">
                {[
                  { val: policy.affectedAssets,   label: 'Assets',      accent: 'border-l-blue-400',    alert: false },
                  { val: policy.relatedAlerts,     label: 'Alerts',      accent: 'border-l-red-400',     alert: policy.relatedAlerts > 0 },
                  { val: policy.linkedSimulations, label: 'Simulations', accent: 'border-l-violet-400',  alert: false },
                ].map(({ val, label, accent, alert }) => (
                  <div key={label} className={cn('bg-gray-50 rounded-lg border border-gray-100 border-l-[3px] py-2.5 px-3', accent)}>
                    <p className={cn('text-[20px] font-bold tabular-nums leading-none mb-1', alert ? 'text-red-600' : 'text-gray-900')}>{val}</p>
                    <p className="text-[10px] text-gray-400 leading-none">{label}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Applies to */}
            <div className="px-5 py-4">
              <SectionLabel>Applies To</SectionLabel>
              <div className="mt-3 space-y-2.5">
                {[
                  { label: 'Agents',       icon: Bot,      items: policy.agents       },
                  { label: 'Tools',        icon: Wrench,   items: policy.tools        },
                  { label: 'Data Sources', icon: Database, items: policy.dataSources  },
                  { label: 'Environments', icon: Globe,    items: policy.environments },
                ].filter(r => r.items.length > 0).map(({ label, icon: Icon, items }) => (
                  <div key={label} className="flex items-start gap-3">
                    <div className="w-5 h-5 rounded bg-gray-100 flex items-center justify-center shrink-0 mt-0.5">
                      <Icon size={11} className="text-gray-400" strokeWidth={1.75} />
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-400 font-medium mb-1.5">{label}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {items.map(item => <Chip key={item} label={item} />)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Last simulation */}
            <div className="px-5 py-4">
              <div className="flex items-center justify-between mb-3">
                <SectionLabel>Last Simulation Impact</SectionLabel>
                <button className="text-[11px] text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1 transition-colors">
                  <Sparkles size={10} strokeWidth={2} /> Run again
                </button>
              </div>
              <div className="bg-gray-50 rounded-xl border border-gray-100 px-4 py-3">
                <ImpactBar impact={policy.impact} />
              </div>
            </div>

          </div>
        )}

        {/* ── LOGIC ── */}
        {tab === 'Logic' && (
          <div className="flex flex-col h-full">

            {/* Dark toolbar — unified with editor */}
            <div className="flex items-center gap-2 px-4 py-2 bg-gray-900 border-b border-gray-700/80 shrink-0">
              {/* File info */}
              <div className="flex items-center gap-2 min-w-0">
                <FileCode2 size={13} className="text-gray-500 shrink-0" strokeWidth={1.75} />
                <span className="text-[11px] text-gray-400 font-mono truncate">
                  {policy.name.toLowerCase().replace(/-/g, '_')}.{isRego ? 'rego' : 'json'}
                </span>
                <span className="text-[10px] text-gray-600 shrink-0">{isRego ? 'Rego · OPA 0.59' : 'JSON · Schema v2'}</span>
              </div>
              <div className="flex-1" />
              {/* Toolbar actions — dark style */}
              <button className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded bg-gray-800 border border-gray-700 text-[11px] text-gray-300 hover:bg-gray-700 hover:text-white transition-colors font-medium">
                <Play size={10} strokeWidth={2.5} /> Validate
              </button>
              <button className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded bg-gray-800 border border-gray-700 text-[11px] text-gray-300 hover:bg-gray-700 hover:text-white transition-colors font-medium">
                <TestTube2 size={10} strokeWidth={2} /> Test
              </button>
              <button className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded bg-gray-800 border border-gray-700 text-[11px] text-gray-300 hover:bg-gray-700 hover:text-white transition-colors font-medium">
                <Sparkles size={10} strokeWidth={2} /> Simulate
              </button>
              <button className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded bg-blue-600 border border-blue-500 text-[11px] text-white hover:bg-blue-500 transition-colors font-semibold ml-1">
                <Save size={10} strokeWidth={2} /> Save Draft
              </button>
            </div>

            {/* Editor area */}
            <div className="flex-1 overflow-y-auto bg-gray-950 py-4">
              <CodeBlock tokens={policy.logic} />
            </div>

            {/* Status bar — VS Code style */}
            <div className="flex items-center gap-0 px-0 py-0 bg-[#1a1a2e] border-t border-gray-800/80 shrink-0">
              {/* Left cluster */}
              <div className="flex items-center h-[22px]">
                <span className="flex items-center gap-1.5 px-3 h-full text-[10px] text-emerald-400 font-medium border-r border-gray-800">
                  <CheckCircle2 size={9} strokeWidth={2.5} /> Validated
                </span>
                <span className="px-3 h-full flex items-center text-[10px] text-gray-600 border-r border-gray-800">0 errors</span>
                <span className="px-3 h-full flex items-center text-[10px] text-gray-600 border-r border-gray-800">0 warnings</span>
              </div>
              <div className="flex-1" />
              {/* Right cluster */}
              <div className="flex items-center h-[22px]">
                <span className="px-3 h-full flex items-center text-[10px] text-gray-600 border-l border-gray-800 tabular-nums">Ln 1, Col 1</span>
                <span className="px-3 h-full flex items-center text-[10px] text-gray-600 border-l border-gray-800">UTF-8</span>
                <span className="px-3 h-full flex items-center text-[10px] text-gray-600 border-l border-gray-800">LF</span>
                <span className="px-3 h-full flex items-center text-[10px] text-gray-500 border-l border-gray-800">{isRego ? 'Rego' : 'JSON'}</span>
                <span className="px-3 h-full flex items-center text-[10px] text-gray-600 border-l border-gray-800 tabular-nums">{policy.version}</span>
                <span className="px-3 h-full flex items-center text-[10px] text-gray-600 border-l border-gray-800 tabular-nums">saved {policy.updated}</span>
              </div>
            </div>

          </div>
        )}

        {/* ── SCOPE ── */}
        {tab === 'Scope' && (
          <div className="divide-y divide-gray-100">
            {[
              { label: 'Agents',       icon: Bot,      key: 'agents',       hint: 'policy applies to all agents' },
              { label: 'Tools',        icon: Wrench,   key: 'tools',        hint: 'policy applies to all tools' },
              { label: 'Data Sources', icon: Database, key: 'dataSources',  hint: 'policy applies to all data sources' },
              { label: 'Environments', icon: Globe,    key: 'environments', hint: 'policy applies to all environments' },
            ].map(({ label, icon: Icon, key, hint }) => {
              const items = policy[key] ?? []
              return (
                <div key={key} className="px-5 py-3.5">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <div className="w-5 h-5 rounded bg-gray-100 flex items-center justify-center shrink-0">
                        <Icon size={11} className="text-gray-500" strokeWidth={1.75} />
                      </div>
                      <span className="text-[11px] font-semibold text-gray-600">{label}</span>
                      {items.length > 0 && (
                        <span className="text-[10px] text-gray-400 tabular-nums bg-gray-100 px-1.5 py-px rounded-full">{items.length}</span>
                      )}
                    </div>
                    <button className="text-[10.5px] text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1 transition-colors">
                      <Plus size={10} strokeWidth={2.5} /> Add
                    </button>
                  </div>
                  <div className={cn(
                    'flex flex-wrap gap-1.5 rounded-lg border px-3 py-2 min-h-[38px] items-center',
                    items.length === 0 ? 'bg-gray-50/70 border-dashed border-gray-200' : 'bg-white border-gray-100',
                  )}>
                    {items.length === 0
                      ? <p className="text-[10.5px] text-gray-400 italic">None assigned — {hint}</p>
                      : items.map(item => <Chip key={item} label={item} icon={Icon} onRemove={() => {}} />)
                    }
                  </div>
                </div>
              )
            })}

            {/* Exceptions */}
            <div className="px-5 py-3.5">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className="w-5 h-5 rounded bg-amber-50 flex items-center justify-center shrink-0 border border-amber-100">
                    <TriangleAlert size={11} className="text-amber-500" strokeWidth={1.75} />
                  </div>
                  <span className="text-[11px] font-semibold text-gray-600">Exceptions</span>
                  {policy.exceptions.length > 0 && (
                    <span className="text-[10px] text-amber-600 font-semibold tabular-nums bg-amber-50 border border-amber-200 px-1.5 py-px rounded-full">{policy.exceptions.length}</span>
                  )}
                </div>
                <button className="text-[10.5px] text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1 transition-colors">
                  <Plus size={10} strokeWidth={2.5} /> Add exception
                </button>
              </div>
              <div className={cn(
                'flex flex-wrap gap-1.5 rounded-lg border px-3 py-2 min-h-[38px] items-center',
                policy.exceptions.length === 0
                  ? 'bg-gray-50/70 border-dashed border-gray-200'
                  : 'bg-amber-50/40 border-amber-200',
              )}>
                {policy.exceptions.length === 0
                  ? <p className="text-[10.5px] text-gray-400 italic">No exceptions configured</p>
                  : policy.exceptions.map(ex => (
                      <span key={ex} className="inline-flex items-center gap-1.5 bg-amber-50 text-amber-700 border border-amber-200 rounded-full px-2.5 py-0.5 text-[11px] font-medium">
                        <TriangleAlert size={9} strokeWidth={2} className="shrink-0" />
                        {ex}
                        <button className="ml-0.5 text-amber-400 hover:text-amber-700 transition-colors">
                          <X size={10} strokeWidth={2} />
                        </button>
                      </span>
                    ))
                }
              </div>
            </div>
          </div>
        )}

        {/* ── HISTORY ── */}
        {tab === 'History' && (
          <div className="px-5 py-4">
            <div className="flex items-center justify-between mb-4">
              <SectionLabel>Change History</SectionLabel>
              <button className="text-[11px] text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1 transition-colors">
                <RotateCcw size={10} strokeWidth={2} /> Restore a version
              </button>
            </div>

            <div className="relative">
              {/* Spine */}
              <div className="absolute left-[13px] top-3 bottom-3 w-px bg-gray-200" />
              <div className="space-y-3">
                {policy.history.map((h, i) => (
                  <div key={i} className="relative pl-9">
                    {/* Dot */}
                    <div className={cn(
                      'absolute left-[7px] top-[14px] w-[13px] h-[13px] rounded-full ring-2 ring-white',
                      i === 0 ? 'bg-blue-500' : 'bg-gray-300',
                    )} />

                    <div className={cn(
                      'rounded-lg border overflow-hidden',
                      i === 0 ? 'bg-blue-50/50 border-blue-100' : 'bg-white border-gray-200',
                    )}>
                      {/* Card header */}
                      <div className={cn(
                        'flex items-center justify-between px-3 py-2 border-b',
                        i === 0 ? 'bg-blue-50/80 border-blue-100' : 'bg-gray-50 border-gray-100',
                      )}>
                        <div className="flex items-center gap-2">
                          <span className={cn('text-[12px] font-bold font-mono', i === 0 ? 'text-blue-700' : 'text-gray-700')}>{h.version}</span>
                          {i === 0 && (
                            <span className="text-[8.5px] font-bold bg-blue-500 text-white px-1.5 py-px rounded-full tracking-wide uppercase">
                              current
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-gray-400">
                          <Users size={9} strokeWidth={2} className="shrink-0" />
                          <span>{h.by}</span>
                          <span className="text-gray-300">·</span>
                          <span className="tabular-nums">{h.when}</span>
                        </div>
                      </div>
                      {/* Change description — diff style */}
                      <div className="px-3 py-2">
                        <p className="text-[11.5px] text-gray-600 leading-relaxed font-mono bg-gray-50/80 rounded px-2 py-1.5 border border-gray-100">
                          <span className="text-emerald-600 font-semibold select-none mr-1.5">+</span>{h.change}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

// ── Select control ─────────────────────────────────────────────────────────────

function Sel({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="h-8 rounded-lg border border-gray-200 bg-white pl-2.5 pr-6 text-[12px] text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 cursor-pointer"
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

// ── Policies page ──────────────────────────────────────────────────────────────

export default function Policies() {
  const [selectedId,    setSelectedId]    = useState('pg-v3')
  const [search,        setSearch]        = useState('')
  const [typeFilter,    setTypeFilter]    = useState('All')
  const [modeFilter,    setModeFilter]    = useState('All')
  const [ownerFilter,   setOwnerFilter]   = useState('All')
  const [recentOnly,    setRecentOnly]    = useState(false)
  const [activeTab,     setActiveTab]     = useState('Overview')

  const selectedPolicy = POLICIES.find(p => p.id === selectedId) ?? null

  // Reset tab when policy changes
  const handleSelectPolicy = (id) => {
    setSelectedId(id)
    setActiveTab('Overview')
  }

  const filtered = POLICIES.filter(p => {
    const q = search.toLowerCase()
    if (q && !p.name.toLowerCase().includes(q) && !p.scope.toLowerCase().includes(q) && !p.owner.toLowerCase().includes(q)) return false
    if (typeFilter !== 'All' && p.type !== typeFilter) return false
    if (modeFilter !== 'All' && p.mode !== modeFilter) return false
    if (ownerFilter !== 'All' && p.owner !== ownerFilter) return false
    if (recentOnly && !['2d ago','3d ago','4d ago','5d ago','6d ago'].includes(p.updated)) return false
    return true
  })

  const enforced     = POLICIES.filter(p => p.mode === 'Enforce').length
  const monitored    = POLICIES.filter(p => p.mode === 'Monitor').length
  const exceptions   = POLICIES.reduce((n, p) => n + p.exceptions.length, 0)

  const owners = ['All', ...Array.from(new Set(POLICIES.map(p => p.owner))).sort()]

  return (
    <PageContainer>

      {/* ── Header ── */}
      <PageHeader
        title="Policies & Guardrails"
        subtitle="Define, scope, and enforce AI security rules across agents, tools, and context flows"
        actions={
          <>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Upload size={13} strokeWidth={2} /> Import
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Download size={13} strokeWidth={2} /> Export
            </Button>
            <Button variant="default" size="sm" className="gap-1.5">
              <Plus size={13} strokeWidth={2} /> Create Policy
            </Button>
          </>
        }
      />

      {/* ── KPI strip ── */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="Total Policies"    value={POLICIES.length} sub="Across all scopes"   accentClass="border-l-blue-500"    />
        <KpiCard label="Enforced"          value={enforced}        sub="Active enforcement"  accentClass="border-l-emerald-500"  />
        <KpiCard label="Monitor Only"      value={monitored}       sub="Logging, not blocking" accentClass="border-l-yellow-400" />
        <KpiCard label="Exceptions / Waivers" value={exceptions}  sub="Active exclusions"   accentClass="border-l-orange-500"  />
      </div>

      {/* ── Filter bar ── */}
      <div className="bg-white rounded-xl border border-gray-200 px-3 h-11 flex items-center gap-2.5">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search policies…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-52 h-8 pl-8 pr-3 rounded-lg border border-gray-200 bg-gray-50 text-[12px] text-gray-700 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 focus:bg-white"
          />
        </div>

        <div className="w-px h-4 bg-gray-200 shrink-0" />

        <Sel value={typeFilter} onChange={setTypeFilter} options={[
          { value: 'All',               label: 'All Types'          },
          { value: 'prompt-safety',     label: 'Prompt Safety'      },
          { value: 'tool-access',       label: 'Tool Access'        },
          { value: 'data-access',       label: 'Data Access'        },
          { value: 'output-validation', label: 'Output Validation'  },
          { value: 'privacy',           label: 'Privacy / Redaction'},
          { value: 'tenant-isolation',  label: 'Tenant Isolation'   },
          { value: 'rate-limit',        label: 'Budget / Rate Limits'},
        ]} />

        <Sel value={modeFilter} onChange={setModeFilter} options={[
          { value: 'All',      label: 'All Modes' },
          { value: 'Enforce',  label: 'Enforce'   },
          { value: 'Monitor',  label: 'Monitor'   },
          { value: 'Disabled', label: 'Disabled'  },
        ]} />

        <Sel value={ownerFilter} onChange={setOwnerFilter}
          options={owners.map(o => ({ value: o, label: o === 'All' ? 'All Owners' : o }))}
        />

        <div className="w-px h-4 bg-gray-200 shrink-0" />

        <button
          onClick={() => setRecentOnly(p => !p)}
          className={cn(
            'flex items-center gap-1.5 h-8 px-2.5 rounded-lg border text-[12px] font-medium transition-colors shrink-0',
            recentOnly
              ? 'bg-blue-50 border-blue-200 text-blue-600'
              : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50',
          )}
        >
          <Clock size={11} strokeWidth={2} /> Recently changed
        </button>

        <div className="flex-1" />
        <span className="text-[11px] text-gray-400 tabular-nums">{filtered.length} / {POLICIES.length} policies</span>
      </div>

      {/* ── Main layout ── */}
      <div className="grid grid-cols-12 gap-3" style={{ height: 'calc(100vh - 316px)', minHeight: 520 }}>

        {/* LEFT — policy list (5 cols) */}
        <div className="col-span-5 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
          <div className="h-10 px-3 flex items-center justify-between border-b border-gray-100 shrink-0">
            <div className="flex items-center gap-2">
              <ScrollText size={13} className="text-gray-400" strokeWidth={1.75} />
              <span className="text-[12px] font-semibold text-gray-700">Policy Library</span>
            </div>
            <span className="text-[11px] text-gray-400 tabular-nums">{filtered.length}</span>
          </div>

          {filtered.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center py-12 text-center">
              <Search size={20} className="text-gray-300 mb-2" />
              <p className="text-[13px] text-gray-400">No policies match filters</p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
              {filtered.map(p => (
                <PolicyRow
                  key={p.id}
                  policy={p}
                  selected={p.id === selectedId}
                  onClick={() => handleSelectPolicy(p.id)}
                />
              ))}
            </div>
          )}
        </div>

        {/* RIGHT — detail panel (7 cols) */}
        <div className="col-span-7 bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
          {selectedPolicy ? (
            <DetailPanel key={selectedPolicy.id} policy={selectedPolicy} />
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center">
              <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center mb-3">
                <ScrollText size={18} className="text-gray-400" />
              </div>
              <p className="text-[13px] font-medium text-gray-500">No policy selected</p>
              <p className="text-[11px] text-gray-400 mt-1">Select a policy from the list to inspect or edit</p>
            </div>
          )}
        </div>

      </div>
    </PageContainer>
  )
}
