// ui/src/admin/agents/PolicySelector.jsx
//
// Editable "Linked Policies" surface for an agent. Used inside the
// PreviewPanel section that previously read "No policies applied".
//
// Behaviour
// ─────────
//   - Fetches the agent's currently-linked policies on mount via
//     listAgentPolicies(agent._backendId).
//   - Fetches the full CPM policy registry once via fetchPolicies()
//     (already shipped in admin/api/spm.js) for the picker dropdown.
//   - Renders attached policies as removable chips.
//   - "+ Add policy" dropdown shows the not-yet-attached subset.
//   - Each change calls setAgentPolicies() with the full new set —
//     atomic replace, so any partial-failure recovery is the
//     operator's next click rather than reconciliation logic here.
//
// Mocks (rows that came from the inline ASSETS catalog in
// Inventory.jsx) are detected via the absence of agent._backendId
// and render a read-only "register an agent.py to manage policies"
// stub instead.

import { Plus, Shield, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { listAgentPolicies, setAgentPolicies } from "../api/agents"
import { fetchPolicies }                       from "../api/spm"


function _byId(arr) {
  const out = {}
  for (const p of arr || []) {
    if (p && p.id) out[String(p.id)] = p
  }
  return out
}


/**
 * @param {object}   props
 * @param {object}   props.agent             — the agent row
 * @param {Function} [props.onChange]        — fires after a successful save
 */
export default function PolicySelector({ agent, onChange }) {
  const backendId = agent?._backendId
  const isLive    = Boolean(backendId)

  const [linked,  setLinked]  = useState([])     // [{policy_id, ...}]
  const [catalog, setCatalog] = useState([])     // [{id, name, ...}]
  const [busy,    setBusy]    = useState(false)
  const [error,   setError]   = useState(null)
  const [picking, setPicking] = useState(false)

  const dropdownRef = useRef(null)

  // Initial load — only for live agents.
  useEffect(() => {
    if (!isLive) return
    let cancelled = false
    Promise.all([
      listAgentPolicies(backendId).catch(() => []),
      fetchPolicies().catch(() => []),
    ]).then(([linkedRows, catalogRows]) => {
      if (cancelled) return
      setLinked(linkedRows)
      setCatalog(catalogRows)
    })
    return () => { cancelled = true }
  }, [backendId, isLive])

  // Click-outside to close the picker.
  useEffect(() => {
    if (!picking) return
    const onDown = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setPicking(false)
      }
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [picking])

  const linkedIds  = useMemo(() => new Set(linked.map(r => r.policy_id)), [linked])
  const catalogMap = useMemo(() => _byId(catalog), [catalog])
  const addable    = useMemo(
    () => catalog.filter(p => !linkedIds.has(String(p.id))),
    [catalog, linkedIds],
  )

  if (!isLive) {
    return (
      <p className="text-[12px] text-orange-500 font-medium">
        Register an agent.py to manage linked policies.
      </p>
    )
  }

  async function _saveSet(nextIds) {
    if (busy) return
    setBusy(true); setError(null)
    try {
      const updated = await setAgentPolicies(backendId, nextIds)
      setLinked(updated)
      if (onChange) onChange(updated)
    } catch (e) {
      setError(e.message || "Save failed")
    } finally {
      setBusy(false)
    }
  }

  function _attach(policyId) {
    const next = Array.from(new Set([
      ...linked.map(r => r.policy_id),
      String(policyId),
    ]))
    setPicking(false)
    _saveSet(next)
  }

  function _detach(policyId) {
    const next = linked
      .map(r => r.policy_id)
      .filter(p => p !== policyId)
    _saveSet(next)
  }

  return (
    <div className="space-y-2">
      {linked.length === 0 ? (
        <p className="text-[12px] text-orange-500 font-medium">
          No policies applied
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {linked.map(row => {
            const meta = catalogMap[row.policy_id]
            const label = meta?.name || row.policy_id
            return (
              <span
                key={row.policy_id}
                className={
                  "inline-flex items-center gap-1 px-2 py-0.5 rounded " +
                  "border border-blue-200 bg-blue-50 text-[11px] " +
                  "font-medium text-blue-700 max-w-full"
                }
                title={`Attached by ${row.attached_by || "unknown"} on ${row.attached_at || "—"}`}
              >
                <Shield size={10} aria-hidden />
                <span className="truncate max-w-[140px]">{label}</span>
                <button
                  type="button"
                  onClick={() => _detach(row.policy_id)}
                  disabled={busy}
                  className="text-blue-400 hover:text-rose-600 disabled:opacity-50"
                  aria-label={`Detach ${label}`}
                >
                  <X size={10} />
                </button>
              </span>
            )
          })}
        </div>
      )}

      <div className="relative" ref={dropdownRef}>
        <button
          type="button"
          onClick={() => setPicking(v => !v)}
          disabled={busy}
          className={
            "inline-flex items-center gap-1 px-2 py-0.5 rounded-md " +
            "border border-dashed border-slate-300 hover:border-blue-400 " +
            "hover:bg-blue-50/50 text-[11px] text-slate-600 disabled:opacity-50"
          }
        >
          <Plus size={10} aria-hidden />
          {busy ? "Saving…" : "Add policy"}
        </button>

        {picking && addable.length > 0 && (
          <ul
            role="menu"
            className={
              "absolute left-0 mt-1 z-30 min-w-[200px] max-h-[260px] " +
              "overflow-y-auto py-1 rounded-md shadow-lg bg-white " +
              "border border-slate-200 text-[12px]"
            }
          >
            {addable.map(p => (
              <li
                key={p.id}
                role="menuitem"
                onClick={() => _attach(p.id)}
                className="px-3 py-1.5 cursor-pointer hover:bg-slate-50"
              >
                <div className="font-medium text-slate-800 truncate">
                  {p.name || p.id}
                </div>
                {p.description && (
                  <div className="text-[11px] text-slate-500 truncate">
                    {p.description}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {picking && addable.length === 0 && (
          <ul
            role="menu"
            className={
              "absolute left-0 mt-1 z-30 min-w-[200px] py-2 px-3 rounded-md " +
              "shadow-lg bg-white border border-slate-200 text-[11px] " +
              "text-slate-500"
            }
          >
            All available policies are already attached.
          </ul>
        )}
      </div>

      {error && (
        <p className="text-[11px] text-rose-600" role="alert">
          ⚠ {error}
        </p>
      )}
    </div>
  )
}
