/**
 * lib/policyResolution.js
 * ────────────────────────
 * Shared helpers for reasoning about policy attribution on simulation events.
 *
 * The backend uses a well-known sentinel shape — `__unresolved__:<probe>` — to
 * signal "a guard decision fired, but no named OPA policy was matched."  The
 * UI must NEVER surface this as "Unknown" because it destroys operator trust;
 * instead every tab that renders a policy decision routes it through here so
 * the fallback and the originating probe are always visible and truthful.
 *
 * These helpers are pure — no React, no DOM — so they can be exercised by
 * unit tests without mounting a component tree.
 */

// Matches `__unresolved__:<probe>` exactly (case-sensitive, probe is free-form).
const UNRESOLVED_PREFIX = '__unresolved__:'

/**
 * Is the policy name absent or the backend's unresolved sentinel?
 * Returns true for:
 *   - null / undefined / empty string
 *   - the literal "Unknown" (legacy UI leak — treat as unresolved)
 *   - "__unresolved__:<probe>"  (explicit backend signal)
 */
export function isUnresolvedPolicy(policyName) {
  if (policyName == null) return true
  const s = String(policyName).trim()
  if (s === '') return true
  if (s.toLowerCase() === 'unknown') return true
  if (s.startsWith(UNRESOLVED_PREFIX)) return true
  return false
}

/**
 * Extract the probe name from a `__unresolved__:<probe>` sentinel.
 * Returns null if the string is not in sentinel shape.
 */
export function probeFromUnresolved(policyName) {
  if (policyName == null) return null
  const s = String(policyName)
  if (!s.startsWith(UNRESOLVED_PREFIX)) return null
  const probe = s.slice(UNRESOLVED_PREFIX.length).trim()
  return probe || null
}

/**
 * Build a UI-safe description of a policy decision.  Never returns "Unknown".
 *
 * Input: raw values captured from the simulation event stream.
 *   {
 *     policyName: string | null,   // e.g. "pii.block_pii" or "__unresolved__:tooluse"
 *     probeName:  string | null,   // fallback context when policy is unresolved
 *     action:     string | null,   // BLOCK | ALLOW | ESCALATE | FLAG | SKIP
 *   }
 *
 * Output: deterministic shape consumable by PolicyImpact.jsx without further
 * guarding:
 *   {
 *     unresolved:   boolean
 *     displayName:  string       — "PII Block Pii" | "Unresolved Policy"
 *     sourceLabel:  string       — "Default guard (<probe>)" when unresolved
 *     probe:        string|null  — canonical probe name (never empty)
 *     action:       string       — normalised verb, always populated
 *   }
 */
export function resolvePolicyDecision({ policyName, probeName, action }) {
  const unresolved = isUnresolvedPolicy(policyName)
  const probeFromSentinel = probeFromUnresolved(policyName)
  const probe = probeFromSentinel || probeName || null

  const normalizedAction = (action || (unresolved ? 'BLOCK' : 'ALLOW'))
    .toString()
    .toUpperCase()

  if (unresolved) {
    return {
      unresolved: true,
      displayName: 'Unresolved Policy',
      sourceLabel: probe
        ? `Default guard (${probe})`
        : 'Default guard',
      probe,
      action: normalizedAction,
    }
  }

  // Only humanise machine-formatted ids (snake_case / dot.separated / colon:id).
  // Names that already contain whitespace or mixed case are treated as
  // human-authored and passed through verbatim — otherwise we corrupt cases
  // like "Prompt-Guard v3" into "Prompt-Guard V3".
  const raw = String(policyName)
  const looksMachineFormatted = /^[a-z0-9_.:\-]+$/i.test(raw)
    && /[_.:]/.test(raw)
    && !/\s/.test(raw)

  const displayName = looksMachineFormatted
    ? raw
        .replace(/[._:]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, c => c.toUpperCase())
    : raw

  return {
    unresolved: false,
    displayName: displayName || raw,
    sourceLabel: probe ? `Probe: ${probe}` : 'Policy engine',
    probe,
    action: normalizedAction,
  }
}
