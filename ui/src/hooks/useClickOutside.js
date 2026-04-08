import { useEffect } from 'react'

/**
 * useClickOutside — fires `handler` when a mousedown event occurs
 * outside all provided refs.
 *
 * @param {React.RefObject | React.RefObject[]} refs   — one or many refs
 * @param {(e: MouseEvent) => void}             handler — callback
 *
 * Usage (single ref):
 *   const ref = useRef(null)
 *   useClickOutside(ref, () => setOpen(false))
 *
 * Usage (multiple refs — e.g. button + dropdown):
 *   useClickOutside([buttonRef, menuRef], () => setOpen(false))
 */
export function useClickOutside(refs, handler) {
  useEffect(() => {
    const targets = Array.isArray(refs) ? refs : [refs]

    function onMouseDown(e) {
      const inside = targets.some(r => r.current && r.current.contains(e.target))
      if (!inside) handler(e)
    }

    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [refs, handler])
}
