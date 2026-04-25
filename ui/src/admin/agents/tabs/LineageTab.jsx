// ui/src/admin/agents/tabs/LineageTab.jsx
//
// Tab 5 — reuses the existing Lineage view, scoped to this agent.
// Phase 3 lays out the shell; the actual lineage component lives in
// Runtime.jsx today and gets a `?agent_id=` filter pass in Phase 4.

import { GitBranch, ExternalLink } from "lucide-react"
import { Link } from "react-router-dom"


export default function LineageTab({ agent }) {
  if (!agent) return null

  return (
    <div className="p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-[13px] font-semibold text-slate-900 flex items-center gap-2">
          <GitBranch size={14} className="text-slate-500" aria-hidden />
          Lineage
        </h3>
        <Link
          to={`/admin/runtime?filter=agent:${encodeURIComponent(agent.id)}`}
          className="inline-flex items-center gap-1 text-[11px] text-blue-700 hover:underline"
        >
          Open in Runtime <ExternalLink size={10} aria-hidden />
        </Link>
      </header>

      <p className="text-[12px] text-slate-500 italic">
        Tool-call → LLM-call → response chains for this agent. Phase 4
        scopes the existing Runtime lineage view by agent_id; for now,
        the link above opens Runtime with the filter pre-applied.
      </p>
    </div>
  )
}
