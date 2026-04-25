// ui/src/admin/agents/AgentDetailDrawer.jsx
//
// 5-tab right-side drawer for one agent. Mirrors the visual style of
// PreviewPanel (risk-tinted header, fixed right column) but wider —
// PreviewPanel is 300px, this is ~560px to fit tabbed content.
//
// Lifecycle
//   - Controlled by `open` prop. Parent handles open/close.
//   - When the agent prop changes (e.g. parent's polling refreshes),
//     the drawer re-syncs without resetting tab state.
//   - Closing fires `onClose` so the parent can clear its `setDetailAgent`.
//
// The drawer is NOT a route. Single-click opens it via state; it lives
// alongside the inventory page rather than being a dedicated URL.
// Phase 4 may promote it to a route if linkability becomes important.

import { X } from "lucide-react"
import { useState } from "react"

import ActivityTab  from "./tabs/ActivityTab"
import ConfigureTab from "./tabs/ConfigureTab"
import LineageTab   from "./tabs/LineageTab"
import OverviewTab  from "./tabs/OverviewTab"
import SessionsTab  from "./tabs/SessionsTab"


// Risk → header tint (mirrors PreviewPanel's `risk-header-bg` pattern
// from Inventory.jsx). Kept as a literal map here so this file is
// self-contained and easy to relocate later.
const RISK_TINT = {
  critical: "bg-rose-100   border-rose-300   text-rose-900",
  high:     "bg-rose-50    border-rose-200   text-rose-900",
  medium:   "bg-amber-50   border-amber-200  text-amber-900",
  low:      "bg-emerald-50 border-emerald-200 text-emerald-900",
}


const TABS = [
  { key: "overview",  label: "Overview"  },
  { key: "configure", label: "Configure" },
  { key: "activity",  label: "Activity"  },
  { key: "sessions",  label: "Sessions"  },
  { key: "lineage",   label: "Lineage"   },
]


/**
 * @param {object}   props
 * @param {boolean}  props.open
 * @param {object}   [props.agent]              — null when drawer is closed
 * @param {Function} [props.onClose]
 * @param {Function} [props.onOpenChat]         — passed through to Overview tab
 * @param {Function} [props.onAgentChanged]     — fires after PATCH or run/stop
 */
export default function AgentDetailDrawer({
  open, agent, onClose, onOpenChat, onAgentChanged,
}) {
  const [tab, setTab] = useState("overview")

  if (!open || !agent) return null

  const tint = RISK_TINT[agent.risk] || RISK_TINT.low

  return (
    <aside
      role="dialog" aria-modal="false" aria-label={`Agent ${agent.name}`}
      className={
        "fixed top-0 right-0 z-40 h-screen w-[560px] max-w-[90vw] " +
        "bg-white border-l border-slate-200 shadow-2xl flex flex-col"
      }
      data-testid="agent-detail-drawer"
    >
      {/* Risk-tinted header — mirrors PreviewPanel */}
      <header className={`flex items-start justify-between p-4 border-b ${tint}`}>
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider opacity-70">
            Agent
          </div>
          <h2 className="text-[15px] font-semibold mt-0.5">{agent.name}</h2>
          <div className="text-[11px] mt-1 opacity-80">
            {agent.agent_type} · v{agent.version} · {agent.runtime_state}
          </div>
        </div>
        <button
          type="button" onClick={onClose}
          aria-label="Close drawer"
          className="p-1 rounded hover:bg-black/10 text-current"
        >
          <X size={16} />
        </button>
      </header>

      {/* Tab strip */}
      <nav
        role="tablist"
        className="flex border-b border-slate-200 bg-slate-50 px-2 overflow-x-auto"
      >
        {TABS.map(t => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            data-tab-key={t.key}
            onClick={() => setTab(t.key)}
            className={
              "px-3 py-2 text-[12px] font-medium whitespace-nowrap " +
              "border-b-2 -mb-px transition-colors " +
              (tab === t.key
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-slate-600 hover:text-slate-900")
            }
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Tab body — scrollable. Each tab manages its own internal scroll. */}
      <div className="flex-1 overflow-y-auto" data-testid="drawer-tab-body">
        {tab === "overview" && (
          <OverviewTab
            agent={agent}
            onOpenChat={onOpenChat}
            onStateChange={(newState) =>
              onAgentChanged && onAgentChanged({ ...agent, runtime_state: newState })
            }
          />
        )}
        {tab === "configure" && (
          <ConfigureTab agent={agent} onSaved={onAgentChanged} />
        )}
        {tab === "activity" && <ActivityTab agent={agent} />}
        {tab === "sessions" && <SessionsTab agent={agent} />}
        {tab === "lineage"  && <LineageTab  agent={agent} />}
      </div>
    </aside>
  )
}
