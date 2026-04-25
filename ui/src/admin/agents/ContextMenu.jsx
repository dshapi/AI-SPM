// ui/src/admin/agents/ContextMenu.jsx
//
// Right-click context-menu primitive. Reusable beyond agents — kept in
// the agents/ folder for now since that's the only consumer in Phase 3.
// Move to ui/src/components/ContextMenu/ when a second consumer lands.
//
// Usage
// ─────
//
//   <ContextMenu items={[
//     { label: "Open Chat", icon: <MessageSquare/>,  onClick: () => ... },
//     { label: "Configure", icon: <Settings/>,       onClick: () => ... },
//     { kind:  "separator" },
//     { label: "Stop",      icon: <Square/>,         onClick: () => ...,
//       danger: true },
//     { label: "Retire",    icon: <Trash2/>,         onClick: () => ...,
//       danger: true,
//       confirm: { title: "Retire agent?",
//                  body:  "Stops container, deletes topics, drops the row.",
//                  cta:   "Retire" } },
//   ]}>
//     <tr>...</tr>
//   </ContextMenu>
//
// Behaviour
// ─────────
//   - Right-click on the wrapped child opens the menu at clientX/Y.
//   - Click outside, scroll, Escape, or Tab away → closes.
//   - Arrow keys move highlight; Enter activates; Esc closes.
//   - Items with `confirm` open a small modal that gates onClick.
//   - Disabled items render greyed-out and skip onClick.
//   - The wrapped child is rendered AS-IS — no wrapping div — so its
//     own click handlers, hover styles, and ARIA roles survive.

import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { createPortal } from "react-dom"


// ─── Position helper — keep menu inside the viewport ──────────────────────

function _clamp(x, y, menuWidth = 220, menuHeight = 280) {
  const vw = typeof window !== "undefined" ? window.innerWidth  : 1024
  const vh = typeof window !== "undefined" ? window.innerHeight : 768
  return {
    x: Math.min(x, Math.max(0, vw - menuWidth  - 8)),
    y: Math.min(y, Math.max(0, vh - menuHeight - 8)),
  }
}


// ─── Confirm modal ─────────────────────────────────────────────────────────

function ConfirmModal({ confirm, onConfirm, onCancel }) {
  const ctaRef = useRef(null)
  useEffect(() => { ctaRef.current?.focus() }, [])

  return createPortal(
    <div
      role="dialog" aria-modal="true"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
      onClick={onCancel}
    >
      <div
        className="bg-white rounded-lg shadow-xl border border-slate-200 p-5 w-[420px] max-w-[92vw]"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[14px] font-semibold text-slate-900 mb-2">
          {confirm.title}
        </h3>
        {confirm.body && (
          <p className="text-[12px] text-slate-600 mb-4">{confirm.body}</p>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-[12px] rounded-md border border-slate-300 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            ref={ctaRef}
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 text-[12px] rounded-md bg-rose-600 text-white hover:bg-rose-700"
          >
            {confirm.cta || "Confirm"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}


// ─── ContextMenu ───────────────────────────────────────────────────────────

/**
 * @param {object}   props
 * @param {Array}    props.items                — menu items (see usage above)
 * @param {React.ReactNode} props.children      — element to wrap (right-click target)
 * @param {(open:boolean)=>void} [props.onOpenChange]
 */
export default function ContextMenu({ items, children, onOpenChange }) {
  const [open,    setOpen]    = useState(false)
  const [pos,     setPos]     = useState({ x: 0, y: 0 })
  const [hl,      setHl]      = useState(0)             // highlighted index
  const [pending, setPending] = useState(null)          // item awaiting confirm

  const menuRef = useRef(null)

  const close = useCallback(() => {
    setOpen(false)
    setPending(null)
    if (onOpenChange) onOpenChange(false)
  }, [onOpenChange])

  // Close on click-outside / Escape / scroll / resize.
  useEffect(() => {
    if (!open) return
    const onDocClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) close()
    }
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close() }
    }
    const onScroll = () => close()
    const onResize = () => close()
    document.addEventListener("mousedown", onDocClick)
    document.addEventListener("keydown",   onKey)
    window  .addEventListener("scroll",    onScroll, true)
    window  .addEventListener("resize",    onResize)
    return () => {
      document.removeEventListener("mousedown", onDocClick)
      document.removeEventListener("keydown",   onKey)
      window  .removeEventListener("scroll",    onScroll, true)
      window  .removeEventListener("resize",    onResize)
    }
  }, [open, close])

  // Keyboard nav — arrows + Enter once the menu is open.
  useEffect(() => {
    if (!open) return
    const indexable = items
      .map((it, i) => ({ it, i }))
      .filter(({ it }) => it.kind !== "separator" && !it.disabled)

    const onKey = (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault()
        const cur = indexable.findIndex(({ i }) => i === hl)
        const dir = e.key === "ArrowDown" ? 1 : -1
        const next = (cur + dir + indexable.length) % indexable.length
        setHl(indexable[next].i)
      } else if (e.key === "Enter") {
        e.preventDefault()
        _activate(items[hl])
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, hl, items])

  const _activate = (item) => {
    if (!item || item.kind === "separator" || item.disabled) return
    if (item.confirm) {
      setPending(item)
    } else {
      close()
      // Defer the callback to the next tick so the menu unmounts first.
      // Without this, fast onClick handlers can race with the close
      // animation and the menu briefly flashes back open.
      setTimeout(() => item.onClick && item.onClick(), 0)
    }
  }

  // Open the menu on right-click of the wrapped child.
  const onContextMenu = (e) => {
    e.preventDefault()
    e.stopPropagation()
    const { x, y } = _clamp(e.clientX, e.clientY)
    setPos({ x, y })
    setOpen(true)
    setHl(items.findIndex((it) => it.kind !== "separator" && !it.disabled) || 0)
    if (onOpenChange) onOpenChange(true)
  }

  // Inject onContextMenu onto the wrapped child without an extra div.
  // Falls back to wrapping in a span if children isn't a single element.
  const wrapped = useMemo(() => {
    if (isValidElement(children)) {
      const existing = children.props.onContextMenu
      return cloneElement(children, {
        onContextMenu: (e) => {
          if (existing) existing(e)
          if (e.defaultPrevented) return
          onContextMenu(e)
        },
      })
    }
    return (
      <span onContextMenu={onContextMenu}>{children}</span>
    )
  }, [children])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {wrapped}
      {open && createPortal(
        <ul
          ref={menuRef}
          role="menu"
          tabIndex={-1}
          className={
            "fixed z-50 min-w-[180px] py-1 rounded-md shadow-lg " +
            "bg-white border border-slate-200 text-[12px]"
          }
          style={{ top: pos.y, left: pos.x }}
          onContextMenu={(e) => e.preventDefault()}
        >
          {items.map((item, i) => {
            if (item.kind === "separator") {
              return (
                <li
                  key={`sep-${i}`}
                  role="separator"
                  className="my-1 border-t border-slate-100"
                />
              )
            }
            const danger   = !!item.danger
            const disabled = !!item.disabled
            return (
              <li
                key={item.label || `item-${i}`}
                role="menuitem"
                aria-disabled={disabled || undefined}
                className={
                  "px-3 py-1.5 cursor-pointer flex items-center gap-2 " +
                  (disabled
                    ? "text-slate-400 cursor-not-allowed "
                    : "hover:bg-slate-50 ") +
                  (i === hl && !disabled ? "bg-slate-50 " : "") +
                  (danger && !disabled ? "text-rose-600 " : "text-slate-700 ")
                }
                onMouseEnter={() => !disabled && setHl(i)}
                onClick={() => _activate(item)}
              >
                {item.icon && (
                  <span className="opacity-80" aria-hidden>{item.icon}</span>
                )}
                <span>{item.label}</span>
              </li>
            )
          })}
        </ul>,
        document.body,
      )}
      {pending && (
        <ConfirmModal
          confirm={pending.confirm}
          onConfirm={() => {
            const fn = pending.onClick
            close()
            setTimeout(() => fn && fn(), 0)
          }}
          onCancel={() => setPending(null)}
        />
      )}
    </>
  )
}
