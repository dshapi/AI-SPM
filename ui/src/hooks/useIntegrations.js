/**
 * hooks/useIntegrations.js
 * ────────────────────────
 * React hooks for the spm-api integrations module.
 *
 * - `useIntegrations(filters?)` — list + metrics, auto-refetches when
 *   filters change.  Exposes `{ integrations, metrics, loading, error,
 *   refresh }`.
 *
 * - `useIntegration(id)` — single integration's full detail (all nested
 *   tab data).  Exposes `{ integration, loading, error, refresh }`.
 *
 * Both hooks are fetch-on-mount + manual-refresh; no polling (the
 * Integrations page will expose a "Sync" button that calls refresh()).
 * SSE / websocket push was considered and deferred — the integrations
 * surface changes at human-edit speed, not at stream speed, so pulling
 * the subscription infrastructure in would be unjustified overhead.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  listIntegrations,
  getIntegrationsMetrics,
  getIntegration,
} from '../admin/api/integrationsApi.js'


/**
 * Stable empty objects so callers can destructure without guarding.
 * Exported for tests only.
 */
export const EMPTY_METRICS = Object.freeze({
  total: 0,
  connected: 0,
  healthy: 0,
  needs_attention: 0,
  failed_syncs_24h: 0,
})


/**
 * List + metrics hook.
 *
 * @param {object}  [filters]
 * @param {string}  [filters.category]  propagates to ?category=
 * @param {string}  [filters.status]    propagates to ?status=
 * @param {string}  [filters.q]         propagates to ?q= (case-insensitive)
 *
 * @returns {{
 *   integrations: IntegrationSummary[],
 *   metrics:      { total, connected, healthy, needs_attention, failed_syncs_24h },
 *   loading:      boolean,
 *   error:        Error | null,
 *   refresh:      () => Promise<void>,
 * }}
 */
export function useIntegrations(filters = {}) {
  // Destructure so the effect depends on the individual strings rather than
  // the filter object identity.  Callers commonly pass a fresh object literal
  // each render, which would re-fetch on every render if we depended on
  // `filters` itself.
  const { category, status, q } = filters

  const [integrations, setIntegrations] = useState([])
  const [metrics, setMetrics]           = useState(EMPTY_METRICS)
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState(null)

  // ``seq`` protects against the classic "stale response" race: if the user
  // flips a filter mid-request, the in-flight call can resolve AFTER the
  // newer one and overwrite fresh data with stale.  We tag each request
  // with a monotonic id and drop responses that aren't the latest.
  const seqRef = useRef(0)

  const fetchAll = useCallback(async () => {
    const mySeq = ++seqRef.current
    setLoading(true)
    setError(null)
    try {
      const [list, m] = await Promise.all([
        listIntegrations({ category, status, q }),
        getIntegrationsMetrics(),
      ])
      if (mySeq !== seqRef.current) return   // a newer fetch has superseded us
      setIntegrations(list)
      setMetrics(m || EMPTY_METRICS)
    } catch (e) {
      if (mySeq !== seqRef.current) return
      setError(e)
      // Don't wipe the cached list on error — a transient network blip
      // shouldn't nuke the UI.  Re-render shows the error banner instead.
    } finally {
      if (mySeq === seqRef.current) setLoading(false)
    }
  }, [category, status, q])

  useEffect(() => { fetchAll() }, [fetchAll])

  return { integrations, metrics, loading, error, refresh: fetchAll }
}


/**
 * Single-integration detail hook.  Useful for the right-hand detail panel
 * in Integrations.jsx, which needs the nested `credentials`, `connection`,
 * `auth`, `coverage`, `activity`, `workflows` fields beyond what the list
 * endpoint returns.
 *
 * @param {string | null | undefined} id  UUID or external_id slug (e.g. 'int-003')
 *
 * @returns {{
 *   integration: IntegrationDetail | null,
 *   loading:     boolean,
 *   error:       Error | null,
 *   refresh:     () => Promise<void>,
 * }}
 */
export function useIntegration(id) {
  const [integration, setIntegration] = useState(null)
  const [loading, setLoading]         = useState(!!id)
  const [error, setError]             = useState(null)
  const seqRef = useRef(0)

  const fetchOne = useCallback(async () => {
    if (!id) {
      setIntegration(null)
      setLoading(false)
      setError(null)
      return
    }
    const mySeq = ++seqRef.current
    setLoading(true)
    setError(null)
    try {
      const data = await getIntegration(id)
      if (mySeq !== seqRef.current) return
      setIntegration(data)
    } catch (e) {
      if (mySeq !== seqRef.current) return
      setError(e)
    } finally {
      if (mySeq === seqRef.current) setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchOne() }, [fetchOne])

  return { integration, loading, error, refresh: fetchOne }
}


export default useIntegrations
