// src/admin/shell/Topbar.jsx
import { useState, useEffect, useRef } from 'react'
import { PanelLeftClose, PanelLeftOpen, CalendarDays, ChevronDown, CircleHelp, Settings, LogOut } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { SearchCommand }     from './SearchCommand.jsx'
import { NotificationsMenu } from './NotificationsMenu.jsx'
import { IconButton }        from '../../components/ui/IconButton.jsx'
import { Separator }         from '../../components/ui/Separator.jsx'
import { Breadcrumbs }       from '../../components/navigation/Breadcrumbs.jsx'
import { logout }            from '../../api.js'

// ── Time range selector ────────────────────────────────────────────────────────
function TimeRange() {
  return (
    <button className={cn(
      'flex items-center gap-2 h-10 px-3 rounded-lg border border-gray-200 bg-white',
      'text-sm font-medium text-gray-600',
      'hover:border-gray-300 hover:bg-gray-50 transition-colors duration-150',
      'whitespace-nowrap shrink-0',
    )}>
      <CalendarDays size={14} strokeWidth={1.75} className="text-gray-400 shrink-0" />
      Last 24 hours
      <ChevronDown  size={12} strokeWidth={2}    className="text-gray-400 shrink-0" />
    </button>
  )
}

// ── Avatar menu ────────────────────────────────────────────────────────────────
function AvatarMenu() {
  const [open, setOpen] = useState(false)
  const [pos, setPos]   = useState({ top: 0, right: 0 })
  const btnRef   = useRef(null)
  const panelRef = useRef(null)

  function handleOpen() {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({ top: r.bottom + 8, right: window.innerWidth - r.right })
    }
    setOpen(v => !v)
  }

  useEffect(() => {
    if (!open) return
    function handle(e) {
      // Close only when clicking outside BOTH the trigger button and the panel.
      // Without the panelRef check, mousedown on "Log out" closes the panel
      // before the click event fires, so the handler never runs.
      const outsideBtn   = btnRef.current   && !btnRef.current.contains(e.target)
      const outsidePanel = panelRef.current && !panelRef.current.contains(e.target)
      if (outsideBtn && outsidePanel) setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [open])

  return (
    <div className="relative shrink-0">
      <button
        ref={btnRef}
        onClick={handleOpen}
        className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-sm font-bold text-white shrink-0 hover:opacity-90 transition-opacity"
        title="Account"
        aria-haspopup="true"
        aria-expanded={open}
      >
        A
      </button>

      {open && (
        <div
          ref={panelRef}
          style={{ position: 'fixed', top: pos.top, right: pos.right, zIndex: 9999 }}
          className="w-56 bg-white border border-gray-200 rounded-lg shadow-lg py-1"
        >
          <div className="px-4 py-3">
            <p className="text-[13px] font-semibold text-gray-700 leading-tight">Admin</p>
            <p className="text-[12px] text-gray-400 leading-tight mt-0.5">admin@orbyx.ai</p>
          </div>
          <div className="h-px bg-gray-200 mx-1 my-1" />
          <button
            onClick={() => { setOpen(false); logout() }}
            className="flex items-center gap-2.5 w-full px-4 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors duration-150"
          >
            <LogOut size={14} strokeWidth={1.75} className="text-gray-400 shrink-0" />
            Log out
          </button>
        </div>
      )}
    </div>
  )
}

// ── Topbar ─────────────────────────────────────────────────────────────────────
export function Topbar({ collapsed, onToggle }) {
  return (
    <header className="h-16 shrink-0 bg-white border-b border-gray-200 flex items-center px-4 gap-3">

      {/* Collapse toggle */}
      <IconButton
        onClick={onToggle}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className="shrink-0"
      >
        {collapsed
          ? <PanelLeftOpen  size={18} strokeWidth={1.75} />
          : <PanelLeftClose size={18} strokeWidth={1.75} />}
      </IconButton>

      <Separator orientation="vertical" />

      {/* Breadcrumbs — takes remaining left space */}
      <div className="flex-1 min-w-0 flex items-center">
        <Breadcrumbs />
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-2">

        <SearchCommand />

        <Separator orientation="vertical" />

        <TimeRange />

        <Separator orientation="vertical" className="ml-1" />

        <div className="flex items-center gap-0.5">
          <NotificationsMenu />
          <IconButton title="Help">
            <CircleHelp size={18} strokeWidth={1.75} />
          </IconButton>
          <IconButton title="Settings">
            <Settings size={18} strokeWidth={1.75} />
          </IconButton>
        </div>

        <Separator orientation="vertical" />

        <AvatarMenu />

      </div>

    </header>
  )
}
