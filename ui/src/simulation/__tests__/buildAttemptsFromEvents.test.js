/**
 * Tests for buildAttemptsFromEvents.js
 *
 * Focus areas (from task #22):
 *   • classifyAttempt — correctness of the four output labels
 *       ('full', 'guard_only', 'probe_error', 'invalid') and in particular
 *       the priority rule that probe_error WINS over prompt/response/guard
 *       checks.
 *   • buildTimelineView — stamps row.type from classifyAttempt, filters
 *       invalid rows, groups by phase, and computes rollups correctly.
 *   • buildAttemptsFromEvents — end-to-end check that a
 *       simulation.probe_error envelope produces a classify-able attempt
 *       that reaches the Timeline as row.type === 'probe_error'.
 *
 * These guard against regressions in two places the Timeline depends on
 * simultaneously: data synthesis (classify) and view assembly (groupBy).
 * We deliberately do NOT test the React components — that's a separate
 * file and would couple this suite to JSX rendering.
 */

import { describe, it, expect } from 'vitest'
import {
  classifyAttempt,
  buildTimelineView,
  buildAttemptsFromEvents,
  inferPhaseAndCategory,
  PHASE_ORDER,
} from '../buildAttemptsFromEvents.js'

// ─────────────────────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────────────────────

// Minimal Attempt shape — keep in sync with buildAttemptsFromEvents() output.
// Tests pass overrides for the fields they care about; everything else stays
// at a neutral default so no test accidentally triggers an unrelated branch.
const makeAttempt = (overrides = {}) => ({
  attempt_id:       'a-1',
  session_id:       's-1',
  probe:            'promptinject',
  probe_raw:        'promptinject',
  phase:            'exploit',
  category:         'Prompt Injection',
  status:           'completed',
  result:           'blocked',
  risk_score:       50,
  model_invoked:    false,
  started_at:       '2026-01-01T00:00:00Z',
  completed_at:     '2026-01-01T00:00:01Z',
  latency_ms:       1000,
  prompt_raw:       '',
  prompt_sanitized: '',
  guard_input:      '',
  model_response:   null,
  guard_decision:   null,
  error:            null,
  meta: {
    is_straggler:      false,
    garak_probe_class: 'promptinject',
    detector:          undefined,
    defense_outcome:   null,
    probe_error:       false,
    severity:          undefined,
  },
  _arrival: 0,
  ...overrides,
})

// Minimal normalized SimulationEvent — mirrors the shape produced by
// eventSchema.normalizeEvent().  Tests override event_type / stage / details
// to simulate each terminal event kind.
const makeEvent = (overrides = {}) => ({
  id:             'ev-1',
  event_type:     'simulation.blocked',
  stage:          'blocked',
  timestamp:      '2026-01-01T00:00:00Z',
  correlation_id: 'cid-1',
  session_id:     's-1',
  source_service: 'api',
  details:        {},
  ...overrides,
})

// ─────────────────────────────────────────────────────────────────────────────
// classifyAttempt
// ─────────────────────────────────────────────────────────────────────────────

describe('classifyAttempt', () => {
  it("returns 'invalid' for null / non-object input", () => {
    expect(classifyAttempt(null)).toBe('invalid')
    expect(classifyAttempt(undefined)).toBe('invalid')
    expect(classifyAttempt('a string')).toBe('invalid')
    expect(classifyAttempt(42)).toBe('invalid')
  })

  it("returns 'invalid' when no prompt, response, guard, or invocation", () => {
    const a = makeAttempt()
    expect(classifyAttempt(a)).toBe('invalid')
  })

  it("returns 'full' when the model was invoked and both prompt + response are present", () => {
    const a = makeAttempt({
      model_invoked:  true,
      prompt_raw:     'hello',
      model_response: 'world',
    })
    expect(classifyAttempt(a)).toBe('full')
  })

  it("returns 'guard_only' when the model was NOT invoked but a guard decision exists", () => {
    const a = makeAttempt({
      model_invoked:  false,
      guard_decision: { action: 'BLOCK', score: 0.92 },
    })
    expect(classifyAttempt(a)).toBe('guard_only')
  })

  it("returns 'full' when we have a prompt + guard decision even if model was NOT invoked (encoding case)", () => {
    // Encoding probes ship base64-encoded prompts that the guard blocks
    // BEFORE model invocation.  Previously these rows were classified as
    // 'guard_only' and rendered with a compact card that hid the prompt,
    // which made encoding rows visibly different from every other probe.
    // They now classify as 'full' so the standard card renders with the
    // prompt + guard decision; the Model response section omits itself.
    const a = makeAttempt({
      model_invoked:  false,
      prompt_raw:     'SWdub3JlIHByZXZpb3VzIGluc3RydWN0aW9ucw==',
      model_response: null,
      guard_decision: { action: 'BLOCK', score: 0.91, threshold: 0.85 },
      result:         'blocked',
      meta: { defense_outcome: 'stopped', probe_error: false },
    })
    expect(classifyAttempt(a)).toBe('full')
  })

  it("returns 'probe_error' when meta.probe_error === true", () => {
    const a = makeAttempt({
      meta: { probe_error: true },
      error: 'probe timed out after 60s',
    })
    expect(classifyAttempt(a)).toBe('probe_error')
  })

  it("probe_error wins over full: even with prompt + response + invocation, classifier picks 'probe_error'", () => {
    // This is the whole point of task #20 — a probe-level infrastructure
    // failure must surface distinctly, even if one attempt happened to
    // complete before the probe errored out.  Without this priority, the
    // row would be rendered as a full card and the operator would miss
    // the probe-level failure entirely.
    const a = makeAttempt({
      model_invoked:  true,
      prompt_raw:     'hello',
      model_response: 'world',
      guard_decision: { action: 'ALLOW', score: 0.01 },
      meta: { probe_error: true },
    })
    expect(classifyAttempt(a)).toBe('probe_error')
  })

  it("probe_error wins over guard_only: synthetic probe_error row has no prompt/response but may have null guard", () => {
    const a = makeAttempt({
      model_invoked:  false,
      guard_decision: null,
      meta: { probe_error: true },
    })
    expect(classifyAttempt(a)).toBe('probe_error')
  })

  it("returns 'invalid' for a partial row with prompt but no response, no guard, no invocation", () => {
    const a = makeAttempt({
      model_invoked:  false,
      prompt_raw:     'hello',
      model_response: null,
      guard_decision: null,
    })
    expect(classifyAttempt(a)).toBe('invalid')
  })

  it("handles missing meta object gracefully (legacy attempts have no meta)", () => {
    const a = { ...makeAttempt(), meta: undefined }
    // No meta → no probe_error flag → falls through to the prompt/response
    // / guard checks, which all fail on the default fixture.
    expect(classifyAttempt(a)).toBe('invalid')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// buildTimelineView
// ─────────────────────────────────────────────────────────────────────────────

describe('buildTimelineView', () => {
  it('returns an empty view for non-array / empty input', () => {
    expect(buildTimelineView(null)).toEqual({
      phases: [],
      rollup: { total: 0, blocked: 0, allowed: 0, error: 0, running: 0 },
    })
    expect(buildTimelineView([])).toEqual({
      phases: [],
      rollup: { total: 0, blocked: 0, allowed: 0, error: 0, running: 0 },
    })
  })

  it('drops invalid attempts before grouping', () => {
    const view = buildTimelineView([makeAttempt()]) // invalid by default
    expect(view.phases).toEqual([])
    expect(view.rollup.total).toBe(0)
  })

  it("stamps row.type='full' on complete attempts", () => {
    const view = buildTimelineView([
      makeAttempt({
        attempt_id: 'a-full',
        model_invoked:  true,
        prompt_raw:     'hi',
        model_response: 'there',
        result:         'allowed',
      }),
    ])
    expect(view.phases).toHaveLength(1)
    expect(view.phases[0].rows).toHaveLength(1)
    expect(view.phases[0].rows[0].type).toBe('full')
  })

  it("stamps row.type='guard_only' on guard short-circuit attempts", () => {
    const view = buildTimelineView([
      makeAttempt({
        attempt_id:     'a-guard',
        model_invoked:  false,
        guard_decision: { action: 'BLOCK', score: 0.99 },
        result:         'blocked',
      }),
    ])
    expect(view.phases[0].rows[0].type).toBe('guard_only')
  })

  it("stamps row.type='probe_error' on probe-level error attempts", () => {
    const view = buildTimelineView([
      makeAttempt({
        attempt_id: 'a-err',
        result:     'error',
        error:      'probe timeout',
        meta:       { probe_error: true, severity: 'high' },
      }),
    ])
    expect(view.phases[0].rows[0].type).toBe('probe_error')
  })

  it('groups attempts into the expected phase buckets', () => {
    // One attempt per phase (plus one in 'other' for an unrecognised probe).
    const attempts = [
      makeAttempt({ attempt_id: 'r', probe: 'recon.probe',  phase: 'recon',
        model_invoked: true, prompt_raw: 'p', model_response: 'r', result: 'allowed' }),
      makeAttempt({ attempt_id: 'x', probe: 'promptinject', phase: 'exploit',
        model_invoked: true, prompt_raw: 'p', model_response: 'r', result: 'blocked' }),
      makeAttempt({ attempt_id: 'ev', probe: 'encoding',     phase: 'evasion',
        result: 'error', meta: { probe_error: true } }),
      makeAttempt({ attempt_id: 'o', probe: 'mysterious',   phase: 'other',
        model_invoked: true, prompt_raw: 'p', model_response: 'r', result: 'allowed' }),
    ]
    const view = buildTimelineView(attempts)

    const phases = view.phases.map(p => p.phase)
    // Empty phases are filtered out, but the ones we populated must appear
    // in canonical PHASE_ORDER.
    expect(phases).toEqual(['recon', 'exploit', 'evasion', 'other'])
    expect(PHASE_ORDER).toContain('recon')
    expect(PHASE_ORDER).toContain('other')

    // Each row lives in its own phase bucket.
    for (const phase of view.phases) {
      expect(phase.rows).toHaveLength(1)
    }
  })

  it('computes per-phase and grand-total rollups that match the input mix', () => {
    // Three exploit attempts: 1 blocked (full), 1 allowed (full), 1 probe_error.
    // One exfil attempt: 1 error (full).
    const attempts = [
      makeAttempt({ attempt_id: 'e1', phase: 'exploit',
        model_invoked: true, prompt_raw: 'p', model_response: 'r', result: 'blocked' }),
      makeAttempt({ attempt_id: 'e2', phase: 'exploit',
        model_invoked: true, prompt_raw: 'p', model_response: 'r', result: 'allowed' }),
      makeAttempt({ attempt_id: 'e3', phase: 'exploit', result: 'error',
        meta: { probe_error: true } }),
      makeAttempt({ attempt_id: 'x1', phase: 'exfiltration',
        model_invoked: true, prompt_raw: 'p', model_response: 'r', result: 'error' }),
    ]
    const view = buildTimelineView(attempts)

    const exploit = view.phases.find(p => p.phase === 'exploit')
    expect(exploit.rollup).toEqual({ total: 3, blocked: 1, allowed: 1, error: 1, running: 0 })

    const exfil = view.phases.find(p => p.phase === 'exfiltration')
    expect(exfil.rollup).toEqual({ total: 1, blocked: 0, allowed: 0, error: 1, running: 0 })

    expect(view.rollup).toEqual({ total: 4, blocked: 1, allowed: 1, error: 2, running: 0 })
  })

  it('counts running attempts in the rollup regardless of result field', () => {
    const view = buildTimelineView([
      makeAttempt({
        attempt_id:     'running-1',
        status:         'running',
        // A running attempt can still carry a prompt (we stream llm.prompt
        // before llm.response arrives); classify wants something non-invalid
        // so the row reaches the rollup.
        model_invoked:  true,
        prompt_raw:     'hi',
        model_response: 'partial',
        result:         null,  // backend hasn't decided yet
      }),
    ])
    expect(view.rollup.running).toBe(1)
    expect(view.rollup.total).toBe(1)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// buildAttemptsFromEvents — probe_error end-to-end
// ─────────────────────────────────────────────────────────────────────────────

describe('buildAttemptsFromEvents (probe_error path)', () => {
  it('synthesises an Attempt with meta.probe_error=true from a simulation.probe_error event', () => {
    const { attempts } = buildAttemptsFromEvents([
      makeEvent({
        id:         'ev-started',
        event_type: 'session.started',
        stage:      'started',
      }),
      makeEvent({
        id:             'ev-probe-err',
        event_type:     'simulation.probe_error',
        stage:          'probe_error',
        correlation_id: 'enc-timeout',
        details: {
          probe_name:      'encoding',
          decision_reason: 'probe timed out after 60s',
          severity:        'high',
        },
      }),
    ])

    expect(attempts).toHaveLength(1)
    const a = attempts[0]
    expect(a.meta.probe_error).toBe(true)
    expect(a.meta.severity).toBe('high')
    expect(a.result).toBe('error')
    expect(a.error).toContain('probe timed out')
    // Phase inference must still work even though we have no trace data.
    expect(a.probe).toBe('encoding')
    expect(a.phase).toBe('evasion')
  })

  it('synthesised probe_error attempt is classified and rendered as probe_error in the Timeline', () => {
    const { attempts } = buildAttemptsFromEvents([
      makeEvent({
        id:             'ev-probe-err',
        event_type:     'simulation.probe_error',
        stage:          'probe_error',
        correlation_id: 'enc-timeout',
        details: {
          probe_name: 'encoding',
          message:    'CPM pipeline crashed',
          severity:   'critical',
        },
      }),
    ])

    expect(classifyAttempt(attempts[0])).toBe('probe_error')

    const view = buildTimelineView(attempts)
    expect(view.phases).toHaveLength(1)
    const row = view.phases[0].rows[0]
    expect(row.type).toBe('probe_error')
    expect(row.attempt.error).toBe('CPM pipeline crashed')
    expect(view.rollup).toEqual({ total: 1, blocked: 0, allowed: 0, error: 1, running: 0 })
  })

  it('supplies a default error message when the probe_error event carries none', () => {
    const { attempts } = buildAttemptsFromEvents([
      makeEvent({
        id:         'ev-probe-err',
        event_type: 'simulation.probe_error',
        stage:      'probe_error',
        details:    { probe_name: 'encoding' }, // no error_message / message / decision_reason
      }),
    ])
    // A synthetic row with nothing useful on it must still surface —
    // otherwise a silent backend regression would silently hide errors.
    expect(attempts[0].error).toBe('Probe errored (timeout or crash)')
    expect(classifyAttempt(attempts[0])).toBe('probe_error')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// inferPhaseAndCategory — smoke test to lock in the probe→phase mapping
// used by the tests above.
// ─────────────────────────────────────────────────────────────────────────────

describe('inferPhaseAndCategory', () => {
  it('routes encoding probes to the evasion phase', () => {
    expect(inferPhaseAndCategory('encoding').phase).toBe('evasion')
  })
  it('routes promptinject probes to the exploit phase', () => {
    expect(inferPhaseAndCategory('promptinject').phase).toBe('exploit')
  })
  it('routes unknown probe names to other / General', () => {
    expect(inferPhaseAndCategory('mysterious-probe')).toEqual({
      phase: 'other',
      category: 'General',
    })
  })
  it('handles empty / missing input defensively', () => {
    expect(inferPhaseAndCategory('')).toEqual({ phase: 'other', category: 'General' })
    expect(inferPhaseAndCategory(undefined)).toEqual({ phase: 'other', category: 'General' })
  })
})
