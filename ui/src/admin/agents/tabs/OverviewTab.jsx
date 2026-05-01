// ui/src/admin/agents/tabs/OverviewTab.jsx
//
// Tab 1 of AgentDetailDrawer. Read-only summary of the agent + the
// run/stop control + Open-Chat CTA. Layout mirrors the existing
// PreviewPanel right drawer (risk-tinted header, scrollable body) but
// with denser key-value rows and a runtime-status block.

import { Activity, MessageSquare, Shield, ShieldCheck, ShieldX } from "lucide-react"

import AgentRunStopToggle from "../AgentRunStopToggle"


// ─── Tiny presentational helpers ───────────────────────────────────────────

function Row({ label, value }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-3 py-1 text-[12px]">
      <div className="text-slate-500">{label}</div>
      <div className="text-slate-800 break-words">{value || <span className="text-slate-400">—</span>}</div>
    </div>
  )
}


function PolicyBadge({ status }) {
  const map = {
    covered: { Icon: ShieldCheck, cls: "text-emerald-700 bg-emerald-50 border-emerald-200" },
    partial: { Icon: Shield,      cls: "text-amber-700  bg-amber-50  border-amber-200"  },
    none:    { Icon: ShieldX,     cls: "text-rose-700   bg-rose-50   border-rose-200"   },
  }
  const { Icon, cls } = map[status] || map.none
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[11px] font-medium ${cls}`}>
      <Icon size={11} aria-hidden /> {status || "none"}
    </span>
  )
}


// ─── OverviewTab ───────────────────────────────────────────────────────────

/**
 * @param {object}   props
 * @param {object}   props.agent           — the agent row
 * @param {Function} [props.onOpenChat]    — fired when "Open Chat" clicked
 * @param {Function} [props.onStateChange] — fired after run/stop succeeds
 */
export default function OverviewTab({ agent, onOpenChat, onStateChange }) {
  if (!agent) return null

  return (
    <div className="space-y-5 p-4">
      {/* Identity block */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-[13px] font-semibold text-slate-900">
            {agent.name}
          </h3>
          <PolicyBadge status={agent.policy_status} />
        </div>
        <Row label="Agent type"  value={agent.agent_type} />
        <Row label="Version"     value={agent.version} />
        <Row label="Risk"        value={agent.risk} />
        <Row label="Provider"    value={agent.provider} />
        <Row label="Owner"       value={agent.owner} />
        <Row label="Last seen"
              value={agent.last_seen_at ? new Date(agent.last_seen_at).toLocaleString() : null} />
        {agent.description && (
          <p className="text-[12px] text-slate-700 mt-2 italic">
            {agent.description}
          </p>
        )}
      </section>

      {/* Runtime block — the main interactive surface */}
      <section className="border-t border-slate-200 pt-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-[12px]">
            <Activity size={13} className="text-slate-500" aria-hidden />
            <span className="text-slate-500">Runtime status</span>
            <span
              className="font-medium text-slate-800"
              data-testid="runtime-state-label"
            >
              {agent.runtime_state || "stopped"}
            </span>
          </div>
          {/* Run/stop only renders for live agents — mock seed rows
              don't have a real backend container behind them. */}
          {agent._live && (
            <AgentRunStopToggle agent={agent} onChange={onStateChange} />
          )}
        </div>

        {/* Open Chat — only for live, customer-uploaded agents.
            - Mocks would 404 on the chat endpoint (seed rows aren't
              registered with a real mcp_token / llm_api_key).
            - System agents (threat-hunting-agent, etc.) are
              platform-internal services — they have an inventory row
              + llm_api_key for spm-llm-proxy auth but do not expose a
              chat surface. Hiding the button avoids a dead-end click.
            We key off `agentKind` (not `kind`) because `kind` at this
            level is the inventory asset category set in adaptLiveAgent,
            which is always "agent" for this drawer. agentKind is the
            agent-level distinction sourced from the backend column. */}
        {agent._live && agent.agentKind !== "system" ? (
          <button
            type="button"
            onClick={onOpenChat}
            className={
              "mt-3 inline-flex items-center gap-2 px-3 py-1.5 rounded-md " +
              "border border-slate-300 hover:bg-slate-50 text-[12px] font-medium"
            }
          >
            <MessageSquare size={13} aria-hidden />
            Open Chat
          </button>
        ) : agent.agentKind === "system" ? (
          <p className="mt-3 text-[11px] text-slate-500 italic">
            Platform-internal system agent — runs as a Kubernetes Deployment
            and does not expose a chat surface. Visible in the inventory so
            its <code>llm_api_key</code> is auditable alongside customer agents.
          </p>
        ) : (
          <p className="mt-3 text-[11px] text-slate-500 italic">
            This is a seed mock — register an agent.py to enable chat &amp; lifecycle controls.
          </p>
        )}
      </section>

      {/* Linked policies + alerts (Phase 4 will hydrate the counts —
          Phase 3 renders placeholders so the UI shape is locked in.) */}
      <section className="border-t border-slate-200 pt-4">
        <h4 className="text-[12px] font-semibold text-slate-800 mb-2">
          Linked policies
        </h4>
        <p className="text-[12px] text-slate-500 italic">
          Policy linking lands in Phase 4 (audit consumer wiring).
        </p>
      </section>

      <section className="border-t border-slate-200 pt-4">
        <h4 className="text-[12px] font-semibold text-slate-800 mb-2">
          Code
        </h4>
        <Row label="Path"   value={<code className="text-[11px]">{agent.code_path}</code>} />
        <Row label="SHA-256"
              value={<code className="text-[11px] break-all">{agent.code_sha256}</code>} />
      </section>
    </div>
  )
}
