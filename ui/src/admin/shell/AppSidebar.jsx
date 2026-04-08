import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/utils.js'
import {
  LayoutDashboard, Shield, TriangleAlert,
  Boxes, Database, Fingerprint,
  Activity, ScrollText, GitBranch,
  FlaskConical, ClipboardList, Workflow,
  Plug, Settings, ChevronRight,
} from 'lucide-react'

/**
 * AppSidebar — true collapsible navigation sidebar.
 *
 * ─────────────────────────────────────────────────────────────
 * COLLAPSE IMPLEMENTATION — WHY THIS WORKS
 * ─────────────────────────────────────────────────────────────
 *
 * Previous attempts used CSS max-width/opacity tricks to "hide" labels,
 * which caused layout artifacts and an incomplete visual collapse.
 *
 * This implementation uses CONDITIONAL RENDERING:
 *   {!collapsed && <span>{label}</span>}
 *
 * Why this is correct:
 * 1. Labels are truly absent from the DOM when collapsed — no hidden
 *    text contributes to layout, no overflow, no bleed.
 * 2. The width transition (transition-[width] duration-200) on the aside
 *    provides all the visual animation. The content switches cleanly.
 * 3. No layout hacks required: full-width items in both states.
 *
 * NAV ITEMS IN COLLAPSED MODE
 * ─────────────────────────────────────────────────────────────
 * Expanded:   w-full, flex, gap-3, px-3, icon + label
 * Collapsed:  w-full, flex, justify-center, no padding — icon only
 *
 * Full-width (not fixed w-10) ensures the hover background extends to
 * the full 80px rail edge-to-edge, matching Wiz/Datadog behavior.
 *
 * TOOLTIP POSITIONING
 * ─────────────────────────────────────────────────────────────
 * Tooltip: position absolute, left: 100% of group/navitem div.
 *
 * In collapsed mode, nav has NO horizontal padding, so group/navitem
 * fills the full sidebar content width (80px - 1px border = 79px).
 * left:100% puts tooltip right at sidebar edge. ml-2 adds 8px gap.
 *
 * Tooltips are NOT clipped because:
 * - aside has no overflow set (defaults to visible)
 * - nav only gets overflow-y-auto in EXPANDED mode (setting overflow-y
 *   to anything non-visible forces overflow-x:auto per CSS spec §9.1.1,
 *   which would clip absolutely-positioned tooltip children)
 *
 * SECTION HEADERS
 * ─────────────────────────────────────────────────────────────
 * Conditionally rendered (not hidden with CSS). In collapsed mode,
 * the space they occupied is also gone — a thin divider replaces them.
 */

// ── Navigation data ───────────────────────────────────────────────────────────
const NAV = [
  {
    section: 'Overview',
    items: [
      { label: 'Dashboard',        to: '/admin',              icon: LayoutDashboard, end: true },
      { label: 'Posture',          to: '/admin/posture',      icon: Shield },
      { label: 'Alerts',           to: '/admin/alerts',       icon: TriangleAlert },
    ],
  },
  {
    section: 'Discover',
    items: [
      { label: 'Inventory',        to: '/admin/inventory',    icon: Boxes },
      { label: 'Data & Knowledge', to: '/admin/data',         icon: Database },
      { label: 'Identity & Trust', to: '/admin/identity',     icon: Fingerprint },
    ],
  },
  {
    section: 'Protect',
    items: [
      { label: 'Runtime',          to: '/admin/runtime',      icon: Activity },
      { label: 'Policies',         to: '/admin/policies',     icon: ScrollText },
      { label: 'Lineage',          to: '/admin/lineage',      icon: GitBranch },
    ],
  },
  {
    section: 'Validate',
    items: [
      { label: 'Simulation',       to: '/admin/simulation',   icon: FlaskConical },
      { label: 'Cases',            to: '/admin/cases',        icon: ClipboardList },
      { label: 'Automation',       to: '/admin/automation',   icon: Workflow },
    ],
  },
  {
    section: 'Platform',
    items: [
      { label: 'Integrations',     to: '/admin/integrations', icon: Plug },
      { label: 'Settings',         to: '/admin/settings',     icon: Settings },
    ],
  },
]

// ── NavItem ───────────────────────────────────────────────────────────────────
function NavItem({ to, icon: Icon, label, end = false, collapsed }) {
  return (
    <div className="relative group/navitem">

      <NavLink
        to={to}
        end={end}
        className={({ isActive }) =>
          cn(
            // Base — always full width, 40px tall
            'relative flex items-center w-full h-10 text-[13px] rounded-lg',
            'transition-colors duration-150 cursor-pointer select-none',
            // Layout: centered icon-only when collapsed, padded row when expanded
            collapsed ? 'justify-center' : 'gap-3 px-3',
            // Color state
            isActive
              ? 'bg-blue-50 text-blue-600 font-semibold'
              : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700 font-medium',
          )
        }
      >
        {({ isActive }) => (
          <>
            {/* Active accent pill — expanded mode only */}
            {isActive && !collapsed && (
              <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-blue-600 rounded-full" />
            )}

            <Icon
              size={16}
              strokeWidth={1.75}
              className={cn(
                'block shrink-0 transition-opacity duration-150',
                isActive ? 'opacity-100' : 'opacity-50 group-hover/navitem:opacity-90',
              )}
            />

            {/* Label — conditionally rendered. NOT a CSS display hack.
                When collapsed is true, label is completely absent from DOM. */}
            {!collapsed && (
              <span className="truncate leading-none">{label}</span>
            )}
          </>
        )}
      </NavLink>

      {/* Tooltip — collapsed mode only.
          Positioned relative to group/navitem (position:relative parent).
          left:100% fires at the right edge of the full-width nav item.
          ml-2 clears the 1px sidebar border with 8px gap. */}
      {collapsed && (
        <div
          className={cn(
            'pointer-events-none',
            'absolute left-full top-1/2 -translate-y-1/2 ml-2',
            'px-2.5 py-1.5 bg-gray-900 text-white text-xs font-medium',
            'rounded-md whitespace-nowrap shadow-md',
            'opacity-0 group-hover/navitem:opacity-100',
            'transition-opacity duration-150',
            'z-50',
          )}
        >
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
      <div
        className={cn(
          'h-16 shrink-0 flex items-center border-b border-gray-200',
          collapsed ? 'justify-center' : 'px-4 gap-3',
        )}
      >
        {/* Logo mark */}
        <img
          src="/logo.png"
          alt="Orbyx"
          className="w-12 h-12 object-contain shrink-0"
        />

        {/* Brand text — conditionally rendered, gone when collapsed */}
        {!collapsed && (
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900 leading-none">Orbyx</p>
            <p className="text-xs text-gray-400 mt-[3px] leading-none">AI-SPM</p>
          </div>
        )}
      </div>

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      {/*
        IMPORTANT: px-2 and overflow-y-auto only in EXPANDED mode.

        In collapsed mode:
          - No px: items are full-width (w-full) for edge-to-edge hover bg
          - No overflow-y: preserves overflow-x:visible so tooltips render
            outside the sidebar without being clipped
      */}
      <nav
        className={cn(
          'flex-1 py-3',
          !collapsed && 'px-2 overflow-y-auto',
        )}
      >
        {NAV.map(({ section, items }, i) => (
          <div key={section} className={i > 0 ? 'mt-1' : ''}>

            {/* Section header — fully absent when collapsed */}
            {!collapsed ? (
              <p className="px-3 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-gray-400 leading-none">
                {section}
              </p>
            ) : (
              i > 0 && (
                <div className="border-t border-gray-100 my-2 mx-3" />
              )
            )}

            {/* Items */}
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
        <div
          className={cn(
            'flex items-center cursor-pointer rounded-lg',
            'hover:bg-gray-50 transition-colors duration-150 group/footer',
            collapsed ? 'justify-center h-10 mx-0' : 'gap-3 px-4 py-2.5 mx-2',
          )}
        >
          {/* Avatar */}
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-[11px] font-bold text-white shrink-0">
            A
          </div>

          {/* User info + chevron — absent when collapsed */}
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
