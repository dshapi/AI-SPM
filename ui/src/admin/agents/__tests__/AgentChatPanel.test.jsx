// ui/src/admin/agents/__tests__/AgentChatPanel.test.jsx

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import AgentChatPanel from "../AgentChatPanel"


// ─── SSE mock — turn an array of "data: …" lines into a streaming Response

function _sseResponse(chunks) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  })
}


const RUNNING = {
  id: "ag-1", name: "Test", runtime_state: "running", risk: "low",
}
const STOPPED = { ...RUNNING, runtime_state: "stopped" }


beforeEach(() => {
  global.fetch = vi.fn(async (url, opts) => {
    if (typeof url === "string" && url.endsWith("/api/dev-token")) {
      return new Response(
        JSON.stringify({ token: "tok", expires_in: 3600 }),
        { status: 200 },
      )
    }
    return new Response("", { status: 500 })  // tests override
  })
})
afterEach(() => vi.restoreAllMocks())


describe("AgentChatPanel — visibility", () => {
  it("renders nothing when not open", () => {
    const { container } = render(<AgentChatPanel open={false} agent={RUNNING} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing without an agent", () => {
    const { container } = render(<AgentChatPanel open agent={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("shows agent name in header when open", () => {
    render(<AgentChatPanel open agent={RUNNING} />)
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Test")
  })
})


describe("AgentChatPanel — composer", () => {
  it("disables the textarea when agent is not running", () => {
    render(<AgentChatPanel open agent={STOPPED} />)
    expect(screen.getByPlaceholderText(/start it to chat/i)).toBeDisabled()
  })

  it("Send button is disabled until there's a message", () => {
    render(<AgentChatPanel open agent={RUNNING} />)
    const send = screen.getByRole("button", { name: /send message/i })
    expect(send).toBeDisabled()
  })

  it("close button fires onClose", () => {
    const onClose = vi.fn()
    render(<AgentChatPanel open agent={RUNNING} onClose={onClose} />)
    fireEvent.click(screen.getByLabelText(/close chat/i))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})


describe("AgentChatPanel — round trip", () => {
  it("sends a message and renders the streamed reply", async () => {
    global.fetch = vi.fn(async (url) => {
      if (typeof url === "string" && url.endsWith("/api/dev-token")) {
        return new Response(
          JSON.stringify({ token: "tok", expires_in: 3600 }),
          { status: 200 },
        )
      }
      // Two token chunks then a done.
      return _sseResponse([
        'data: {"type":"token","text":"hi "}\n',
        'data: {"type":"token","text":"there"}\n',
        'data: {"type":"done","text":"hi there"}\n',
      ])
    })

    render(<AgentChatPanel open agent={RUNNING} />)
    const input = screen.getByPlaceholderText(/Message Test/i)
    fireEvent.change(input, { target: { value: "hello" } })
    fireEvent.click(screen.getByRole("button", { name: /send message/i }))

    // The user turn shows up immediately.
    await waitFor(() => {
      expect(screen.getByText("hello")).toBeInTheDocument()
    })

    // The agent turn populates from the SSE stream.
    await waitFor(() => {
      expect(screen.getByText("hi there")).toBeInTheDocument()
    }, { timeout: 2000 })
  })

  it("renders an error indicator when the request fails", async () => {
    global.fetch = vi.fn(async (url) => {
      if (typeof url === "string" && url.endsWith("/api/dev-token")) {
        return new Response(
          JSON.stringify({ token: "tok", expires_in: 3600 }),
          { status: 200 },
        )
      }
      return new Response("server died", { status: 500 })
    })

    render(<AgentChatPanel open agent={RUNNING} />)
    fireEvent.change(screen.getByPlaceholderText(/Message Test/i), {
      target: { value: "x" },
    })
    fireEvent.click(screen.getByRole("button", { name: /send message/i }))

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument(),
                   { timeout: 2000 })
  })
})
