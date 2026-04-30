/**
 * sessionResults.js
 * ──────────────────
 * Production-grade Kafka event → Results panel data model.
 *
 * Exports
 * ───────
 *   CANONICAL_EVENT_TYPES   Full registry of canonical event type strings.
 *   SESSION_RESULTS_SCHEMA  Field-level documentation of the SessionResults shape.
 *   canonicalise(event)     Normalise a raw WsEvent to its canonical event_type.
 *   EVENT_MAP               Per-event-type mapping → UI panel impact.
 *   transformSessionEvents  Pure function: WsEvent[] → SessionResults.
 *
 * Design principles
 * ─────────────────
 *  1. Pure / deterministic — same input always produces same output.
 *  2. Streaming-safe — valid SessionResults returned even with 0 events.
 *  3. Backward-compatible — works with both legacy pipeline event_type values
 *     and orchestrator EventEnvelope event_type values.
 *  4. No side effects — never mutates input arrays.
 *  5. Stable ordering — decision_trace steps sorted by ISO-8601 timestamp;
 *     recommendations sorted by priority weight.
 */

// ─────────────────────────────────────────────────────────────────────────────
// A.  CANONICAL EVENT TYPES
// ─────────────────────────────────────────────────────────────────────────────
//
// Naming convention: <domain>.<noun>.<verb-past>
// All strings are lowercase, dot-separated, no spaces.
//
// These are the event_type values the UI understands natively.
// Incoming events are normalised to this vocabulary by canonicalise().

export const CANONICAL_EVENT_TYPES = {
  // ── Session lifecycle ──────────────────────────────────────────────────────
  SESSION_STARTED:    'session.started',    // first prompt received by ingress
  SESSION_CREATED:    'session.created',    // session record committed to DB
  SESSION_COMPLETED:  'session.completed',  // pipeline fully finished, result ready
  SESSION_BLOCKED:    'session.blocked',    // hard-blocked before LLM invocation
  SESSION_FAILED:     'session.failed',     // unexpected pipeline error

  // ── Context retrieval ──────────────────────────────────────────────────────
  CONTEXT_RETRIEVED:  'context.retrieved',  // RAG / memory context fetched

  // ── Risk / posture ─────────────────────────────────────────────────────────
  RISK_ENRICHED:      'risk.enriched',      // multi-dimensional posture score (processor)
  RISK_CALCULATED:    'risk.calculated',    // orchestrator-side risk scoring

  // ── Policy / enforcement ───────────────────────────────────────────────────
  POLICY_ALLOWED:     'policy.allowed',     // decision = allow
  POLICY_BLOCKED:     'policy.blocked',     // decision = block
  POLICY_ESCALATED:   'policy.escalated',   // decision = escalate (HITL)

  // ── Agent planning ─────────────────────────────────────────────────────────
  AGENT_MEMORY_REQUESTED:  'agent.memory.requested',   // agent requested mem read/write
  AGENT_MEMORY_RESOLVED:   'agent.memory.resolved',    // memory result returned
  AGENT_TOOL_PLANNED:      'agent.tool.planned',        // agent decided to invoke a tool
  AGENT_RESPONSE_READY:    'agent.response.ready',      // agent assembled final response

  // ── Tool execution ─────────────────────────────────────────────────────────
  TOOL_INVOKED:            'tool.invoked',              // executor dispatched the tool
  TOOL_APPROVAL_REQUIRED:  'tool.approval.required',    // HITL approval gate opened
  TOOL_COMPLETED:          'tool.completed',            // tool returned result
  TOOL_OBSERVED:           'tool.observed',             // tool-parser validated output

  // ── Output generation ──────────────────────────────────────────────────────
  OUTPUT_GENERATED:   'output.generated',   // LLM response produced
  OUTPUT_SCANNED:     'output.scanned',     // output safety scan complete

  // ── Audit / completion ─────────────────────────────────────────────────────
  AUDIT_LOGGED:       'audit.logged',       // audit record written to export

  // ── Garak red-team execution trace ────────────────────────────────────────
  // Per-attempt detail events emitted by garak_runner.py.
  // These flow through the same WS → useSimulationState pipeline but are
  // stored separately (prompts[], responses[], guardDecisions[]) rather than
  // appearing as Decision Trace steps, so EVENT_MAP marks them trace:false.
  LLM_PROMPT:         'llm.prompt',         // exact prompt sent to the model
  LLM_RESPONSE:       'llm.response',       // raw model completion
  GUARD_DECISION:     'guard.decision',     // guard/detector verdict
  TOOL_CALL:          'tool.call',          // tool invoked by a probe
  GUARD_INPUT:        'guard.input',        // raw prompt captured before sanitization

  // ── Garak probe-level errors (infrastructure failure, not a security finding)
  PROBE_ERROR:        'simulation.probe_error', // probe crashed / timed out
}

// ─────────────────────────────────────────────────────────────────────────────
// Normalisation table: raw event_type → canonical event_type
//
// Two source vocabularies co-exist in production:
//   • Legacy pipeline (send_event() enriched): "posture.enriched", "policy.decision", …
//   • Orchestrator EventEnvelope: "prompt_received", "risk_calculated", …
//
// Policy events are split by payload.decision (allow/block/escalate) so the
// UI can render verdict-specific styling without inspecting payload fields.
// ─────────────────────────────────────────────────────────────────────────────

const _RAW_TO_CANONICAL = {
  // Legacy pipeline
  'raw_event':               CANONICAL_EVENT_TYPES.SESSION_STARTED,
  'context.retrieved':       CANONICAL_EVENT_TYPES.CONTEXT_RETRIEVED,
  'posture.enriched':        CANONICAL_EVENT_TYPES.RISK_ENRICHED,
  // 'policy.decision' handled separately (split by payload.decision)
  'memory.request':          CANONICAL_EVENT_TYPES.AGENT_MEMORY_REQUESTED,
  'memory.result':           CANONICAL_EVENT_TYPES.AGENT_MEMORY_RESOLVED,
  'tool.request':            CANONICAL_EVENT_TYPES.AGENT_TOOL_PLANNED,
  'tool.approval_requested': CANONICAL_EVENT_TYPES.TOOL_APPROVAL_REQUIRED,
  'tool.result':             CANONICAL_EVENT_TYPES.TOOL_COMPLETED,
  'tool.observation':        CANONICAL_EVENT_TYPES.TOOL_OBSERVED,
  'final.response':          CANONICAL_EVENT_TYPES.AGENT_RESPONSE_READY,

  // Orchestrator EventEnvelope
  'prompt_received':         CANONICAL_EVENT_TYPES.SESSION_STARTED,
  'risk_calculated':         CANONICAL_EVENT_TYPES.RISK_CALCULATED,
  // 'policy_decision' handled separately
  'session.created':         CANONICAL_EVENT_TYPES.SESSION_CREATED,
  'session.blocked':         CANONICAL_EVENT_TYPES.SESSION_BLOCKED,
  'session.completed':       CANONICAL_EVENT_TYPES.SESSION_COMPLETED,
  'llm_response':            CANONICAL_EVENT_TYPES.OUTPUT_GENERATED,
  'output_scanned':          CANONICAL_EVENT_TYPES.OUTPUT_SCANNED,

  // Aliases / legacy spellings
  'session_completed':       CANONICAL_EVENT_TYPES.SESSION_COMPLETED,
  'session_blocked':         CANONICAL_EVENT_TYPES.SESSION_BLOCKED,
  'session_created':         CANONICAL_EVENT_TYPES.SESSION_CREATED,

  // Backend simulation.* direct events (simulation.py _ws_emit calls)
  'simulation.started':      CANONICAL_EVENT_TYPES.SESSION_STARTED,
  'simulation.blocked':      CANONICAL_EVENT_TYPES.SESSION_BLOCKED,
  'simulation.allowed':      CANONICAL_EVENT_TYPES.POLICY_ALLOWED,
  'simulation.completed':    CANONICAL_EVENT_TYPES.SESSION_COMPLETED,
  'simulation.error':        CANONICAL_EVENT_TYPES.SESSION_FAILED,
  // simulation.progress has no canonical equivalent — falls through as raw string → stage 'progress'

  // Garak execution trace events — identity mappings (already canonical)
  'llm.prompt':    CANONICAL_EVENT_TYPES.LLM_PROMPT,
  'llm.response':  CANONICAL_EVENT_TYPES.LLM_RESPONSE,
  'guard.decision': CANONICAL_EVENT_TYPES.GUARD_DECISION,
  'tool.call':     CANONICAL_EVENT_TYPES.TOOL_CALL,
  'guard.input':   CANONICAL_EVENT_TYPES.GUARD_INPUT,

  // Garak probe-level infrastructure error (non-terminal — probe failed to run)
  'simulation.probe_error': CANONICAL_EVENT_TYPES.PROBE_ERROR,

  // Agent-runtime events from the chat path (Phase 2 streaming PR).
  //
  // ``AgentChatMessage`` is split by ``payload.role`` in canonicalise()
  // below — user turns become SESSION_STARTED (renders as "User Prompt"
  // node in the lineage graph), agent turns become OUTPUT_GENERATED
  // (renders as the output node). It's intentionally NOT mapped here;
  // canonicalise() handles it ahead of this lookup.
  //
  // ``AgentLLMCall`` is the spm-llm-proxy → upstream model invocation;
  // surfaces as "LLM Processing" via RISK_CALCULATED (the lineage
  // builder uses payload.risk_score when present, falls back to 0).
  //
  // ``AgentToolCall`` is the spm-mcp tool invocation (web_fetch etc.);
  // TOOL_COMPLETED gives us the tool node + completion edge.
  'AgentLLMCall':  CANONICAL_EVENT_TYPES.RISK_CALCULATED,
  'AgentToolCall': CANONICAL_EVENT_TYPES.TOOL_COMPLETED,
}

const _POLICY_EVENT_TYPES = new Set(['policy.decision', 'policy_decision'])

/**
 * Normalise a raw WsEvent to its canonical event_type.
 * Policy events are split based on payload.decision.
 *
 * @param {{ event_type: string, payload?: object }} event
 * @returns {string} canonical event_type
 */
export function canonicalise(event) {
  const raw = event.event_type ?? ''

  if (_POLICY_EVENT_TYPES.has(raw)) {
    const d = (event.payload?.decision ?? '').toLowerCase()
    if (d === 'block')    return CANONICAL_EVENT_TYPES.POLICY_BLOCKED
    if (d === 'escalate') return CANONICAL_EVENT_TYPES.POLICY_ESCALATED
    return CANONICAL_EVENT_TYPES.POLICY_ALLOWED
  }

  // AgentChatMessage events carry role=user|agent in their payload.
  // Split into the two canonical types the lineage graph already
  // knows how to render — without this the chat events fall through
  // as raw strings and don't add nodes.
  if (raw === 'AgentChatMessage') {
    const role = (event.payload?.role ?? '').toLowerCase()
    if (role === 'agent' || role === 'assistant') {
      return CANONICAL_EVENT_TYPES.OUTPUT_GENERATED
    }
    return CANONICAL_EVENT_TYPES.SESSION_STARTED  // user (default)
  }

  return _RAW_TO_CANONICAL[raw] ?? raw
}

// ─────────────────────────────────────────────────────────────────────────────
// B.  SessionResults SCHEMA (documentation)
// ─────────────────────────────────────────────────────────────────────────────
//
// This object is exported as a reference. It is not used at runtime.
// All fields are present even in partial/streaming results — missing data
// is represented by null / [] / 0 rather than absent keys.

export const SESSION_RESULTS_SCHEMA = {
  /**
   * Internal metadata — not rendered directly in any tab.
   * Used by SimulationResult to make per-tab decisions.
   */
  _meta: {
    session_id:           'string',
    correlation_id:       'string',
    /** 'pending' while pipeline is running; 'completed'|'blocked'|'failed' when done */
    status:               "'pending' | 'running' | 'completed' | 'blocked' | 'failed'",
    started_at:           'string | null',      // ISO-8601 of session.started
    completed_at:         'string | null',      // ISO-8601 of session.completed|blocked
    duration_ms:          'number | null',
    /** Ordered list of source_service values that processed this session */
    service_chain:        'string[]',
    /** True while pipeline is still running (partial stream) */
    partial:              'boolean',
  },

  /** Summary tab */
  summary: {
    verdict:              "'allowed' | 'blocked' | 'escalated' | 'pending'",
    verdict_reason:       'string',
    risk_score:           'number (0–100)',
    risk_level:           "'low' | 'medium' | 'high' | 'critical'",
    execution_ms:         'number',
    policies_triggered:   'string[]',
    tools_invoked:        'string[]',   // tool_name values
    memory_ops:           'number',     // count of memory read/write ops
    context_items:        'number',     // count of RAG items retrieved
  },

  /** Decision Trace tab — timeline of pipeline steps */
  decision_trace: [{
    step:         'number (1-based)',
    event_type:   'string (canonical)',
    title:        'string',
    source:       'string (source_service)',
    /** 'ok' | 'warn' | 'critical' | 'blocked' | 'pending' */
    status:       'string',
    /** Null unless this step produced a binary decision */
    decision:     'string | null',
    detail:       'string',             // human-readable detail line
    timestamp:    'string (ISO-8601)',
    latency_ms:   'number | null',      // ms since previous step; null for first
  }],

  /** Risk Analysis tab */
  risk_analysis: {
    score:          'number (0.0–1.0 float)',
    score_pct:      'number (0–100 integer)',
    tier:           "'low' | 'medium' | 'high' | 'critical'",
    /** Six risk dimension scores from PostureEnrichedEvent */
    dimensions: {
      prompt_risk:      'number',
      behavioral_risk:  'number',
      identity_risk:    'number',
      memory_risk:      'number',
      retrieval_trust:  'number',   // higher = safer (inverted scale)
      guard_risk:       'number',
      intent_drift:     'number',
    },
    signals:          'string[]',   // raw signal slugs e.g. "prompt_injection_detected"
    behavioral_signals: 'string[]',
    ttps:             'string[]',   // CEP-derived MITRE-style TTPs
    guard_verdict:    "'allow' | 'flag' | 'block' | 'unchecked'",
    guard_score:      'number',
    guard_categories: 'string[]',
    /** Derived boolean flags for the Anomaly Detection sub-section */
    anomaly_flags: {
      injection_detected:   'boolean',
      pii_detected:         'boolean',
      role_escalation:      'boolean',
      data_exfiltration:    'boolean',
      jailbreak_attempt:    'boolean',
    },
    /** Confidence 0–1 derived from guard_score vs posture_score agreement */
    confidence:       'number',
    explanation:      'string',     // generated analyst summary
  },

  /** Policy Impact tab */
  policy_impact: {
    decision:           "'allowed' | 'blocked' | 'escalated' | 'pending'",
    reason:             'string',
    policy_version:     'string',
    /** One entry per policy evaluation observed */
    rules_triggered: [{
      rule_id:    'string',
      rule_name:  'string',
      action:     "'BLOCK' | 'FLAG' | 'ESCALATE' | 'ALLOW'",
      severity:   "'critical' | 'high' | 'medium' | 'low' | 'neutral'",
      trigger:    'string',   // human-readable trigger description
    }],
    tools_blocked:      'string[]',
    tools_approved:     'string[]',
    approval_required:  'boolean',
    approval_id:        'string | null',
    override_reason:    'string | null',
  },

  /** Output tab */
  output: {
    status:               "'available' | 'blocked' | 'pending' | 'error'",
    final_text:           'string | null',
    pii_redacted:         'boolean',
    response_latency_ms:  'number',
    scan_verdict:         "'clean' | 'flagged' | null",
    scan_notes:           'string[]',
    /** One entry per tool invocation observed */
    tool_outputs: [{
      tool_name:          'string',
      status:             "'ok' | 'blocked' | 'error' | 'pending_approval'",
      output:             'object',
      error:              'string | null',
      execution_ms:       'number',
      observation:        'object | null',
      sanitization_notes: 'string[]',
      schema_violations:  'string[]',
    }],
    /** Memory operations observed during agent planning */
    memory_ops: [{
      operation:  "'read' | 'write' | 'delete' | 'list'",
      namespace:  'string',
      status:     "'ok' | 'denied' | 'not_found' | 'error'",
      key:        'string',
    }],
  },

  /** Recommendations tab */
  recommendations: [{
    id:        'string (deterministic slug)',
    priority:  "'urgent' | 'high' | 'medium' | 'low'",
    category:  "'policy' | 'security' | 'performance' | 'compliance' | 'operations'",
    title:     'string',
    detail:    'string',
    /** Call-to-action label; null if read-only */
    action:    'string | null',
    /** Which event/condition triggered this recommendation */
    trigger:   'string',
  }],
}

// ─────────────────────────────────────────────────────────────────────────────
// C.  EVENT → UI PANEL MAPPING TABLE
// ─────────────────────────────────────────────────────────────────────────────
//
// For each canonical event_type, documents:
//   affects[]  — which SessionResults sections are updated
//   trace      — whether this event creates a decision_trace entry
//   summary    — prose description of the transformation

export const EVENT_MAP = {
  'session.started': {
    affects:  ['_meta', 'summary', 'decision_trace'],
    trace:    true,
    summary:  'Sets _meta.started_at and _meta.status=running. ' +
              'Captures session_id/correlation_id. ' +
              'Creates trace step: "Prompt received".',
  },
  'session.created': {
    affects:  ['_meta', 'decision_trace'],
    trace:    true,
    summary:  'Sets _meta.status=running. Trace step: "Session created".',
  },
  'session.completed': {
    affects:  ['_meta', 'summary', 'decision_trace'],
    trace:    true,
    summary:  'Sets _meta.status=completed, _meta.completed_at, ' +
              '_meta.duration_ms. Closes summary.execution_ms.',
  },
  'session.blocked': {
    affects:  ['_meta', 'summary', 'policy_impact', 'output', 'decision_trace'],
    trace:    true,
    summary:  'Sets verdict=blocked, output.status=blocked, ' +
              'output.final_text=null. Terminal trace step.',
  },
  'session.failed': {
    affects:  ['_meta', 'summary', 'decision_trace'],
    trace:    true,
    summary:  'Sets _meta.status=failed. Trace step: "Pipeline error".',
  },

  'context.retrieved': {
    affects:  ['summary', 'risk_analysis', 'decision_trace'],
    trace:    true,
    summary:  'summary.context_items = payload.retrieved_contexts.length. ' +
              'risk_analysis dimensions carry retrieval_trust from this event.',
  },

  'risk.enriched': {
    affects:  ['summary', 'risk_analysis', 'decision_trace'],
    trace:    true,
    summary:  'Full risk_analysis population: score, dimensions (prompt_risk, ' +
              'behavioral_risk, identity_risk, memory_risk, retrieval_trust, ' +
              'guard_risk, intent_drift), signals, behavioral_signals, ttps, ' +
              'guard_verdict, guard_score, guard_categories, anomaly_flags. ' +
              'summary.risk_score + risk_level derived from posture_score.',
  },
  'risk.calculated': {
    affects:  ['summary', 'risk_analysis', 'decision_trace'],
    trace:    true,
    summary:  'Orchestrator-side risk: risk_analysis.score from payload.risk_score, ' +
              'tier from payload.risk_tier, signals from payload.signals. ' +
              'No dimension breakdown (orchestrator does not surface sub-scores).',
  },

  'policy.allowed': {
    affects:  ['summary', 'policy_impact', 'decision_trace'],
    trace:    true,
    summary:  'policy_impact.decision=allowed. Adds rules_triggered entry with ' +
              'action=ALLOW. summary.policies_triggered updated.',
  },
  'policy.blocked': {
    affects:  ['summary', 'policy_impact', 'output', 'decision_trace'],
    trace:    true,
    summary:  'policy_impact.decision=blocked. Adds rules_triggered with action=BLOCK, ' +
              'severity=critical. output.status=blocked if no LLM response yet.',
  },
  'policy.escalated': {
    affects:  ['summary', 'policy_impact', 'decision_trace'],
    trace:    true,
    summary:  'policy_impact.decision=escalated, approval_required=true. ' +
              'Adds rules_triggered with action=ESCALATE.',
  },

  'agent.memory.requested': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Appends a memory_op entry (operation, namespace, key) to output.memory_ops. ' +
              'Increments summary.memory_ops counter.',
  },
  'agent.memory.resolved': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Updates the matching memory_op entry (by key) with status from payload.',
  },
  'agent.tool.planned': {
    affects:  ['summary', 'output', 'decision_trace'],
    trace:    true,
    summary:  'Adds tool_name to summary.tools_invoked (if not already present). ' +
              'Creates a pending tool_output entry in output.tool_outputs.',
  },
  'agent.response.ready': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Sets output.final_text=payload.text when payload.blocked=false. ' +
              'Sets output.status=blocked when payload.blocked=true. ' +
              'Captures pii_redacted, response_latency_ms.',
  },

  'tool.invoked': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Updates or creates tool_output entry with status=pending.',
  },
  'tool.approval.required': {
    affects:  ['policy_impact', 'output', 'decision_trace'],
    trace:    true,
    summary:  'policy_impact.approval_required=true, approval_id captured. ' +
              'Marks tool_output as status=pending_approval.',
  },
  'tool.completed': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Completes tool_output entry: status, output, error, execution_ms. ' +
              'If status=blocked: policy_impact.tools_blocked updated.',
  },
  'tool.observed': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Adds observation, sanitization_notes, schema_violations to ' +
              'the matching tool_output entry. ' +
              'schema_violations.length > 0 contributes to recommendations.',
  },

  'output.generated': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Sets output.final_text from payload.response_text or payload.text. ' +
              'Captures output_tokens for decision_trace detail.',
  },
  'output.scanned': {
    affects:  ['output', 'decision_trace'],
    trace:    true,
    summary:  'Sets output.scan_verdict (clean|flagged), scan_notes.',
  },

  'audit.logged': {
    affects:  ['decision_trace'],
    trace:    false,   // audit events do not generate visible trace steps
    summary:  'No UI change; available for future audit trail tab.',
  },

  // ── Garak execution trace (stored in useSimulationState, not Decision Trace)
  'llm.prompt': {
    affects:  [],      // handled by useSimulationState.prompts[]
    trace:    false,
    summary:  'Accumulated into state.prompts[] by useSimulationState reducer.',
  },
  'llm.response': {
    affects:  [],      // handled by useSimulationState.responses[]
    trace:    false,
    summary:  'Accumulated into state.responses[] by useSimulationState reducer.',
  },
  'guard.decision': {
    affects:  [],      // handled by useSimulationState.guardDecisions[]
    trace:    false,
    summary:  'Accumulated into state.guardDecisions[] by useSimulationState reducer.',
  },
  'tool.call': {
    affects:  [],      // handled by useSimulationState.toolCalls[]
    trace:    false,
    summary:  'Accumulated into state.toolCalls[] by useSimulationState reducer.',
  },
  'guard.input': {
    affects:  [],
    trace:    false,
    summary:  'Accumulated into state.guardInputs[] by useSimulationState reducer.',
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

const _RISK_TIER = score =>
  score >= 0.85 ? 'critical' :
  score >= 0.65 ? 'high'     :
  score >= 0.40 ? 'medium'   : 'low'

const _VERDICT_FROM_DECISION = d =>
  d === 'block'    ? 'blocked'   :
  d === 'escalate' ? 'escalated' :
  d === 'allow'    ? 'allowed'   : 'pending'

// Humanise a signal slug: "prompt_injection_detected" → "Prompt Injection Detected"
const _humanise = s =>
  (s ?? '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

const _tsMs = iso => {
  if (!iso) return 0
  const ms = new Date(iso).getTime()
  return isNaN(ms) ? 0 : ms
}

const _fmtTs = iso => {
  const d = new Date(iso)
  if (isNaN(d)) return '--:--:--.---'
  return d.toTimeString().slice(0, 8) + '.' + String(d.getMilliseconds()).padStart(3, '0')
}

// ── Injection / jailbreak / exfiltration signal keyword sets ─────────────────

const _KW_INJECTION    = ['injection', 'override', 'instruction']
const _KW_JAILBREAK    = ['jailbreak', 'dan ', 'roleplay', 'persona', 'bypass']
const _KW_EXFILTRATION = ['exfiltrat', 'data_leak', 'pii', 'external_url', 'ssn', 'credit_card']
const _KW_ROLE_ESC     = ['role_escal', 'privilege', 'admin', 'sudo', 'escalat']

const _matchesAny = (s, kws) => kws.some(kw => s.toLowerCase().includes(kw))

function _deriveAnomalyFlags(signals, behavioralSignals, guardCategories) {
  const all = [...signals, ...behavioralSignals, ...guardCategories].map(s => s.toLowerCase())
  return {
    injection_detected:  all.some(s => _matchesAny(s, _KW_INJECTION)),
    pii_detected:        all.some(s => _matchesAny(s, ['pii', 'ssn', 'credit_card', 'personal_data'])),
    role_escalation:     all.some(s => _matchesAny(s, _KW_ROLE_ESC)),
    data_exfiltration:   all.some(s => _matchesAny(s, _KW_EXFILTRATION)),
    jailbreak_attempt:   all.some(s => _matchesAny(s, _KW_JAILBREAK)),
  }
}

// Confidence: how much guard_score and posture_score agree (0–1)
function _confidence(guardScore, postureScore) {
  if (guardScore === 0 && postureScore === 0) return 0
  const delta = Math.abs(guardScore - postureScore)
  return Math.max(0, 1 - delta * 2)   // 0 agreement → 0 confidence; full agreement → 1
}

// ── Trace step builder ────────────────────────────────────────────────────────

const _TRACE_TITLES = {
  'session.started':          'Prompt received',
  'session.created':          'Session created',
  'session.completed':        'Session completed',
  'session.blocked':          'Request terminated',
  'session.failed':           'Pipeline error',
  'context.retrieved':        'Context retrieved',
  'risk.enriched':            'Risk assessed',
  'risk.calculated':          'Risk scored',
  'policy.allowed':           'Policy evaluated — ALLOW',
  'policy.blocked':           'Policy evaluated — BLOCK',
  'policy.escalated':         'Policy evaluated — ESCALATE',
  'agent.memory.requested':   'Memory read requested',
  'agent.memory.resolved':    'Memory result received',
  'agent.tool.planned':       'Tool invocation planned',
  'agent.response.ready':     'Agent response assembled',
  'tool.invoked':             'Tool dispatched',
  'tool.approval.required':   'Approval gate opened',
  'tool.completed':           'Tool returned result',
  'tool.observed':            'Tool output validated',
  'output.generated':         'LLM response generated',
  'output.scanned':           'Output safety scan',
}

const _TRACE_STATUS = {
  'session.blocked':   'blocked',
  'session.failed':    'critical',
  'policy.blocked':    'critical',
  'policy.escalated':  'warn',
  'policy.allowed':    'ok',
}

function _traceStatus(canonical, payload) {
  if (_TRACE_STATUS[canonical]) return _TRACE_STATUS[canonical]
  if (canonical === 'risk.enriched' || canonical === 'risk.calculated') {
    const score = payload?.posture_score ?? payload?.risk_score ?? 0
    return score >= 0.85 ? 'critical' : score >= 0.5 ? 'warn' : 'ok'
  }
  if (canonical === 'tool.completed') {
    return payload?.status === 'blocked' ? 'critical'
         : payload?.status === 'error'   ? 'warn' : 'ok'
  }
  if (canonical === 'output.scanned') {
    return payload?.verdict === 'flagged' ? 'warn' : 'ok'
  }
  return 'ok'
}

function _traceDecision(canonical, payload) {
  if (canonical === 'policy.allowed')   return 'ALLOW'
  if (canonical === 'policy.blocked')   return 'BLOCK'
  if (canonical === 'policy.escalated') return 'ESCALATE'
  if (canonical === 'tool.completed')   return (payload?.status ?? 'ok').toUpperCase()
  return null
}

function _traceDetail(canonical, payload, riskTierRaw) {
  switch (canonical) {
    case 'session.started': {
      const parts = []
      if (payload?.prompt_len != null) parts.push(`${payload.prompt_len} tokens`)
      if (payload?.agent_id)           parts.push(`agent: ${payload.agent_id}`)
      if (payload?.prompt?.length)     parts.push(`${payload.prompt.length} chars`)
      return parts.join(' · ') || 'Prompt ingested'
    }
    case 'context.retrieved': {
      const n = payload?.retrieved_contexts?.length ?? 0
      const ms = payload?.retrieval_latency_ms ?? 0
      return `${n} context item${n !== 1 ? 's' : ''} · ${ms}ms latency`
    }
    case 'risk.enriched': {
      const s = payload?.posture_score ?? 0
      const t = riskTierRaw ?? _RISK_TIER(s)
      const sigs = (payload?.signals ?? []).filter(x => x && x !== 'none')
      return `Score: ${s.toFixed(3)} · tier: ${t}${sigs.length ? ' · ' + sigs[0] : ''}`
    }
    case 'risk.calculated': {
      const s = payload?.risk_score ?? 0
      const t = payload?.risk_tier ?? _RISK_TIER(s)
      return `Score: ${s.toFixed(3)} · tier: ${t}`
    }
    case 'policy.allowed':
    case 'policy.blocked':
    case 'policy.escalated': {
      const d  = (payload?.decision ?? '').toUpperCase()
      const r  = payload?.reason ?? ''
      const pv = payload?.policy_version ?? ''
      return `${d} — ${r}${pv ? ' [' + pv + ']' : ''}`.trim()
    }
    case 'agent.memory.requested':
      return `${payload?.operation ?? 'read'} · namespace: ${payload?.namespace ?? 'session'} · key: ${payload?.key ?? '?'}`
    case 'agent.memory.resolved':
      return `status: ${payload?.status ?? 'ok'} · namespace: ${payload?.namespace ?? 'session'}`
    case 'agent.tool.planned':
      return `Tool: ${payload?.tool_name ?? '?'} · intent: ${payload?.intent ?? 'general'}`
    case 'tool.invoked':
      return `Tool: ${payload?.tool_name ?? '?'} dispatched to executor`
    case 'tool.approval.required':
      return `Approval required for: ${payload?.tool_name ?? '?'} · id: ${payload?.approval_id ?? '?'}`
    case 'tool.completed': {
      const st = payload?.status ?? 'ok'
      const ms = payload?.execution_ms ?? 0
      return st === 'blocked'
        ? `Tool blocked by executor policy (${payload?.tool_name ?? '?'})`
        : `${payload?.tool_name ?? '?'} · status: ${st} · ${ms}ms`
    }
    case 'tool.observed': {
      const viol = (payload?.schema_violations ?? []).length
      const notes = (payload?.sanitization_notes ?? []).length
      return `${payload?.tool_name ?? '?'} output validated · ${viol} violation${viol !== 1 ? 's' : ''} · ${notes} sanitization note${notes !== 1 ? 's' : ''}`
    }
    case 'agent.response.ready': {
      if (payload?.blocked) return `Response blocked — ${payload?.reason ?? 'policy violation'}`
      const pii = payload?.pii_redacted ? ' · PII redacted' : ''
      return `Response assembled · ${payload?.response_latency_ms ?? 0}ms${pii}`
    }
    case 'output.generated':
      return payload?.output_tokens != null
        ? `${payload.output_tokens} output tokens generated`
        : 'LLM response produced'
    case 'output.scanned':
      return `Scan verdict: ${payload?.verdict ?? 'clean'}` +
             (payload?.notes?.length ? ` · ${payload.notes[0]}` : '')
    case 'session.completed': {
      const dur = payload?.duration_ms ?? 0
      const cnt = payload?.event_count ?? 0
      return `${cnt > 0 ? cnt + ' events · ' : ''}${dur}ms total`
    }
    case 'session.blocked':
      return `Request terminated — ${payload?.reason ?? 'policy violation'}`
    case 'session.failed':
      return `Error: ${payload?.error ?? 'unexpected pipeline failure'}`
    default:
      return payload?.summary ?? canonical
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// H.  RECOMMENDATIONS ENGINE
// ─────────────────────────────────────────────────────────────────────────────
//
// Pure rule-based. Each rule has:
//   test(state)  — predicate on the accumulated state object
//   rec          — the Recommendation to emit when true
//
// Rules are evaluated after all events have been processed.
// The first rule that matches a given "id" wins (no duplicates).

const _REC_RULES = [
  // ── Security — high risk + blocked ─────────────────────────────────────────
  {
    id: 'policy-working-correctly',
    test: s => s.policy.decision === 'blocked' && s.risk.score >= 0.85,
    rec: s => ({
      priority: 'low', category: 'policy',
      title:    'Policy engine correctly blocked this request',
      detail:   `Score ${s.risk.score.toFixed(2)} — well above the block threshold. ` +
                `Policy "${s.policy.reason || s.policy.version}" performed as designed.`,
      action:   null,
      trigger:  'policy.blocked + risk_score ≥ 0.85',
    }),
  },
  {
    id: 'tighten-threshold-blocked',
    test: s => s.policy.decision === 'blocked' && s.risk.score < 0.85 && s.risk.score >= 0.65,
    rec: s => ({
      priority: 'medium', category: 'policy',
      title:    'Review block threshold for this risk tier',
      detail:   `Score ${s.risk.score.toFixed(2)} is in the high tier but below 0.85. ` +
                'Consider lowering the block threshold to 0.70 to catch marginal cases earlier.',
      action:   'Edit Policy',
      trigger:  'policy.blocked + 0.65 ≤ risk_score < 0.85',
    }),
  },
  {
    id: 'upgrade-to-block-flagged',
    test: s => s.policy.decision === 'allowed' && s.risk.score >= 0.65,
    rec: s => ({
      priority: 'high', category: 'policy',
      title:    'Consider upgrading policy action to BLOCK',
      detail:   `Score ${s.risk.score.toFixed(2)} exceeds the high-risk threshold but the ` +
                `policy decision was ALLOW. Upgrade to BLOCK mode to prevent this attack class.`,
      action:   'Edit Policy',
      trigger:  'policy.allowed + risk_score ≥ 0.65',
    }),
  },
  {
    id: 'lower-flag-threshold',
    test: s => s.policy.decision === 'allowed' && s.risk.score >= 0.4 && s.risk.score < 0.65,
    rec: s => ({
      priority: 'medium', category: 'policy',
      title:    'Lower the flagging threshold',
      detail:   `Score ${s.risk.score.toFixed(2)} is in the medium tier but passed. ` +
                'Closing the gap between flag and block thresholds reduces blind spots.',
      action:   'Edit Policy',
      trigger:  'policy.allowed + 0.40 ≤ risk_score < 0.65',
    }),
  },

  // ── Injection / jailbreak signals ──────────────────────────────────────────
  {
    id: 'injection-detected-signal',
    test: s => s.anomalyFlags.injection_detected,
    rec: () => ({
      priority: 'urgent', category: 'security',
      title:    'Prompt injection pattern detected',
      detail:   'Instruction-override language found in the prompt. ' +
                'Ensure Prompt-Guard policy is in BLOCK mode with threshold ≤ 0.85.',
      action:   'Review Policy',
      trigger:  'anomaly_flags.injection_detected',
    }),
  },
  {
    id: 'jailbreak-detected-signal',
    test: s => s.anomalyFlags.jailbreak_attempt,
    rec: () => ({
      priority: 'urgent', category: 'security',
      title:    'Jailbreak attempt detected',
      detail:   'Roleplay or persona-override framing detected. ' +
                'Verify your jailbreak signature library is current and add semantic similarity detection.',
      action:   'Add Policy',
      trigger:  'anomaly_flags.jailbreak_attempt',
    }),
  },
  {
    id: 'pii-exfiltration-detected',
    test: s => s.anomalyFlags.data_exfiltration || s.anomalyFlags.pii_detected,
    rec: () => ({
      priority: 'urgent', category: 'compliance',
      title:    'Data exfiltration or PII leak attempt detected',
      detail:   'The request attempted to reference or transmit personally-identifiable data. ' +
                'Confirm PII-Detect policy is in BLOCK + REDACT mode and review data governance rules.',
      action:   'Edit Policy',
      trigger:  'anomaly_flags.data_exfiltration || anomaly_flags.pii_detected',
    }),
  },
  {
    id: 'role-escalation-detected',
    test: s => s.anomalyFlags.role_escalation,
    rec: () => ({
      priority: 'high', category: 'security',
      title:    'Privilege / role escalation attempt detected',
      detail:   'The prompt attempted to reference elevated privileges or admin contexts. ' +
                'Tighten identity risk thresholds and audit agent permission scopes.',
      action:   'Review Permissions',
      trigger:  'anomaly_flags.role_escalation',
    }),
  },

  // ── Tool execution ─────────────────────────────────────────────────────────
  {
    id: 'tool-blocked-by-opa',
    test: s => s.toolsBlocked.length > 0,
    rec: s => ({
      priority: 'high', category: 'security',
      title:    `Tool blocked: ${s.toolsBlocked[0]}`,
      detail:   `The executor rejected the tool call(s): ${s.toolsBlocked.join(', ')}. ` +
                'Review OPA tool-scope policies and confirm agent permissions are correctly scoped.',
      action:   'Review Tool Permissions',
      trigger:  'tool.completed with status=blocked',
    }),
  },
  {
    id: 'tool-schema-violations',
    test: s => s.schemaViolations > 0,
    rec: s => ({
      priority: 'medium', category: 'operations',
      title:    'Tool output schema violations detected',
      detail:   `${s.schemaViolations} schema violation${s.schemaViolations !== 1 ? 's' : ''} ` +
                'found during tool-parser validation. ' +
                'Update the tool output schema or sanitization rules to prevent data corruption.',
      action:   'Review Tool Schema',
      trigger:  'tool.observed with schema_violations.length > 0',
    }),
  },
  {
    id: 'approval-gate-active',
    test: s => s.policy.approvalRequired,
    rec: s => ({
      priority: 'medium', category: 'policy',
      title:    'Human-in-the-loop approval gate triggered',
      detail:   `Approval ID: ${s.policy.approvalId ?? 'unknown'}. ` +
                'If approvals are always granted, consider whether the escalation threshold is too sensitive.',
      action:   'Review Escalation Rules',
      trigger:  'tool.approval.required',
    }),
  },

  // ── Memory operations ──────────────────────────────────────────────────────
  {
    id: 'memory-denied',
    test: s => s.memoryDenied,
    rec: () => ({
      priority: 'high', category: 'security',
      title:    'Memory access denied during agent planning',
      detail:   'The memory service denied at least one read/write request. ' +
                'Review memory namespace ACLs and agent identity risk configuration.',
      action:   'Review Memory Policy',
      trigger:  'agent.memory.resolved with status=denied',
    }),
  },

  // ── High behavioral risk ───────────────────────────────────────────────────
  {
    id: 'high-behavioral-risk',
    test: s => (s.dimensions.behavioral_risk ?? 0) >= 0.65,   // high tier threshold
    rec: s => ({
      priority: 'high', category: 'security',
      title:    'Elevated behavioral risk detected',
      detail:   `Behavioral risk score: ${s.dimensions.behavioral_risk.toFixed(2)}. ` +
                'This user or agent has exhibited anomalous behaviour patterns. ' +
                'Review session history and consider a temporary rate-limit or freeze.',
      action:   'Investigate Behavior',
      trigger:  'risk.enriched with behavioral_risk ≥ 0.65',
    }),
  },

  // ── Drift ──────────────────────────────────────────────────────────────────
  {
    id: 'intent-drift-high',
    test: s => (s.dimensions.intent_drift ?? 0) >= 0.6,
    rec: s => ({
      priority: 'medium', category: 'security',
      title:    'High intent drift detected',
      detail:   `Intent drift score: ${s.dimensions.intent_drift.toFixed(2)}. ` +
                'The prompt deviates significantly from the agent\'s expected intent profile. ' +
                'Enable semantic anomaly detection for this agent identity.',
      action:   'Add Policy',
      trigger:  'risk.enriched with intent_drift ≥ 0.60',
    }),
  },

  // ── Output safety ──────────────────────────────────────────────────────────
  {
    id: 'output-flagged-by-scan',
    test: s => s.outputScanVerdict === 'flagged',
    rec: () => ({
      priority: 'high', category: 'compliance',
      title:    'Output flagged by safety scan',
      detail:   'The LLM response was flagged during output scanning. ' +
                'Review output validation policy thresholds and consider adding PII redaction.',
      action:   'Review Output Policy',
      trigger:  'output.scanned with verdict=flagged',
    }),
  },
  {
    id: 'pii-redacted-in-output',
    test: s => s.piiRedacted,
    rec: () => ({
      priority: 'low', category: 'compliance',
      title:    'PII automatically redacted from response',
      detail:   'The output contained personally-identifiable information that was redacted before delivery. ' +
                'Confirm the redaction policy covers all relevant PII categories for your compliance framework.',
      action:   null,
      trigger:  'agent.response.ready with pii_redacted=true',
    }),
  },

  // ── Clean result ───────────────────────────────────────────────────────────
  {
    id: 'no-action-needed',
    test: s => s.policy.decision === 'allowed' && s.risk.score < 0.4
            && !s.anomalyFlags.injection_detected
            && !s.anomalyFlags.jailbreak_attempt
            && s.toolsBlocked.length === 0,
    rec: () => ({
      priority: 'low', category: 'operations',
      title:    'No action needed',
      detail:   'All policies evaluated and passed. No adversarial signals detected. ' +
                'Request processed normally.',
      action:   null,
      trigger:  'policy.allowed + risk_score < 0.40 + no anomaly flags',
    }),
  },
]

const _PRIORITY_WEIGHT = { urgent: 4, high: 3, medium: 2, low: 1 }

/**
 * Build recommendations from the accumulated pipeline state.
 * Returns a stable-ordered array (urgent → high → medium → low).
 * Each rule fires at most once per session.
 *
 * @param {object} state  Internal accumulator passed after all events processed.
 * @returns {Array<Recommendation>}
 */
function _buildRecommendations(state) {
  const seen = new Set()
  const recs = []

  for (const rule of _REC_RULES) {
    if (seen.has(rule.id)) continue
    try {
      if (rule.test(state)) {
        const rec = rule.rec(state)
        recs.push({ id: rule.id, ...rec })
        seen.add(rule.id)
      }
    } catch {
      // Rule evaluation should never throw, but guard anyway
    }
  }

  recs.sort((a, b) =>
    (_PRIORITY_WEIGHT[b.priority] ?? 0) - (_PRIORITY_WEIGHT[a.priority] ?? 0)
  )

  return recs
}

// ─────────────────────────────────────────────────────────────────────────────
// I + J.  transformSessionEvents — pure, streaming-safe
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Transform an array of raw WsEvent objects into a structured SessionResults.
 *
 * @param {Array<{
 *   session_id:     string,
 *   correlation_id: string,
 *   event_type:     string,
 *   source_service: string,
 *   timestamp:      string,
 *   payload:        object,
 * }>} events  Raw WsEvent objects, any order, any subset of the full stream.
 *
 * @returns {SessionResults}  Always a complete, valid object.
 *                             Missing data is represented as null / [] / 0.
 *                             partial=true when pipeline has not yet completed.
 */
export function transformSessionEvents(events) {
  // ── 0. Sort input by timestamp, deduplicate by event_type ──────────────────
  //    (event_type is unique per pipeline step; earlier events win on dedup)
  const seen = new Set()
  const sorted = [...events]
    .sort((a, b) => _tsMs(a.timestamp) - _tsMs(b.timestamp))
    .filter(e => {
      const key = canonicalise(e)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })

  // ── 1. Accumulated state (mutable within this function only) ───────────────
  const state = {
    sessionId:      events[0]?.session_id      ?? '',
    correlationId:  events[0]?.correlation_id  ?? '',
    serviceChain:   [],

    // _meta
    startedAt:    null,
    completedAt:  null,
    durationMs:   null,
    status:       'pending',

    // Risk
    risk: {
      score: 0, tier: 'low',
      dimensions: {
        prompt_risk: 0, behavioral_risk: 0, identity_risk: 0,
        memory_risk: 0, retrieval_trust: 1, guard_risk: 0, intent_drift: 0,
      },
      signals: [], behavioralSignals: [], ttps: [],
      guardVerdict: 'unchecked', guardScore: 0, guardCategories: [],
    },

    // Policy
    policy: {
      decision: 'pending', reason: '', version: '',
      rulesTriggered: [],
      approvalRequired: false, approvalId: null, overrideReason: null,
    },

    // Tools
    toolOutputs:  {},    // tool_name → tool_output object (last-write-wins)
    toolsBlocked: [],
    toolsApproved: [],
    schemaViolations: 0,

    // Memory
    memoryOps:   {},    // key → { operation, namespace, status, key }
    memoryDenied: false,
    memoryOpCount: 0,

    // Output
    finalText:          null,
    piiRedacted:        false,
    responseLattencyMs: 0,
    outputScanVerdict:  null,
    outputScanNotes:    [],
    outputBlocked:      false,

    // Context
    contextItems:  0,

    // Anomaly flags (derived after risk events)
    anomalyFlags:  {
      injection_detected:  false,
      pii_detected:        false,
      role_escalation:     false,
      data_exfiltration:   false,
      jailbreak_attempt:   false,
    },

    // Dimensions shortcut (for recommendation rules)
    dimensions: {
      behavioral_risk: 0, intent_drift: 0,
    },

    // Trace
    traceSteps: [],
  }

  // ── 2. Process events one by one ───────────────────────────────────────────
  let prevTimestampMs = 0

  for (const rawEvent of sorted) {
    const canonical = canonicalise(rawEvent)
    const p = rawEvent.payload ?? {}
    const svc = rawEvent.source_service ?? ''

    if (svc && !state.serviceChain.includes(svc)) {
      state.serviceChain.push(svc)
    }

    // Compute latency from previous step
    const thisMs = _tsMs(rawEvent.timestamp)
    const latencyMs = prevTimestampMs > 0 && thisMs > 0
      ? Math.max(0, thisMs - prevTimestampMs) : null
    prevTimestampMs = thisMs || prevTimestampMs

    // ── Per-canonical-type processing ────────────────────────────────────────

    switch (canonical) {

      case 'session.started':
        state.startedAt = rawEvent.timestamp
        state.status    = 'running'
        break

      case 'session.created':
        state.status = 'running'
        break

      case 'session.completed':
        state.status      = 'completed'
        state.completedAt = rawEvent.timestamp
        state.durationMs  = p.duration_ms ??
          (state.startedAt
            ? Math.max(0, _tsMs(rawEvent.timestamp) - _tsMs(state.startedAt))
            : null)
        break

      case 'session.blocked':
        state.status       = 'blocked'
        state.completedAt  = rawEvent.timestamp
        state.outputBlocked = true
        state.durationMs   = state.startedAt
          ? Math.max(0, _tsMs(rawEvent.timestamp) - _tsMs(state.startedAt))
          : null
        break

      case 'session.failed':
        state.status = 'failed'
        break

      case 'context.retrieved':
        state.contextItems = (p.retrieved_contexts ?? []).length || state.contextItems
        // retrieval_trust also available here
        if (p.retrieval_trust != null) state.risk.dimensions.retrieval_trust = p.retrieval_trust
        break

      case 'risk.enriched': {
        // Full multi-dimensional risk from PostureEnrichedEvent
        const s = p.posture_score ?? 0
        state.risk.score  = s
        state.risk.tier   = _RISK_TIER(s)
        state.risk.dimensions = {
          prompt_risk:     p.prompt_risk      ?? 0,
          behavioral_risk: p.behavioral_risk  ?? 0,
          identity_risk:   p.identity_risk    ?? 0,
          memory_risk:     p.memory_risk      ?? 0,
          retrieval_trust: p.retrieval_trust  ?? 1,
          guard_risk:      p.guard_risk       ?? 0,
          intent_drift:    p.intent_drift_score ?? 0,
        }
        state.risk.signals           = p.signals          ?? []
        state.risk.behavioralSignals = p.behavioral_signals ?? []
        state.risk.ttps              = p.cep_ttps          ?? []
        state.risk.guardVerdict      = p.guard_verdict     ?? 'unchecked'
        state.risk.guardScore        = p.guard_score       ?? 0
        state.risk.guardCategories   = p.guard_categories  ?? []
        state.anomalyFlags = _deriveAnomalyFlags(
          state.risk.signals, state.risk.behavioralSignals, state.risk.guardCategories
        )
        state.dimensions.behavioral_risk = p.behavioral_risk ?? 0
        state.dimensions.intent_drift    = p.intent_drift_score ?? 0
        break
      }

      case 'risk.calculated': {
        // Orchestrator-side risk (less granular, no dimension breakdown)
        const s = p.risk_score ?? 0
        // Only overwrite if this score is higher (posture.enriched is authoritative when both present)
        if (s > state.risk.score) {
          state.risk.score = s
          state.risk.tier  = p.risk_tier ?? _RISK_TIER(s)
        }
        if ((p.signals ?? []).length > 0) {
          state.risk.signals = [...new Set([...state.risk.signals, ...p.signals])]
        }
        break
      }

      case 'policy.allowed':
      case 'policy.blocked':
      case 'policy.escalated': {
        const decision = canonical.split('.')[1]   // 'allowed' | 'blocked' | 'escalated'
        state.policy.decision  = decision
        state.policy.reason    = p.reason         ?? ''
        state.policy.version   = p.policy_version ?? ''

        const actionMap = { allowed: 'ALLOW', blocked: 'BLOCK', escalated: 'ESCALATE' }
        const sevMap    = { allowed: 'neutral', blocked: 'critical', escalated: 'high' }

        state.policy.rulesTriggered.push({
          rule_id:   p.policy_version ?? canonical,
          rule_name: `Policy Engine${p.policy_version ? ' · ' + p.policy_version : ''}`,
          action:    actionMap[decision] ?? 'ALLOW',
          severity:  sevMap[decision]   ?? 'neutral',
          trigger:   p.reason ?? 'Policy evaluation complete',
        })

        // Signals also produce policy impact rows
        ;(p.signals ?? state.risk.signals).forEach(sig => {
          if (!sig || sig === 'none') return
          state.policy.rulesTriggered.push({
            rule_id:  sig,
            rule_name: _humanise(sig),
            action:   actionMap[decision] ?? 'ALLOW',
            severity: sevMap[decision]   ?? 'neutral',
            trigger:  'Signal detected during risk assessment',
          })
        })

        if (canonical === 'policy.blocked') state.outputBlocked = true
        break
      }

      case 'agent.memory.requested': {
        const key = p.key ?? `mem-${Object.keys(state.memoryOps).length}`
        state.memoryOps[key] = {
          operation: p.operation ?? 'read',
          namespace: p.namespace ?? 'session',
          status:    'pending',
          key,
        }
        state.memoryOpCount++
        break
      }

      case 'agent.memory.resolved': {
        const key = p.key ?? Object.keys(state.memoryOps).at(-1) ?? 'unknown'
        if (state.memoryOps[key]) {
          state.memoryOps[key].status = p.status ?? 'ok'
        } else {
          state.memoryOps[key] = {
            operation: p.operation ?? 'read',
            namespace: p.namespace ?? 'session',
            status: p.status ?? 'ok',
            key,
          }
        }
        if (p.status === 'denied') state.memoryDenied = true
        break
      }

      case 'agent.tool.planned': {
        const name = p.tool_name ?? 'unknown'
        if (!state.toolOutputs[name]) {
          state.toolOutputs[name] = {
            tool_name: name,
            status:    'pending',
            output:    {},
            error:     null,
            execution_ms:       0,
            observation:        null,
            sanitization_notes: [],
            schema_violations:  [],
          }
        }
        break
      }

      case 'tool.approval.required': {
        state.policy.approvalRequired = true
        state.policy.approvalId       = p.approval_id ?? null
        const name = p.tool_name ?? 'unknown'
        if (state.toolOutputs[name]) {
          state.toolOutputs[name].status = 'pending_approval'
        }
        break
      }

      case 'tool.completed': {
        const name = p.tool_name ?? 'unknown'
        const existing = state.toolOutputs[name] ?? {
          tool_name: name, observation: null, sanitization_notes: [], schema_violations: [],
        }
        state.toolOutputs[name] = {
          ...existing,
          status:       p.status       ?? 'ok',
          output:       p.output       ?? {},
          error:        p.error        ?? null,
          execution_ms: p.execution_ms ?? 0,
        }
        if (p.status === 'blocked' && !state.toolsBlocked.includes(name)) {
          state.toolsBlocked.push(name)
        } else if (p.status === 'ok' && !state.toolsApproved.includes(name)) {
          state.toolsApproved.push(name)
        }
        break
      }

      case 'tool.observed': {
        const name = p.tool_name ?? 'unknown'
        const existing = state.toolOutputs[name] ?? {
          tool_name: name, status: 'ok', output: {}, error: null, execution_ms: 0,
        }
        state.toolOutputs[name] = {
          ...existing,
          observation:        p.observation         ?? null,
          sanitization_notes: p.sanitization_notes  ?? [],
          schema_violations:  p.schema_violations   ?? [],
        }
        state.schemaViolations += (p.schema_violations ?? []).length
        break
      }

      case 'agent.response.ready': {
        if (!p.blocked) {
          state.finalText          = p.text ?? null
          state.piiRedacted        = p.pii_redacted       ?? false
          state.responseLattencyMs = p.response_latency_ms ?? 0
        } else {
          state.outputBlocked = true
        }
        break
      }

      case 'output.generated': {
        // Orchestrator path — may complement or replace agent.response.ready
        const text = p.response_text ?? p.text ?? null
        if (text && !state.finalText) state.finalText = text
        break
      }

      case 'output.scanned': {
        state.outputScanVerdict = p.verdict ?? 'clean'
        state.outputScanNotes   = p.notes ?? p.output_scan_notes ?? []
        if (state.outputScanVerdict === 'flagged') state.outputBlocked = true
        break
      }

      // audit.logged — no UI state change
      default:
        break
    }

    // ── Build trace step ─────────────────────────────────────────────────────
    if (EVENT_MAP[canonical]?.trace !== false) {
      state.traceSteps.push({
        step:       state.traceSteps.length + 1,
        event_type: canonical,
        title:      _TRACE_TITLES[canonical] ?? canonical,
        source:     rawEvent.source_service ?? '',
        status:     _traceStatus(canonical, p),
        decision:   _traceDecision(canonical, p),
        detail:     _traceDetail(canonical, p, state.risk.tier),
        timestamp:  rawEvent.timestamp,
        ts:         _fmtTs(rawEvent.timestamp),   // pre-formatted HH:MM:SS.mmm
        latency_ms: latencyMs,
      })
    }
  }

  // ── 3. Derive partial flag ─────────────────────────────────────────────────
  const terminal = new Set(['completed', 'blocked', 'failed'])
  const partial  = !terminal.has(state.status)

  // ── 4. Assemble summary ───────────────────────────────────────────────────
  const riskScorePct = Math.min(100, Math.round(state.risk.score * 100))
  const riskLevel    = {
    low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical',
  }[state.risk.tier] ?? 'Low'

  const verdictFromStatus = s =>
    s === 'blocked'   ? 'blocked'   :
    s === 'completed' ? (state.policy.decision === 'allowed' ? 'allowed' : state.policy.decision) :
    s === 'failed'    ? 'blocked'   : 'pending'

  const verdict = state.policy.decision !== 'pending'
    ? state.policy.decision
    : verdictFromStatus(state.status)

  const verdictReason =
    state.policy.reason ||
    (verdict === 'blocked'   ? 'Request blocked by policy engine.' :
     verdict === 'allowed'   ? 'All policies passed.' :
     verdict === 'escalated' ? 'Escalated for human review.' :
     'Evaluation in progress.')

  const executionMs = state.durationMs ??
    (state.startedAt && state.completedAt
      ? Math.max(0, _tsMs(state.completedAt) - _tsMs(state.startedAt))
      : 0)

  const policiesTriggered = state.policy.rulesTriggered
    .filter((r, i, arr) => arr.findIndex(x => x.rule_id === r.rule_id) === i)
    .map(r => r.rule_name)

  // ── 5. Assemble risk_analysis ──────────────────────────────────────────────
  const conf = _confidence(state.risk.guardScore, state.risk.score)
  const af   = state.anomalyFlags

  const techniques = [
    ...state.risk.signals,
    ...state.risk.behavioralSignals,
  ].filter((s, i, a) => s && s !== 'none' && a.indexOf(s) === i)

  const explanation =
    `Risk score ${state.risk.score.toFixed(3)} (${riskLevel} tier). ` + (
    verdict === 'blocked'
      ? `Policy engine blocked: "${state.policy.reason || 'policy violation'}". ` +
        (techniques.length ? `Signals: ${techniques.slice(0, 3).join(', ')}.` : '')
    : verdict === 'escalated'
      ? `Request escalated for review. ${techniques.length ? 'Active signals: ' + techniques.join(', ') + '.' : ''}`
    : verdict === 'allowed'
      ? 'All policies passed. No adversarial signals breached threshold.'
    : 'Evaluation in progress — partial data.'
    )

  // ── 6. Recommendations ────────────────────────────────────────────────────
  const recommendations = _buildRecommendations(state)

  // ── 7. Output tab ─────────────────────────────────────────────────────────
  const outputStatus =
    state.outputBlocked && !state.finalText ? 'blocked' :
    state.finalText                         ? 'available' :
    partial                                 ? 'pending'   : 'blocked'

  const toolOutputsArr = Object.values(state.toolOutputs)

  // ── 8. Assemble final SessionResults ──────────────────────────────────────
  return {
    _meta: {
      session_id:    state.sessionId,
      correlation_id: state.correlationId,
      status:        state.status,
      started_at:    state.startedAt,
      completed_at:  state.completedAt,
      duration_ms:   state.durationMs,
      service_chain: state.serviceChain,
      partial,
    },

    summary: {
      verdict,
      verdict_reason:     verdictReason,
      risk_score:         riskScorePct,
      risk_level:         riskLevel,
      execution_ms:       executionMs,
      policies_triggered: policiesTriggered,
      tools_invoked:      Object.keys(state.toolOutputs),
      memory_ops:         state.memoryOpCount,
      context_items:      state.contextItems,
    },

    decision_trace: state.traceSteps,

    risk_analysis: {
      score:             state.risk.score,
      score_pct:         riskScorePct,
      tier:              state.risk.tier,
      dimensions:        state.risk.dimensions,
      signals:           state.risk.signals,
      behavioral_signals: state.risk.behavioralSignals,
      ttps:              state.risk.ttps,
      guard_verdict:     state.risk.guardVerdict,
      guard_score:       state.risk.guardScore,
      guard_categories:  state.risk.guardCategories,
      anomaly_flags:     state.anomalyFlags,
      confidence:        conf,
      explanation,
    },

    policy_impact: {
      decision:         state.policy.decision,
      reason:           state.policy.reason,
      policy_version:   state.policy.version,
      rules_triggered:  state.policy.rulesTriggered,
      tools_blocked:    state.toolsBlocked,
      tools_approved:   state.toolsApproved,
      approval_required: state.policy.approvalRequired,
      approval_id:      state.policy.approvalId,
      override_reason:  state.policy.overrideReason,
    },

    output: {
      status:              outputStatus,
      final_text:          state.finalText,
      pii_redacted:        state.piiRedacted,
      response_latency_ms: state.responseLattencyMs,
      scan_verdict:        state.outputScanVerdict,
      scan_notes:          state.outputScanNotes,
      tool_outputs:        toolOutputsArr,
      memory_ops:          Object.values(state.memoryOps),
    },

    recommendations,
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// K.  EXAMPLE INPUT + OUTPUT
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Example A — blocked prompt injection (full stream, 7 events)
 */
export const EXAMPLE_EVENTS_BLOCKED = [
  {
    session_id:     'sess-abc-001',
    correlation_id: 'corr-xyz-001',
    event_type:     'raw_event',          // → session.started
    source_service: 'api',
    timestamp:      '2024-01-15T09:14:03.002Z',
    payload:        { prompt_len: 23, agent_id: 'FinanceAssistant-v2' },
  },
  {
    session_id:     'sess-abc-001',
    correlation_id: 'corr-xyz-001',
    event_type:     'context.retrieved',
    source_service: 'retrieval_gateway',
    timestamp:      '2024-01-15T09:14:03.008Z',
    payload:        { retrieved_contexts: [{ id: 'ctx-1', text: '...' }], retrieval_latency_ms: 6 },
  },
  {
    session_id:     'sess-abc-001',
    correlation_id: 'corr-xyz-001',
    event_type:     'posture.enriched',   // → risk.enriched
    source_service: 'processor',
    timestamp:      '2024-01-15T09:14:03.014Z',
    payload:        {
      posture_score:     0.94,
      prompt_risk:       0.97,
      behavioral_risk:   0.30,
      identity_risk:     0.10,
      memory_risk:       0.05,
      retrieval_trust:   0.95,
      guard_risk:        0.85,
      intent_drift_score: 0.20,
      signals:           ['prompt_injection_detected', 'instruction_override_attempt'],
      behavioral_signals: [],
      cep_ttps:          ['T1055', 'T1059'],
      guard_verdict:     'block',
      guard_score:       0.97,
      guard_categories:  ['injection'],
    },
  },
  {
    session_id:     'sess-abc-001',
    correlation_id: 'corr-xyz-001',
    event_type:     'policy.decision',    // → policy.blocked (decision=block)
    source_service: 'policy_decider',
    timestamp:      '2024-01-15T09:14:03.018Z',
    payload:        {
      decision:       'block',
      reason:         'prompt_injection_detected score=0.97 > threshold 0.85',
      policy_version: 'Prompt-Guard-v3',
      signals:        ['prompt_injection_detected'],
    },
  },
  {
    session_id:     'sess-abc-001',
    correlation_id: 'corr-xyz-001',
    event_type:     'session.blocked',
    source_service: 'api',
    timestamp:      '2024-01-15T09:14:03.022Z',
    payload:        { reason: 'prompt_injection_detected score=0.97 > threshold 0.85' },
  },
]

/**
 * Example B — allowed request with tool use (full stream, 11 events)
 */
export const EXAMPLE_EVENTS_ALLOWED_TOOL = [
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'raw_event', source_service: 'api',
    timestamp: '2024-01-15T09:15:00.000Z',
    payload: { prompt_len: 12, agent_id: 'CustomerSupport-GPT' },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'context.retrieved', source_service: 'retrieval_gateway',
    timestamp: '2024-01-15T09:15:00.010Z',
    payload: { retrieved_contexts: [{}, {}, {}], retrieval_latency_ms: 10 },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'posture.enriched', source_service: 'processor',
    timestamp: '2024-01-15T09:15:00.018Z',
    payload: {
      posture_score: 0.12, prompt_risk: 0.08, behavioral_risk: 0.15,
      identity_risk: 0.05, memory_risk: 0.02, retrieval_trust: 0.98,
      guard_risk: 0.10, intent_drift_score: 0.06,
      signals: [], behavioral_signals: [], cep_ttps: [],
      guard_verdict: 'allow', guard_score: 0.12, guard_categories: [],
    },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'policy.decision', source_service: 'policy_decider',
    timestamp: '2024-01-15T09:15:00.024Z',
    payload: { decision: 'allow', reason: 'all policies passed', policy_version: 'PG-v3+PII-v2' },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'memory.request', source_service: 'agent',
    timestamp: '2024-01-15T09:15:00.030Z',
    payload: { operation: 'read', namespace: 'session', key: 'user_prefs' },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'memory.result', source_service: 'memory_service',
    timestamp: '2024-01-15T09:15:00.035Z',
    payload: { operation: 'read', namespace: 'session', key: 'user_prefs', status: 'ok' },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'tool.request', source_service: 'agent',
    timestamp: '2024-01-15T09:15:00.040Z',
    payload: { tool_name: 'calendar_read', intent: 'read_only' },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'tool.result', source_service: 'executor',
    timestamp: '2024-01-15T09:15:00.060Z',
    payload: {
      tool_name: 'calendar_read', status: 'ok',
      output: { events: [{ id: 'evt-001', title: 'Budget Review' }] },
      execution_ms: 20,
    },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'tool.observation', source_service: 'tool_parser',
    timestamp: '2024-01-15T09:15:00.065Z',
    payload: {
      tool_name: 'calendar_read',
      observation: { verified: true },
      sanitization_notes: [],
      schema_violations: [],
    },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'final.response', source_service: 'agent',
    timestamp: '2024-01-15T09:15:00.100Z',
    payload: {
      text: 'You have a Budget Review meeting today. Is there anything else I can help with?',
      blocked: false, pii_redacted: false, response_latency_ms: 60,
    },
  },
  {
    session_id: 'sess-def-002', correlation_id: 'corr-uvw-002',
    event_type: 'session.completed', source_service: 'api',
    timestamp: '2024-01-15T09:15:00.110Z',
    payload: { duration_ms: 110, event_count: 10 },
  },
]

/**
 * Example C — partial stream (only 2 events arrived so far)
 * Demonstrates streaming-safe partial results.
 */
export const EXAMPLE_EVENTS_PARTIAL = [
  {
    session_id: 'sess-ghi-003', correlation_id: 'corr-rst-003',
    event_type: 'raw_event', source_service: 'api',
    timestamp: '2024-01-15T09:16:00.000Z',
    payload: { prompt_len: 31, agent_id: 'ThreatHunter-AI' },
  },
  {
    session_id: 'sess-ghi-003', correlation_id: 'corr-rst-003',
    event_type: 'posture.enriched', source_service: 'processor',
    timestamp: '2024-01-15T09:16:00.012Z',
    payload: {
      posture_score: 0.72, prompt_risk: 0.78, behavioral_risk: 0.65,
      identity_risk: 0.15, memory_risk: 0.08, retrieval_trust: 0.90,
      guard_risk: 0.55, intent_drift_score: 0.61,
      signals: ['role_escalation_attempt'],
      behavioral_signals: ['anomalous_request_rate'],
      cep_ttps: ['T1055'],
      guard_verdict: 'flag', guard_score: 0.72, guard_categories: ['privilege_abuse'],
    },
  },
  // — policy decision and session outcome not yet received —
]
