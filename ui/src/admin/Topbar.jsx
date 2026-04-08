import {
  PanelLeftClose, PanelLeftOpen,
  CalendarDays, ChevronDown,
  CircleHelp, Settings,
} from 'lucide-react'
import SearchInput          from './components/SearchInput.jsx'
import NotificationDropdown from './components/NotificationDropdown.jsx'

/**
 * Topbar — global horizontal navigation bar.
 *
 * Props:
 *   collapsed  boolean    — mirrors sidebar collapsed state
 *   onToggle   () => void — fires sidebar collapse/expand
 *
 * Layout (left → right):
 *   [toggle] [sep] [breadcrumb …flex-1] [search …fixed w-80] [controls …flex-1] [avatar]
 *
 * Design tokens:
 *   height         h-16 — aligns with sidebar logo zone border-b on same pixel
 *   bg             bg-white border-b border-gray-200
 *   padding        px-4 (slightly tighter than px-6 to leave room for toggle)
 *   icon buttons   w-10 h-10 rounded-lg, text-gray-400 hover:text-gray-700 hover:bg-gray-100
 *   separators     w-px h-5 bg-gray-200
 *   no shadows     — borders only
 */

// ── Separator ─────────────────────────────────────────────────────────────
const Sep = () => (
  <div className="w-px h-5 bg-gray-200 shrink-0" aria-hidden="true" />
)

// ── Breadcrumb ────────────────────────────────────────────────────────────
// Static for now; a real app would derive this from the current route.
function Breadcrumb() {
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span className="text-[13px] font-medium text-gray-400 leading-none whitespace-nowrap">Orbyx</span>
      <span className="text-gray-300 leading-none select-none">/</span>
      <span className="text-[13px] font-semibold text-gray-700 leading-none truncate">Dashboard</span>
    </div>
  )
}

// ── Time range selector ───────────────────────────────────────────────────
function TimeRange() {
  return (
    <button className="flex items-center gap-2 h-10 px-3 bg-white border border-gray-200 rounded-lg text-[13px] font-medium text-gray-600 hover:border-gray-300 hover:bg-gray-50 transition-colors duration-150 whitespace-nowrap shrink-0">
      <CalendarDays size={14} strokeWidth={1.75} className="text-gray-400 shrink-0" />
      Last 24 hours
      <ChevronDown  size={12} strokeWidth={2}    className="text-gray-400 shrink-0" />
    </button>
  )
}

// ── Generic icon button ───────────────────────────────────────────────────
function IconButton({ icon: Icon, title }) {
  return (
    <button
      className="flex items-center justify-center w-10 h-10 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors duration-150"
      title={title}
    >
      <Icon size={18} strokeWidth={1.75} />
    </button>
  )
}

// ── Avatar button ─────────────────────────────────────────────────────────
function AvatarButton() {
  return (
    <button
      className="flex items-center justify-center w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 text-[13px] font-bold text-white shrink-0 hover:opacity-90 transition-opacity duration-150"
      title="Account"
    >
      A
    </button>
  )
}

// ── Topbar ────────────────────────────────────────────────────────────────
export default function Topbar({ collapsed, onToggle }) {
  return (
    <header className="h-16 shrink-0 bg-white border-b border-gray-200 flex items-center px-4 gap-3">

      {/* ── Sidebar toggle ───────────────────────────────────────────────── */}
      <button
        onClick={onToggle}
        className="flex items-center justify-center w-10 h-10 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors duration-150 shrink-0"
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed
          ? <PanelLeftOpen  size={18} strokeWidth={1.75} />
          : <PanelLeftClose size={18} strokeWidth={1.75} />}
      </button>

      <Sep />

      {/* ── LEFT — breadcrumb ────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex items-center">
        <Breadcrumb />
      </div>

      {/* ── CENTER — global search ───────────────────────────────────────── */}
      <SearchInput />

      {/* ── RIGHT — time range · icons · avatar ─────────────────────────── */}
      {/*
       * Spacing system: gap-2 (8px) between every direct child.
       * Children: [TimeRange] [Sep] [icon cluster] [Sep] [Avatar]
       * Effective visual gap between groups: 8px + 1px sep + 8px = 17px.
       */}
      <div className="flex-1 min-w-0 flex items-center justify-end gap-2">

        <TimeRange />

        <Sep />

        {/* Icon cluster — gap-1 (4px) keeps 40×40 hover targets close but distinct */}
        <div className="flex items-center gap-1">
          <NotificationDropdown />
          <IconButton icon={CircleHelp} title="Help"     />
          <IconButton icon={Settings}  title="Settings"  />
        </div>

        <Sep />

        <AvatarButton />

      </div>

    </header>
  )
}
