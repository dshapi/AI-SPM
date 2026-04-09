// src/admin/shell/Topbar.jsx
import { PanelLeftClose, PanelLeftOpen, CalendarDays, ChevronDown, CircleHelp, Settings, Building2 } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { SearchCommand }     from './SearchCommand.jsx'
import { NotificationsMenu } from './NotificationsMenu.jsx'
import { IconButton }        from '../../components/ui/IconButton.jsx'
import { Separator }         from '../../components/ui/Separator.jsx'
import { Breadcrumbs }       from '../../components/navigation/Breadcrumbs.jsx'
import { useTenant }         from '../../context/TenantContext.jsx'

// ── Tenant selector ────────────────────────────────────────────────────────────
function TenantSelector() {
  const { tenant, setTenant, tenants } = useTenant()
  const current = tenants.find(t => t.id === tenant) ?? tenants[0]

  return (
    <div className="relative group/tenant">
      <button className={cn(
        'flex items-center gap-2 h-10 px-3 rounded-lg border border-gray-200 bg-white',
        'text-sm font-medium text-gray-600',
        'hover:border-gray-300 hover:bg-gray-50 transition-colors duration-150',
        'whitespace-nowrap shrink-0',
      )}>
        <Building2 size={14} strokeWidth={1.75} className="text-gray-400 shrink-0" />
        {current.label}
        <ChevronDown size={12} strokeWidth={2} className="text-gray-400 shrink-0" />
      </button>

      {/* Dropdown */}
      <div className={cn(
        'absolute top-full right-0 mt-1.5 min-w-[160px] z-50',
        'bg-white border border-gray-200 rounded-xl shadow-lg py-1',
        'opacity-0 pointer-events-none group-hover/tenant:opacity-100 group-hover/tenant:pointer-events-auto',
        'transition-opacity duration-150',
      )}>
        {tenants.map(t => (
          <button
            key={t.id}
            onClick={() => setTenant(t.id)}
            className={cn(
              'w-full text-left px-3 py-2 text-sm transition-colors duration-100',
              t.id === tenant
                ? 'text-blue-600 font-semibold bg-blue-50'
                : 'text-gray-700 hover:bg-gray-50',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
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

        <TenantSelector />

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
