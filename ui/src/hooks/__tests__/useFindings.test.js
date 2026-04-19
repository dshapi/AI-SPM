/**
 * hooks/__tests__/useFindings.test.js
 * ─────────────────────────────────────
 * Regression tests for useFindings hook.
 *
 * Verifies:
 *   1. Data is fetched on mount.
 *   2. Background polling fires every pollIntervalMs.
 *   3. Background poll does NOT set loading=true (silent refresh).
 *   4. Polling stops on unmount (interval cleared).
 *   5. Polling can be disabled by passing pollIntervalMs=0.
 *   6. refetch() triggers a foreground fetch (sets loading=true).
 *   7. Errors during background poll keep previous findings visible.
 *   8. Filter changes re-fetch with loading=true.
 *
 * Timer note: tests that check polling advance fake timers via
 * `vi.advanceTimersByTime()` inside `act()`.  We also flush microtasks
 * with a `Promise.resolve()` tick so that mocked API calls resolve.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFindings } from '../useFindings.js'

// ── Mock findingsApi ──────────────────────────────────────────────────────────
vi.mock('../../api/findingsApi.js', () => ({
  listFindings:        vi.fn(),
  getFinding:          vi.fn(),
  updateFindingStatus: vi.fn(),
  linkFindingCase:     vi.fn(),
}))

import { listFindings } from '../../api/findingsApi.js'

const MOCK_PAGE_1 = {
  items: [
    { id: 'f1', title: 'Finding 1', severity: 'High', status: 'Open',
      asset: { name: 'srv1' }, type: 'prompt_injection', risk_score: 0.8, confidence: 0.9 },
  ],
  total: 1,
}

const MOCK_PAGE_2 = {
  items: [
    ...MOCK_PAGE_1.items,
    { id: 'f2', title: 'New Finding', severity: 'Critical', status: 'Open',
      asset: { name: 'srv2' }, type: 'tool_abuse', risk_score: 0.95, confidence: 0.8 },
  ],
  total: 2,
}

/** Flush all pending microtasks (resolved promises) without advancing fake timers. */
const flushPromises = () => act(async () => { await Promise.resolve() })

beforeEach(() => {
  vi.useFakeTimers()
  listFindings.mockReset()
  listFindings.mockResolvedValue(MOCK_PAGE_1)
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

// ── Initial load ──────────────────────────────────────────────────────────────

describe('useFindings — initial load', () => {
  it('fetches findings on mount', async () => {
    const { result } = renderHook(() => useFindings())

    // Loading starts true before the async fetch completes
    expect(result.current.loading).toBe(true)

    await flushPromises()

    expect(listFindings).toHaveBeenCalledTimes(1)
    expect(result.current.findings).toHaveLength(1)
    expect(result.current.total).toBe(1)
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('exposes error when API fails on mount', async () => {
    listFindings.mockRejectedValueOnce(new Error('Server error'))

    const { result } = renderHook(() => useFindings())
    await flushPromises()

    expect(result.current.error).toBe('Server error')
    expect(result.current.loading).toBe(false)
  })
})

// ── Background polling ────────────────────────────────────────────────────────

describe('useFindings — background polling', () => {
  it('polls at the configured interval', async () => {
    const { result } = renderHook(() =>
      useFindings({}, { pollIntervalMs: 30_000 })
    )
    await flushPromises()
    expect(listFindings).toHaveBeenCalledTimes(1)  // initial mount

    // Advance one interval + flush the resulting promise
    listFindings.mockResolvedValueOnce(MOCK_PAGE_2)
    await act(async () => {
      vi.advanceTimersByTime(30_000)
      await Promise.resolve()
    })

    expect(listFindings).toHaveBeenCalledTimes(2)
    expect(result.current.findings).toHaveLength(2)
    expect(result.current.total).toBe(2)
  })

  it('does NOT set loading=true during a background poll', async () => {
    const { result } = renderHook(() =>
      useFindings({}, { pollIntervalMs: 30_000 })
    )
    await flushPromises()
    expect(result.current.loading).toBe(false)

    // Intercept poll call — don't resolve yet
    let pollResolve
    listFindings.mockReturnValueOnce(new Promise(r => { pollResolve = r }))

    await act(async () => { vi.advanceTimersByTime(30_000) })

    // Loading must remain false during a background poll
    expect(result.current.loading).toBe(false)

    // Resolve the poll
    await act(async () => {
      pollResolve(MOCK_PAGE_2)
      await Promise.resolve()
    })

    expect(result.current.findings).toHaveLength(2)
  })

  it('fires multiple polls over consecutive intervals', async () => {
    renderHook(() => useFindings({}, { pollIntervalMs: 10_000 }))
    await flushPromises()

    // Advance 3 intervals
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        vi.advanceTimersByTime(10_000)
        await Promise.resolve()
      })
    }

    // 1 mount + 3 polls
    expect(listFindings).toHaveBeenCalledTimes(4)
  })

  it('stops polling after unmount', async () => {
    const { unmount } = renderHook(() =>
      useFindings({}, { pollIntervalMs: 30_000 })
    )
    await flushPromises()
    const callsBefore = listFindings.mock.calls.length

    unmount()

    await act(async () => {
      vi.advanceTimersByTime(120_000)
      await Promise.resolve()
    })

    expect(listFindings.mock.calls.length).toBe(callsBefore)
  })

  it('disables polling when pollIntervalMs=0', async () => {
    renderHook(() => useFindings({}, { pollIntervalMs: 0 }))
    await flushPromises()
    const callsBefore = listFindings.mock.calls.length

    await act(async () => {
      vi.advanceTimersByTime(120_000)
      await Promise.resolve()
    })

    expect(listFindings.mock.calls.length).toBe(callsBefore)
  })

  it('defaults to a 30s polling interval when no opts provided', async () => {
    const { result } = renderHook(() => useFindings())
    await flushPromises()

    listFindings.mockResolvedValueOnce(MOCK_PAGE_2)
    await act(async () => {
      vi.advanceTimersByTime(30_000)
      await Promise.resolve()
    })

    expect(result.current.findings).toHaveLength(2)
  })
})

// ── Error handling ────────────────────────────────────────────────────────────

describe('useFindings — error handling', () => {
  it('keeps previous findings on background poll error', async () => {
    const { result } = renderHook(() =>
      useFindings({}, { pollIntervalMs: 30_000 })
    )
    await flushPromises()
    expect(result.current.findings).toHaveLength(1)

    listFindings.mockRejectedValueOnce(new Error('Network error'))
    await act(async () => {
      vi.advanceTimersByTime(30_000)
      await Promise.resolve()
    })

    // Previous data still visible — table not wiped on transient error
    expect(result.current.findings).toHaveLength(1)
    expect(result.current.loading).toBe(false)
  })
})

// ── refetch ───────────────────────────────────────────────────────────────────

describe('useFindings — refetch', () => {
  it('refetch() triggers a foreground fetch that sets loading=true', async () => {
    const { result } = renderHook(() => useFindings())
    await flushPromises()
    expect(result.current.loading).toBe(false)

    let resolveRefetch
    listFindings.mockReturnValueOnce(new Promise(r => { resolveRefetch = r }))

    // Start refetch
    act(() => { result.current.refetch() })
    expect(result.current.loading).toBe(true)

    // Resolve
    await act(async () => {
      resolveRefetch(MOCK_PAGE_2)
      await Promise.resolve()
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.findings).toHaveLength(2)
  })
})

// ── Filter change ─────────────────────────────────────────────────────────────

describe('useFindings — filter change', () => {
  it('re-fetches (with loading=true) when filters change', async () => {
    const { result, rerender } = renderHook(
      ({ filters }) => useFindings(filters),
      { initialProps: { filters: { severity: 'high' } } }
    )
    await flushPromises()
    expect(listFindings).toHaveBeenCalledTimes(1)

    listFindings.mockResolvedValueOnce(MOCK_PAGE_2)
    rerender({ filters: { severity: 'critical' } })

    // Should immediately enter loading state
    expect(result.current.loading).toBe(true)

    await flushPromises()

    expect(listFindings).toHaveBeenCalledTimes(2)
    expect(result.current.findings).toHaveLength(2)
    expect(result.current.loading).toBe(false)
  })
})
