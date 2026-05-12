import { useState, useEffect, useCallback } from 'react'
import { Lock, Save, RotateCcw, RefreshCw, Check } from 'lucide-react'
import { cn }            from '../../lib/utils.js'
import { PageContainer } from '../../components/layout/PageContainer.jsx'
import { PageHeader }    from '../../components/layout/PageHeader.jsx'
import { Button }        from '../../components/ui/Button.jsx'
import { getToken }      from '../../api.js'

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchMatrix() {
  const token = await getToken()
  const res = await fetch('/api/spm/rbac/matrix', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function saveMatrix(matrix) {
  const token = await getToken()
  const res = await fetch('/api/spm/rbac/matrix', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ matrix }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail?.message || body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Permission metadata ───────────────────────────────────────────────────────

const PERMISSION_GROUPS = [
  {
    label: 'Session',
    color: 'bg-blue-500',
    perms: [
      { key: 'session.read',     desc: 'View session records and event history' },
      { key: 'session.write',    desc: 'Modify session state' },
      { key: 'session.override', desc: 'Force-block or unblock a session regardless of policy' },
    ],
  },
  {
    label: 'Agent',
    color: 'bg-purple-500',
    perms: [
      { key: 'agent.invoke',  desc: 'Start a new agent session' },
      { key: 'agent.read',   desc: 'View agent definitions and details' },
      { key: 'agent.write',  desc: 'Create and modify agent definitions' },
      { key: 'agent.manage', desc: 'Start, stop, and delete agents' },
    ],
  },
  {
    label: 'Model',
    color: 'bg-green-500',
    perms: [
      { key: 'model.read',   desc: 'View model registry entries' },
      { key: 'model.write',  desc: 'Register and update models' },
      { key: 'model.delete', desc: 'Remove models from the registry' },
    ],
  },
  {
    label: 'Integration',
    color: 'bg-orange-500',
    perms: [
      { key: 'integration.read',  desc: 'View integration configurations' },
      { key: 'integration.write', desc: 'Create and configure integrations' },
    ],
  },
  {
    label: 'Compliance',
    color: 'bg-teal-500',
    perms: [
      { key: 'compliance.read',  desc: 'View compliance reports and evidence' },
      { key: 'compliance.write', desc: 'Run compliance evaluations' },
    ],
  },
  {
    label: 'Posture',
    color: 'bg-cyan-500',
    perms: [
      { key: 'posture.read',  desc: 'View posture snapshots and KPIs' },
      { key: 'posture.write', desc: 'Write posture data' },
    ],
  },
  {
    label: 'Chat',
    color: 'bg-indigo-500',
    perms: [
      { key: 'chat.invoke', desc: 'Use the chat interface to interact with agents' },
    ],
  },
  {
    label: 'Audit',
    color: 'bg-red-500',
    perms: [
      { key: 'audit.read',  desc: 'View audit logs and security alerts' },
      { key: 'audit.write', desc: 'Acknowledge and suppress audit alerts' },
    ],
  },
]

const ROLES = [
  { key: 'spm:viewer',           label: 'Viewer',           admin: false },
  { key: 'spm:auditor',          label: 'Auditor',          admin: false },
  { key: 'spm:security-analyst', label: 'Security Analyst', admin: false },
  { key: 'spm:admin',            label: 'Admin',            admin: true  },
]

const DEFAULT_MATRIX = Object.fromEntries(
  ROLES.map(r => [
    r.key,
    Object.fromEntries(
      PERMISSION_GROUPS.flatMap(g => g.perms).map(p => [p.key, false])
    ),
  ])
)

// ── RBAC Matrix component ─────────────────────────────────────────────────────

function RbacMatrix({ isAdmin }) {
  const [serverMatrix, setServerMatrix] = useState(null)
  const [localMatrix,  setLocalMatrix]  = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [saving,   setSaving]   = useState(false)
  const [error,    setError]    = useState(null)
  const [saved,    setSaved]    = useState(false)
  const [tooltip,  setTooltip]  = useState(null) // { key, desc }

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchMatrix()
      setServerMatrix(data)
      setLocalMatrix(JSON.parse(JSON.stringify(data)))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const toggleCell = (role, perm) => {
    if (!isAdmin) return
    setLocalMatrix(prev => ({
      ...prev,
      [role]: { ...prev[role], [perm]: !prev[role]?.[perm] },
    }))
  }

  const revert = () => {
    if (serverMatrix) setLocalMatrix(JSON.parse(JSON.stringify(serverMatrix)))
  }

  const resetToDefaults = () => {
    setLocalMatrix(JSON.parse(JSON.stringify(DEFAULT_MATRIX)))
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const data = await saveMatrix(localMatrix)
      setServerMatrix(data)
      setLocalMatrix(JSON.parse(JSON.stringify(data)))
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  // Count changed cells
  const changedCount = localMatrix && serverMatrix
    ? PERMISSION_GROUPS.flatMap(g => g.perms).reduce((n, p) =>
        ROLES.filter(r => !r.admin).reduce((m, r) =>
          (localMatrix[r.key]?.[p.key] !== serverMatrix[r.key]?.[p.key] ? m + 1 : m), n), 0)
    : 0

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-gray-400 gap-2">
        <RefreshCw size={14} className="animate-spin" />
        Loading matrix…
      </div>
    )
  }

  const matrix = localMatrix || DEFAULT_MATRIX

  return (
    <div>
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm font-semibold text-gray-700">Permission Matrix</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {isAdmin ? 'Click cells to toggle. Admin column is locked.' : 'Read-only — requires Admin role to edit.'}
          </p>
        </div>
        {isAdmin && (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={revert} disabled={changedCount === 0 || saving}>
              <RotateCcw size={12} className="mr-1" />
              Revert
            </Button>
            <Button variant="outline" size="sm" onClick={resetToDefaults} disabled={saving}>
              Reset to defaults
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={changedCount === 0 || saving}
              className={saved ? 'bg-green-600 hover:bg-green-700' : ''}
            >
              {saved
                ? <><Check size={12} className="mr-1" />Saved</>
                : saving
                  ? <><RefreshCw size={12} className="mr-1 animate-spin" />Saving…</>
                  : <>
                      <Save size={12} className="mr-1" />
                      Save changes {changedCount > 0 && `(${changedCount})`}
                    </>
              }
            </Button>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
          {error}
        </div>
      )}

      {/* Tooltip — fixed-height slot prevents layout shift on hover */}
      <div className="mb-3 h-8 flex items-center">
        {tooltip && (
          <div className="px-3 py-1.5 bg-gray-800 text-white rounded-lg text-xs max-w-xs">
            <span className="font-mono font-semibold">{tooltip.key}</span>
            <span className="text-gray-300 ml-2">— {tooltip.desc}</span>
          </div>
        )}
      </div>

      {/* Matrix table */}
      <div className="overflow-x-auto rounded-xl border border-gray-200">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-50/80 border-b border-gray-200">
              <th className="w-52 px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-gray-400">
                Permission
              </th>
              {ROLES.map(r => (
                <th key={r.key} className="px-3 py-3 text-center text-[11px] font-bold uppercase tracking-wide text-gray-500">
                  <div className="flex flex-col items-center gap-0.5">
                    {r.admin && <Lock size={10} className="text-gray-300" />}
                    {r.label}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PERMISSION_GROUPS.map(group => (
              <>
                <tr key={`group-${group.label}`} className="bg-gray-50/40 border-y border-gray-100">
                  <td
                    colSpan={ROLES.length + 1}
                    className="px-4 py-1.5"
                  >
                    <div className="flex items-center gap-2">
                      <span className={cn('w-2 h-2 rounded-full', group.color)} />
                      <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        {group.label}
                      </span>
                    </div>
                  </td>
                </tr>
                {group.perms.map(perm => (
                  <tr
                    key={perm.key}
                    className="border-b border-gray-100 last:border-0 hover:bg-gray-50/30 transition-colors"
                  >
                    <td
                      className="px-4 py-2.5 cursor-help"
                      onMouseEnter={() => setTooltip(perm)}
                      onMouseLeave={() => setTooltip(null)}
                    >
                      <div className="flex items-center gap-2">
                        <span className={cn('w-1 self-stretch rounded-full', group.color)} />
                        <span className="font-mono text-[12px] text-gray-700">{perm.key}</span>
                      </div>
                    </td>
                    {ROLES.map(role => {
                      const granted = matrix[role.key]?.[perm.key] ?? false
                      const changed = serverMatrix && (matrix[role.key]?.[perm.key] !== serverMatrix[role.key]?.[perm.key])
                      return (
                        <td key={role.key} className="px-3 py-2.5 text-center">
                          <button
                            onClick={() => toggleCell(role.key, perm.key)}
                            disabled={role.admin || !isAdmin}
                            title={role.admin ? 'Admin always has all permissions' : undefined}
                            className={cn(
                              'w-6 h-6 rounded border-2 flex items-center justify-center mx-auto transition-all',
                              role.admin
                                ? 'bg-gray-100 border-gray-200 cursor-not-allowed'
                                : granted
                                  ? cn('bg-blue-600 border-blue-600', changed && 'ring-2 ring-amber-400 ring-offset-1')
                                  : cn('bg-white border-gray-300', isAdmin && 'hover:border-blue-400 cursor-pointer', changed && 'ring-2 ring-amber-400 ring-offset-1'),
                            )}
                          >
                            {role.admin
                              ? <Lock size={10} className="text-gray-400" />
                              : granted && <Check size={11} className="text-white" />
                            }
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </>
            ))}
          </tbody>
        </table>
      </div>

      {/* Per-role permission counts */}
      <div className="mt-4 flex items-center gap-4">
        {ROLES.filter(r => !r.admin).map(role => {
          const grantedCount = PERMISSION_GROUPS.flatMap(g => g.perms)
            .filter(p => matrix[role.key]?.[p.key]).length
          const total = PERMISSION_GROUPS.flatMap(g => g.perms).length
          const pct = Math.round((grantedCount / total) * 100)
          return (
            <div key={role.key} className="flex-1">
              <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
                <span>{role.label}</span>
                <span>{grantedCount}/{total}</span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Settings page ──────────────────────────────────────────────────────────────

const TABS = ['General', 'Access Control']

export default function Settings() {
  const [activeTab, setActiveTab] = useState('Access Control')
  // Determine if the current user has admin role to show/hide save controls.
  // The RBAC matrix GET endpoint requires audit.read (all roles); the PUT
  // endpoint enforces admin server-side — we just hide the controls here
  // for a better UX. We use a simple heuristic: try to parse the JWT from
  // localStorage.
  const [isAdmin, setIsAdmin] = useState(false)

  useEffect(() => {
    try {
      const raw = localStorage.getItem('kc_token') || localStorage.getItem('aispm_token') || ''
      if (raw) {
        const payload = JSON.parse(atob(raw.split('.')[1]))
        const roles = payload?.realm_access?.roles || payload?.roles || []
        setIsAdmin(roles.some(r => r === 'spm:admin' || r === 'admin'))
      }
    } catch (_) { /* token absent or malformed — stay non-admin */ }
  }, [])

  return (
    <PageContainer>
      <PageHeader
        title="Settings"
        subtitle="Platform configuration, access control, and notifications"
      />

      {/* Tab bar */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab
                ? 'text-blue-600 border-blue-600'
                : 'text-gray-500 border-transparent hover:text-gray-700',
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'General' && (
        <div className="bg-white border border-gray-200 rounded-xl p-8 flex flex-col items-center justify-center h-48 gap-2">
          <p className="text-sm font-semibold text-gray-400">General settings</p>
          <p className="text-xs text-gray-300">Thresholds and notification configuration — coming soon</p>
        </div>
      )}

      {activeTab === 'Access Control' && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
          <RbacMatrix isAdmin={isAdmin} />
        </div>
      )}
    </PageContainer>
  )
}
