// ui/src/admin/agents/hooks/useAgentList.js
//
// Live polling hook for the Inventory → Agents tab. Fetches
// /api/spm/agents on a tick, exposes the latest rows, and provides a
// pure merge helper so callers can blend mock data (used for offline
// dev) with live data without losing offline-only rows.
//
// Why poll instead of SSE/WebSocket?
//   * The set of agents changes on operator action (register, retire,
//     run/stop). 5s polling is plenty for the UI's freshness needs.
//   * Phase 4 will add a /agents/stream SSE for runtime_state changes
//     so the run/stop flicker happens without waiting for the next
//     poll cycle. Phase 3 keeps the wiring simple — Inventory pages
//     are already used to 5s data lag.

import { useEffect, useRef, useState } from "react"

import { listAgents } from "../../api/agents"


/**
 * Merge mock agent rows with live ones. Live takes precedence; mocks
 * are kept ONLY for names not present in live data, so offline dev
 * still sees the full seed catalog while production sees real rows.
 *
 * The merged rows carry a `_source: "live" | "mock"` tag so the UI can
 * render a small live-data dot next to live rows.
 */
export function mergeAgents(mocks, live) {
  const liveNames = new Set((live || []).map(a => a && a.name))
  return [
    ...((live  || []).map(a => ({ ...a, _source: "live" }))),
    ...((mocks || []).filter(m => m && !liveNames.has(m.name))
                     .map(m => ({ ...m, _source: "mock" }))),
  ]
}


/**
 * Poll listAgents() every `pollMs` and expose:
 *   - live:    last successfully-fetched array (defaults to []).
 *   - error:   the last fetch error, or null.
 *   - loading: true on the first tick before either resolves.
 *   - refresh: synchronous re-poll trigger for "I just took an action,
 *              don't wait 5s to see the result."
 *
 * The hook is safe to mount in a component that uses StrictMode —
 * cleanup cancels any in-flight tick on unmount.
 */
export function useAgentList({ pollMs = 5000 } = {}) {
  const [live,    setLive]    = useState([])
  const [error,   setError]   = useState(null)
  const [loading, setLoading] = useState(true)

  // Track the latest in-flight tick so we can cancel stale results.
  const tickRef = useRef(0)

  useEffect(() => {
    let cancelled = false

    const tick = async () => {
      const myId = ++tickRef.current
      try {
        const rows = await listAgents()
        if (cancelled || myId !== tickRef.current) return
        setLive(rows)
        setError(null)
      } catch (e) {
        if (cancelled || myId !== tickRef.current) return
        setError(e)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    tick()
    const id = setInterval(tick, Math.max(500, pollMs))
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [pollMs])

  // Manual refresh — bumps the tick id so any in-flight stale tick is
  // dropped on resolution.
  const refresh = () => { tickRef.current++; return _refreshOnce(setLive, setError) }

  return { live, error, loading, refresh }
}


// Helper used by `refresh()` so the public surface stays clean.
async function _refreshOnce(setLive, setError) {
  try {
    const rows = await listAgents()
    setLive(rows)
    setError(null)
  } catch (e) {
    setError(e)
  }
}
