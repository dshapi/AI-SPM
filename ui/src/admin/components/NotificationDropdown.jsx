import { useRef, useState, useEffect } from 'react'
import { Bell, TriangleAlert, Info, CheckCheck, BellOff } from 'lucide-react'
import { useCaseNotifications } from '../../hooks/useCaseNotifications.js'

/**
 * NotificationDropdown — bell icon with unread badge + notification panel.
 * Data is sourced live from GET /api/v1/cases via useCaseNotifications hook.
 */

// ── Type → icon / colours map ─────────────────────────────────────────────
const TYPE_STYLE = {
  alert:   { Icon: TriangleAlert, bg: 'bg-red-50',   color: 'text-red-500'  },
  info:    { Icon: Info,          bg: 'bg-blue-50',  color: 'text-blue-500' },
}

// ── Component ────────────────────────────────────────────────────────────
export default function NotificationDropdown() {
  const { notifications, markRead, markAllRead, loading } = useCaseNotifications()
  const [open, setOpen] = useState(false)
  const buttonRef       = useRef(null)
  const dropdownRef     = useRef(null)

  const unreadCount = notifications.filter(n => n.unread).length

  // ── Outside click ────────────────────────────────────────────────────────
  useEffect(() => {
    function onMouseDown(e) {
      if (
        open &&
        !buttonRef.current?.contains(e.target) &&
        !dropdownRef.current?.contains(e.target)
      ) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  // ── Escape ───────────────────────────────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e) { if (e.key === 'Escape' && open) setOpen(false) }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

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
            {loading ? (
              <div className="flex items-center justify-center py-10 text-gray-400">
                <span className="text-[13px]">Loading…</span>
              </div>
            ) : notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 gap-2 text-gray-400">
                <BellOff size={22} strokeWidth={1.5} />
                <span className="text-[13px]">No notifications yet</span>
                <span className="text-[11px] text-gray-300">Cases opened by you or the threat hunter will appear here</span>
              </div>
            ) : (
              notifications.map(n => {
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
                      <p className="text-[12px] text-gray-400 mt-0.5 truncate">{n.sub}</p>
                      <p className="text-[11px] text-gray-400 mt-1">{n.time}</p>
                    </div>

                    {/* Unread indicator dot */}
                    {n.unread && (
                      <div className="w-1.5 h-1.5 bg-blue-500 rounded-full shrink-0 mt-2" />
                    )}
                  </button>
                )
              })
            )}
          </div>

          {/* Footer */}
          <div className="px-4 py-3 border-t border-gray-100 bg-gray-50">
            <a
              href="/admin/cases"
              className="w-full block text-center text-[13px] font-medium text-blue-600 hover:text-blue-700 transition-colors"
              onClick={() => setOpen(false)}
            >
              View all cases →
            </a>
          </div>

        </div>
      )}

    </div>
  )
}
