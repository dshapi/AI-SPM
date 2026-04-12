/**
 * useFindings.js
 * ──────────────
 * React hooks for loading, filtering, and mutating Findings.
 *
 * useFindings(filters) — paginated list with filter state
 * useFinding(id)       — single finding detail (for detail panel or breadcrumb)
 */

import { useState, useEffect, useCallback } from 'react'
import {
  listFindings,
  getFinding,
  updateFindingStatus,
  linkFindingCase,
} from '../api/findingsApi.js'

// ── useFindings ───────────────────────────────────────────────────────────────

/**
 * Load a paginated, filtered list of findings.
 *
 * @param {object} filters   - severity, status, asset, min_risk_score, …
 * @returns {{
 *   findings: object[],
 *   total: number,
 *   loading: boolean,
 *   error: string|null,
 *   refetch: () => void,
 *   markStatus: (id, status) => Promise<void>,
 *   attachCase: (id, caseId) => Promise<void>,
 * }}
 */
export function useFindings(filters = {}) {
  const [findings, setFindings] = useState([])
  const [total,    setTotal]    = useState(0)
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)

  // Stable key so effect only re-runs when filter values actually change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const filterKey = JSON.stringify(filters)

  const fetchFindings = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listFindings(filters)
      setFindings(data.items)
      setTotal(data.total)
    } catch (e) {
      console.error('[useFindings] fetch error:', e)
      setError(e.message || 'Failed to load findings')
      // Keep previous data visible — don't wipe the table on transient errors
    } finally {
      setLoading(false)
    }
  // filterKey is the stable dep; individual filter props are captured by closure
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  useEffect(() => { fetchFindings() }, [fetchFindings])

  // ── Mutations ─────────────────────────────────────────────────────────────

  /**
   * Optimistically update a finding's status then confirm via API.
   * On failure, reverts to the previous value.
   */
  const markStatus = useCallback(async (findingId, newStatus) => {
    const cap   = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s
    const prev  = findings.find(f => f.id === findingId)

    // Optimistic
    setFindings(prev => prev.map(f =>
      f.id === findingId ? { ...f, status: cap(newStatus) } : f
    ))

    try {
      await updateFindingStatus(findingId, newStatus)
    } catch (e) {
      console.error('[useFindings] markStatus failed:', e)
      // Revert
      if (prev) {
        setFindings(cur => cur.map(f =>
          f.id === findingId ? { ...f, status: prev.status } : f
        ))
      }
      throw e
    }
  }, [findings])

  /**
   * Attach a case ID to a finding (optimistic update).
   */
  const attachCase = useCallback(async (findingId, caseId) => {
    setFindings(prev => prev.map(f =>
      f.id === findingId ? { ...f, case_id: caseId } : f
    ))
    try {
      await linkFindingCase(findingId, caseId)
    } catch (e) {
      console.error('[useFindings] attachCase failed:', e)
      // Revert
      setFindings(prev => prev.map(f =>
        f.id === findingId ? { ...f, case_id: null } : f
      ))
      throw e
    }
  }, [])

  return { findings, total, loading, error, refetch: fetchFindings, markStatus, attachCase }
}

// ── useFinding (single-item fetch) ────────────────────────────────────────────

/**
 * Fetch a single finding by ID.
 * Used when the selected finding is not in the current page
 * (e.g. deep-linked via URL param).
 */
export function useFinding(id) {
  const [finding, setFinding] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (!id) {
      setFinding(null)
      return
    }
    setLoading(true)
    setError(null)
    getFinding(id)
      .then(setFinding)
      .catch(e => {
        console.error('[useFinding] fetch error:', e)
        setError(e.message || 'Finding not found')
      })
      .finally(() => setLoading(false))
  }, [id])

  return { finding, loading, error }
}
