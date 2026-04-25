// ui/src/admin/agents/AgentRunStopToggle.jsx
//
// Reusable run/stop button for an agent row. Used in three places:
//   - PreviewPanel header (Inventory page)
//   - AgentDetailDrawer Overview tab
//   - Right-click ContextMenu (Stop / Start items)
//
// Behaviour matrix:
//
//   runtime_state    button shows    primary action     spinner during action
//   ─────────────    ─────────────   ────────────────   ──────────────────────
//   stopped          ▶ Start         POST /start        until next poll shows starting/running
//   starting         ⏳ Starting     (disabled)         always
//   running          ◼ Stop          POST /stop         until next poll shows stopped
//   crashed          ↻ Restart       POST /start        same as Start
//
// Errors are surfaced inline as a small red dot with a tooltip; the
// button doesn't unmount on error so the operator can retry.

import { Loader2, Play, RefreshCw, Square } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { startAgent, stopAgent } from "../api/agents"


// Tailwind class string consumers can override via `className`.
const BASE_CLS = (
  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] " +
  "font-medium border transition-colors focus:outline-none focus:ring-2 " +
  "focus:ring-offset-1 disabled:opacity-60 disabled:cursor-not-allowed"
)

const VARIANT_CLS = {
  start: (
    "bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-700 " +
    "focus:ring-emerald-400"
  ),
  stop: (
    "bg-rose-600 hover:bg-rose-700 text-white border-rose-700 " +
    "focus:ring-rose-400"
  ),
  restart: (
    "bg-amber-600 hover:bg-amber-700 text-white border-amber-700 " +
    "focus:ring-amber-400"
  ),
  starting: (
    "bg-slate-200 text-slate-700 border-slate-300 cursor-wait"
  ),
}


/**
 * @param {object} props
 * @param {{id:string, runtime_state:string}} props.agent
 * @param {(newState:string) => void} [props.onChange]   — fires after successful action
 * @param {string} [props.size="md"]                      — "sm" | "md"
 * @param {string} [props.className]                      — append extra classes
 */
export default function AgentRunStopToggle({
  agent, onChange, size = "md", className = "",
}) {
  const [busy,  setBusy]  = useState(false)
  const [error, setError] = useState(null)

  // Persistent "in-flight" flag — stays true from click until the
  // polled runtime_state actually reflects the action. The API call
  // itself returns in tens of ms, but the container takes seconds to
  // come up / shut down; without this the button looks frozen-but-idle
  // for the gap, and the operator clicks it again.
  const [pending, setPending] = useState(false)
  const pendingFromRef = useRef(null) // state we saw at click-time

  // Hooks MUST run unconditionally — derive `state` (used by the
  // useEffect below) before any early-return so the hooks order stays
  // stable across renders.
  const state = (agent && agent.runtime_state) || "stopped"

  // Clear pending once the polled state has actually moved off
  // whatever it was when we clicked.
  useEffect(() => {
    if (!pending) return
    const from = pendingFromRef.current
    if (from && state !== from) {
      setPending(false)
      pendingFromRef.current = null
    }
  }, [state, pending])

  if (!agent || !agent.id) return null

  // Decide button mode + label + icon + variant
  let mode, label, Icon, variant
  if (state === "running") {
    mode = "stop"; label = "Stop"; Icon = Square; variant = "stop"
  } else if (state === "starting") {
    mode = "starting"; label = "Starting…"; Icon = Loader2; variant = "starting"
  } else if (state === "crashed") {
    mode = "start"; label = "Restart"; Icon = RefreshCw; variant = "restart"
  } else {
    // stopped or anything unknown
    mode = "start"; label = "Start"; Icon = Play; variant = "start"
  }

  const disabled = busy || pending || mode === "starting"

  const onClick = async (ev) => {
    ev.stopPropagation()
    if (disabled) return
    setBusy(true)
    setError(null)
    // Capture pre-click state so the spinner clears as soon as the
    // poll sees a *different* runtime_state — not just any tick.
    pendingFromRef.current = state
    setPending(true)
    try {
      if (mode === "start") {
        await startAgent(agent.id)
        onChange && onChange("starting")
      } else if (mode === "stop") {
        await stopAgent(agent.id)
        onChange && onChange("stopped")
      }
    } catch (e) {
      setError(e.message || "Action failed")
      // Action failed — don't keep the spinner up forever waiting on
      // a state change that won't happen.
      setPending(false)
      pendingFromRef.current = null
    } finally {
      setBusy(false)
    }
  }

  const padding = size === "sm" ? "px-2 py-0.5 text-[11px]" : ""
  const iconSize = size === "sm" ? 11 : 13
  const spinning = busy || pending || mode === "starting"

  // While pending we show a fixed Loader2 + label so the user gets a
  // clear "working on it" hint instead of a button that looks idle
  // between the API call returning and the next 5s poll arriving.
  const showPendingPill = pending && mode !== "starting"

  return (
    <div className="relative inline-flex items-center gap-1">
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className={`${BASE_CLS} ${VARIANT_CLS[variant]} ${padding} ${className}`}
        aria-label={`${label} agent`}
        title={error || (showPendingPill
          ? `${label} pending — waiting for the agent to respond`
          : label)}
        data-runtime-state={state}
        data-pending={showPendingPill ? "true" : "false"}
      >
        <Icon
          size={iconSize}
          className={spinning ? "animate-spin" : ""}
          aria-hidden
        />
        {label}
      </button>
      {showPendingPill && (
        <span
          className="inline-flex items-center gap-1 text-[11px] text-slate-600"
          aria-live="polite"
          aria-label="Action pending"
        >
          <Loader2 size={12} className="animate-spin" aria-hidden />
          working…
        </span>
      )}
      {error && (
        <span
          className="text-rose-600 text-[11px] font-medium"
          title={error}
          role="alert"
        >
          ⚠
        </span>
      )}
    </div>
  )
}
