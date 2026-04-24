import { useState } from 'react'
import {
  Search, ChevronDown, X, Play, Pause, Plus,
  Zap, Clock, CheckCircle2, XCircle, AlertTriangle,
  User, Settings, Copy, Trash2, ToggleLeft, ToggleRight,
  ChevronRight, ArrowRight, Filter, MoreHorizontal,
  Shield, ShieldAlert, Bell, Database, Mail, Webhook,
  GitBranch, List, Activity, Calendar, Timer,
  RefreshCw, Terminal, FlaskConical, Network, Lock,
  Eye, Send, Cloud, Layers, Cpu, Bot,
} from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { Badge }         from '../../components/ui/Badge.jsx'

// ── Design tokens ──────────────────────────────────────────────────────────────

const PB_STATUS_VARIANT = {
  Active:   'success',
  Disabled: 'neutral',
  Error:    'critical',
  Draft:    'medium',
}
const PB_STATUS_DOT = {
  Active:   'bg-emerald-400',
  Disabled: 'bg-gray-300',
  Error:    'bg-red-500',
  Draft:    'bg-yellow-400',
}

const RUN_RESULT_VARIANT = {
  Success:   'success',
  Failed:    'critical',
  Partial:   'medium',
  Skipped:   'neutral',
  Running:   'info',
}
const RUN_RESULT_DOT = {
  Success:   'bg-emerald-400',
  Failed:    'bg-red-500',
  Partial:   'bg-yellow-400',
  Skipped:   'bg-gray-300',
  Running:   'bg-blue-400',
}

const TRIGGER_CFG = {
  'Alert Threshold':  { icon: Bell,       color: 'text-red-500',    bg: 'bg-red-50',      border: 'border-red-100'    },
  'Schedule':         { icon: Calendar,   color: 'text-violet-500', bg: 'bg-violet-50',   border: 'border-violet-100' },
  'Policy Match':     { icon: Shield,     color: 'text-orange-500', bg: 'bg-orange-50',   border: 'border-orange-100' },
  'Manual':           { icon: Play,       color: 'text-blue-500',   bg: 'bg-blue-50',     border: 'border-blue-100'   },
  'Webhook':          { icon: Webhook,    color: 'text-cyan-500',   bg: 'bg-cyan-50',     border: 'border-cyan-100'   },
  'Risk Score':       { icon: Activity,   color: 'text-amber-500',  bg: 'bg-amber-50',    border: 'border-amber-100'  },
}

const ACTION_TYPE_CFG = {
  'Quarantine Session': { icon: Lock,       color: 'text-red-600',    bg: 'bg-red-50'    },
  'Send Alert':         { icon: Bell,       color: 'text-orange-500', bg: 'bg-orange-50' },
  'Notify Slack':       { icon: Send,       color: 'text-blue-600',   bg: 'bg-blue-50'   },
  'Send Email':         { icon: Mail,       color: 'text-violet-600', bg: 'bg-violet-50' },
  'Create Case':        { icon: Layers,     color: 'text-cyan-600',   bg: 'bg-cyan-50'   },
  'Apply Policy':       { icon: Shield,     color: 'text-amber-600',  bg: 'bg-amber-50'  },
  'Escalate':           { icon: ShieldAlert,color: 'text-red-500',    bg: 'bg-red-50'    },
  'Webhook Call':       { icon: Webhook,    color: 'text-teal-600',   bg: 'bg-teal-50'   },
  'Block Tool':         { icon: XCircle,    color: 'text-red-600',    bg: 'bg-red-50'    },
  'Log to SIEM':        { icon: Terminal,   color: 'text-gray-600',   bg: 'bg-gray-50'   },
  'Run Simulation':     { icon: FlaskConical,color:'text-indigo-600', bg: 'bg-indigo-50' },
  'Rotate Key':         { icon: RefreshCw,  color: 'text-emerald-600',bg: 'bg-emerald-50'},
}

const FLOW_NODE_CFG = {
  trigger:   { bar: 'bg-blue-500',    label: 'TRIGGER',    bg: 'bg-blue-50',    border: 'border-blue-200'    },
  condition: { bar: 'bg-amber-500',   label: 'CONDITION',  bg: 'bg-amber-50',   border: 'border-amber-200'   },
  action:    { bar: 'bg-emerald-500', label: 'ACTION',     bg: 'bg-emerald-50', border: 'border-emerald-200' },
  output:    { bar: 'bg-violet-500',  label: 'OUTPUT',     bg: 'bg-violet-50',  border: 'border-violet-200'  },
}

// ── Mock data ──────────────────────────────────────────────────────────────────

const MOCK_PLAYBOOKS = [
  {
    id: 'pb-001',
    name: 'Prompt Injection Auto-Response',
    description: 'Automatically quarantine sessions and create cases when Prompt-Guard score exceeds 0.85. Notifies security ops via Slack and email.',
    status: 'Active',
    trigger: 'Alert Threshold',
    scope: 'Production',
    owner: 'sarah.chen',
    ownerDisplay: 'Sarah Chen',
    lastRun: '2m ago',
    lastRunResult: 'Success',
    runsToday: 4,
    successRate: 98,
    enabled: true,
    tags: ['prompt-injection', 'auto-quarantine'],
    conditions: [
      { label: 'Alert type',      op: 'equals',          value: 'Prompt Injection Detected' },
      { label: 'Policy score',    op: 'greater than',    value: '0.85'                      },
      { label: 'Environment',     op: 'equals',          value: 'Production'                },
    ],
    actions: [
      { step: 1, type: 'Quarantine Session', config: 'Terminate active session immediately'       },
      { step: 2, type: 'Create Case',        config: 'Priority: P1 · Assign to security-ops'     },
      { step: 3, type: 'Notify Slack',       config: '#security-incidents — include session ID'   },
      { step: 4, type: 'Send Email',         config: 'security-ops@company.com + CISO digest'     },
      { step: 5, type: 'Log to SIEM',        config: 'Splunk HEC endpoint — severity=critical'    },
    ],
    integrations: ['Slack', 'SendGrid', 'Splunk'],
    workflow: [
      { nodeType: 'trigger',   icon: Bell,       title: 'Alert Threshold Exceeded',   detail: 'Prompt-Guard score > 0.85 on any production agent'    },
      { nodeType: 'condition', icon: Filter,      title: 'Environment Check',          detail: 'Scope = Production AND alert.severity ≥ High'         },
      { nodeType: 'condition', icon: Activity,    title: 'Confidence Gate',            detail: 'Policy confidence > 0.85 AND session not already quarantined' },
      { nodeType: 'action',    icon: Lock,        title: 'Quarantine Session',         detail: 'Terminate session · block originating user for 24h'   },
      { nodeType: 'action',    icon: Layers,      title: 'Create P1 Case',             detail: 'Auto-assign to security-ops team · set P1/Critical'   },
      { nodeType: 'output',    icon: Send,        title: 'Notify & Log',               detail: 'Slack #security-incidents · Email CISO · Splunk HEC'  },
    ],
    auditHistory: [
      { ts: 'Apr 8 · 14:32 UTC', actor: 'System',       action: 'Playbook triggered — run pb-run-0892'    },
      { ts: 'Apr 7 · 09:15 UTC', actor: 'sarah.chen',   action: 'Threshold updated: 0.80 → 0.85'         },
      { ts: 'Apr 6 · 16:00 UTC', actor: 'System',       action: 'Playbook triggered — run pb-run-0871'    },
      { ts: 'Apr 5 · 11:30 UTC', actor: 'raj.patel',    action: 'Slack channel updated to #security-incidents' },
    ],
  },
  {
    id: 'pb-002',
    name: 'PII Exfiltration Escalation',
    description: 'Escalates to CISO and triggers legal notification workflow when PII-Guard detects records retrieved above threshold. Creates mandatory evidence preservation task.',
    status: 'Active',
    trigger: 'Alert Threshold',
    scope: 'All Environments',
    owner: 'mike.torres',
    ownerDisplay: 'Mike Torres',
    lastRun: '47m ago',
    lastRunResult: 'Success',
    runsToday: 1,
    successRate: 100,
    enabled: true,
    tags: ['pii', 'gdpr', 'escalation'],
    conditions: [
      { label: 'Alert type',   op: 'equals',        value: 'PII Exposure Detected'  },
      { label: 'Record count', op: 'greater than',  value: '50'                     },
    ],
    actions: [
      { step: 1, type: 'Create Case',    config: 'Priority: P1 · Tag: pii, gdpr'           },
      { step: 2, type: 'Escalate',       config: 'Escalate to CISO + Legal team'             },
      { step: 3, type: 'Send Email',     config: 'legal@company.com · privacy@company.com'  },
      { step: 4, type: 'Apply Policy',   config: 'Enforce RAG result-size cap: max 50 rows' },
      { step: 5, type: 'Log to SIEM',    config: 'Splunk HEC — severity=high, tag=pii'      },
    ],
    integrations: ['SendGrid', 'Splunk', 'PagerDuty'],
    workflow: [
      { nodeType: 'trigger',   icon: Bell,       title: 'PII Guard Threshold Exceeded', detail: 'Records retrieved > 50 in single session'             },
      { nodeType: 'condition', icon: Filter,      title: 'PII Field Check',              detail: 'Output contains SSN, account number, or address fields' },
      { nodeType: 'action',    icon: Layers,      title: 'Create & Escalate Case',       detail: 'Create P1 case · Escalate to CISO + Legal'            },
      { nodeType: 'action',    icon: Shield,      title: 'Apply RAG Limit Policy',       detail: 'Cap result-size to 50 records across all RAG queries'  },
      { nodeType: 'output',    icon: Mail,        title: 'Legal & SIEM Notification',    detail: 'Email legal team · Log to Splunk with pii tag'         },
    ],
    auditHistory: [
      { ts: 'Apr 8 · 11:15 UTC', actor: 'System',       action: 'Playbook triggered — run pb-run-0889'    },
      { ts: 'Apr 3 · 14:00 UTC', actor: 'mike.torres',  action: 'Added PagerDuty integration'             },
      { ts: 'Mar 28 · 09:00 UTC', actor: 'lisa.wong',   action: 'Legal email added to notification list'  },
    ],
  },
  {
    id: 'pb-003',
    name: 'Daily Security Posture Digest',
    description: 'Scheduled daily report summarizing risk scores, open cases, and policy hit rates. Delivered to security leadership at 08:00 UTC.',
    status: 'Active',
    trigger: 'Schedule',
    scope: 'Global',
    owner: 'alex.kim',
    ownerDisplay: 'Alex Kim',
    lastRun: '6h ago',
    lastRunResult: 'Success',
    runsToday: 1,
    successRate: 100,
    enabled: true,
    tags: ['reporting', 'scheduled'],
    conditions: [
      { label: 'Schedule', op: 'cron',    value: '0 8 * * * (UTC)'   },
      { label: 'Scope',    op: 'equals',  value: 'Global'        },
    ],
    actions: [
      { step: 1, type: 'Send Email',   config: 'security-leadership@company.com · HTML digest'  },
      { step: 2, type: 'Notify Slack', config: '#daily-security-digest — summary thread'         },
      { step: 3, type: 'Log to SIEM',  config: 'Splunk — daily_digest event type'               },
    ],
    integrations: ['SendGrid', 'Slack', 'Splunk'],
    workflow: [
      { nodeType: 'trigger',   icon: Calendar,    title: 'Daily Schedule',              detail: 'Cron: 0 8 * * * (08:00 UTC every day)'                },
      { nodeType: 'condition', icon: Activity,    title: 'Data Freshness Check',        detail: 'Verify posture data < 1h old before generating report' },
      { nodeType: 'action',    icon: Terminal,    title: 'Compile Posture Digest',      detail: 'Aggregate risk scores, cases, and policy hits'   },
      { nodeType: 'output',    icon: Mail,        title: 'Distribute Report',           detail: 'Email leadership · Slack digest · Splunk log'          },
    ],
    auditHistory: [
      { ts: 'Apr 8 · 08:00 UTC', actor: 'System',     action: 'Scheduled run — pb-run-0891'            },
      { ts: 'Apr 7 · 08:00 UTC', actor: 'System',     action: 'Scheduled run — pb-run-0878'            },
      { ts: 'Apr 1 · 10:30 UTC', actor: 'alex.kim',   action: 'Added Splunk output step'               },
    ],
  },
  {
    id: 'pb-004',
    name: 'Model Drift Auto-Containment',
    description: 'Detects anomalous behavioral drift from baseline model profiles and automatically applies rate-limiting while notifying the ML ops team.',
    status: 'Active',
    trigger: 'Risk Score',
    scope: 'Production',
    owner: 'raj.patel',
    ownerDisplay: 'Raj Patel',
    lastRun: '3h ago',
    lastRunResult: 'Partial',
    runsToday: 2,
    successRate: 85,
    enabled: true,
    tags: ['model-drift', 'containment'],
    conditions: [
      { label: 'Risk score delta', op: 'greater than', value: '0.30 from baseline'  },
      { label: 'Duration',         op: 'sustained for', value: '> 5 minutes'        },
      { label: 'Model tier',       op: 'equals',        value: 'Production'         },
    ],
    actions: [
      { step: 1, type: 'Apply Policy',    config: 'Rate-limit: max 10 req/min per session' },
      { step: 2, type: 'Create Case',     config: 'Priority: P2 · Assign to ml-ops'        },
      { step: 3, type: 'Notify Slack',    config: '#ml-ops-alerts — drift profile attached' },
      { step: 4, type: 'Run Simulation',  config: 'Replay last 100 sessions against baseline' },
    ],
    integrations: ['Slack', 'Simulation Lab'],
    workflow: [
      { nodeType: 'trigger',   icon: Activity,    title: 'Risk Score Delta Detected',   detail: 'Model risk score drifted > 0.30 from 7-day baseline'   },
      { nodeType: 'condition', icon: Timer,        title: 'Sustained Drift Gate',        detail: 'Drift persists for > 5 minutes (not transient spike)'  },
      { nodeType: 'action',    icon: Shield,       title: 'Apply Rate Limit Policy',     detail: 'Throttle to 10 req/min · flag sessions for review'     },
      { nodeType: 'action',    icon: FlaskConical, title: 'Trigger Simulation Replay',   detail: 'Replay last 100 sessions against clean baseline'        },
      { nodeType: 'output',    icon: Layers,       title: 'Case & Notification',         detail: 'Create P2 case · Notify #ml-ops-alerts in Slack'       },
    ],
    auditHistory: [
      { ts: 'Apr 8 · 09:00 UTC', actor: 'System',      action: 'Triggered — drift detected on gpt-4o-prod · run pb-run-0887' },
      { ts: 'Apr 8 · 12:00 UTC', actor: 'System',      action: 'Triggered — drift detected on claude-3-5 · run pb-run-0890' },
      { ts: 'Apr 2 · 15:00 UTC', actor: 'raj.patel',   action: 'Simulation step added to workflow'                          },
    ],
  },
  {
    id: 'pb-005',
    name: 'Credential Leak Revocation',
    description: 'Monitors model outputs for exposed API keys, tokens, or credentials. Immediately blocks the output, rotates the detected key if integration is available, and alerts security.',
    status: 'Error',
    trigger: 'Policy Match',
    scope: 'All Environments',
    owner: 'sarah.chen',
    ownerDisplay: 'Sarah Chen',
    lastRun: '1h ago',
    lastRunResult: 'Failed',
    runsToday: 1,
    successRate: 60,
    enabled: true,
    tags: ['credential-leak', 'auto-rotate'],
    conditions: [
      { label: 'Policy match', op: 'equals',  value: 'Output-Guard: Credential Pattern' },
      { label: 'Confidence',   op: 'greater than', value: '0.90'                        },
    ],
    actions: [
      { step: 1, type: 'Block Tool',     config: 'Block output delivery — return safe fallback' },
      { step: 2, type: 'Rotate Key',     config: 'Vault rotation for detected key type'         },
      { step: 3, type: 'Create Case',    config: 'Priority: P1 · Tag: credential-leak'          },
      { step: 4, type: 'Send Alert',     config: 'PagerDuty P1 alert → security-on-call'        },
    ],
    integrations: ['HashiCorp Vault', 'PagerDuty'],
    workflow: [
      { nodeType: 'trigger',   icon: Shield,      title: 'Output-Guard Policy Match',   detail: 'Credential pattern detected in model output (conf > 0.90)' },
      { nodeType: 'condition', icon: Filter,       title: 'Pattern Validation',          detail: 'Validate regex match against known key formats (AWS, GCP, etc.)' },
      { nodeType: 'action',    icon: XCircle,      title: 'Block Output Delivery',       detail: 'Intercept response · substitute safe error message'       },
      { nodeType: 'action',    icon: RefreshCw,    title: 'Rotate Credential',           detail: 'HashiCorp Vault API — rotate detected key type'           },
      { nodeType: 'output',    icon: Bell,         title: 'PagerDuty P1 Alert',          detail: 'Create P1 case · Fire PagerDuty alert to on-call'         },
    ],
    auditHistory: [
      { ts: 'Apr 8 · 13:00 UTC', actor: 'System',     action: 'Run pb-run-0888 FAILED — Vault timeout'  },
      { ts: 'Apr 8 · 13:01 UTC', actor: 'System',     action: 'Error: HashiCorp Vault connection refused' },
      { ts: 'Apr 3 · 11:00 UTC', actor: 'sarah.chen', action: 'Added Vault rotation step'               },
    ],
  },
  {
    id: 'pb-006',
    name: 'After-Hours Access Alert',
    description: 'Sends a low-priority Slack notification when AI agents are accessed outside business hours (22:00–06:00 UTC). Informational only — no automated action taken.',
    status: 'Disabled',
    trigger: 'Schedule',
    scope: 'Production',
    owner: 'alex.kim',
    ownerDisplay: 'Alex Kim',
    lastRun: '2d ago',
    lastRunResult: 'Success',
    runsToday: 0,
    successRate: 97,
    enabled: false,
    tags: ['access-control', 'low-priority'],
    conditions: [
      { label: 'Time window', op: 'outside',    value: '06:00–22:00 UTC'         },
      { label: 'Session count', op: 'greater than', value: '0 in last 15 minutes' },
    ],
    actions: [
      { step: 1, type: 'Notify Slack', config: '#after-hours-access — low priority thread' },
    ],
    integrations: ['Slack'],
    workflow: [
      { nodeType: 'trigger',   icon: Clock,       title: 'Time Window Check',           detail: 'Any session detected between 22:00–06:00 UTC'             },
      { nodeType: 'condition', icon: Filter,       title: 'Activity Gate',               detail: 'At least 1 session in past 15 minutes · exclude batch jobs' },
      { nodeType: 'output',    icon: Send,         title: 'Slack Notification',          detail: '#after-hours-access · low-priority · informational'       },
    ],
    auditHistory: [
      { ts: 'Apr 6 · 22:15 UTC', actor: 'System',     action: 'Last run — pb-run-0863 · Success'    },
      { ts: 'Apr 5 · 16:00 UTC', actor: 'alex.kim',   action: 'Playbook disabled — review pending'  },
    ],
  },
]

const MOCK_RUNS = [
  { id: 'pb-run-0892', playbookId: 'pb-001', playbookName: 'Prompt Injection Auto-Response', triggeredBy: 'Alert al-001',          result: 'Success',  duration: '1.2s',  ts: 'Apr 8 · 14:32 UTC' },
  { id: 'pb-run-0891', playbookId: 'pb-003', playbookName: 'Daily Security Posture Digest',  triggeredBy: 'Scheduled (08:00 UTC)',  result: 'Success',  duration: '3.8s',  ts: 'Apr 8 · 08:00 UTC' },
  { id: 'pb-run-0890', playbookId: 'pb-004', playbookName: 'Model Drift Auto-Containment',   triggeredBy: 'Risk score delta 0.41', result: 'Partial',  duration: '5.1s',  ts: 'Apr 8 · 12:00 UTC' },
  { id: 'pb-run-0889', playbookId: 'pb-002', playbookName: 'PII Exfiltration Escalation',    triggeredBy: 'Alert al-003',          result: 'Success',  duration: '2.4s',  ts: 'Apr 8 · 11:15 UTC' },
  { id: 'pb-run-0888', playbookId: 'pb-005', playbookName: 'Credential Leak Revocation',     triggeredBy: 'Policy match output-guard', result: 'Failed', duration: '0.9s', ts: 'Apr 8 · 13:00 UTC' },
  { id: 'pb-run-0887', playbookId: 'pb-004', playbookName: 'Model Drift Auto-Containment',   triggeredBy: 'Risk score delta 0.33', result: 'Success',  duration: '4.7s',  ts: 'Apr 8 · 09:00 UTC' },
  { id: 'pb-run-0886', playbookId: 'pb-001', playbookName: 'Prompt Injection Auto-Response', triggeredBy: 'Alert al-006',          result: 'Success',  duration: '1.1s',  ts: 'Apr 7 · 22:15 UTC' },
  { id: 'pb-run-0885', playbookId: 'pb-001', playbookName: 'Prompt Injection Auto-Response', triggeredBy: 'Alert al-007',          result: 'Success',  duration: '1.3s',  ts: 'Apr 7 · 18:44 UTC' },
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
        <span className={cn('text-[10.5px] font-semibold tabular-nums w-5', checked ? 'text-emerald-600' : 'text-gray-400')}>
          {checked ? 'On' : 'Off'}
        </span>
      )}
    </div>
  )
}

function OwnerAvatar({ name, size = 'sm' }) {
  const parts = name.split('.')
  const initials = parts.map(p => p[0].toUpperCase()).join('')
  const colors = ['bg-blue-500','bg-violet-500','bg-emerald-500','bg-amber-500','bg-rose-500','bg-cyan-500']
  const color  = colors[name.charCodeAt(0) % colors.length]
  const sz = size === 'sm' ? 'w-6 h-6 text-[9px]' : 'w-7 h-7 text-[10px]'
  return (
    <div className={cn('rounded-full flex items-center justify-center text-white font-bold shrink-0', sz, color)}>
      {initials}
    </div>
  )
}

function StatusPip({ status }) {
  const dot   = PB_STATUS_DOT[status]   || 'bg-gray-300'
  const colors = {
    Active:   'text-emerald-700 bg-emerald-50',
    Disabled: 'text-gray-500   bg-gray-100',
    Error:    'text-red-700    bg-red-50',
    Draft:    'text-yellow-700 bg-yellow-50',
  }
  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium', colors[status])}>
      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', dot,
        status === 'Active' ? 'animate-pulse' : '',
        status === 'Running' ? 'animate-pulse' : '',
      )} />
      {status}
    </span>
  )
}

function TriggerChip({ trigger }) {
  const cfg = TRIGGER_CFG[trigger] || { icon: Zap, color: 'text-gray-500', bg: 'bg-gray-50', border: 'border-gray-200' }
  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10.5px] font-medium', cfg.color, cfg.bg, cfg.border)}>
      <Icon size={10} />
      {trigger}
    </span>
  )
}

// ── KPI strip ─────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, icon: Icon, iconColor, valueTint }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-5 py-4 flex items-center gap-4 shadow-sm hover:border-gray-300 transition-colors">
      <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center shrink-0', iconColor)}>
        <Icon size={18} className="text-white" strokeWidth={1.75} />
      </div>
      <div className="min-w-0">
        <p className={cn('text-[22px] font-black tabular-nums leading-none', valueTint ?? 'text-gray-900')}>{value}</p>
        <p className="text-[11px] font-semibold text-gray-500 mt-0.5 leading-snug">{label}</p>
        {sub && <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

// ── Playbook table ─────────────────────────────────────────────────────────────

// Left-border accent by status for table rows
const PB_ROW_BDR = {
  Active:   'border-l-emerald-400',
  Disabled: 'border-l-gray-200',
  Error:    'border-l-red-500',
  Draft:    'border-l-yellow-400',
}

// Result pill colors
const RUN_RESULT_PILL = {
  Success: 'text-emerald-700 bg-emerald-50',
  Failed:  'text-red-700    bg-red-50',
  Partial: 'text-yellow-700 bg-yellow-50',
  Skipped: 'text-gray-500   bg-gray-100',
  Running: 'text-blue-700   bg-blue-50',
}

const PB_COLS = [
  { key: 'name',        label: 'Playbook',      w: 'w-[260px] min-w-[200px]' },
  { key: 'trigger',     label: 'Trigger',       w: 'w-[140px]'               },
  { key: 'scope',       label: 'Scope',         w: 'w-[110px]'               },
  { key: 'owner',       label: 'Owner',         w: 'w-[120px]'               },
  { key: 'status',      label: 'Status',        w: 'w-[100px]'               },
  { key: 'lastRun',     label: 'Last Run',      w: 'w-[130px]'               },
  { key: 'successRate', label: 'Success',       w: 'w-[90px]'                },
  { key: 'enabled',     label: 'Active',        w: 'w-[80px]'                },
]

function PlaybooksTable({ playbooks, selectedId, onSelect, onToggle }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50/80">
            {/* Spacer for left border */}
            <th className="w-0 p-0" />
            {PB_COLS.map(col => (
              <th key={col.key} className={cn('px-3.5 py-2.5 text-[10.5px] font-bold uppercase tracking-[0.06em] text-gray-400 whitespace-nowrap', col.w)}>
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {playbooks.map(pb => {
            const isSelected = pb.id === selectedId
            const bdr = PB_ROW_BDR[pb.status] || 'border-l-gray-200'
            return (
              <tr
                key={pb.id}
                onClick={() => onSelect(pb.id)}
                className={cn(
                  'cursor-pointer transition-colors duration-100 group border-l-[3px]',
                  bdr,
                  isSelected ? 'bg-blue-50/60' : 'hover:bg-gray-50/50',
                )}
              >
                {/* Left border spacer */}
                <td className="w-0 p-0" />

                {/* Playbook name */}
                <td className="px-3.5 py-3">
                  <div className="flex flex-col gap-1">
                    <span className={cn('text-[12.5px] font-semibold leading-snug', isSelected ? 'text-blue-700' : 'text-gray-800 group-hover:text-gray-900')}>
                      {pb.name}
                    </span>
                    <div className="flex items-center gap-1 flex-wrap">
                      {pb.tags.map(t => (
                        <span key={t} className="text-[9px] font-medium text-gray-400 border border-gray-200 rounded px-1.5 py-px bg-white leading-tight">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                </td>
                {/* Trigger */}
                <td className="px-3.5 py-3">
                  <TriggerChip trigger={pb.trigger} />
                </td>
                {/* Scope */}
                <td className="px-3.5 py-3">
                  <span className="text-[11.5px] text-gray-500">{pb.scope}</span>
                </td>
                {/* Owner */}
                <td className="px-3.5 py-3">
                  <div className="flex items-center gap-1.5">
                    <OwnerAvatar name={pb.owner} />
                    <span className="text-[11.5px] text-gray-600">{pb.ownerDisplay}</span>
                  </div>
                </td>
                {/* Status */}
                <td className="px-3.5 py-3">
                  <StatusPip status={pb.status} />
                </td>
                {/* Last run */}
                <td className="px-3.5 py-3">
                  <div className="flex flex-col gap-1">
                    <span className="text-[11px] text-gray-500 font-mono">{pb.lastRun}</span>
                    <span className={cn(
                      'inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-px rounded-full self-start',
                      RUN_RESULT_PILL[pb.lastRunResult] || 'text-gray-400 bg-gray-50',
                    )}>
                      <span className={cn('w-1 h-1 rounded-full shrink-0', RUN_RESULT_DOT[pb.lastRunResult] || 'bg-gray-300')} />
                      {pb.lastRunResult}
                    </span>
                  </div>
                </td>
                {/* Success rate */}
                <td className="px-3.5 py-3">
                  <div className="flex flex-col gap-1.5">
                    <span className={cn(
                      'text-[12px] font-bold tabular-nums leading-none',
                      pb.successRate >= 95 ? 'text-emerald-600' : pb.successRate >= 80 ? 'text-amber-500' : 'text-red-500',
                    )}>
                      {pb.successRate}%
                    </span>
                    <div className="h-[3px] w-12 rounded-full bg-gray-100 overflow-hidden">
                      <div
                        className={cn('h-full rounded-full', pb.successRate >= 95 ? 'bg-emerald-400' : pb.successRate >= 80 ? 'bg-amber-400' : 'bg-red-400')}
                        style={{ width: `${pb.successRate}%` }}
                      />
                    </div>
                  </div>
                </td>
                {/* Toggle */}
                <td className="px-3.5 py-3" onClick={e => e.stopPropagation()}>
                  <Toggle checked={pb.enabled} onChange={v => onToggle(pb.id, v)} showLabel />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// Left-border colors for workflow node types
const FLOW_NODE_LBR = {
  trigger:   'border-l-blue-500',
  condition: 'border-l-amber-400',
  action:    'border-l-emerald-500',
  output:    'border-l-violet-500',
}
const FLOW_NODE_ICON_BG = {
  trigger:   'bg-blue-100 text-blue-600',
  condition: 'bg-amber-100 text-amber-600',
  action:    'bg-emerald-100 text-emerald-600',
  output:    'bg-violet-100 text-violet-600',
}
const FLOW_NODE_LABEL_COLOR = {
  trigger:   'text-blue-600',
  condition: 'text-amber-600',
  action:    'text-emerald-600',
  output:    'text-violet-600',
}

// ── Workflow flow (visual) ─────────────────────────────────────────────────────

function WorkflowFlow({ nodes }) {
  return (
    <div className="flex flex-col">
      {nodes.map((node, idx) => {
        const cfg    = FLOW_NODE_CFG[node.nodeType]
        const lbr    = FLOW_NODE_LBR[node.nodeType]
        const iconBg = FLOW_NODE_ICON_BG[node.nodeType]
        const lblClr = FLOW_NODE_LABEL_COLOR[node.nodeType]
        const Icon   = node.icon
        const isLast = idx === nodes.length - 1
        return (
          <div key={idx} className="flex gap-3 items-start">
            {/* Step spine */}
            <div className="flex flex-col items-center shrink-0 pt-3">
              <div className={cn('w-6 h-6 rounded-full flex items-center justify-center border-2 border-white shadow-sm', iconBg)}>
                <Icon size={11} strokeWidth={2} />
              </div>
              {!isLast && (
                <div className="flex-1 mt-1 mb-1 w-px border-l-2 border-dashed border-gray-200 min-h-[20px]" />
              )}
            </div>

            {/* Node card */}
            <div className={cn(
              'flex-1 min-w-0 mb-2.5 rounded-xl bg-white border border-gray-150 border-l-[3px] shadow-[0_1px_3px_rgba(0,0,0,0.05)] overflow-hidden',
              lbr,
            )}>
              <div className="px-3.5 pt-2.5 pb-2.5">
                <div className="flex items-center gap-2 mb-1">
                  <span className={cn('text-[9px] font-black tracking-[0.1em] uppercase', lblClr)}>{cfg.label}</span>
                  <span className="flex-1 h-px bg-gray-100" />
                  <span className="text-[9px] text-gray-400 font-mono">step {String(idx + 1).padStart(2, '0')}</span>
                </div>
                <p className="text-[12px] font-semibold text-gray-800 leading-snug">{node.title}</p>
                <p className="text-[10.5px] text-gray-500 mt-0.5 leading-snug">{node.detail}</p>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Playbook detail panel ──────────────────────────────────────────────────────

const DETAIL_TABS = ['Overview', 'Workflow', 'Conditions', 'Actions', 'Integrations', 'Audit']

function PlaybookDetailPanel({ pb, onClose }) {
  const [activeTab, setActiveTab] = useState('Overview')

  if (!pb) return null

  // Accent strip color by status
  const HDR_STRIP = pb.status === 'Error'   ? 'bg-red-500' :
                    pb.status === 'Active'  ? 'bg-emerald-500' :
                    pb.status === 'Draft'   ? 'bg-yellow-400' : 'bg-gray-300'
  const HDR_BG    = pb.status === 'Error'   ? 'bg-red-50/50 border-b-red-100' :
                    pb.status === 'Active'  ? 'bg-emerald-50/30 border-b-emerald-100' :
                    'bg-gray-50/60 border-b-gray-100'

  return (
    <div className="w-[440px] shrink-0 bg-white border border-gray-200 rounded-xl shadow-sm flex flex-col overflow-hidden">
      {/* Accent strip */}
      <div className={cn('h-[3px] w-full shrink-0', HDR_STRIP)} />

      {/* Header */}
      <div className={cn('px-5 py-4 border-b shrink-0', HDR_BG)}>
        {/* Row 1: ID + badges + close */}
        <div className="flex items-center justify-between gap-2 mb-2.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10.5px] font-mono text-gray-400 tracking-wide">{pb.id}</span>
            <StatusPip status={pb.status} />
            <TriggerChip trigger={pb.trigger} />
          </div>
          <button
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded-md hover:bg-black/[0.06] text-gray-400 hover:text-gray-600 transition-colors shrink-0"
          >
            <X size={13} />
          </button>
        </div>

        {/* Row 2: name */}
        <h2 className="text-[15px] font-bold text-gray-900 leading-snug mb-2">{pb.name}</h2>

        {/* Row 3: owner + scope + runs */}
        <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-3.5">
          <OwnerAvatar name={pb.owner} size="sm" />
          <span className="font-semibold text-gray-600">{pb.ownerDisplay}</span>
          <span className="text-gray-300">·</span>
          <span>{pb.scope}</span>
          <span className="text-gray-300">·</span>
          <span className="font-mono text-gray-400">{pb.runsToday} run{pb.runsToday !== 1 ? 's' : ''} today</span>
        </div>

        {/* Row 4: action groups */}
        <div className="flex items-center gap-1.5">
          {/* Primary group */}
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <Settings size={11} /> Edit
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
            <Copy size={11} /> Duplicate
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] border-blue-200 text-blue-600 hover:bg-blue-50">
            <Play size={11} /> Run Test
          </Button>

          {/* Separator */}
          <div className="w-px h-5 bg-gray-200 mx-0.5" />

          {/* Enable / Disable — right of separator */}
          {pb.enabled ? (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-orange-600 border-orange-200 hover:bg-orange-50">
              <Pause size={11} /> Disable
            </Button>
          ) : (
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px] text-emerald-600 border-emerald-200 hover:bg-emerald-50">
              <Play size={11} /> Enable
            </Button>
          )}
        </div>
      </div>

      {/* Tabs — see Integrations.jsx for the pixel-perfect structure rationale */}
      <div className="bg-white shrink-0 px-4 pb-2 overflow-x-auto">
        <div className="flex gap-0 border-b border-gray-100 min-w-max">
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
            {/* Description */}
            <div>
              <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400 mb-2">Description</p>
              <p className="text-[12.5px] text-gray-700 leading-relaxed">{pb.description}</p>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'Runs Today',    value: pb.runsToday     },
                { label: 'Success Rate',  value: `${pb.successRate}%` },
                { label: 'Last Run',      value: pb.lastRun       },
              ].map(s => (
                <div key={s.label} className="bg-gray-50 rounded-lg border border-gray-100 px-3 py-2.5">
                  <p className="text-[18px] font-black tabular-nums text-gray-900 leading-none">{s.value}</p>
                  <p className="text-[9.5px] font-semibold text-gray-400 uppercase tracking-wide mt-1">{s.label}</p>
                </div>
              ))}
            </div>

            {/* Last run result */}
            <div className="bg-gray-50 rounded-xl border border-gray-100 p-3.5">
              <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400 mb-2">Last Execution</p>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    'w-2 h-2 rounded-full shrink-0',
                    RUN_RESULT_DOT[pb.lastRunResult] || 'bg-gray-300',
                    pb.lastRunResult === 'Running' ? 'animate-pulse' : '',
                  )} />
                  <span className="text-[12px] font-semibold text-gray-700">{pb.lastRunResult}</span>
                </div>
                <span className="text-[11px] font-mono text-gray-400">{pb.lastRun}</span>
              </div>
              {pb.status === 'Error' && (
                <div className="mt-2 px-3 py-2 bg-red-50 border border-red-100 rounded-lg">
                  <p className="text-[11px] text-red-600 font-medium">Integration error: HashiCorp Vault connection refused. Check Vault endpoint health.</p>
                </div>
              )}
            </div>

            {/* Tags */}
            <div>
              <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400 mb-2">Tags</p>
              <div className="flex flex-wrap gap-1.5">
                {pb.tags.map(t => (
                  <span key={t} className="text-[11px] font-medium text-gray-500 border border-gray-200 rounded-md px-2 py-0.5 bg-white">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Workflow ── */}
        {activeTab === 'Workflow' && (
          <div className="p-5">
            <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400 mb-4">Visual Workflow</p>
            <WorkflowFlow nodes={pb.workflow} />
          </div>
        )}

        {/* ── Conditions ── */}
        {activeTab === 'Conditions' && (
          <div className="p-5 space-y-3">
            <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400">Trigger Conditions</p>
            <div className="space-y-0">
              {pb.conditions.map((cond, idx) => {
                const isLast = idx === pb.conditions.length - 1
                return (
                  <div key={idx} className="flex gap-3">
                    {/* Spine */}
                    <div className="flex flex-col items-center shrink-0">
                      <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-2.5">
                        <span className="text-[9px] font-black">{idx + 1}</span>
                      </div>
                      {!isLast && <div className="flex-1 mt-1 mb-1 w-px border-l border-dashed border-gray-200 min-h-[12px]" />}
                    </div>
                    {/* Card */}
                    <div className="flex-1 min-w-0 mb-2 bg-white rounded-xl border border-gray-150 border-l-[3px] border-l-blue-300 px-3.5 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                      <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{cond.label}</p>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-[10.5px] text-gray-400 italic">{cond.op}</span>
                        <span className="text-[12px] font-mono font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-100 leading-tight">{cond.value}</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="flex items-center gap-2 pt-1">
              <span className="h-px flex-1 bg-gray-100" />
              <p className="text-[10px] text-gray-400 font-medium">All conditions must be satisfied</p>
              <span className="h-px flex-1 bg-gray-100" />
            </div>
          </div>
        )}

        {/* ── Actions ── */}
        {activeTab === 'Actions' && (
          <div className="p-5 space-y-3">
            <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400">Response Actions</p>
            <div className="space-y-0">
              {pb.actions.map((action, idx) => {
                const cfg    = ACTION_TYPE_CFG[action.type] || { icon: Zap, color: 'text-gray-600', bg: 'bg-gray-50' }
                const Icon   = cfg.icon
                const isLast = idx === pb.actions.length - 1
                return (
                  <div key={action.step} className="flex gap-3">
                    {/* Spine */}
                    <div className="flex flex-col items-center shrink-0">
                      <div className={cn('w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-2 border-2 border-white shadow-sm', cfg.bg)}>
                        <Icon size={12} className={cfg.color} strokeWidth={2} />
                      </div>
                      {!isLast && <div className="flex-1 mt-1 mb-1 w-px border-l-2 border-dashed border-gray-200 min-h-[12px]" />}
                    </div>
                    {/* Card */}
                    <div className="flex-1 min-w-0 mb-2.5">
                      <div className={cn(
                        'bg-white rounded-xl border border-gray-150 border-l-[3px] px-3.5 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]',
                        cfg.color.replace('text-', 'border-l-'),
                      )}>
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className="text-[9px] font-black text-gray-300 tabular-nums">
                            {String(action.step).padStart(2, '0')}
                          </span>
                          <span className="text-[12px] font-semibold text-gray-800 leading-snug">{action.type}</span>
                        </div>
                        <p className="text-[11px] text-gray-500 leading-snug pl-5">{action.config}</p>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── Integrations ── */}
        {activeTab === 'Integrations' && (
          <div className="p-5 space-y-3">
            <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400">Linked Integrations</p>
            <div className="space-y-2">
              {pb.integrations.map((intg, idx) => {
                const hasError = pb.status === 'Error' && (intg === 'HashiCorp Vault')
                return (
                  <div key={idx} className={cn(
                    'flex items-center justify-between px-3.5 py-3 bg-white border rounded-xl',
                    hasError ? 'border-red-200 border-l-[3px] border-l-red-500' : 'border-gray-200 border-l-[3px] border-l-emerald-400',
                  )}>
                    <div className="flex items-center gap-2.5">
                      <div className={cn(
                        'w-7 h-7 rounded-lg border flex items-center justify-center',
                        hasError ? 'bg-red-50 border-red-200' : 'bg-gray-50 border-gray-200',
                      )}>
                        {hasError
                          ? <AlertTriangle size={12} className="text-red-500" />
                          : <Cloud size={12} className="text-gray-400" />}
                      </div>
                      <div>
                        <span className="text-[12px] font-semibold text-gray-700">{intg}</span>
                        {hasError && <p className="text-[10px] text-red-500 font-medium mt-0.5">Connection refused</p>}
                      </div>
                    </div>
                    <Badge variant={hasError ? 'critical' : 'success'}>{hasError ? 'Error' : 'Connected'}</Badge>
                  </div>
                )
              })}
            </div>
            {pb.status === 'Error' && (
              <div className="flex items-start gap-2.5 px-3.5 py-3 bg-red-50 border border-red-200 rounded-xl">
                <AlertTriangle size={13} className="text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-[11.5px] font-semibold text-red-700">Integration Error</p>
                  <p className="text-[11px] text-red-600 mt-0.5 leading-snug">HashiCorp Vault: Connection refused. Verify the Vault endpoint URL and network access policy.</p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Audit ── */}
        {activeTab === 'Audit' && (
          <div className="p-5 space-y-3">
            <p className="text-[10.5px] font-bold uppercase tracking-[0.07em] text-gray-400">Audit History</p>
            <div className="space-y-0">
              {pb.auditHistory.map((entry, idx) => {
                const isSystem = entry.actor === 'System'
                const isLast   = idx === pb.auditHistory.length - 1
                return (
                  <div key={idx} className="flex gap-3">
                    {/* Spine */}
                    <div className="flex flex-col items-center shrink-0">
                      <div className={cn(
                        'w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-2.5 border-2 border-white shadow-sm',
                        isSystem ? 'bg-gray-100' : 'bg-blue-100',
                      )}>
                        {isSystem
                          ? <Cpu size={10} className="text-gray-400" />
                          : <User size={10} className="text-blue-500" />}
                      </div>
                      {!isLast && <div className="flex-1 mt-1 mb-1 w-px border-l border-dashed border-gray-200 min-h-[12px]" />}
                    </div>
                    {/* Card */}
                    <div className="flex-1 min-w-0 mb-2">
                      <div className={cn(
                        'bg-white rounded-xl border border-gray-150 border-l-[3px] px-3 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]',
                        isSystem ? 'border-l-gray-300' : 'border-l-blue-400',
                      )}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <span className={cn('text-[10.5px] font-bold', isSystem ? 'text-gray-400' : 'text-blue-600')}>
                              {isSystem ? 'System' : entry.actor}
                            </span>
                            <p className="text-[11.5px] text-gray-700 mt-0.5 leading-snug">{entry.action}</p>
                          </div>
                          <span className="text-[9.5px] font-mono text-gray-400 shrink-0 mt-0.5 whitespace-nowrap">{entry.ts}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Left-border accent by run result
const RUN_ROW_BDR = {
  Success: 'border-l-emerald-400',
  Failed:  'border-l-red-500',
  Partial: 'border-l-yellow-400',
  Skipped: 'border-l-gray-200',
  Running: 'border-l-blue-400',
}

// ── Recent runs table ──────────────────────────────────────────────────────────

function RecentRunsTable({ runs }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <p className="text-[13px] font-semibold text-gray-900">Recent Execution Runs</p>
          <span className="text-[11px] text-gray-400 font-medium">{runs.length} runs</span>
        </div>
        <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
          <RefreshCw size={11} /> Refresh
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/80">
              {/* Left border spacer */}
              <th className="w-0 p-0" />
              {['Run ID', 'Playbook', 'Triggered By', 'Result', 'Duration', 'Timestamp'].map(col => (
                <th key={col} className="px-3.5 py-2.5 text-[10.5px] font-bold uppercase tracking-[0.06em] text-gray-400 whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {runs.map(run => {
              const bdr = RUN_ROW_BDR[run.result] || 'border-l-gray-200'
              return (
                <tr key={run.id} className={cn('hover:bg-gray-50/50 transition-colors group border-l-[3px]', bdr)}>
                  <td className="w-0 p-0" />
                  <td className="px-3.5 py-2.5">
                    <span className="text-[11px] font-mono font-medium text-gray-500 group-hover:text-blue-600 transition-colors">{run.id}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="text-[12px] font-medium text-gray-700">{run.playbookName}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="text-[11.5px] text-gray-500">{run.triggeredBy}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className={cn(
                      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10.5px] font-semibold',
                      RUN_RESULT_PILL[run.result] || 'text-gray-500 bg-gray-100',
                    )}>
                      <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', RUN_RESULT_DOT[run.result] || 'bg-gray-300')} />
                      {run.result}
                    </span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="text-[11.5px] font-mono text-gray-400">{run.duration}</span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className="text-[11px] font-mono text-gray-400">{run.ts}</span>
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

export default function Automation() {
  const [playbooks, setPlaybooks] = useState(MOCK_PLAYBOOKS)
  const [runs]                    = useState(MOCK_RUNS)
  const [selectedId, setSelectedId] = useState('pb-001')
  const [search, setSearch]       = useState('')
  const [filterStatus, setFilterStatus]  = useState('All Statuses')
  const [filterTrigger, setFilterTrigger] = useState('All Triggers')
  const [filterOwner, setFilterOwner]    = useState('All Owners')
  const [filterScope, setFilterScope]    = useState('All Scopes')
  const [onlyFailed, setOnlyFailed]      = useState(false)

  const selectedPb = playbooks.find(p => p.id === selectedId) || null

  function handleToggle(id, enabled) {
    setPlaybooks(prev => prev.map(p =>
      p.id === id ? { ...p, enabled, status: enabled ? 'Active' : 'Disabled' } : p,
    ))
  }

  // Derived filter options
  const statusOpts  = ['All Statuses',  ...Array.from(new Set(playbooks.map(p => p.status)))]
  const triggerOpts = ['All Triggers',  ...Array.from(new Set(playbooks.map(p => p.trigger)))]
  const ownerOpts   = ['All Owners',    ...Array.from(new Set(playbooks.map(p => p.ownerDisplay)))]
  const scopeOpts   = ['All Scopes',    ...Array.from(new Set(playbooks.map(p => p.scope)))]

  const filtered = playbooks.filter(p => {
    const q = search.toLowerCase()
    if (q && !p.name.toLowerCase().includes(q) && !p.tags.some(t => t.includes(q))) return false
    if (filterStatus  !== 'All Statuses'  && p.status       !== filterStatus)  return false
    if (filterTrigger !== 'All Triggers'  && p.trigger      !== filterTrigger) return false
    if (filterOwner   !== 'All Owners'    && p.ownerDisplay !== filterOwner)   return false
    if (filterScope   !== 'All Scopes'    && p.scope        !== filterScope)   return false
    if (onlyFailed && p.lastRunResult !== 'Failed') return false
    return true
  })

  // KPI values
  const activeCount   = playbooks.filter(p => p.status === 'Active').length
  const disabledCount = playbooks.filter(p => p.status === 'Disabled').length
  const runsToday     = playbooks.reduce((s, p) => s + p.runsToday, 0)
  const failedRuns    = runs.filter(r => r.result === 'Failed').length

  return (
    <PageContainer>
      {/* Page header */}
      <PageHeader
        title="Automation"
        subtitle="Security playbooks and automated response orchestration"
        actions={
          <>
            <Button size="sm" variant="outline" className="gap-1.5">
              <RefreshCw size={13} /> Sync
            </Button>
            <Button size="sm" className="gap-1.5">
              <Plus size={13} /> New Playbook
            </Button>
          </>
        }
      />

      {/* KPI strip */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="Active Playbooks"  value={activeCount}   sub="Enabled & running"    icon={Zap}        iconColor="bg-emerald-500" valueTint="text-emerald-600" />
        <KpiCard label="Disabled"          value={disabledCount} sub="Paused or draft"       icon={Pause}      iconColor="bg-gray-400"    valueTint="text-gray-500"   />
        <KpiCard label="Runs Today"        value={runsToday}     sub="Across all playbooks"  icon={Activity}   iconColor="bg-blue-500"    valueTint="text-blue-600"   />
        <KpiCard label="Failed Runs"       value={failedRuns}    sub="In last 24 hours"      icon={XCircle}    iconColor="bg-red-500"     valueTint={failedRuns > 0 ? 'text-red-600' : 'text-gray-900'} />
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-[300px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search playbooks…"
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

        <FilterSelect value={filterStatus}  onChange={setFilterStatus}  options={statusOpts}  />
        <FilterSelect value={filterTrigger} onChange={setFilterTrigger} options={triggerOpts} />
        <FilterSelect value={filterOwner}   onChange={setFilterOwner}   options={ownerOpts}   />
        <FilterSelect value={filterScope}   onChange={setFilterScope}   options={scopeOpts}   />

        {/* Only failed toggle */}
        <div className="flex items-center gap-2 ml-auto">
          <Toggle checked={onlyFailed} onChange={setOnlyFailed} />
          <span className="text-[12px] font-medium text-gray-500">Only failed recently</span>
        </div>
      </div>

      {/* Main area: list + detail */}
      <div className="flex gap-4 items-start">
        {/* Playbooks table */}
        <div className="flex-1 min-w-0 bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
            <p className="text-[13px] font-semibold text-gray-700">
              Playbooks
              <span className="ml-2 text-[11px] font-medium text-gray-400">{filtered.length} of {playbooks.length}</span>
            </p>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" className="h-7 gap-1 text-[11px]">
                <List size={11} /> Export
              </Button>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="py-16 flex flex-col items-center gap-2 text-center">
              <Filter size={20} className="text-gray-300" />
              <p className="text-[12.5px] text-gray-400 font-medium">No playbooks match your filters</p>
              <p className="text-[11px] text-gray-300">Try adjusting the search or filter criteria</p>
            </div>
          ) : (
            <PlaybooksTable
              playbooks={filtered}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onToggle={handleToggle}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedPb && (
          <PlaybookDetailPanel
            pb={selectedPb}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>

      {/* Recent execution runs */}
      <RecentRunsTable runs={runs} />
    </PageContainer>
  )
}
