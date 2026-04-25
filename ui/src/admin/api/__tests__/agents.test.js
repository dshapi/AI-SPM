// ui/src/admin/api/__tests__/agents.test.js
//
// Unit tests for the agents API client. We mock global.fetch and
// verify the wire — URL, method, headers, body — for each function.
// XHR-based uploads are exercised by stubbing XMLHttpRequest.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  __internals,
  createAgentWithFile,
  deleteAgent,
  getAgent,
  listAgents,
  patchAgent,
  startAgent,
  stopAgent,
} from "../agents"


// ─── Shared setup ──────────────────────────────────────────────────────────

const ORIGINAL_FETCH = global.fetch
const ORIGINAL_XHR   = global.XMLHttpRequest

beforeEach(() => {
  // Reset the module's token cache so each test starts cold and can
  // assert on the dev-token fetch. Without this the cache persists
  // across tests because the module is imported once.
  __internals._resetTokenCache()

  // Stub the dev-token endpoint so getToken() returns a deterministic
  // value for every test. listAgents()/getAgent()/etc. then make the
  // *second* fetch call — so we always assert on .mock.calls[1].
  global.fetch = vi.fn(async (url) => {
    if (typeof url === "string" && url.endsWith("/api/dev-token")) {
      return new Response(
        JSON.stringify({ token: "test-token", expires_in: 3600 }),
        { status: 200 },
      )
    }
    // Tests override this case explicitly.
    return new Response("", { status: 500 })
  })
})

afterEach(() => {
  global.fetch         = ORIGINAL_FETCH
  global.XMLHttpRequest = ORIGINAL_XHR
  vi.restoreAllMocks()
})


function _setApiResponse({ status = 200, json = null, text = "" } = {}) {
  global.fetch.mockImplementation(async (url) => {
    if (typeof url === "string" && url.endsWith("/api/dev-token")) {
      return new Response(
        JSON.stringify({ token: "test-token", expires_in: 3600 }),
        { status: 200 },
      )
    }
    // 204/205/304 are "null body" statuses — the Response constructor
    // throws if body is non-null. Use null body for those.
    const isNullBodyStatus = [204, 205, 304].includes(status)
    if (isNullBodyStatus) {
      return new Response(null, { status })
    }
    if (json !== null) {
      return new Response(JSON.stringify(json), { status })
    }
    return new Response(text, { status })
  })
}


// ─── listAgents ────────────────────────────────────────────────────────────

describe("listAgents", () => {
  it("GETs /api/spm/agents with bearer token", async () => {
    _setApiResponse({ json: [{ id: "ag-001", name: "x" }] })

    const out = await listAgents()
    expect(out).toEqual([{ id: "ag-001", name: "x" }])

    // dev-token is fetch[0]; the API call is fetch[1].
    const apiCall = global.fetch.mock.calls.find(
      ([u]) => typeof u === "string" && u.endsWith("/api/spm/agents"),
    )
    expect(apiCall).toBeTruthy()
    const [, opts] = apiCall
    expect(opts.headers.Authorization).toBe("Bearer test-token")
  })

  it("returns [] on non-array response", async () => {
    _setApiResponse({ json: { unexpected: "shape" } })
    expect(await listAgents()).toEqual([])
  })

  it("throws structured error on non-2xx", async () => {
    _setApiResponse({ status: 500, json: { detail: "boom" } })
    await expect(listAgents()).rejects.toMatchObject({
      message: "boom",
      status:  500,
    })
  })
})


// ─── getAgent ──────────────────────────────────────────────────────────────

describe("getAgent", () => {
  it("requires agentId", async () => {
    await expect(getAgent("")).rejects.toThrow(/agentId required/)
  })

  it("GETs /api/spm/agents/{id}", async () => {
    _setApiResponse({ json: { id: "ag-001", name: "x" } })
    const out = await getAgent("ag-001")
    expect(out).toEqual({ id: "ag-001", name: "x" })

    const apiCall = global.fetch.mock.calls.find(
      ([u]) => typeof u === "string" && u.endsWith("/agents/ag-001"),
    )
    expect(apiCall).toBeTruthy()
  })

  it("404 surfaces as Error with status", async () => {
    _setApiResponse({ status: 404, json: { detail: "agent not found" } })
    await expect(getAgent("nope")).rejects.toMatchObject({
      message: "agent not found",
      status:  404,
    })
  })
})


// ─── patchAgent ────────────────────────────────────────────────────────────

describe("patchAgent", () => {
  it("PATCHes JSON body and returns the row", async () => {
    _setApiResponse({ json: { id: "ag-001", description: "updated" } })
    const out = await patchAgent("ag-001", { description: "updated" })
    expect(out.description).toBe("updated")

    const apiCall = global.fetch.mock.calls.find(
      ([u]) => typeof u === "string" && u.endsWith("/agents/ag-001"),
    )
    const [, opts] = apiCall
    expect(opts.method).toBe("PATCH")
    expect(JSON.parse(opts.body)).toEqual({ description: "updated" })
    expect(opts.headers["Content-Type"]).toBe("application/json")
  })

  it("400 with disallowed field surfaces detail", async () => {
    _setApiResponse({
      status: 400,
      json: { detail: "unknown / disallowed fields: ['mcp_token']" },
    })
    await expect(patchAgent("ag-001", { mcp_token: "x" })).rejects.toMatchObject({
      status: 400,
    })
  })
})


// ─── deleteAgent ───────────────────────────────────────────────────────────

describe("deleteAgent", () => {
  it("DELETEs and resolves on 204", async () => {
    _setApiResponse({ status: 204, text: "" })
    await expect(deleteAgent("ag-001")).resolves.toBeUndefined()

    const apiCall = global.fetch.mock.calls.find(
      ([u]) => typeof u === "string" && u.endsWith("/agents/ag-001"),
    )
    expect(apiCall[1].method).toBe("DELETE")
  })

  it("rejects on non-2xx", async () => {
    _setApiResponse({ status: 404, json: { detail: "missing" } })
    await expect(deleteAgent("nope")).rejects.toMatchObject({ status: 404 })
  })
})


// ─── startAgent / stopAgent ────────────────────────────────────────────────

describe("lifecycle endpoints", () => {
  it("startAgent POSTs /agents/{id}/start", async () => {
    _setApiResponse({ status: 202, json: { status: "starting" } })
    const out = await startAgent("ag-001")
    expect(out.status).toBe("starting")

    const apiCall = global.fetch.mock.calls.find(
      ([u]) => typeof u === "string" && u.endsWith("/agents/ag-001/start"),
    )
    expect(apiCall[1].method).toBe("POST")
  })

  it("stopAgent POSTs /agents/{id}/stop", async () => {
    _setApiResponse({ status: 202, json: { status: "stopping" } })
    const out = await stopAgent("ag-001")
    expect(out.status).toBe("stopping")

    const apiCall = global.fetch.mock.calls.find(
      ([u]) => typeof u === "string" && u.endsWith("/agents/ag-001/stop"),
    )
    expect(apiCall[1].method).toBe("POST")
  })
})


// ─── createAgentWithFile (XHR multipart) ───────────────────────────────────

class FakeXHR {
  constructor() {
    this.upload  = {}
    this.headers = {}
    this.method  = null
    this.url     = null
    this.sent    = null
    this.status  = 0
    this.responseText = ""
  }
  open(method, url) { this.method = method; this.url = url }
  setRequestHeader(k, v) { this.headers[k] = v }
  send(body) {
    this.sent = body
    // schedule the configured response on next tick so the await in the
    // promise has a chance to set up onload first.
    setTimeout(() => {
      this.status       = FakeXHR.nextStatus       ?? 201
      this.responseText = FakeXHR.nextResponseText ?? '{"id":"ag-new"}'
      if (this.onload) this.onload()
    }, 0)
  }
  abort() { if (this.onabort) this.onabort() }
}
FakeXHR.nextStatus       = null
FakeXHR.nextResponseText = null


describe("createAgentWithFile", () => {
  it("rejects if file missing", async () => {
    await expect(
      createAgentWithFile({ name: "x", version: "1", agentType: "custom" })
    ).rejects.toThrow(/file required/)
  })

  it("POSTs multipart and resolves with the new agent", async () => {
    global.XMLHttpRequest = FakeXHR
    FakeXHR.nextStatus       = 201
    FakeXHR.nextResponseText = '{"id":"ag-new","name":"x","runtime_state":"stopped"}'

    const file = new File(
      ["import asyncio\nasync def main():\n    pass\n"],
      "agent.py",
      { type: "text/x-python" },
    )

    let progressSeen = false
    // Capture the XHR instance to drive progress events.
    const orig = FakeXHR.prototype.send
    FakeXHR.prototype.send = function (body) {
      if (this.upload.onprogress) {
        this.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 })
      }
      orig.call(this, body)
    }

    try {
      const out = await createAgentWithFile({
        name: "x", version: "1.0", agentType: "custom",
        file,
        onProgress: (pct) => { if (pct === 50) progressSeen = true },
      })
      expect(out.id).toBe("ag-new")
      expect(out.runtime_state).toBe("stopped")
      expect(progressSeen).toBe(true)
    } finally {
      FakeXHR.prototype.send = orig
    }
  })

  it("rejects on validation failure (422 with detail array)", async () => {
    global.XMLHttpRequest = FakeXHR
    FakeXHR.nextStatus       = 422
    FakeXHR.nextResponseText = JSON.stringify({
      detail: ["Python syntax error at line 1: invalid syntax"],
    })

    const file = new File(["bad("], "agent.py")
    await expect(
      createAgentWithFile({
        name: "x", version: "1", agentType: "custom", file,
      })
    ).rejects.toMatchObject({ status: 422 })
  })

  it("respects abort signal", async () => {
    global.XMLHttpRequest = FakeXHR

    const ac   = new AbortController()
    const file = new File(["async def main(): pass"], "agent.py")

    const p = createAgentWithFile({
      name: "x", version: "1", agentType: "custom",
      file, signal: ac.signal,
    })
    ac.abort()

    await expect(p).rejects.toMatchObject({ aborted: true })
  })
})


// ─── Token caching ─────────────────────────────────────────────────────────

describe("token caching", () => {
  it("re-uses the same token across calls within the freshness window", async () => {
    _setApiResponse({ json: [] })
    await listAgents()
    await listAgents()

    const tokenCalls = global.fetch.mock.calls.filter(
      ([u]) => typeof u === "string" && u.endsWith("/api/dev-token"),
    )
    expect(tokenCalls).toHaveLength(1)
  })
})
