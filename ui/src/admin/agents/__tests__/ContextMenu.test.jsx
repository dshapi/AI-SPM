// ui/src/admin/agents/__tests__/ContextMenu.test.jsx

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import ContextMenu from "../ContextMenu"


function _items({ onOpenChat = vi.fn(), onStop = vi.fn(), onRetire = vi.fn() } = {}) {
  return [
    { label: "Open Chat", onClick: onOpenChat },
    { label: "Configure", onClick: vi.fn() },
    { kind: "separator" },
    { label: "Stop",   onClick: onStop, danger: true },
    { label: "Retire", onClick: onRetire, danger: true,
      confirm: { title: "Retire?", body: "irreversible", cta: "Retire" } },
    { label: "Disabled-thing", onClick: vi.fn(), disabled: true },
  ]
}


describe("ContextMenu — open / close", () => {
  it("does not render the menu by default", () => {
    render(<ContextMenu items={_items()}><tr><td>row</td></tr></ContextMenu>)
    expect(screen.queryByRole("menu")).toBeNull()
  })

  it("right-click opens the menu", () => {
    const onOpenChange = vi.fn()
    render(
      <ContextMenu items={_items()} onOpenChange={onOpenChange}>
        <div data-testid="row">row</div>
      </ContextMenu>
    )
    fireEvent.contextMenu(screen.getByTestId("row"), { clientX: 50, clientY: 60 })
    expect(screen.getByRole("menu")).toBeInTheDocument()
    expect(onOpenChange).toHaveBeenCalledWith(true)
  })

  it("Escape closes the menu", () => {
    render(
      <ContextMenu items={_items()}><div data-testid="row">row</div></ContextMenu>
    )
    fireEvent.contextMenu(screen.getByTestId("row"))
    expect(screen.getByRole("menu")).toBeInTheDocument()
    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.queryByRole("menu")).toBeNull()
  })

  it("click outside closes the menu", () => {
    render(
      <div>
        <ContextMenu items={_items()}><div data-testid="row">row</div></ContextMenu>
        <div data-testid="outside">elsewhere</div>
      </div>
    )
    fireEvent.contextMenu(screen.getByTestId("row"))
    expect(screen.getByRole("menu")).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByTestId("outside"))
    expect(screen.queryByRole("menu")).toBeNull()
  })
})


describe("ContextMenu — items", () => {
  it("renders separator items as role=separator", () => {
    render(<ContextMenu items={_items()}><div data-testid="row">row</div></ContextMenu>)
    fireEvent.contextMenu(screen.getByTestId("row"))
    expect(screen.getAllByRole("separator")).toHaveLength(1)
  })

  it("clicking a non-confirm item fires onClick and closes the menu", async () => {
    const onOpenChat = vi.fn()
    render(
      <ContextMenu items={_items({ onOpenChat })}>
        <div data-testid="row">row</div>
      </ContextMenu>
    )
    fireEvent.contextMenu(screen.getByTestId("row"))
    fireEvent.click(screen.getByText("Open Chat"))
    await waitFor(() => expect(onOpenChat).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole("menu")).toBeNull()
  })

  it("disabled items don't fire onClick", () => {
    const items = [
      { label: "Disabled", onClick: vi.fn(), disabled: true },
    ]
    render(
      <ContextMenu items={items}><div data-testid="row">row</div></ContextMenu>
    )
    fireEvent.contextMenu(screen.getByTestId("row"))
    fireEvent.click(screen.getByText("Disabled"))
    expect(items[0].onClick).not.toHaveBeenCalled()
  })
})


describe("ContextMenu — confirm modal", () => {
  it("clicking a confirm item opens a dialog instead of firing onClick", () => {
    const onRetire = vi.fn()
    render(
      <ContextMenu items={_items({ onRetire })}>
        <div data-testid="row">row</div>
      </ContextMenu>
    )
    fireEvent.contextMenu(screen.getByTestId("row"))
    fireEvent.click(screen.getByText("Retire"))

    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(onRetire).not.toHaveBeenCalled()
  })

  it("Cancel closes the dialog without firing onClick", () => {
    const onRetire = vi.fn()
    render(
      <ContextMenu items={_items({ onRetire })}>
        <div data-testid="row">row</div>
      </ContextMenu>
    )
    fireEvent.contextMenu(screen.getByTestId("row"))
    fireEvent.click(screen.getByText("Retire"))
    fireEvent.click(screen.getByText("Cancel"))
    expect(onRetire).not.toHaveBeenCalled()
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("clicking the dialog CTA fires onClick", async () => {
    const onRetire = vi.fn()
    render(
      <ContextMenu items={_items({ onRetire })}>
        <div data-testid="row">row</div>
      </ContextMenu>
    )
    fireEvent.contextMenu(screen.getByTestId("row"))
    fireEvent.click(screen.getByText("Retire"))
    // Two "Retire" buttons exist now: the menu item (still in the DOM
    // until close) and the modal CTA. Find the one inside role=dialog.
    const dialog = screen.getByRole("dialog")
    const cta = dialog.querySelector("button.bg-rose-600")
    fireEvent.click(cta)
    await waitFor(() => expect(onRetire).toHaveBeenCalledTimes(1))
  })
})


describe("ContextMenu — wrapped child preservation", () => {
  it("preserves the child's existing onClick handler", () => {
    const onRowClick = vi.fn()
    render(
      <ContextMenu items={_items()}>
        <div data-testid="row" onClick={onRowClick}>row</div>
      </ContextMenu>
    )
    fireEvent.click(screen.getByTestId("row"))
    expect(onRowClick).toHaveBeenCalled()
  })

  it("does NOT add a wrapping element when child is a valid element", () => {
    const { container } = render(
      <ContextMenu items={_items()}>
        <button data-testid="row">row</button>
      </ContextMenu>
    )
    // Top-level child of the render container is the button itself,
    // not a wrapping span/div.
    expect(container.firstChild.tagName).toBe("BUTTON")
  })
})
