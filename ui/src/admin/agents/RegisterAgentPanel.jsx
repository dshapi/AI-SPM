// ui/src/admin/agents/RegisterAgentPanel.jsx
//
// Right-side drawer mirroring RegisterAssetPanel's layout but tailored
// for uploading a customer agent.py. Lives separately from
// RegisterAssetPanel so the model-registration flow stays simple.
//
// Wire path: createAgentWithFile() → POST /api/spm/agents (multipart).
// Backend's three-step validate_agent_code runs server-side; failures
// come back as 422 with a `detail` array which we render inline.

import { FileUp, Loader2, Upload, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { createAgentWithFile } from "../api/agents"


const FIELD_CLS = (
  "w-full bg-white border border-slate-300 rounded-md px-2 py-1 text-[12px] " +
  "focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
)
const SELECT_CLS = FIELD_CLS + " appearance-none pr-7"
const LABEL_CLS  = "block text-[11px] font-medium text-slate-600 mb-1"


const AGENT_TYPES = [
  { value: "langchain",        label: "LangChain"        },
  { value: "llamaindex",       label: "LlamaIndex"       },
  { value: "autogpt",          label: "AutoGPT"          },
  { value: "openai_assistant", label: "OpenAI Assistant" },
  { value: "custom",           label: "Custom (plain async def main)" },
]


/**
 * @param {object}   props
 * @param {Function} props.onClose
 * @param {Function} [props.onRegistered] — fires with the new agent row
 *        after a successful upload so the parent can refresh its list.
 * @param {string[]} [props.ownerOptions] — owners present in the
 *        merged asset list, fed into the Owner dropdown for consistency
 *        with RegisterAssetPanel.
 */
export default function RegisterAgentPanel({
  onClose, onRegistered, ownerOptions = [],
}) {
  const [name,        setName]        = useState("")
  const [version,     setVersion]     = useState("1.0.0")
  const [agentType,   setAgentType]   = useState("custom")
  const [owner,       setOwner]       = useState("")
  const [description, setDescription] = useState("")
  const [deployAfter, setDeployAfter] = useState(true)
  const [file,        setFile]        = useState(null)

  const [errors,   setErrors]   = useState({})
  const [busy,     setBusy]     = useState(false)
  const [progress, setProgress] = useState(0)
  const [apiError, setApiError] = useState(null)
  const [warnings, setWarnings] = useState([])

  const fileInputRef = useRef(null)
  const abortRef     = useRef(null)

  // Esc closes the panel when not uploading.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !busy) cancelAndClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  // Cancel any in-flight upload on unmount.
  useEffect(() => () => { try { abortRef.current?.abort() } catch {} }, [])

  function cancelAndClose() {
    try { abortRef.current?.abort() } catch {}
    onClose && onClose()
  }

  function validate() {
    const e = {}
    if (!name.trim())          e.name        = "Name is required"
    if (!version.trim())       e.version     = "Version is required"
    if (!agentType)            e.agentType   = "Agent type is required"
    if (!file)                 e.file        = "Upload an agent.py file"
    else if (!file.name.endsWith(".py")) e.file = "File must be a .py"
    return e
  }

  async function handleApply() {
    if (busy) return
    setApiError(null)
    setWarnings([])
    const e = validate()
    setErrors(e)
    if (Object.keys(e).length > 0) return

    const ctrl = new AbortController()
    abortRef.current = ctrl
    setBusy(true)

    try {
      const out = await createAgentWithFile({
        name:        name.trim(),
        version:     version.trim(),
        agentType,
        owner:       owner || undefined,
        description: description.trim(),
        deployAfter,
        file,
        signal:      ctrl.signal,
        onProgress:  (p) => setProgress(p),
      })
      // The 422-validator path returns warnings inline as out.warnings.
      if (Array.isArray(out?.warnings) && out.warnings.length > 0) {
        setWarnings(out.warnings)
      }
      if (onRegistered) onRegistered(out)
      // Close after a short pause so the operator sees the warnings.
      if (!out?.warnings?.length) onClose && onClose()
    } catch (err) {
      if (err?.aborted) return
      setApiError(err)
      // 422 with detail array → field-level error list
      if (err?.status === 422 && Array.isArray(err?.detail)) {
        setErrors({ file: err.detail.join(" / ") })
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside
      className={
        "w-[300px] flex-shrink-0 border-l border-slate-200 bg-slate-50 " +
        "flex flex-col h-full"
      }
      data-testid="register-agent-panel"
      role="dialog" aria-modal="false" aria-label="Register Agent"
    >
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-white">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
            Register
          </div>
          <h2 className="text-[14px] font-semibold text-slate-900 mt-0.5">
            New agent
          </h2>
        </div>
        <button
          type="button" onClick={cancelAndClose}
          aria-label="Close"
          className="p-1 rounded hover:bg-slate-100 text-slate-500"
          disabled={busy}
        >
          <X size={15} />
        </button>
      </header>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        <div>
          <label className={LABEL_CLS}>Name</label>
          <input className={FIELD_CLS} value={name} onChange={(e) => setName(e.target.value)} placeholder="my-agent" />
          <FieldError msg={errors.name} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL_CLS}>Version</label>
            <input className={FIELD_CLS} value={version} onChange={(e) => setVersion(e.target.value)} />
            <FieldError msg={errors.version} />
          </div>
          <div>
            <label className={LABEL_CLS}>Agent type</label>
            <select className={SELECT_CLS} value={agentType} onChange={(e) => setAgentType(e.target.value)}>
              {AGENT_TYPES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            <FieldError msg={errors.agentType} />
          </div>
        </div>

        <div>
          <label className={LABEL_CLS}>Owner</label>
          {ownerOptions.length > 0 ? (
            <select className={SELECT_CLS} value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">— No owner —</option>
              {ownerOptions.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input className={FIELD_CLS} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="ml-platform" />
          )}
        </div>

        <div>
          <label className={LABEL_CLS}>Description</label>
          <textarea
            className={FIELD_CLS + " min-h-[60px]"}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What does this agent do?"
          />
        </div>

        {/* File picker — same chip pattern as RegisterAssetPanel */}
        <div>
          <label className={LABEL_CLS}>agent.py</label>
          <input
            ref={fileInputRef}
            type="file"
            accept=".py,text/x-python"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          {file ? (
            <div className="flex items-center justify-between bg-white border border-slate-300 rounded-md px-2 py-1">
              <span className="text-[12px] truncate">
                <FileUp size={12} className="inline mr-1 text-slate-500" aria-hidden />
                {file.name}
                <span className="text-slate-400 ml-2">{Math.ceil(file.size/1024)} KB</span>
              </span>
              <button
                type="button" onClick={() => setFile(null)}
                aria-label="Clear file"
                className="text-slate-400 hover:text-rose-600"
                disabled={busy}
              >
                <X size={12} />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className={
                "w-full inline-flex items-center justify-center gap-2 " +
                "px-2 py-2 rounded-md border-2 border-dashed border-slate-300 " +
                "hover:border-blue-400 hover:bg-blue-50/50 text-[12px] text-slate-600"
              }
            >
              <Upload size={13} aria-hidden />
              Choose agent.py…
            </button>
          )}
          <FieldError msg={errors.file} />
        </div>

        {/* Deploy after — defaults to true so the agent comes up
            immediately after upload. Operators who want to inspect
            before deploying can uncheck. */}
        <label className="flex items-center gap-2 text-[12px] text-slate-700">
          <input
            type="checkbox"
            checked={deployAfter}
            onChange={(e) => setDeployAfter(e.target.checked)}
          />
          Deploy after registration
        </label>

        {/* Validator warnings — non-blocking but worth surfacing */}
        {warnings.length > 0 && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
            <div className="text-[12px] font-medium text-amber-900 mb-1">
              Validator warnings (registration succeeded):
            </div>
            <ul className="text-[11px] text-amber-800 list-disc pl-4 space-y-0.5">
              {warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </div>
        )}

        {apiError && (
          <p className="text-[11px] text-rose-700" role="alert">
            ⚠ {apiError.message}
          </p>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-slate-200 p-3 bg-white flex items-center justify-between">
        <button
          type="button"
          onClick={cancelAndClose}
          disabled={busy}
          className="text-[12px] text-slate-500 hover:text-slate-800 disabled:opacity-50"
        >
          Cancel
        </button>
        <div className="flex items-center gap-2">
          {busy && progress > 0 && (
            <span className="text-[11px] text-slate-500 tabular-nums">
              {progress}%
            </span>
          )}
          <button
            type="button"
            onClick={handleApply}
            disabled={busy}
            className={
              "inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-[12px] " +
              "font-medium border " +
              (busy
                ? "bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-700 text-white border-blue-700")
            }
          >
            {busy
              ? <Loader2 size={12} className="animate-spin" aria-hidden />
              : <Upload  size={12} aria-hidden />}
            {busy ? "Uploading…" : "Register agent"}
          </button>
        </div>
      </div>
    </aside>
  )
}


function FieldError({ msg }) {
  if (!msg) return null
  return <p className="mt-1 text-[11px] text-rose-600 font-medium">{msg}</p>
}
