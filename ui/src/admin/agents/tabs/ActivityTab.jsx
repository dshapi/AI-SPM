// ui/src/admin/agents/tabs/ActivityTab.jsx
//
// Tab 3 — recent activity for one agent. Phase 4 wires the audit
// consumer to push AgentChatMessage / AgentToolCall / AgentLLMCall
// events; Phase 3 renders the shell with a placeholder list and a
// refresh action so the layout is locked in.

import { Activity, RefreshCw } from "lucide-react"


export default function ActivityTab({ agent }) {
  if (!agent) return null

  return (
    <div className="p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-[13px] font-semibold text-slate-900 flex items-center gap-2">
          <Activity size={14} className="text-slate-500" aria-hidden />
          Recent activity
        </h3>
        <button
          type="button"
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-slate-300 hover:bg-slate-50 text-[11px]"
          aria-label="Refresh activity"
          disabled
          title="Live tail wiring lands in Phase 4"
        >
          <RefreshCw size={11} aria-hidden /> Refresh
        </button>
      </header>

      <p className="text-[12px] text-slate-500 italic">
        Live tail of <code>AgentChatMessage</code>, <code>AgentToolCall</code>,
        and <code>AgentLLMCall</code> events for this agent. Backend audit
        consumer wiring lands in Phase 4 — until then this list stays empty
        even when the agent is active.
      </p>
    </div>
  )
}
