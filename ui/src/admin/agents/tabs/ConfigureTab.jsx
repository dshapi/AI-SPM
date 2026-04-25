// ui/src/admin/agents/tabs/ConfigureTab.jsx
//
// Tab 2 — editable per-agent configuration. Backed by PATCH /agents/{id}.
// The Phase 1 backend's ALLOWED_PATCH_FIELDS gates which fields land in
// the DB; the form below mirrors that allow-list so unsaved fields fail
// loudly during dev rather than silently being dropped server-side.
//
// Restart-required changes (LLM override, env vars, resource limits)
// show a banner so the operator knows clicking Save will bounce the
// container. Phase 3 fires a manual restart afterward; Phase 4 will
// add a "save and restart" combo action that's atomic on the server.

import { AlertTriangle, Save } from "lucide-react"
import { useEffect, useState } from "react"

import { patchAgent, startAgent, stopAgent } from "../../api/agents"


// Same value list the backend's agent_routes.py enforces.
const ALLOWED_PATCH_FIELDS = [
  "name", "version", "agent_type", "owner",
  "description", "risk", "policy_status",
]


// Tailwind styles to match the existing FIELD_CLS / SELECT_CLS look.
const INPUT_CLS = (
  "w-full bg-white border border-slate-300 rounded-md px-2 py-1 text-[12px] " +
  "focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
)
const SELECT_CLS = INPUT_CLS + " appearance-none pr-7"
const LABEL_CLS  = "block text-[11px] font-medium text-slate-600 mb-1"


// Restart-required field set — kept as a constant so the banner logic
// and the save handler agree on what triggers the restart.
const RESTART_REQUIRED = new Set([
  // Phase 3 doesn't expose LLM override / env vars / resource limits in
  // the patch payload yet (backend ALLOWED_PATCH_FIELDS only covers
  // metadata). Phase 4 will widen both. The set is here so adding a
  // restart-required field is one-line.
])


function _diff(original, edited) {
  const out = {}
  for (const k of ALLOWED_PATCH_FIELDS) {
    if (edited[k] !== undefined && edited[k] !== original[k]) {
      out[k] = edited[k]
    }
  }
  return out
}


export default function ConfigureTab({ agent, onSaved }) {
  const [draft,    setDraft]    = useState({})
  const [saving,   setSaving]   = useState(false)
  const [err,      setErr]      = useState(null)
  const [savedAt,  setSavedAt]  = useState(null)

  // Reset the draft whenever the upstream agent row changes (e.g. after
  // a successful save the parent re-fetches and passes the new row).
  useEffect(() => {
    if (!agent) { setDraft({}); return }
    setDraft({
      name:          agent.name          ?? "",
      version:       agent.version       ?? "",
      agent_type:    agent.agent_type    ?? "custom",
      owner:         agent.owner         ?? "",
      description:   agent.description   ?? "",
      risk:          agent.risk          ?? "low",
      policy_status: agent.policy_status ?? "none",
    })
  }, [agent])

  if (!agent) return null

  const patch = _diff(agent, draft)
  const dirty = Object.keys(patch).length > 0
  const restartNeeded = dirty &&
    Object.keys(patch).some(k => RESTART_REQUIRED.has(k))

  const onSave = async () => {
    if (!dirty || saving) return
    setSaving(true); setErr(null)
    try {
      const updated = await patchAgent(agent.id, patch)
      if (restartNeeded && agent.runtime_state === "running") {
        // Phase 3: stop+start sequence. Phase 4 introduces a single
        // /restart endpoint that's atomic.
        await stopAgent(agent.id)
        await startAgent(agent.id)
      }
      setSavedAt(Date.now())
      if (onSaved) onSaved(updated)
    } catch (e) {
      setErr(e.message || "Save failed")
    } finally {
      setSaving(false)
    }
  }

  const set = (k) => (e) => setDraft({ ...draft, [k]: e.target.value })

  return (
    <div className="p-4 space-y-4">
      {/* Restart-required banner */}
      {restartNeeded && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-md border border-amber-200 bg-amber-50 text-[12px] text-amber-800">
          <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" aria-hidden />
          <span>
            Saving will restart the agent (~5s). Active chat sessions will
            briefly show a "paused" banner.
          </span>
        </div>
      )}

      {/* Identity */}
      <fieldset>
        <legend className="text-[12px] font-semibold text-slate-800 mb-2">Identity</legend>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL_CLS}>Name</label>
            <input className={INPUT_CLS} value={draft.name || ""} onChange={set("name")} />
          </div>
          <div>
            <label className={LABEL_CLS}>Version</label>
            <input className={INPUT_CLS} value={draft.version || ""} onChange={set("version")} />
          </div>
          <div>
            <label className={LABEL_CLS}>Agent type</label>
            <select className={SELECT_CLS} value={draft.agent_type || "custom"} onChange={set("agent_type")}>
              <option value="langchain">langchain</option>
              <option value="llamaindex">llamaindex</option>
              <option value="autogpt">autogpt</option>
              <option value="openai_assistant">openai_assistant</option>
              <option value="custom">custom</option>
            </select>
          </div>
          <div>
            <label className={LABEL_CLS}>Owner</label>
            <input className={INPUT_CLS} value={draft.owner || ""} onChange={set("owner")} />
          </div>
          <div className="col-span-2">
            <label className={LABEL_CLS}>Description</label>
            <textarea
              className={INPUT_CLS + " min-h-[60px]"}
              value={draft.description || ""}
              onChange={set("description")}
            />
          </div>
        </div>
      </fieldset>

      {/* Risk + Policy */}
      <fieldset>
        <legend className="text-[12px] font-semibold text-slate-800 mb-2">Risk &amp; Policy</legend>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL_CLS}>Risk</label>
            <select className={SELECT_CLS} value={draft.risk || "low"} onChange={set("risk")}>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </div>
          <div>
            <label className={LABEL_CLS}>Policy status</label>
            <select className={SELECT_CLS} value={draft.policy_status || "none"} onChange={set("policy_status")}>
              <option value="covered">covered</option>
              <option value="partial">partial</option>
              <option value="none">none</option>
            </select>
          </div>
        </div>
      </fieldset>

      {/* Phase 4 placeholders — listed so customers know what's coming */}
      <fieldset className="opacity-60">
        <legend className="text-[12px] font-semibold text-slate-800 mb-1">
          LLM, Resources, Custom env vars, Tools
        </legend>
        <p className="text-[11px] text-slate-500 italic">
          Override LLM / model name, memory + CPU limits, per-agent
          secrets, and tool toggles arrive in Phase 4. Edit them via
          <code className="mx-1">PATCH /agents/{"{id}"}</code> directly until then.
        </p>
      </fieldset>

      {/* Footer — Save button + status */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-200">
        <div className="text-[11px] text-slate-500">
          {err && <span className="text-rose-600">⚠ {err}</span>}
          {!err && savedAt && <span>Saved {new Date(savedAt).toLocaleTimeString()}</span>}
        </div>
        <button
          type="button"
          disabled={!dirty || saving}
          onClick={onSave}
          className={
            "inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-[12px] " +
            "font-medium border transition-colors " +
            (dirty && !saving
              ? "bg-blue-600 hover:bg-blue-700 text-white border-blue-700"
              : "bg-slate-100 text-slate-500 border-slate-200 cursor-not-allowed")
          }
        >
          <Save size={12} aria-hidden />
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  )
}
