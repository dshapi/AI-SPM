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


// Risk → header tint. Mirrors PreviewPanel's lighter palette (bg-red-50
// etc.) so a user moving from PreviewPanel → "View Detail" → drawer
// sees the same visual language. The drawer used deeper bg-rose-100
// + uppercase eyebrow + 15px title before; that read as a different
// component. Now the header looks like a wider PreviewPanel header.
const RISK_TINT = {
  Critical: "bg-red-50",
  High:     "bg-orange-50",
  Medium:   "bg-yellow-50",
  Low:      "bg-emerald-50",
  // lowercase aliases (backend returns these too)
  critical: "bg-red-50",
  high:     "bg-orange-50",
  medium:   "bg-yellow-50",
  low:      "bg-emerald-50",
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

  const riskBg = RISK_TINT[agent.risk] || "bg-gray-50"

  // Layout: this drawer is INLINE — it sits in the same right-side
  // 300px slot the parent uses for PreviewPanel / AgentChatPanel /
  // RegisterAgentPanel. The parent (Inventory.jsx) decides which one
  // to render via a conditional ladder; we just match the slot's
  // contract: 300px wide, ``shrink-0``, ``h-full``, no overlay.
  return (
    <aside
      role="region" aria-label={`Agent ${agent.name}`}
      // ``min-h-0`` lets the inner ``flex-1 min-h-0`` tab body actually
      // collapse to the parent's available height instead of expanding
      // to fit the largest tab's natural content size — without this
      // the Activity tab's long timeline would push the close button
      // off the bottom of the drawer.
      className="w-[300px] shrink-0 flex flex-col h-full min-h-0 bg-white"
      data-testid="agent-detail-drawer"
    >
      {/* Header — same shape, padding, and typography as PreviewPanel.
          Risk tint is the lighter palette (bg-red-50 etc.); no
          uppercase eyebrow, no 15px title, no heavy shadow. */}
      <div className={`px-4 py-3.5 border-b border-gray-100 flex items-start justify-between gap-2 ${riskBg}`}>
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-gray-900 leading-snug truncate">
            {agent.name}
          </p>
          <p className="text-[11px] text-gray-500 mt-0.5">
            {agent.agent_type || "agent"}
            {agent.version ? ` · v${agent.version}` : ""}
            {agent.runtime_state ? ` · ${agent.runtime_state}` : ""}
          </p>
        </div>
        <button
          type="button" onClick={onClose}
          aria-label="Close drawer"
          className="w-6 h-6 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-600 hover:bg-black/5 transition-colors shrink-0 mt-0.5"
        >
          <X size={13} />
        </button>
      </div>

      {/* Tab strip — neutral grays matching the rest of the system.
          Active state uses gray-900 + a thin gray-900 underline rather
          than the previous heavy blue treatment, so the strip reads
          as part of the panel rather than a separate widget. */}
      <nav
        role="tablist"
        // 300px is tight for 5 tabs — px-2 + px-1.5 per item just
        // barely fits "Overview / Configure / Activity / Sessions /
        // Lineage" at 11px without truncation. overflow-x-auto is the
        // safety net for translations that come out longer.
        className="flex border-b border-gray-100 px-2 overflow-x-auto"
      >
        {TABS.map(t => {
          const active = tab === t.key
          return (
            <button
              key={t.key}
              role="tab"
              aria-selected={active}
              data-tab-key={t.key}
              onClick={() => setTab(t.key)}
              className={
                "relative px-1.5 py-2 text-[11px] font-medium whitespace-nowrap transition-colors " +
                (active
                  ? "text-gray-900"
                  : "text-gray-500 hover:text-gray-700")
              }
            >
              {t.label}
              {active && (
                <span
                  aria-hidden
                  className="absolute left-1 right-1 -bottom-px h-[2px] bg-gray-900 rounded-full"
                />
              )}
            </button>
          )
        })}
      </nav>

      {/* Tab body — bounded, non-scrolling at this level. Each tab
          either manages its own scroll (e.g. ActivityTab keeps its
          header pinned and scrolls only the timeline) or gets wrapped
          in the default `overflow-y-auto` shell below. ``flex-1
          min-h-0`` lets the tab actually fill the remaining space
          inside the parent flex column instead of growing past it.
          Without ``min-h-0`` the inner ``overflow-y-auto`` doesn't
          fire because flex children default to ``min-height: auto``. */}
      <div className="flex-1 min-h-0 bg-white" data-testid="drawer-tab-body">
        {tab === "activity" ? (
          // ActivityTab manages its own scroll so its header + Refresh
          // button stay pinned while the timeline scrolls below them.
          <ActivityTab agent={agent} />
        ) : (
          // All other tabs render naturally; we provide a single
          // scroll container so long Configure forms / Sessions
          // tables don't push the close button off-screen.
          <div className="h-full overflow-y-auto">
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
            {tab === "sessions" && <SessionsTab agent={agent} />}
            {tab === "lineage"  && <LineageTab  agent={agent} />}
          </div>
        )}
      </div>
    </aside>
  )
}
