/**
 * simulation/buildAttemptsFromEvents.js
 * ──────────────────────────────────────
 * Frontend-side attempt synthesis.  The backend currently emits envelope
 * events (simulation.blocked / allowed / error / progress) plus Garak trace
 * events (llm.prompt, llm.response, guard.decision, guard.input).  The live
 * Timeline used to render those events directly.
 *
 * The attempt-based Timeline expects Attempt rows — one row per probe
 * outcome, carrying prompt, response, guard decision, lineage, and risk as
 * a single unit.  Rather than wait for the backend to emit a dedicated
 * `simulation.attempt` event, we derive Attempts here by joining each
 * terminal decision event with its matching trace records.  The join key
 * is `correlation_id` — set by the backend orchestrator on every event
 * that belongs to the same probe attempt.
 *
 * Contract
 * ────────
 * Input:   simEvents (ordered by timestamp, as produced by
 *          useSimulationStream)
 * Output:  { attempts: Attempt[], arrivalById: {id: number} }
 *          sorted by (sequence asc nulls last, arrival asc) — currently
 *          arrival-only because envelope sequence isn't on the wire yet.
 *
 * This adapter is pure and has no React dependency; tests can exercise it
 * directly with an event array.
 */

// ── Kill-chain phase inference ─────────────────────────────────────────────
//
// The staging spec uses {recon, exploit, evasion, execution, exfiltration,
// other}.  The backend doesn't emit a phase field yet, so we heuristically
// infer from the probe name.  Unknown → 'other'.  The mapping leans on
// Garak's probe module naming convention (probemodule.ProbeClass).

const PROBE_PHASE_MATCHERS = [
  // most specific first
  { re: /(^|[._])exfil/i,                        phase: 'exfiltration', category: 'Exfiltration'        },
  { re: /(^|[._])pii/i,                          phase: 'exfiltration', category: 'PII Leakage'         },
  { re: /(^|[._])leak/i,                         phase: 'exfiltration', category: 'Leakage'             },
  { re: /(^|[._])encoding/i,                     phase: 'evasion',      category: 'Encoding Bypass'     },
  { re: /(^|[._])obfusc/i,                       phase: 'evasion',      category: 'Obfuscation'         },
  { re: /(^|[._])unicode/i,                      phase: 'evasion',      category: 'Unicode Evasion'     },
  { re: /(^|[._])malwaregen/i,                   phase: 'execution',    category: 'Code Generation'     },
  { re: /(^|[._])tool(use|abuse|_)/i,            phase: 'execution',    category: 'Tool Abuse'          },
  { re: /(^|[._])continuation/i,                 phase: 'execution',    category: 'Continuation Attack' },
  { re: /(^|[._])hijack/i,                       phase: 'execution',    category: 'Hijack'              },
  { re: /(^|[._])dan([._]|$)/i,                  phase: 'exploit',      category: 'DAN / Role-play'     },
  { re: /(^|[._])jailbreak/i,                    phase: 'exploit',      category: 'Jailbreak'           },
  { re: /(^|[._])roleplay/i,                     phase: 'exploit',      category: 'Role-play'           },
  { re: /(^|[._])promptinject|(^|[._])injection/i, phase: 'exploit',    category: 'Prompt Injection'    },
  { re: /(^|[._])probe([._]|$)|(^|[._])recon/i,  phase: 'recon',        category: 'Reconnaissance'      },
]

export function inferPhaseAndCategory(probeName) {
  if (!probeName) return { phase: 'other', category: 'General' }
  for (const { re, phase, category } of PROBE_PHASE_MATCHERS) {
    if (re.test(probeName)) return { phase, category }
  }
  return { phase: 'other', category: 'General' }
}

// ── Risk score derivation ──────────────────────────────────────────────────
//
// Matches the existing Timeline's STAGE_RISK mapping so the new UI doesn't
// show different numbers from the legacy one when the backend omits an
// explicit risk_score.

const STAGE_RISK = {
  started:   10,
  progress:  50,
  blocked:   90,
  allowed:   30,
  error:     70,
  completed: 10,
}

function riskFromEvent(ev) {
  const explicit = ev?.details?.risk_score
  if (typeof explicit === 'number' && !Number.isNaN(explicit)) {
    // Normalize 0..1 → 0..100 if the backend sent a probability.
    return explicit <= 1 ? Math.round(explicit * 100) : Math.round(explicit)
  }
  return STAGE_RISK[ev?.stage] ?? 50
}

// ── Guard decision normalization ───────────────────────────────────────────
//
// A guard decision can come from two sources:
//
//   1. A matching `guard.decision` trace record — the authoritative source.
//      Carries a real numeric score, reason, and (optionally) threshold /
//      policy_name from the guard layer.  Garak runs produce these for
//      every attempt routed through the PromptSecurityService.
//
//   2. A bare terminal envelope event (`simulation.blocked` / `.allowed` /
//      `policy.decision` blocked) — used by single-prompt simulations that
//      don't emit a separate trace.  Here the event itself is the decision.
//
// HARD RULE — NEVER fabricate numeric fields.
// ────────────────────────────────────────────
// score, threshold, and policy_id MUST reflect real backend values or be
// null.  A previous version synthesised `{ score: 0, threshold: 0.85 }`
// when the terminal event carried neither, which produced ghost cards
// showing "action=block / score=0.000 / threshold=0.85" — visibly
// impossible (a 0 score cannot have crossed a 0.85 threshold) and erodes
// operator trust.  GuardOnlyCard / AttemptCard already render "—" for
// `null` numeric fields, so leaving them null is the truthful path.
function buildGuardDecision(traceRecord, terminalEvent) {
  const haveTrace    = traceRecord != null
  const haveTerminal = terminalEvent != null && (
    terminalEvent.stage === 'blocked'
    || terminalEvent.stage === 'allowed'
    || terminalEvent.stage === 'escalated'
  )
  if (!haveTrace && !haveTerminal) return null

  // Action — prefer the trace's decision; otherwise infer from terminal stage.
  const action = traceRecord?.decision
    ?? (terminalEvent?.stage === 'blocked'   ? 'block'
       : terminalEvent?.stage === 'allowed'   ? 'allow'
       : terminalEvent?.stage === 'escalated' ? 'escalate'
       : null)
  if (!action) return null

  // Score — ONLY from the trace record (authoritative guard verdict).
  // Normalize 0..100 → 0..1 if a percentile slipped through.  Null when the
  // terminal event is our only source: there is no real number to show.
  const rawScore = typeof traceRecord?.score === 'number' ? traceRecord.score : null
  const score = rawScore == null
    ? null
    : (rawScore <= 1 ? rawScore : rawScore / 100)

  // Threshold — ONLY from the trace record.  Never hardcoded.
  const threshold = typeof traceRecord?.threshold === 'number'
    ? traceRecord.threshold
    : null

  const reason = traceRecord?.reason
    ?? terminalEvent?.details?.decision_reason
    ?? terminalEvent?.details?.message
    ?? ''

  return {
    action,
    score,
    threshold,
    policy_id:   traceRecord?.policy_id   ?? terminalEvent?.details?.policy_id   ?? '',
    policy_name: traceRecord?.policy_name ?? terminalEvent?.details?.policy_name ?? null,
    reason,
  }
}

// ── Main builder ───────────────────────────────────────────────────────────

/**
 * Build Attempt rows from the current simEvents stream.
 *
 * @param {Array} simEvents — ordered list of SimulationEvent (see eventSchema.js)
 * @returns {{ attempts: Array, arrivalById: Object }}
 */
export function buildAttemptsFromEvents(simEvents) {
  if (!Array.isArray(simEvents) || simEvents.length === 0) {
    return { attempts: [], arrivalById: {} }
  }

  // Index trace records by correlation_id for O(1) join with terminal events.
  const promptByCorr   = new Map()   // correlation_id → llm.prompt details
  const responseByCorr = new Map()   // correlation_id → llm.response details
  const guardByCorr    = new Map()   // correlation_id → guard.decision details
  const guardInByCorr  = new Map()   // correlation_id → guard.input details

  for (const ev of simEvents) {
    const cid = ev.correlation_id ?? ev.details?.correlation_id ?? null
    if (!cid) continue
    switch (ev.event_type) {
      case 'llm.prompt':     promptByCorr  .set(cid, ev.details); break
      case 'llm.response':   responseByCorr.set(cid, ev.details); break
      case 'guard.decision': guardByCorr   .set(cid, ev.details); break
      case 'guard.input':    guardInByCorr .set(cid, ev.details); break
      default: /* no-op */
    }
  }

  // simulation.started gives us session start time — used for latency_ms fallback.
  const startedEvent = simEvents.find(e => e.stage === 'started')
  const sessionStartMs = startedEvent?.timestamp
    ? new Date(startedEvent.timestamp).getTime()
    : null
  const sessionId = startedEvent?.session_id
    ?? startedEvent?.details?.session_id
    ?? simEvents[0]?.session_id
    ?? null

  // Has probe_completed been observed?  Anything arriving after a completed
  // signal for the same probe is flagged as a straggler.  The backend's
  // simulation.completed is session-level, not per-probe, so we can't mark
  // individual stragglers with confidence — leave this to the backend once
  // it emits probe_completed.  Default: false.
  //
  // (The staging spec's `meta.is_straggler` is intended for the post-probe
  // stream case.  Without that event today, we never mark stragglers —
  // better to under-report than to falsely flag an attempt.)

  const attempts = []
  const arrivalById = {}
  let arrival = 0

  for (const ev of simEvents) {
    // Terminal-like events become Attempts.  Lifecycle/trace/progress events
    // enrich those rows.  `probe_error` is included so probe-level
    // infrastructure failures (timeouts, crashes) render as cards instead of
    // being silently dropped — see ProbeErrorCard.  These events arrive with
    // no per-attempt llm.prompt / guard.* trace data, so they'd otherwise be
    // classified 'invalid' and filtered out.
    if (
      ev.stage !== 'blocked'
      && ev.stage !== 'allowed'
      && ev.stage !== 'error'
      && ev.stage !== 'probe_error'
    ) {
      continue
    }

    const cid          = ev.correlation_id ?? ev.details?.correlation_id ?? ev.id
    const probeRaw     = ev.details?.probe_name ?? ''
    const { phase, category } = inferPhaseAndCategory(probeRaw)

    const promptRec    = promptByCorr  .get(cid)
    const responseRec  = responseByCorr.get(cid)
    const guardRec     = guardByCorr   .get(cid)
    const guardInRec   = guardInByCorr .get(cid)

    const eventMs      = ev.timestamp ? new Date(ev.timestamp).getTime() : Date.now()
    const latencyMs    = sessionStartMs != null && eventMs >= sessionStartMs
      ? eventMs - sessionStartMs
      : null

    // probe_error and error both surface as 'error' result — the distinction
    // (probe-level vs attempt-level) is preserved on meta.probe_error so
    // classifyAttempt can route to ProbeErrorCard.
    const isProbeError = ev.stage === 'probe_error'
    const result =
      ev.stage === 'blocked' ? 'blocked'
      : ev.stage === 'allowed' ? 'allowed'
      : 'error'

    const attempt = {
      attempt_id:       ev.id,
      session_id:       sessionId ?? ev.session_id ?? '',
      probe:            probeRaw || '(single-prompt)',
      probe_raw:        probeRaw,
      phase,
      category,
      status:           'completed',                 // terminal events are, by definition, complete
      result,
      risk_score:       riskFromEvent(ev),
      model_invoked:    responseRec != null,
      started_at:       startedEvent?.timestamp ?? ev.timestamp,
      completed_at:     ev.timestamp,
      latency_ms:       latencyMs,
      prompt_raw:       promptRec?.prompt ?? '',
      prompt_sanitized: promptRec?.prompt ?? '',
      guard_input:      guardInRec?.raw_prompt ?? promptRec?.prompt ?? '',
      model_response:   responseRec?.response ?? null,
      guard_decision:   buildGuardDecision(guardRec, ev),
      error:            ev.stage === 'error' || isProbeError
        ? (ev.details?.error_message
           ?? ev.details?.message
           ?? ev.details?.decision_reason
           ?? (isProbeError ? 'Probe errored (timeout or crash)' : 'Probe errored'))
        : null,
      meta: {
        is_straggler:     false,
        garak_probe_class: ev.details?.probe_class ?? probeRaw,
        detector:          ev.details?.detector ?? undefined,
        // "stopped"  → our defense blocked the attack (win)
        // "missed"   → Garak's detector caught the model being fooled (loss)
        // null/undef → outcome unknown (e.g., single-prompt non-Garak flow)
        defense_outcome:   ev.details?.defense_outcome ?? null,
        // True when this Attempt represents a probe-level infrastructure
        // failure (simulation.probe_error) rather than an attempt-level
        // outcome.  Routed to ProbeErrorCard by classifyAttempt below.
        probe_error:       isProbeError,
        severity:          ev.details?.severity ?? undefined,
      },
      // Internal: keep arrival order for stable sort
      _arrival: arrival,
    }

    attempts.push(attempt)
    arrivalById[attempt.attempt_id] = arrival
    arrival += 1
  }

  // Stable order: arrival asc (envelope sequence isn't on the wire yet).
  attempts.sort((a, b) => a._arrival - b._arrival)

  return { attempts, arrivalById }
}

// ── Phase grouping + rollup ────────────────────────────────────────────────
//
// Mirrors the staging selectors' useTimelineView() output shape so the JSX
// components can render without further transformation.

export const PHASE_ORDER = [
  'recon',
  'exploit',
  'evasion',
  'execution',
  'exfiltration',
  'other',
]

export const PHASE_LABELS = {
  recon:        'Recon',
  exploit:      'Exploit',
  evasion:      'Evasion',
  execution:    'Execution',
  exfiltration: 'Exfiltration',
  other:        'Other',
}

function emptyRollup() {
  return { total: 0, blocked: 0, allowed: 0, error: 0, running: 0 }
}

function bumpRollup(r, attempt) {
  r.total += 1
  if (attempt.status === 'running') { r.running += 1; return }
  switch (attempt.result) {
    case 'blocked': r.blocked += 1; break
    case 'allowed': r.allowed += 1; break
    case 'error':   r.error   += 1; break
    default:        r.running += 1       // defensive
  }
}

// ── Attempt classification ────────────────────────────────────────────────
//
// The Timeline used to render every attempt regardless of completeness. That
// produced "ghost" rows — cards with no prompt, no response, and no policy
// name — which looked like UI bugs. We now classify every attempt up front
// and let the UI pick a representation that only shows fields it actually has:
//
//   "full"        — either (a) model was invoked AND we have both prompt +
//                   response, or (b) we have a prompt + guard decision
//                   (guard short-circuited before the model ran but the
//                   prompt is still worth showing).  The detailed card
//                   omits any section whose data is missing, so both cases
//                   render cleanly.  Encoding probes whose base64 payloads
//                   the guard blocks pre-model follow path (b), which is
//                   why they now look the same as other Timeline rows
//                   instead of the old compact guard-only card.
//   "guard_only"  — guard decision exists but NO prompt was captured.  The
//                   compact card avoids empty prompt/response slots and is
//                   still the right choice for legacy single-prompt flows
//                   where the guard intercepts before any prompt is logged.
//   "probe_error" — probe-level infrastructure failure (simulation.probe_error).
//                   No prompt/response/guard data — but operators MUST see it
//                   so they understand a probe timed out or crashed.  Without
//                   this branch, the row falls through to 'invalid' and
//                   disappears, which is what was happening for encoding
//                   probe timeouts (Timeline badge=N but only 1 card visible).
//   "invalid"     — no prompt, no response, no guard decision, model never
//                   invoked, not a probe_error.  These carry no operator-
//                   actionable information and must NEVER reach the UI —
//                   see the filter in buildTimelineView() below.
//
// Canonical Attempt fields (produced by buildAttemptsFromEvents):
//   prompt_raw         — empty string when the prompt is missing
//   model_response     — null when the model wasn't invoked
//   model_invoked      — boolean
//   guard_decision     — object | null
export function classifyAttempt(a) {
  if (!a || typeof a !== 'object') return 'invalid'

  // probe_error wins over the prompt/response/guard checks: a probe timeout
  // or crash carries operator-critical info even with zero trace data, and
  // we never want it to fall through to 'invalid'.
  if (a.meta?.probe_error === true) return 'probe_error'

  const hasPrompt   = typeof a.prompt_raw === 'string' && a.prompt_raw.length > 0
  const hasResponse = a.model_response != null && String(a.model_response).length > 0
  const invoked     = a.model_invoked === true
  const hasGuard    = a.guard_decision != null

  if (!hasPrompt && !hasResponse && !invoked && !hasGuard) {
    return 'invalid'
  }
  if (invoked && hasPrompt && hasResponse) {
    return 'full'
  }
  // A prompt + guard decision is enough for the full card — the "Model
  // response" section omits itself when model_response is null, so the
  // card degrades cleanly.  Previously these rows rendered as the
  // compact GuardOnlyCard which visibly differed from the rest of the
  // Timeline — encoding probes (whose base64 payloads the guard
  // blocks BEFORE model invocation) looked like a different kind of
  // event.  Routing to 'full' here keeps the Timeline visually
  // homogeneous and still surfaces the guard decision in the expanded
  // panel.  Only attempts that truly have no prompt fall through to
  // 'guard_only'.
  if (hasPrompt && hasGuard) {
    return 'full'
  }
  if (!invoked && hasGuard) {
    return 'guard_only'
  }
  // Defensive: a partial record with a prompt but no response and no guard
  // decision is still invalid — we'd have nothing to show.  Better to hide
  // than to render a blank card.
  if (hasPrompt && hasResponse) return 'full'
  if (hasGuard)                 return 'guard_only'
  return 'invalid'
}

/**
 * Build the Timeline view — phase groups with rollups plus a grand total.
 * Returns empty phases filtered out, preserving PHASE_ORDER for the rest.
 *
 * Invalid attempts are DROPPED before grouping (see classifyAttempt); they
 * never reach the UI.  Every surviving row carries a `type` field so the
 * AttemptCard can pick between the full detail view and the compact
 * guard-only view.
 */
export function buildTimelineView(attempts) {
  const input = Array.isArray(attempts) ? attempts : []

  // Stamp classification once; the invalid filter + the UI both read it.
  const classified = input.map(a => ({ a, type: classifyAttempt(a) }))
  const valid = classified.filter(c => c.type !== 'invalid')

  if (input.length > 0 && valid.length === 0) {
    // Upstream produced only ghost rows — usually a sign of a broken
    // event stream or a backend that forgot to emit prompt/response.
    // Warn so devs notice; the UI will render its empty state.
    // eslint-disable-next-line no-console
    console.warn('[Timeline] all attempts classified as invalid — nothing to render', {
      inputCount: input.length,
    })
  }

  const byPhase = { recon: [], exploit: [], evasion: [], execution: [], exfiltration: [], other: [] }
  const rollupByPhase = {
    recon: emptyRollup(), exploit: emptyRollup(), evasion: emptyRollup(),
    execution: emptyRollup(), exfiltration: emptyRollup(), other: emptyRollup(),
  }
  const total = emptyRollup()

  for (const { a, type } of valid) {
    const phase = PHASE_ORDER.includes(a.phase) ? a.phase : 'other'
    const row = {
      attempt:      a,
      type,                                // 'full' | 'guard_only' | 'probe_error'
      sequence:     null,                  // not on the wire yet
      arrival:      a._arrival,
      is_straggler: a.meta?.is_straggler === true,
    }
    byPhase[phase].push(row)
    bumpRollup(rollupByPhase[phase], a)
    bumpRollup(total, a)
  }

  const phases = []
  for (const phase of PHASE_ORDER) {
    const rows = byPhase[phase]
    if (rows.length === 0) continue
    phases.push({
      phase,
      label:  PHASE_LABELS[phase],
      rollup: rollupByPhase[phase],
      rows,
    })
  }
  return { phases, rollup: total }
}
