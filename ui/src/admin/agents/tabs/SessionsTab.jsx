// ui/src/admin/agents/tabs/SessionsTab.jsx
//
// Tab 4 — list of chat sessions for this agent. Phase 3 lays out the
// shell + click-to-open behaviour. Backend endpoint
// GET /agents/{id}/sessions arrives with Phase 4's chat pipeline
// wiring; Phase 3 renders the empty state + a placeholder list.

import { MessageSquare, Users } from "lucide-react"


export default function SessionsTab({ agent, onOpenSession }) {
  if (!agent) return null

  // Real data lives in /agents/{id}/sessions when wired. Phase 3
  // renders a static empty state.
  const sessions = []

  return (
    <div className="p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-[13px] font-semibold text-slate-900 flex items-center gap-2">
          <Users size={14} className="text-slate-500" aria-hidden />
          Chat sessions
        </h3>
      </header>

      {sessions.length === 0 ? (
        <p className="text-[12px] text-slate-500 italic">
          No persisted chat sessions yet. Open a chat from the Overview tab
          (or right-click the agent → Open Chat) to start one.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {sessions.map(s => (
            <li
              key={s.id}
              className="py-2 flex items-center justify-between cursor-pointer hover:bg-slate-50 -mx-2 px-2 rounded"
              onClick={() => onOpenSession && onOpenSession(s)}
            >
              <div className="flex items-center gap-2">
                <MessageSquare size={12} className="text-slate-400" aria-hidden />
                <span className="text-[12px] text-slate-800">{s.user_id}</span>
              </div>
              <span className="text-[11px] text-slate-500">
                {s.message_count} msgs
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
