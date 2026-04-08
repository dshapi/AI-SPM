import { useRef, useState, useEffect } from 'react'
import {
  Bell, TriangleAlert, FileCheck2,
  Info, CheckCircle2, CheckCheck,
} from 'lucide-react'

/**
 * NotificationDropdown — bell icon with unread badge + notification panel.
 *
 * State:
 *   open          — dropdown visibility
 *   notifications — list with per-item unread flag
 *
 * Interactions:
 *   • Click bell  → open / close
 *   • Click item  → mark that notification read
 *   • Mark all read → flush all unread flags
 *   • Outside click / Escape → close
 *
 * Visual tokens:
 *   button      w-8 h-8 rounded-lg, text-gray-400 hover:text-gray-700 hover:bg-gray-100
 *   badge       absolute top-[5px] right-[5px] w-[7px] h-[7px] bg-red-500 rounded-full ring-white
 *   dropdown    w-[380px] bg-white border-gray-200 rounded-xl shadow-lg z-40
 */

// ── Type → icon / colours map ─────────────────────────────────────────────
const TYPE_STYLE = {
  alert:   { Icon: TriangleAlert,  bg: 'bg-red-50',    color: 'text-red-500'    },
  policy:  { Icon: FileCheck2,     bg: 'bg-orange-50', color: 'text-orange-500' },
  info:    { Icon: Info,           bg: 'bg-blue-50',   color: 'text-blue-500'   },
  success: { Icon: CheckCircle2,   bg: 'bg-green-50',  color: 'text-green-500'  },
}

// ── Mock notifications ────────────────────────────────────────────────────
const INITIAL_NOTIFICATIONS = [
  {
    id: 1,
    type: 'alert',
    title: 'Prompt injection attempt blocked',
    desc:  'lim-agent-prod · gpt-4-turbo · tenant-1',
    time:  '2m ago',
    unread: true,
  },
  {
    id: 2,
    type: 'alert',
    title: 'New high-risk alert on ai-threat-sim-001',
    desc:  'Severity: High · mixtral-8x7b · tenant-2',
    time:  '18m ago',
    unread: true,
  },
  {
    id: 3,
    type: 'policy',
    title: 'Policy violation spike detected',
    desc:  '27 violations in last 1h — +400% above baseline',
    time:  '1h ago',
    unread: true,
  },
  {
    id: 4,
    type: 'success',
    title: 'Simulation run completed successfully',
    desc:  'Policy dry-run on 3,200 events · 0 false positives',
    time:  '2h ago',
    unread: false,
  },
  {
    id: 5,
    type: 'info',
    title: 'New model registered: llama-3.1-405b',
    desc:  'Added to inventory by admin@orbyx.ai',
    time:  '3h ago',
    unread: false,
  },
]

// ── Component ────────────────────────────────────────────────────────────
export default function NotificationDropdown() {
  const [open, setOpen]                 = useState(false)
  const [notifications, setNotifications] = useState(INITIAL_NOTIFICATIONS)
  const buttonRef                       = useRef(null)
  const dropdownRef                     = useRef(null)

  const unreadCount = notifications.filter(n => n.unread).length

  // ── Outside click ────────────────────────────────────────────────────────
  useEffect(() => {
    function onMouseDown(e) {
      if (
        open &&
        !buttonRef.current?.contains(e.target) &&
        !dropdownRef.current?.contains(e.target)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  // ── Escape ───────────────────────────────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape' && open) setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  function markAllRead() {
    setNotifications(prev => prev.map(n => ({ ...n, unread: false })))
  }

  function markRead(id) {
    setNotifications(prev =>
      prev.map(n => (n.id === id ? { ...n, unread: false } : n))
    )
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="relative">

      {/* ── Bell button ────────────────────────────────────────────────────── */}
      <button
        ref={buttonRef}
        onClick={() => setOpen(v => !v)}
        className="relative flex items-center justify-center w-10 h-10 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors duration-150"
        title="Notifications"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <Bell size={18} strokeWidth={1.75} />

        {/* Unread badge — ring-white creates white knockout separating dot from icon */}
        {unreadCount > 0 && (
          <span
            className="absolute top-[5px] right-[5px] w-[7px] h-[7px] bg-red-500 rounded-full ring-[1.5px] ring-white"
            aria-label={`${unreadCount} unread notifications`}
          />
        )}
      </button>

      {/* ── Dropdown ───────────────────────────────────────────────────────── */}
      {open && (
        <div
          ref={dropdownRef}
          role="dialog"
          aria-label="Notifications"
          className="animate-dropdown absolute right-0 top-full mt-2 w-[380px] bg-white border border-gray-200 rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.08),0_1px_4px_rgba(0,0,0,0.04)] z-40 overflow-hidden"
        >

          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-900">Notifications</span>
              {unreadCount > 0 && (
                <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-red-500 text-white text-[10px] font-bold rounded-full leading-none">
                  {unreadCount}
                </span>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="flex items-center gap-1.5 text-[12px] font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                <CheckCheck size={13} strokeWidth={2} />
                Mark all read
              </button>
            )}
          </div>

          {/* Notification list */}
          <div className="max-h-[380px] overflow-y-auto divide-y divide-gray-50">
            {notifications.map(n => {
              const style = TYPE_STYLE[n.type] ?? TYPE_STYLE.info
              const { Icon: NIcon, bg, color } = style

              return (
                <button
                  key={n.id}
                  onClick={() => markRead(n.id)}
                  className="w-full flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors duration-100 text-left"
                >
                  {/* Type icon chip */}
                  <div className={`flex items-center justify-center w-8 h-8 rounded-lg shrink-0 mt-0.5 ${bg}`}>
                    <NIcon size={15} className={color} strokeWidth={1.75} />
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <p className={`text-[13px] leading-snug ${n.unread ? 'font-semibold text-gray-900' : 'font-medium text-gray-600'}`}>
                      {n.title}
                    </p>
                    <p className="text-[12px] text-gray-400 mt-0.5 truncate">{n.desc}</p>
                    <p className="text-[11px] text-gray-400 mt-1">{n.time}</p>
                  </div>

                  {/* Unread indicator dot */}
                  {n.unread && (
                    <div className="w-1.5 h-1.5 bg-blue-500 rounded-full shrink-0 mt-2" />
                  )}
                </button>
              )
            })}
          </div>

          {/* Footer */}
          <div className="px-4 py-3 border-t border-gray-100 bg-gray-50">
            <button className="w-full text-center text-[13px] font-medium text-blue-600 hover:text-blue-700 transition-colors">
              View all notifications →
            </button>
          </div>

        </div>
      )}

    </div>
  )
}
