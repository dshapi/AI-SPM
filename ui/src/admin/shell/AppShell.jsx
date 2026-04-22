import { useState, useEffect, useRef } from 'react'
import { Outlet, useLocation }         from 'react-router-dom'
import { AccentPillar } from './AccentPillar.jsx'
import { AppSidebar }   from './AppSidebar.jsx'
import { Topbar }       from './Topbar.jsx'
import { SimulationContext } from '../../context/SimulationContext.jsx'
import { useSimulationState } from '../../hooks/useSimulationState.js'

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
  const [collapsed, setCollapsed]   = useState(false)
  const mainRef                     = useRef(null)
  const { pathname }                = useLocation()

  // ── Hoist simulation state to layout level ──
  // This ensures simEvents persist across route changes.
  // Lineage, Alerts, Simulation and any other routes consume via
  // useSimulationContext() — they MUST NOT call useSimulationState()
  // locally, or they'll get an independent state instance and the events
  // they generate will never reach other routes (broke Lineage previously).
  const { simState, startSimulation, resetSimulation } = useSimulationState()

  // Scroll the main content area back to the top on every route change.
  // Without this, navigating from a scrolled page (e.g. Overview scrolled
  // to the Launch tiles) retains the old scrollTop, showing blank space
  // at the bottom of shorter destination pages.
  useEffect(() => {
    if (mainRef.current) mainRef.current.scrollTop = 0
  }, [pathname])

  return (
    <SimulationContext.Provider
      value={{
        simEvents: simState.simEvents,
        simState,
        startSimulation,
        resetSimulation,
      }}
    >
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

          <main ref={mainRef} className="flex-1 overflow-y-auto">
            <Outlet />
          </main>

        </div>

      </div>
    </SimulationContext.Provider>
  )
}
