import { useState, useRef, useCallback } from 'react'
import { Bell, TriangleAlert, FileCheck2, Info, CheckCircle2, CheckCheck } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { useClickOutside } from '../../hooks/useClickOutside.js'

// ── Notification types ─────────────────────────────────────────────────────────
const TYPE = {
  alert:   { icon: TriangleAlert,  color: 'text-red-500',    bg: 'bg-red-50'    },
  policy:  { icon: FileCheck2,     color: 'text-orange-500', bg: 'bg-orange-50' },
  info:    { icon: Info,           color: 'text-blue-500',   bg: 'bg-blue-50'   },
  success: { icon: CheckCircle2,   color: 'text-emerald-500',bg: 'bg-emerald-50'},
}

// ── Mock data ──────────────────────────────────────────────────────────────────
const INITIAL = [
  { id: 1, type: 'alert',   title: 'Prompt injection detected',  sub: 'gpt-4-turbo · tenant-1', time: '2m ago',  unread: true  },
  { id: 2, type: 'policy',  title: 'Policy violation threshold',  sub: '27 violations today',    time: '14m ago', unread: true  },
  { id: 3, type: 'info',    title: 'New model registered',        sub: 'llama-3-70b added',      time: '1h ago',  unread: true  },
  { id: 4, type: 'success', title: 'Simulation run complete',     sub: 'Policy v3 passed',       time: '3h ago',  unread: false },
  { id: 5, type: 'alert',   title: 'Jailbreak pattern matched',   sub: 'mixtral-8x7b · tenant-2','time': '5h ago', unread: false },
]

// ── Component ──────────────────────────────────────────────────────────────────
export function NotificationsMenu() {
  const [notes, setNotes] = useState(INITIAL)
  const [open, setOpen]   = useState(false)
  const buttonRef         = useRef(null)
  const menuRef           = useRef(null)

  const unreadCount = notes.filter(n => n.unread).length

  const toggle       = () => setOpen(v => !v)
  const markAllRead  = () => setNotes(ns => ns.map(n => ({ ...n, unread: false })))
  const markRead     = id => setNotes(ns => ns.map(n => n.id === id ? { ...n, unread: false } : n))

  const close = useCallback(() => setOpen(false), [])
  useClickOutside([buttonRef, menuRef], close)

  return (
    <div className="relative">

      {/* ── Bell button ── */}
      <button
        ref={buttonRef}
        onClick={toggle}
        aria-label="Notifications"
        aria-haspopup="true"
        aria-expanded={open}
        className={cn(
          'relative w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
          'transition-colors duration-150 focus-visible:outline-none',
          open
            ? 'bg-gray-100 text-gray-700'
            : 'text-gray-400 hover:text-gray-700 hover:bg-gray-100',
        )}
      >
        <Bell size={18} strokeWidth={1.75} />
        {unreadCount > 0 && (
          <span className="absolute top-[7px] right-[7px] w-[7px] h-[7px] bg-red-500 rounded-full ring-[1.5px] ring-white" />
        )}
      </button>

      {/* ── Dropdown ── */}
      {open && (
        <div
          ref={menuRef}
          className="animate-dropdown absolute right-0 top-full mt-1.5 w-[375px] bg-white border border-gray-200 rounded-xl shadow-[0_4px_24px_rgba(0,0,0,0.08),0_1px_4px_rgba(0,0,0,0.04)] z-50 overflow-hidden"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-900">Notifications</p>
              {unreadCount > 0 && (
                <p className="text-xs text-gray-400 mt-0.5">{unreadCount} unread</p>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                <CheckCheck size={13} strokeWidth={2} />
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-[360px] overflow-y-auto">
            {notes.map(n => {
              const T = TYPE[n.type] ?? TYPE.info
              const Icon = T.icon
              return (
                <button
                  key={n.id}
                  onClick={() => markRead(n.id)}
                  className={cn(
                    'w-full flex items-start gap-3 px-4 py-3.5 text-left',
                    'border-b border-gray-50 last:border-0',
                    'hover:bg-gray-50 transition-colors duration-100',
                    n.unread && 'bg-blue-50/30',
                  )}
                >
                  {/* Icon */}
                  <span className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5', T.bg)}>
                    <Icon size={15} strokeWidth={1.75} className={T.color} />
                  </span>

                  {/* Text */}
                  <div className="flex-1 min-w-0">
                    <p className={cn('text-sm leading-snug truncate', n.unread ? 'font-semibold text-gray-900' : 'font-medium text-gray-700')}>
                      {n.title}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5 truncate">{n.sub}</p>
                    <p className="text-[11px] text-gray-300 mt-1">{n.time}</p>
                  </div>

                  {/* Unread dot */}
                  {n.unread && (
                    <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0 mt-2" />
                  )}
                </button>
              )
            })}
          </div>

          {/* Footer */}
          <div className="px-4 py-2.5 border-t border-gray-100">
            <button className="text-xs font-medium text-blue-600 hover:text-blue-700 transition-colors">
              View all notifications →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
