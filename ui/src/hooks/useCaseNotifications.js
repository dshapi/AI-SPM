/**
 * useCaseNotifications.js
 * ────────────────────────
 * Polls GET /api/v1/cases every 30 s and returns notification-shaped objects
 * for use in the bell icon dropdown.
 *
 * "New" (unread) detection:
 *   Case IDs that have been seen before are persisted in localStorage under
 *   SPM_SEEN_CASE_IDS. Any case_id not in that set is considered unread until
 *   the user explicitly marks it read (or uses "Mark all read").
 */
import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY    = 'spm_seen_case_ids'
const POLL_INTERVAL  = 30_000   // 30 s

// ── localStorage helpers ──────────────────────────────────────────────────────

function getSeenIds() {
  try {
    return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'))
  } catch {
    return new Set()
  }
}

function persistSeenId(id) {
  try {
    const ids = getSeenIds()
    ids.add(id)
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]))
  } catch { /* storage unavailable — silently skip */ }
}

// ── API fetch ─────────────────────────────────────────────────────────────────

async function fetchCasesFromApi() {
  const apiBase  = import.meta.env.VITE_API_URL || '/api'
  const raw      = import.meta.env.VITE_ORCHESTRATOR_URL || ''
  const orchBase = (raw && !raw.startsWith('http')) ? raw : `${apiBase}/v1`

  const tokenRes = await fetch(`${apiBase}/dev-token`)
  if (!tokenRes.ok) throw new Error('token-fetch-failed')
  const { token } = await tokenRes.json()

  const res = await fetch(`${orchBase}/cases`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`cases-fetch-failed-${res.status}`)
  const body = await res.json()
  return Array.isArray(body.cases) ? body.cases : []
}

// ── Shape adapter ─────────────────────────────────────────────────────────────

function riskToSeverity(score) {
  if (score >= 0.85) return 'Critical'
  if (score >= 0.65) return 'High'
  if (score >= 0.40) return 'Medium'
  return 'Low'
}

function relativeTime(isoString) {
  try {
    const diffMs  = Date.now() - new Date(isoString).getTime()
    const diffMin = Math.floor(diffMs / 60_000)
    if (diffMin < 2)    return 'Just now'
    if (diffMin < 60)   return `${diffMin}m ago`
    if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`
    return `${Math.floor(diffMin / 1440)}d ago`
  } catch {
    return 'Recently'
  }
}

function caseToNotification(c, seenIds) {
  const score = typeof c.risk_score === 'number' ? c.risk_score : 0.5
  const sev   = riskToSeverity(score)
  const type  = (sev === 'Critical' || sev === 'High') ? 'alert' : 'info'

  return {
    id:     c.case_id,
    type,
    title:  c.summary || `Case opened — ${c.reason || 'escalation'}`,
    sub:    `Risk ${sev} · session ${c.session_id?.slice(0, 8) ?? '?'}…`,
    time:   relativeTime(c.created_at),
    unread: !seenIds.has(c.case_id),
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * Returns:
 *   notifications  Array<{id, type, title, sub, time, unread}>
 *   markRead(id)   Mark a single notification read
 *   markAllRead()  Mark every notification read
 *   loading        true during the initial fetch
 *   error          true if the last fetch failed (API unavailable)
 */
export function useCaseNotifications() {
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState(false)

  const load = useCallback(async () => {
    try {
      const cases   = await fetchCasesFromApi()
      const seenIds = getSeenIds()

      // Sort: unread first, then newest-created last (API returns newest-first already)
      const notifs = cases.map(c => caseToNotification(c, seenIds))
      setNotifications(notifs)
      setError(false)
    } catch {
      setError(true)
      // Keep current state — don't clear existing notifications on transient failures
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial fetch + polling
  useEffect(() => {
    load()
    const timer = setInterval(load, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [load])

  const markRead = useCallback((id) => {
    persistSeenId(id)
    setNotifications(prev =>
      prev.map(n => n.id === id ? { ...n, unread: false } : n)
    )
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications(prev => {
      prev.forEach(n => persistSeenId(n.id))
      return prev.map(n => ({ ...n, unread: false }))
    })
  }, [])

  return { notifications, markRead, markAllRead, loading, error }
}
