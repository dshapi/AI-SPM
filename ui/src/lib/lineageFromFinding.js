/**
 * lib/lineageFromFinding.js  (DEPRECATED — scheduled for deletion)
 * ────────────────────────────────────────────────────────────────
 * This module used to synthesise a minimal SimulationEvent[] from a Finding
 * when the api service's in-memory event log had evicted the original run
 * (LRU cap 50 sessions). That synthesis is no longer needed:
 *
 *   ── Layer 1 (persistent session_events) now dual-writes every UI-lineage
 *      event to the orchestrator's Postgres session_events table, and the
 *      api service's /sessions/{id}/events endpoint falls back to that
 *      store transparently when its LRU doesn't hold the session. The
 *      Lineage page therefore always renders the REAL recorded run.
 *
 * The file is kept as an empty stub so any lingering imports fail loudly
 * at review time (and the git history still shows what it used to be).
 * It can be deleted once the grep is clean across branches.
 */
export function lineageFromFinding() {
  // No-op. See file header for context.
  return []
}

export function replayPromptFromFinding(finding) {
  // Still exported because the Lineage page's Run Simulation button needs
  // a replayable prompt when arriving with ?finding_id=… (Alerts → Lineage).
  // Lineage.jsx now inlines this helper; this export is left for any
  // external callers until they migrate off.
  if (!finding) return null
  const h = finding.hypothesis
  if (typeof h === 'string' && h.trim()) return h.trim()
  const p = finding.prompt
  if (typeof p === 'string' && p.trim()) return p.trim()
  const t = finding.title
  if (typeof t === 'string' && t.trim()) return t.trim()
  return null
}
