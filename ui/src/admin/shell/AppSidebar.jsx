import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/utils.js'
import { ChevronRight } from 'lucide-react'
import { NAV, PINNED } from '../../config/navigation.js'

/**
 * AppSidebar — collapsible navigation sidebar.
 *
 * Structure:
 *   ┌──────────────────────────┐
 *   │  Branding (h-16)         │
 *   ├──────────────────────────┤
 *   │  ● Overview  (pinned)    │  ← always first, above all sections
 *   ├──────────────────────────┤
 *   │  Monitor                 │
 *   │    Dashboard             │
 *   │    Posture               │
 *   │    Alerts                │
 *   │  Discover                │
 *   │    Inventory             │
 *   │    Identity & Trust      │
 *   │    Data & Knowledge      │
 *   │  Protect                 │
 *   │    Runtime               │
 *   │    Policies              │
 *   │    Lineage               │
 *   │  Validate                │
 *   │    Simulation            │
 *   │    Cases                 │
 *   │    Automation            │
 *   │  Platform                │
 *   │    Integrations          │
 *   │    Settings              │
 *   ├──────────────────────────┤
 *   │  User footer             │
 *   └──────────────────────────┘
 *
 * COLLAPSE: Uses conditional rendering (not CSS hide) for labels and
 * section headers. See inline comments for positioning rationale.
 */

// ── NavItem ───────────────────────────────────────────────────────────────────

function NavItem({ to, icon: Icon, label, end = false, collapsed, pinned = false }) {
  return (
    <div className="relative group/navitem">
      <NavLink
        to={to}
        end={end}
        className={({ isActive }) =>
          cn(
            'relative flex items-center w-full h-10 text-[13px] rounded-lg',
            'transition-colors duration-150 cursor-pointer select-none',
            collapsed ? 'justify-center' : 'gap-3 px-3',
            isActive
              ? pinned
                /* Pinned Overview item: slightly stronger active treatment */
                ? 'bg-blue-50 text-blue-600 font-bold'
                : 'bg-blue-50 text-blue-600 font-semibold'
              : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700 font-medium',
          )
        }
      >
        {({ isActive }) => (
          <>
            {/* Active accent pill — expanded mode only */}
            {isActive && !collapsed && (
              <span className={cn(
                'absolute left-0 top-1/2 -translate-y-1/2 w-[3px] rounded-full',
                pinned ? 'h-6 bg-blue-600' : 'h-5 bg-blue-600',
              )} />
            )}

            <Icon
              size={16}
              strokeWidth={pinned ? 2 : 1.75}
              className={cn(
                'block shrink-0 transition-opacity duration-150',
                isActive ? 'opacity-100' : 'opacity-50 group-hover/navitem:opacity-90',
              )}
            />

            {!collapsed && (
              <span className="truncate leading-none">{label}</span>
            )}
          </>
        )}
      </NavLink>

      {/* Tooltip — collapsed mode only */}
      {collapsed && (
        <div className={cn(
          'pointer-events-none',
          'absolute left-full top-1/2 -translate-y-1/2 ml-2',
          'px-2.5 py-1.5 bg-gray-900 text-white text-xs font-medium',
          'rounded-md whitespace-nowrap shadow-md',
          'opacity-0 group-hover/navitem:opacity-100',
          'transition-opacity duration-150',
          'z-50',
        )}>
          {label}
        </div>
      )}
    </div>
  )
}

// ── AppSidebar ────────────────────────────────────────────────────────────────

export function AppSidebar({ collapsed }) {
  return (
    <aside
      className={cn(
        'shrink-0 h-screen flex flex-col bg-white border-r border-gray-200',
        'transition-[width] duration-200 ease-in-out',
        collapsed ? 'w-20' : 'w-64',
      )}
      style={{ willChange: 'width' }}
    >

      {/* ── Branding ─────────────────────────────────────────────────────── */}
      <div className={cn(
        'h-16 shrink-0 flex items-center border-b border-gray-200',
        collapsed ? 'justify-center' : 'px-4 gap-3',
      )}>
        <img src="/logo.png" alt="Orbyx" className="w-12 h-12 object-contain shrink-0" />
        {!collapsed && (
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900 leading-none">Orbyx</p>
            <p className="text-xs text-gray-400 mt-[3px] leading-none">AI-SPM</p>
          </div>
        )}
      </div>

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      <nav className={cn(
        'flex-1 py-2',
        !collapsed && 'px-2 overflow-y-auto',
      )}>

        {/* ── Pinned Overview item — above all sections ─────────────────── */}
        <div className={cn(!collapsed ? 'px-0 mb-1' : 'mb-1')}>
          <NavItem collapsed={collapsed} pinned {...PINNED} />
        </div>

        {/* Separator between pinned item and sections */}
        {!collapsed
          ? <div className="border-t border-gray-100 mx-1 mb-2" />
          : <div className="border-t border-gray-100 mx-3 mb-2" />
        }

        {/* ── Sectioned navigation ──────────────────────────────────────── */}
        {NAV.map(({ section, items }, i) => (
          <div key={section} className={i > 0 ? 'mt-1' : ''}>

            {!collapsed ? (
              <p className="px-3 pt-2.5 pb-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-gray-400 leading-none">
                {section}
              </p>
            ) : (
              i > 0 && <div className="border-t border-gray-100 my-2 mx-3" />
            )}

            <div className="space-y-px">
              {items.map(item => (
                <NavItem key={item.to} collapsed={collapsed} {...item} />
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* ── Footer — user account ─────────────────────────────────────────── */}
      <div className="border-t border-gray-100 shrink-0 py-3">
        <div className={cn(
          'flex items-center cursor-pointer rounded-lg',
          'hover:bg-gray-50 transition-colors duration-150 group/footer',
          collapsed ? 'justify-center h-10 mx-0' : 'gap-3 px-4 py-2.5 mx-2',
        )}>
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-[11px] font-bold text-white shrink-0">
            A
          </div>
          {!collapsed && (
            <>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-gray-800 truncate leading-snug">Admin</p>
                <p className="text-[11px] text-gray-400 truncate leading-snug">admin@orbyx.ai</p>
              </div>
              <ChevronRight
                size={13}
                strokeWidth={1.75}
                className="text-gray-300 group-hover/footer:text-gray-500 transition-colors shrink-0"
              />
            </>
          )}
        </div>
      </div>

    </aside>
  )
}
