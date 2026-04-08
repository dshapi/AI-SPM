import { useState } from 'react'
import { Outlet }   from 'react-router-dom'
import { AccentPillar } from './AccentPillar.jsx'
import { AppSidebar }   from './AppSidebar.jsx'
import { Topbar }       from './Topbar.jsx'

/**
 * AppShell — root layout for the /admin section.
 *
 * Owns the `collapsed` boolean (single source of truth).
 * Passes it down to AppSidebar (controls width + content)
 * and Topbar (toggle button icon state).
 *
 * Shell structure:
 *
 *  ┌─────┬──────────────────────────────────────────────────────┐
 *  │     │  Topbar (h-16)                                       │
 *  │  A  ├──────────────────────────────────────────────────────┤
 *  │  c  │                                                      │
 *  │  c  │  AppSidebar       │  <Outlet />                      │
 *  │  e  │  w-64 / w-20      │  (page content, overflow-y-auto) │
 *  │  n  │                   │                                  │
 *  │  t  │                   │                                  │
 *  └─────┴──────────────────────────────────────────────────────┘
 *  ↑
 *  AccentPillar (w-1.5, bg-blue-600)
 *
 * Key layout rules:
 *   - `min-w-0` on content column: prevents flex blowout on narrow screens
 *   - `overflow-hidden` on content column: clips scrollbar to correct region
 *   - `overflow-y-auto` on main: allows page content to scroll independently
 */
export function AppShell() {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden bg-[#f6f7fb]">

      {/* Far-left brand accent strip */}
      <AccentPillar />

      {/* Collapsible sidebar */}
      <AppSidebar collapsed={collapsed} />

      {/* Main column — topbar + scrollable page content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

        <Topbar
          collapsed={collapsed}
          onToggle={() => setCollapsed(v => !v)}
        />

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>

      </div>

    </div>
  )
}
