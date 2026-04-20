// ui/src/simulation/types.ts   (v2.1 — correctness audit)
// ───────────────────────────────────────────────────────
// Frontend mirror of platform_shared/simulation/attempts.py.
//
// v2.1 changes
// ────────────
//   * `sequence` is REMOVED from Attempt — it lives only on the envelope.
//   * `model_invoked` and `probe_raw` added to Attempt.
//   * `SimulationProbeCompletedEvent` added (`probe_duration_ms` etc.).
//   * `simulation.probe_started` now carries `probe_raw`.
//   * Envelope `sequence` is `number | null` — the transport may send
//     out-of-band frames (e.g. preconnect-buffer-overflow warning) with
//     `sequence: null`.  Orchestrator-originated frames are always numeric.
//   * `simulation.warning` codes extended to cover every code the backend
//     emits today (see `attempts.py` and `simulation_ws.py`).
//
// These types define the WIRE contract with the backend.  Any drift here
// will manifest as runtime validation errors in the ingestion layer
// (store.ingest).  Keep this file the SINGLE source of type truth for
// every tab in the Simulation Lab.

export type AttemptPhase =
  | 'recon'
  | 'exploit'
  | 'evasion'
  | 'execution'
  | 'exfiltration'
  | 'other'

export type AttemptResult = 'blocked' | 'allowed' | 'error'

export type AttemptStatus = 'running' | 'completed' | 'failed'

export type GuardAction = 'block' | 'allow' | 'review' | 'error'

export interface GuardDecision {
  action:      GuardAction
  score:       number    // 0..1
  threshold:   number    // 0..1
  policy_id:   string    // never empty; "__unresolved__:<probe>" if the
                         //               pipeline omitted real metadata
  policy_name: string    // never empty
  reason:      string
}

export interface AttemptMeta {
  garak_probe_class: string
  garak_profile:     string
  detector?:         string
  // open-ended — extra keys tolerated
  [k: string]: unknown
}

export interface Attempt {
  attempt_id:       string   // uuid — the canonical key for dedup
  session_id:       string   // uuid

  probe:            string   // canonical id (registry-normalised)
  probe_raw:        string   // operator-supplied string BEFORE normalisation
  category:         string
  phase:            AttemptPhase

  started_at:       string   // ISO-8601
  completed_at:     string | null
  latency_ms:       number | null

  prompt_raw:       string
  prompt_sanitized: string
  guard_input:      string
  model_response:   string | null

  guard_decision:   GuardDecision | null
  result:           AttemptResult
  risk_score:       number     // 0..100

  status:           AttemptStatus
  error:            string | null
  model_invoked:    boolean    // True IFF the pipeline reached the model
  meta:             AttemptMeta
}

export interface SimulationSummary {
  probe_count:        number
  attempt_count:      number
  blocked_count:      number
  allowed_count:      number
  error_count:        number
  in_progress_count:  number
  peak_risk_score:    number
  elapsed_ms:         number
  triggered_policies: string[]
}

// ── Event envelope ──────────────────────────────────────────────────────────

interface BaseEvent<T extends string, D> {
  type:       T
  session_id: string
  // Orchestrator-emitted frames carry a non-negative integer here.
  // The transport may emit out-of-band synthetic frames (e.g. the
  // preconnect-buffer-overflow warning) with `sequence: null`.  Treat
  // null as "not part of the orchestrator's sequence space".
  sequence:   number | null
  timestamp:  string
  data:       D
}

export type SimulationStartedEvent = BaseEvent<
  'simulation.started',
  {
    probes:         string[]
    profile:        string
    execution_mode: string
    max_attempts:   number
  }
>

export type SimulationProbeStartedEvent = BaseEvent<
  'simulation.probe_started',
  {
    probe:     string
    probe_raw: string
    category:  string
    phase:     AttemptPhase
    index:     number
    total:     number
  }
>

export type SimulationProbeCompletedEvent = BaseEvent<
  'simulation.probe_completed',
  {
    probe:              string
    probe_raw:          string
    category:           string
    phase:              AttemptPhase
    index:              number
    total:              number
    attempt_count:      number
    blocked_count:      number
    allowed_count:      number
    error_count:        number
    probe_duration_ms:  number
  }
>

export type SimulationAttemptEvent   = BaseEvent<'simulation.attempt',   Attempt>
export type SimulationSummaryEvent   = BaseEvent<'simulation.summary',   SimulationSummary>

export type SimulationCompletedEvent = BaseEvent<
  'simulation.completed',
  { summary: SimulationSummary; total_ms: number }
>

export type SimulationWarningCode =
  // Orchestrator/runner codes — mixed casing for legacy reasons; new
  // codes introduced in v2.2 are UPPER_SNAKE to signal they're load-bearing.
  | 'unknown_probe'
  | 'PROBE_TIMEOUT'
  | 'PROBE_RUNNER_ERROR'
  | 'probe_runner_warning'
  | 'probe_execution_error'
  | 'probe_class_not_found'
  | 'no_attempts_generated'
  | 'garak_unavailable'
  // Transport codes (from the WS manager, always sequence:null).
  | 'PRECONNECT_BUFFER_OVERFLOW'
  | 'WS_QUEUE_OVERFLOW'
  | 'SLOW_CLIENT'
  // Frontend exhaustiveness fallback.
  | 'UNKNOWN_EVENT_TYPE'
  // Escape hatch — the backend may introduce new codes.  Clients MUST
  // render them using the raw code+message instead of hard-crashing.
  | (string & {})

export type SimulationWarningEvent = BaseEvent<
  'simulation.warning',
  {
    code:    SimulationWarningCode
    message: string
    detail?: Record<string, unknown>
  }
>

export type SimulationErrorEvent = BaseEvent<
  'simulation.error',
  { error_message: string; fatal: boolean }
>

// Heartbeat frame — the transport sends this every WS_PING_INTERVAL_S.
// Note this is NOT part of the simulation envelope family; it intentionally
// omits `sequence`, `timestamp` naming, etc., to make it easy to filter.
export interface PingFrame {
  type:       'ping'
  session_id: string
  ts:         string
}

export type SimulationEvent =
  | SimulationStartedEvent
  | SimulationProbeStartedEvent
  | SimulationProbeCompletedEvent
  | SimulationAttemptEvent
  | SimulationSummaryEvent
  | SimulationCompletedEvent
  | SimulationWarningEvent
  | SimulationErrorEvent

// ── Narrowing helpers ──────────────────────────────────────────────────────

export const isAttemptEvent = (e: SimulationEvent): e is SimulationAttemptEvent =>
  e.type === 'simulation.attempt'

export const isProbeCompletedEvent = (e: SimulationEvent): e is SimulationProbeCompletedEvent =>
  e.type === 'simulation.probe_completed'

export const isTerminal = (e: SimulationEvent): boolean =>
  e.type === 'simulation.completed' || e.type === 'simulation.error'

export const isPing = (frame: unknown): frame is PingFrame =>
  typeof frame === 'object' && frame !== null &&
  (frame as Record<string, unknown>).type === 'ping'

// A guard for the "unresolved policy" marker convention used by the
// backend when the pipeline omits policy metadata.  The UI should render
// these with a subdued style / debug hint so operators know the mapping
// is missing in the guard config — NOT that a real "__unresolved__" policy
// exists.
export const UNRESOLVED_POLICY_PREFIX = '__unresolved__:'
export const isUnresolvedPolicy = (d: GuardDecision | null): boolean =>
  !!d && d.policy_id.startsWith(UNRESOLVED_POLICY_PREFIX)
