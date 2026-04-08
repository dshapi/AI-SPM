import { useState } from 'react'
import { Outlet }   from 'react-router-dom'
import AccentPillar from './AccentPillar.jsx'
import Sidebar      from './Sidebar.jsx'
import Topbar       from './Topbar.jsx'

/**
 * DashboardLayout — root shell for the /admin section.
 *
 * Owns the `collapsed` boolean that controls the sidebar width.
 * Both Sidebar and Topbar receive it as a prop; Topbar also gets
 * the toggle callback.
 *
 * Visual structure (left → right, top → bottom):
 *
 *  ┌───┬─────────────────────────────────────────────────────┐
 *  │   │  Topbar (h-16, sticky)                              │
 *  │   ├─────────────────────────────────────────────────────┤
 *  │ ↑ │                                                     │
 *  │ A │  Sidebar (w-64 / w-[72px])  │  Page content        │
 *  │ c │                             │  (overflow-y-auto)   │
 *  │ c │                             │                      │
 *  │ e │                             │                      │
 *  │ n │                             │                      │
 *  │ t │                             │                      │
 *  │ ↓ │                             │                      │
 *  └───┴─────────────────────────────────────────────────────┘
 *  ↑
 *  AccentPillar (w-1.5, bg-blue-600) — far-left brand strip
 *
 * min-w-0 on the content column prevents flex children from pushing
 * the column wider than available space (important on narrow viewports).
 */
export default function DashboardLayout() {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden bg-[#f6f7fb]">

      {/* ── Far-left brand accent ──────────────────────────────────────── */}
      <AccentPillar />

      {/* ── Sidebar ───────────────────────────────────────────────────── */}
      <Sidebar collapsed={collapsed} />

      {/* ── Main column ───────────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

        {/* Topbar — pinned, never scrolls with content */}
        <Topbar
          collapsed={collapsed}
          onToggle={() => setCollapsed(v => !v)}
        />

        {/* Page content — scrollable */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>

      </div>

    </div>
  )
}
