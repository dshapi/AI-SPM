// ui/src/admin/agents/__tests__/AgentRunStopToggle.test.jsx

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import * as agentsApi from "../../api/agents"
import AgentRunStopToggle from "../AgentRunStopToggle"


const RUNNING  = { id: "ag-1", runtime_state: "running" }
const STOPPED  = { id: "ag-1", runtime_state: "stopped" }
const STARTING = { id: "ag-1", runtime_state: "starting" }
const CRASHED  = { id: "ag-1", runtime_state: "crashed" }


beforeEach(() => {
  vi.spyOn(agentsApi, "startAgent").mockResolvedValue({ status: "starting" })
  vi.spyOn(agentsApi, "stopAgent").mockResolvedValue({ status: "stopping" })
})

afterEach(() => {
  vi.restoreAllMocks()
})


describe("AgentRunStopToggle — state-driven label + icon", () => {
  it("renders Start when stopped", () => {
    render(<AgentRunStopToggle agent={STOPPED} />)
    expect(screen.getByRole("button")).toHaveTextContent(/start/i)
  })

  it("renders Stop when running", () => {
    render(<AgentRunStopToggle agent={RUNNING} />)
    expect(screen.getByRole("button")).toHaveTextContent(/stop/i)
  })

  it("renders Restart when crashed", () => {
    render(<AgentRunStopToggle agent={CRASHED} />)
    expect(screen.getByRole("button")).toHaveTextContent(/restart/i)
  })

  it("renders disabled Starting… while transitioning", () => {
    render(<AgentRunStopToggle agent={STARTING} />)
    const btn = screen.getByRole("button")
    expect(btn).toBeDisabled()
    expect(btn).toHaveTextContent(/starting/i)
  })

  it("returns null when agent is missing or has no id", () => {
    const { container } = render(<AgentRunStopToggle agent={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})


describe("AgentRunStopToggle — actions", () => {
  it("clicking Start calls startAgent and fires onChange", async () => {
    const onChange = vi.fn()
    render(<AgentRunStopToggle agent={STOPPED} onChange={onChange} />)
    fireEvent.click(screen.getByRole("button"))

    await waitFor(() => expect(agentsApi.startAgent).toHaveBeenCalledWith("ag-1"))
    expect(onChange).toHaveBeenCalledWith("starting")
  })

  it("clicking Stop calls stopAgent and fires onChange", async () => {
    const onChange = vi.fn()
    render(<AgentRunStopToggle agent={RUNNING} onChange={onChange} />)
    fireEvent.click(screen.getByRole("button"))

    await waitFor(() => expect(agentsApi.stopAgent).toHaveBeenCalledWith("ag-1"))
    expect(onChange).toHaveBeenCalledWith("stopped")
  })

  it("crashed → Restart triggers startAgent (not stopAgent)", async () => {
    render(<AgentRunStopToggle agent={CRASHED} />)
    fireEvent.click(screen.getByRole("button"))
    await waitFor(() => expect(agentsApi.startAgent).toHaveBeenCalled())
    expect(agentsApi.stopAgent).not.toHaveBeenCalled()
  })

  it("surfaces API errors inline without unmounting the button", async () => {
    agentsApi.startAgent.mockRejectedValueOnce(
      Object.assign(new Error("Permission denied"), { status: 403 })
    )
    render(<AgentRunStopToggle agent={STOPPED} />)
    fireEvent.click(screen.getByRole("button"))
    // The error indicator (alert role) appears.
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument())
    // Button is still there for retry.
    expect(screen.getByRole("button")).toBeInTheDocument()
  })

  it("stops event propagation so row click handlers don't fire", () => {
    const rowClick = vi.fn()
    render(
      <div onClick={rowClick}>
        <AgentRunStopToggle agent={RUNNING} />
      </div>
    )
    fireEvent.click(screen.getByRole("button"))
    expect(rowClick).not.toHaveBeenCalled()
  })
})
