import { NavLink } from 'react-router-dom'
import clsx from 'clsx'
import {
  LayoutDashboard, Shield, TriangleAlert,
  Boxes, DatabaseZap, Fingerprint,
  Activity, FileCheck2, GitBranch,
  FlaskConical, ClipboardList, Bot,
  PlugZap, Settings, ChevronRight,
} from 'lucide-react'

/**
 * Sidebar — collapsible left navigation.
 *
 * Props:
 *   collapsed  boolean  — controlled by DashboardLayout
 *
 * States:
 *   expanded   w-64  — logo + section labels + icons + text labels
 *   collapsed  w-20  — logo icon only + icons only + tooltips on hover
 *
 * ─────────────────────────────────────────────────────────────
 * KEY DESIGN DECISIONS
 * ─────────────────────────────────────────────────────────────
 *
 * 1. NAV HAS NO HORIZONTAL PADDING IN COLLAPSED MODE
 *    In expanded mode, nav has px-2 (8px gutters) so items have
 *    rounded-lg and visual breathing room from the sidebar edge.
 *    In collapsed mode, px-2 is removed so NavLinks span the FULL
 *    80px sidebar width — this gives Wiz-style edge-to-edge hover
 *    backgrounds and perfectly centered icons.
 *
 * 2. NAVLINK IS ALWAYS w-full
 *    Expanded: w-full gap-2.5 px-3 (icon + label, left-aligned)
 *    Collapsed: w-full justify-center (icon only, centered)
 *    There is no fixed-size w-10 mx-auto approach — that creates a
 *    floating 40px hover square which is visually wrong.
 *
 * 3. TOOLTIP ANCHOR IS CORRECT BECAUSE OF (1)
 *    group/navitem fills the full sidebar content width (80px - 1px
 *    border = 79px). `left: 100%` fires at that right edge, placing
 *    the tooltip just after the sidebar border. `ml-2` adds 8px gap.
 *
 * 4. OVERFLOW-Y-AUTO ONLY IN EXPANDED MODE (tooltip clip prevention)
 *    CSS spec: setting overflow-y to anything other than `visible`
 *    forces overflow-x to `auto`, which clips absolute-positioned
 *    tooltips that extend to the right. Only apply overflow-y in
 *    expanded mode where no tooltip is visible.
 *
 * 5. TRANSITION
 *    `transition-[width]` on the aside animates only the width,
 *    avoiding repaints on unrelated properties. `will-change: width`
 *    (inline style) promotes the element to its own compositor layer
 *    for GPU-accelerated width animation (prevents jank on slower
 *    machines / large nav trees).
 */

// ── Navigation data ───────────────────────────────────────────────────────
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
      { label: 'Data & Knowledge', to: '/admin/data',         icon: DatabaseZap },
      { label: 'Identity & Trust', to: '/admin/identity',     icon: Fingerprint },
    ],
  },
  {
    section: 'Protect',
    items: [
      { label: 'Runtime',          to: '/admin/runtime',      icon: Activity },
      { label: 'Policies',         to: '/admin/policies',     icon: FileCheck2 },
      { label: 'Lineage',          to: '/admin/lineage',      icon: GitBranch },
    ],
  },
  {
    section: 'Validate',
    items: [
      { label: 'Simulation',       to: '/admin/simulation',   icon: FlaskConical },
      { label: 'Cases',            to: '/admin/cases',        icon: ClipboardList },
      { label: 'Automation',       to: '/admin/automation',   icon: Bot },
    ],
  },
  {
    section: 'Platform',
    items: [
      { label: 'Integrations',     to: '/admin/integrations', icon: PlugZap },
      { label: 'Settings',         to: '/admin/settings',     icon: Settings },
    ],
  },
]

// ── NavItem ───────────────────────────────────────────────────────────────
function NavItem({ to, icon: Icon, label, end = false, collapsed }) {
  return (
    /*
     * group/navitem — scoped Tailwind group so hover on one item
     * doesn't bleed into sibling items' tooltip or icon states.
     *
     * `relative` + `position: absolute` on tooltip means: tooltip is
     * positioned relative to this div, not the sidebar or viewport.
     * With no `overflow` set on this div or its ancestors up to the
     * aside, the tooltip renders correctly outside the nav column.
     */
    <div className="relative group/navitem">

      <NavLink
        to={to}
        end={end}
        className={({ isActive }) =>
          clsx(
            // ── Base — always present ──────────────────────────────────
            'relative flex items-center w-full text-[13px]',
            'transition-colors duration-150 cursor-pointer select-none',

            // ── Layout switches on collapse ────────────────────────────
            // Collapsed: full-width 40px tall, icon centered.
            //   No px — lets hover bg extend edge-to-edge in the rail.
            //   No rounded-lg — Wiz uses full-bleed hover in collapsed.
            // Expanded:  full-width with normal padding + rounded corners.
            collapsed
              ? 'h-10 justify-center'
              : 'gap-2.5 px-3 py-[7px] rounded-lg',

            // ── Color states ───────────────────────────────────────────
            isActive
              ? 'bg-blue-50 text-blue-600 font-semibold'
              : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700 font-medium',

            // ── Collapsed active: left accent border ───────────────────
            // In expanded mode, the accent pill (::before span) handles
            // the left indicator. In collapsed mode, a left border is
            // cleaner since there's no padding to hang the pill in.
            collapsed && isActive && 'border-l-2 border-blue-500'
          )
        }
      >
        {({ isActive }) => (
          <>
            {/*
             * Active left accent pill — expanded mode only.
             * Collapsed uses border-l-2 on the NavLink instead.
             */}
            {isActive && !collapsed && (
              <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-blue-600 rounded-full" />
            )}

            <Icon
              size={16}
              strokeWidth={1.75}
              className={clsx(
                'block shrink-0 transition-opacity duration-150',
                isActive
                  ? 'opacity-100'
                  : 'opacity-50 group-hover/navitem:opacity-90'
              )}
            />

            {/*
             * Label — CSS max-width + opacity transition so text
             * collapses smoothly as the sidebar width animates.
             * `overflow-hidden` at the span level clips the text
             * without requiring overflow-hidden on any ancestor
             * (which would clip tooltips).
             */}
            <span
              className={clsx(
                'leading-none whitespace-nowrap overflow-hidden',
                'transition-[max-width,opacity] duration-200 ease-in-out',
                collapsed
                  ? 'max-w-0 opacity-0'
                  : 'max-w-[200px] opacity-100'
              )}
            >
              {label}
            </span>
          </>
        )}
      </NavLink>

      {/*
       * Tooltip — collapsed mode only.
       *
       * Positioning math (why left-full works correctly here):
       *   - In collapsed mode, nav has NO px padding (see nav below).
       *   - group/navitem fills the full sidebar content width.
       *   - `left: 100%` = right edge of group/navitem = right edge
       *     of sidebar content box (just inside the right border).
       *   - `ml-2` adds 8px gap, clearing the 1px border visually.
       *
       * This tooltip is NOT clipped by any ancestor because:
       *   - aside has no overflow set → defaults to `visible`
       *   - nav has no overflow in collapsed mode
       *   - The root wrapper's overflow-hidden only clips at viewport
       *     bounds, not at the sidebar's right edge
       */}
      {collapsed && (
        <div
          className={clsx(
            'pointer-events-none',
            'absolute left-full top-1/2 -translate-y-1/2 ml-2',
            'px-2.5 py-1.5',
            'bg-gray-900 text-white text-xs font-medium',
            'rounded-md whitespace-nowrap shadow-md',
            'opacity-0 group-hover/navitem:opacity-100',
            'transition-opacity duration-150',
            'z-50'
          )}
        >
          {label}
        </div>
      )}

    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────
export default function Sidebar({ collapsed }) {
  return (
    <aside
      className={clsx(
        'shrink-0 h-screen flex flex-col',
        'bg-white border-r border-gray-200',
        // transition-[width]: only animate width, not all properties.
        // will-change via inline style promotes to compositor layer → GPU animation.
        'transition-[width] duration-200 ease-in-out',
        collapsed ? 'w-20' : 'w-64'
      )}
      style={{ willChange: 'width' }}
    >

      {/* ── Logo zone ───────────────────────────────────────────────────── */}
      {/*
       * No px-2 in collapsed — brand icon must be centered in the full
       * 80px rail, not offset by 8px gutters.
       * `justify-center` achieves pixel-perfect centering.
       */}
      <div
        className={clsx(
          'h-16 shrink-0 flex items-center border-b border-gray-200',
          collapsed ? 'justify-center' : 'px-4 gap-3'
        )}
      >
        {/* Logo mark — logo.png is a circular blue icon, transparent bg.
          * Fixed w-8 h-8 square + object-contain centers it cleanly.
          * Visible in both expanded and collapsed states.
          */}
        <img
          src="/logo.png"
          alt="Orbyx"
          className="w-12 h-12 object-contain shrink-0"
        />

        {/* Brand name — CSS transition, same technique as nav labels */}
        <div
          className={clsx(
            'min-w-0 overflow-hidden',
            'transition-[max-width,opacity] duration-200 ease-in-out',
            collapsed ? 'max-w-0 opacity-0' : 'max-w-[160px] opacity-100'
          )}
        >
          <p className="text-sm font-bold text-gray-900 tracking-tight leading-none whitespace-nowrap">
            Orbyx
          </p>
          <p className="text-[10px] text-gray-400 leading-none mt-[3px] whitespace-nowrap">
            AI-SPM
          </p>
        </div>
      </div>

      {/* ── Navigation ──────────────────────────────────────────────────── */}
      {/*
       * CRITICAL: px-2 and overflow-y-auto are ONLY applied in expanded mode.
       *
       * Why no px in collapsed:
       *   Items are w-full, so removing horizontal padding makes hover
       *   backgrounds span the full sidebar width (Wiz-style). Keeping
       *   px-2 would create floating 64px hover states in an 80px rail.
       *
       * Why no overflow-y-auto in collapsed:
       *   overflow-y: auto → forces overflow-x: auto (CSS spec § 9.1.1)
       *   overflow-x: auto clips absolutely-positioned tooltip children.
       *   In collapsed mode icons fit without scroll, so it's safe to omit.
       */}
      <nav
        className={clsx(
          'flex-1 py-3 space-y-1',
          !collapsed && 'px-2 overflow-y-auto'
        )}
      >
        {NAV.map(({ section, items }, i) => (
          <div key={section}>

            {/* Section header */}
            {!collapsed ? (
              <p className="px-3 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-gray-400 leading-none">
                {section}
              </p>
            ) : (
              i > 0 && (
                // Full-width divider (no mx — we have no nav padding here)
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

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <div className="border-t border-gray-100 shrink-0 py-3">
        <div
          className={clsx(
            'flex items-center rounded-lg cursor-pointer',
            'hover:bg-gray-50 transition-colors duration-150 group/footer',
            // Collapsed: center avatar in full width (no px)
            // Expanded:  normal padding + gap
            collapsed
              ? 'justify-center h-10 mx-0'
              : 'gap-3 px-4 py-2.5 mx-2'
          )}
        >
          {/* Avatar */}
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-[11px] font-bold text-white shrink-0">
            A
          </div>

          {/* User info + chevron — CSS animated */}
          <div
            className={clsx(
              'flex-1 min-w-0 flex items-center gap-1 overflow-hidden',
              'transition-[max-width,opacity] duration-200 ease-in-out',
              collapsed ? 'max-w-0 opacity-0' : 'max-w-[200px] opacity-100'
            )}
          >
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-semibold text-gray-800 truncate leading-snug whitespace-nowrap">Admin</p>
              <p className="text-[11px] text-gray-400 truncate leading-snug whitespace-nowrap">admin@orbyx.ai</p>
            </div>
            <ChevronRight
              size={13}
              strokeWidth={1.75}
              className="text-gray-300 group-hover/footer:text-gray-500 transition-colors shrink-0"
            />
          </div>
        </div>
      </div>

    </aside>
  )
}
