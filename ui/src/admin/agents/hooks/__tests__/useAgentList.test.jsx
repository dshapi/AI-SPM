// ui/src/admin/agents/hooks/__tests__/useAgentList.test.jsx
//
// Tests for the live-polling hook + the mergeAgents helper.

import { renderHook, waitFor, act } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as agentsApi from "../../../api/agents"
import { mergeAgents, useAgentList } from "../useAgentList"


// ─── mergeAgents (pure) ────────────────────────────────────────────────────

describe("mergeAgents", () => {
  const mocks = [
    { id: "mock-1", name: "Alpha",   risk: "low" },
    { id: "mock-2", name: "Bravo",   risk: "high" },
    { id: "mock-3", name: "Charlie", risk: "medium" },
  ]

  it("returns mocks tagged when there is no live data", () => {
    const out = mergeAgents(mocks, [])
    expect(out).toHaveLength(3)
    expect(out.every(r => r._source === "mock")).toBe(true)
  })

  it("live rows replace mocks of the same name", () => {
    const live = [{ id: "ag-001", name: "Alpha", risk: "critical" }]
    const out  = mergeAgents(mocks, live)
    expect(out).toHaveLength(3)
    const alpha = out.find(r => r.name === "Alpha")
    expect(alpha._source).toBe("live")
    expect(alpha.id).toBe("ag-001")
    // The other mocks survive.
    expect(out.find(r => r.name === "Bravo")._source).toBe("mock")
  })

  it("keeps live rows that are NOT in the mock catalog", () => {
    const live = [{ id: "ag-007", name: "Hotel", risk: "low" }]
    const out  = mergeAgents(mocks, live)
    expect(out.find(r => r.name === "Hotel")._source).toBe("live")
    // Mocks all still present (none of them named Hotel).
    expect(out.filter(r => r._source === "mock")).toHaveLength(3)
  })

  it("tolerates null / undefined inputs", () => {
    expect(mergeAgents(null, undefined)).toEqual([])
    expect(mergeAgents(undefined, [{ name: "X" }])).toHaveLength(1)
  })
})


// ─── useAgentList (hook) ───────────────────────────────────────────────────

describe("useAgentList", () => {
  let listAgentsSpy
  beforeEach(() => {
    listAgentsSpy = vi.spyOn(agentsApi, "listAgents").mockResolvedValue([])
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  // Use the smallest interval the hook will accept (clamped to >=500 in
  // production, but tests override via the .min). We use 50ms which is
  // below the clamp — the hook clamps it back up to 500ms internally,
  // so tests poll on a controlled cadence without fake-timers headaches.

  it("starts with loading=true and an empty live list", async () => {
    listAgentsSpy.mockResolvedValueOnce([{ id: "ag-1", name: "x" }])

    const { result } = renderHook(() => useAgentList({ pollMs: 1000 }))

    expect(result.current.loading).toBe(true)
    expect(result.current.live).toEqual([])

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.live).toEqual([{ id: "ag-1", name: "x" }])
  })

  it("re-polls after the configured interval", async () => {
    listAgentsSpy
      .mockResolvedValueOnce([{ id: "ag-1", name: "first"  }])
      .mockResolvedValue    ([{ id: "ag-1", name: "second" }])  // any later tick

    // 600ms is just above the hook's 500ms internal clamp.
    const { result } = renderHook(() => useAgentList({ pollMs: 600 }))

    await waitFor(() => expect(result.current.live[0]?.name).toBe("first"),
                   { timeout: 1500 })
    await waitFor(() => expect(result.current.live[0]?.name).toBe("second"),
                   { timeout: 2500 })
  })

  it("captures errors without throwing", async () => {
    listAgentsSpy.mockRejectedValueOnce(new Error("boom"))
    const { result } = renderHook(() => useAgentList({ pollMs: 1000 }))
    await waitFor(() => expect(result.current.error).toBeTruthy())
    expect(result.current.error.message).toBe("boom")
  })

  it("stops polling on unmount", async () => {
    const { unmount } = renderHook(() => useAgentList({ pollMs: 600 }))

    await waitFor(() => expect(listAgentsSpy).toHaveBeenCalledTimes(1))
    unmount()

    const callsAtUnmount = listAgentsSpy.mock.calls.length

    // Wait long enough that two more ticks WOULD have fired if the
    // interval were still alive. Then assert no new calls.
    await new Promise(r => setTimeout(r, 1300))
    expect(listAgentsSpy.mock.calls.length).toBe(callsAtUnmount)
  })
})
