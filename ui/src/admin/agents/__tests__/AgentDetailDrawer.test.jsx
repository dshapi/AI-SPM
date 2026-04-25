// ui/src/admin/agents/__tests__/AgentDetailDrawer.test.jsx
//
// The drawer is a thin shell around 5 tabs; the tabs themselves are
// covered by their own tests. Here we verify the shell behaviour:
// open/close, tab switching, header content, agent-prop syncing.

import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as agentsApi from "../../api/agents"
import AgentDetailDrawer from "../AgentDetailDrawer"


const AGENT = {
  id:             "ag-001",
  name:           "Test-Agent",
  version:        "1.0",
  agent_type:     "langchain",
  provider:       "internal",
  owner:          "ml",
  description:    "test",
  risk:           "high",
  policy_status:  "partial",
  runtime_state:  "running",
  code_path:      "/agents/x/agent.py",
  code_sha256:    "deadbeef",
}


function _render(ui) {
  // The Lineage tab uses <Link> from react-router; provide a router
  // context so render() doesn't blow up.
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}


beforeEach(() => {
  // ConfigureTab can issue a PATCH if a save fires; spy so live tests
  // don't hit network even if a future test forgets to mock.
  vi.spyOn(agentsApi, "patchAgent").mockResolvedValue(AGENT)
  vi.spyOn(agentsApi, "startAgent").mockResolvedValue({ status: "starting" })
  vi.spyOn(agentsApi, "stopAgent").mockResolvedValue({ status: "stopping" })
})
afterEach(() => vi.restoreAllMocks())


describe("AgentDetailDrawer — shell", () => {
  it("renders nothing when not open", () => {
    const { container } = _render(<AgentDetailDrawer open={false} agent={AGENT} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when agent is null", () => {
    const { container } = _render(<AgentDetailDrawer open={true} agent={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders the agent name + meta in the header", () => {
    _render(<AgentDetailDrawer open agent={AGENT} />)
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Test-Agent")
  })

  it("X button fires onClose", () => {
    const onClose = vi.fn()
    _render(<AgentDetailDrawer open agent={AGENT} onClose={onClose} />)
    fireEvent.click(screen.getByLabelText(/close drawer/i))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})


describe("AgentDetailDrawer — tabs", () => {
  it("defaults to the Overview tab", () => {
    _render(<AgentDetailDrawer open agent={AGENT} />)
    const overview = screen.getByRole("tab", { name: "Overview" })
    expect(overview).toHaveAttribute("aria-selected", "true")
  })

  it("clicking Configure switches the active tab", () => {
    _render(<AgentDetailDrawer open agent={AGENT} />)
    fireEvent.click(screen.getByRole("tab", { name: "Configure" }))
    expect(screen.getByRole("tab", { name: "Configure" }))
      .toHaveAttribute("aria-selected", "true")
    // Overview is no longer selected.
    expect(screen.getByRole("tab", { name: "Overview" }))
      .toHaveAttribute("aria-selected", "false")
  })

  it("renders all 5 tabs in order", () => {
    _render(<AgentDetailDrawer open agent={AGENT} />)
    const tabs = screen.getAllByRole("tab").map(t => t.getAttribute("data-tab-key"))
    expect(tabs).toEqual(["overview", "configure", "activity", "sessions", "lineage"])
  })
})


describe("AgentDetailDrawer — Overview integration", () => {
  it("Open Chat button fires onOpenChat", () => {
    const onOpenChat = vi.fn()
    _render(<AgentDetailDrawer open agent={AGENT} onOpenChat={onOpenChat} />)
    fireEvent.click(screen.getByRole("button", { name: /open chat/i }))
    expect(onOpenChat).toHaveBeenCalled()
  })

  it("run/stop toggle is rendered with the right runtime state", () => {
    _render(<AgentDetailDrawer open agent={AGENT} />)
    expect(screen.getByTestId("runtime-state-label")).toHaveTextContent("running")
    // Running → button label is Stop
    expect(screen.getByRole("button", { name: /stop agent/i })).toBeInTheDocument()
  })
})
