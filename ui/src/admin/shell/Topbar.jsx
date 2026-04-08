import { PanelLeftClose, PanelLeftOpen, CalendarDays, ChevronDown, CircleHelp, Settings } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { SearchCommand }     from './SearchCommand.jsx'
import { NotificationsMenu } from './NotificationsMenu.jsx'
import { IconButton }        from '../../components/ui/IconButton.jsx'
import { Separator }         from '../../components/ui/Separator.jsx'

/**
 * Topbar — global horizontal shell bar.
 *
 * Layout (left → right):
 *   [collapse toggle] [sep] [breadcrumb flex-1] [search] [controls flex-1 justify-end] [avatar]
 *
 * All interactive controls: h-10 (40px) per design system spec.
 * Separators: h-5 (20px).
 */

// ── Breadcrumb ─────────────────────────────────────────────────────────────────
function Breadcrumb() {
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span className="text-sm text-gray-400 leading-none whitespace-nowrap">Orbyx</span>
      <span className="text-gray-300 leading-none select-none">/</span>
      <span className="text-sm font-semibold text-gray-700 leading-none truncate">Dashboard</span>
    </div>
  )
}

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

// ── Topbar ────────────────────────────────────────────────────────────────────
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

      {/* Breadcrumb — takes remaining left space */}
      <div className="flex-1 min-w-0 flex items-center">
        <Breadcrumb />
      </div>

      {/* Right cluster — search anchored left of controls */}
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

        <button
          className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-sm font-bold text-white shrink-0 hover:opacity-90 transition-opacity"
          title="Account"
        >
          A
        </button>

      </div>

    </header>
  )
}
