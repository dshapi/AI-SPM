/**
 * actionHandlers.js
 * ──────────────────
 * Factory that creates handler functions bound to a react-router `navigate`.
 *
 * Usage inside a React component:
 *   const navigate = useNavigate()
 *   dispatch('openLineage', finding, navigate)
 *
 * Adding a new handler: add a key here and reference it in actionRegistry.js.
 * No component code needs to change.
 */

// ── Handler factory ───────────────────────────────────────────────────────────

/**
 * Returns a map of { handlerName: (finding) => void }.
 * All navigation calls are bound to the provided `navigate` function.
 */
export function createHandlers(navigate) {
  return {
    /**
     * Opens the Lineage Graph for the finding's asset, pre-selecting
     * the finding via the finding_id query param.
     */
    openLineage: (finding) =>
      navigate(
        `/admin/lineage?asset=${encodeURIComponent(finding.asset?.name ?? '')}&finding_id=${finding.id}`
      ),

    /**
     * Opens the Runtime Session view, auto-selecting the session
     * associated with this finding (uses correlated_events[0] or finding.id).
     */
    openRuntimeSession: (finding) => {
      const sessionId = finding.correlated_events?.[0] ?? finding.id
      navigate(`/admin/runtime?session_id=${encodeURIComponent(sessionId)}`)
    },

    /**
     * Opens the Runtime view filtered to network/port activity for this finding.
     */
    openRuntimeByPort: (finding) =>
      navigate(
        `/admin/runtime?session_id=${encodeURIComponent(finding.id)}&filter=network`
      ),

    /**
     * Opens the Inventory page filtered to the finding's asset name.
     */
    openInventoryByAsset: (finding) =>
      navigate(
        `/admin/inventory?asset=${encodeURIComponent(finding.asset?.name ?? '')}`
      ),

    /**
     * Opens the Policies page (for permission review actions).
     */
    openPolicy: (_finding) =>
      navigate('/admin/policies'),

    /**
     * Placeholder for secret/credential rotation workflow.
     * Emits a browser alert until a real rotation API is wired in.
     */
    revokeSecret: (_finding) => {
      // eslint-disable-next-line no-alert
      window.alert('Secret rotation workflow — integration coming soon.')
    },
  }
}

// ── Dispatch helper ───────────────────────────────────────────────────────────

/**
 * Calls the named handler for the given finding.
 * Silently no-ops for unknown handler names so new registry entries
 * don't crash the UI before their handlers are implemented.
 *
 * @param {string}   handlerName
 * @param {object}   finding     — normalized finding object
 * @param {Function} navigate    — from useNavigate()
 */
export function dispatch(handlerName, finding, navigate) {
  const handlers = createHandlers(navigate)
  const fn = handlers[handlerName]
  if (typeof fn === 'function') fn(finding)
}
