# Navigation Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Orbyx AI-SPM into a production-grade SaaS navigation system with breadcrumbs, URL-driven filter state, multi-tenant context, and deep linking across all pages.

**Architecture:** Config-driven nav extracted to `config/navigation.js`; filter state migrated from `useState` to `useSearchParams` via a `useFilterParams` hook; `TenantContext` provides tenant identity app-wide with localStorage + URL persistence; a `Breadcrumbs` component reads the route hierarchy for dynamic labels including `:param` segments; detail routes added for Alerts and Inventory.

**Tech Stack:** React 18, React Router v6 (`useSearchParams`, `useNavigate`, `useParams`, `useLocation`), Tailwind CSS v3, plain JSX (no TypeScript)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/config/navigation.js` | **Create** | Single source of truth for nav items, route metadata, breadcrumb labels |
| `src/context/TenantContext.jsx` | **Create** | Tenant state, localStorage persistence, URL param sync |
| `src/hooks/useFilterParams.js` | **Create** | Typed `useSearchParams` wrapper for filter state |
| `src/components/navigation/Breadcrumbs.jsx` | **Create** | Dynamic breadcrumb component for Topbar |
| `src/index.jsx` | **Modify** | Add detail routes; wrap entire Routes tree in `TenantProvider` (inside `BrowserRouter` — required for `useSearchParams`) |
| `src/admin/shell/Topbar.jsx` | **Modify** | Swap static `Breadcrumb` → `Breadcrumbs`; add `TenantSelector` |
| `src/admin/shell/AppSidebar.jsx` | **Modify** | Import `NAV` from `config/navigation.js` instead of inlining |
| `src/admin/pages/Alerts.jsx` | **Modify** | Migrate 7 `useState` filters → `useFilterParams`; row click → detail route |
| `src/admin/pages/Inventory.jsx` | **Modify** | Migrate 7 `useState` filters → `useFilterParams`; row click → detail route |

---

## Task 1: Create `src/config/navigation.js`

**Files:**
- Create: `src/config/navigation.js`

Extract the navigation config currently inlined in `AppSidebar.jsx` into a shared module. Add a `ROUTE_META` map used by `Breadcrumbs` for human-readable labels.

- [ ] **Step 1: Create the file**

```js
// src/config/navigation.js
import {
  Home, LayoutDashboard, Shield, TriangleAlert,
  Boxes, Database, Fingerprint,
  Activity, ScrollText, GitBranch,
  FlaskConical, ClipboardList, Workflow,
  Plug, Settings,
} from 'lucide-react'

/** Overview is pinned above all sections. */
export const PINNED = { label: 'Overview', to: '/admin/overview', icon: Home, end: true }

/** Sectioned navigation in mandatory spec order. */
export const NAV = [
  {
    section: 'Monitor',
    items: [
      { label: 'Dashboard',        to: '/admin/dashboard',    icon: LayoutDashboard },
      { label: 'Posture',          to: '/admin/posture',      icon: Shield          },
      { label: 'Alerts',           to: '/admin/alerts',       icon: TriangleAlert   },
    ],
  },
  {
    section: 'Discover',
    items: [
      { label: 'Inventory',        to: '/admin/inventory',    icon: Boxes      },
      { label: 'Identity & Trust', to: '/admin/identity',     icon: Fingerprint },
      { label: 'Data & Knowledge', to: '/admin/data',         icon: Database   },
    ],
  },
  {
    section: 'Protect',
    items: [
      { label: 'Runtime',          to: '/admin/runtime',      icon: Activity   },
      { label: 'Policies',         to: '/admin/policies',     icon: ScrollText },
      { label: 'Lineage',          to: '/admin/lineage',      icon: GitBranch  },
    ],
  },
  {
    section: 'Validate',
    items: [
      { label: 'Simulation',       to: '/admin/simulation',   icon: FlaskConical },
      { label: 'Cases',            to: '/admin/cases',        icon: ClipboardList },
      { label: 'Automation',       to: '/admin/automation',   icon: Workflow     },
    ],
  },
  {
    section: 'Platform',
    items: [
      { label: 'Integrations',     to: '/admin/integrations', icon: Plug     },
      { label: 'Settings',         to: '/admin/settings',     icon: Settings },
    ],
  },
]

/**
 * ROUTE_META — maps route segment → display label.
 * Used by Breadcrumbs to resolve human-readable names.
 * Param segments (e.g. `:alertId`) are resolved dynamically.
 */
export const ROUTE_META = {
  admin:        'Orbyx',
  overview:     'Overview',
  dashboard:    'Dashboard',
  posture:      'Posture',
  alerts:       'Alerts',
  inventory:    'Inventory',
  identity:     'Identity & Trust',
  data:         'Data & Knowledge',
  runtime:      'Runtime',
  policies:     'Policies',
  lineage:      'Lineage',
  simulation:   'Simulation Lab',
  cases:        'Cases',
  automation:   'Automation',
  integrations: 'Integrations',
  settings:     'Settings',
}
```

- [ ] **Step 2: Commit**
```bash
git add src/config/navigation.js
git commit -m "feat: extract nav config to src/config/navigation.js"
```

---

## Task 2: Create `src/context/TenantContext.jsx`

**Files:**
- Create: `src/context/TenantContext.jsx`

Provides `{ tenant, setTenant }` app-wide. Persists to `localStorage`. Reads initial value from `?tenant=` URL param so links can encode tenant context.

- [ ] **Step 1: Create the file**

```jsx
// src/context/TenantContext.jsx
import { createContext, useContext, useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

const TENANTS = [
  { id: 'prod',       label: 'Production'  },
  { id: 'staging',    label: 'Staging'     },
  { id: 'dev',        label: 'Development' },
  { id: 'customer-a', label: 'Customer A'  },
]

const TenantContext = createContext(null)

export function TenantProvider({ children }) {
  const [searchParams, setSearchParams] = useSearchParams()

  // Priority: URL param → localStorage → default 'prod'
  const [tenant, setTenantState] = useState(() => {
    const fromUrl = searchParams.get('tenant')
    if (fromUrl && TENANTS.some(t => t.id === fromUrl)) return fromUrl
    return localStorage.getItem('orbyx_tenant') ?? 'prod'
  })

  const setTenant = (id) => {
    setTenantState(id)
    localStorage.setItem('orbyx_tenant', id)
    setSearchParams(prev => {
      prev.set('tenant', id)
      return prev
    }, { replace: true })
  }

  // Sync URL on mount if not already present
  useEffect(() => {
    if (!searchParams.get('tenant')) {
      setSearchParams(prev => {
        prev.set('tenant', tenant)
        return prev
      }, { replace: true })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <TenantContext.Provider value={{ tenant, setTenant, tenants: TENANTS }}>
      {children}
    </TenantContext.Provider>
  )
}

export function useTenant() {
  const ctx = useContext(TenantContext)
  if (!ctx) throw new Error('useTenant must be used within TenantProvider')
  return ctx
}
```

- [ ] **Step 2: Commit**
```bash
git add src/context/TenantContext.jsx
git commit -m "feat: add TenantContext with localStorage + URL persistence"
```

---

## Task 3: Create `src/hooks/useFilterParams.js`

**Files:**
- Create: `src/hooks/useFilterParams.js`

Thin wrapper around `useSearchParams` for typed filter state. Returns `[value, setter]` pairs that read/write URL search params. Supports string and boolean values.

- [ ] **Step 1: Create the file**

```js
// src/hooks/useFilterParams.js
import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * useFilterParams — manage page filter state in the URL.
 *
 * @param {Object} defaults — { key: defaultValue } pairs.
 *   - String default: param is omitted from URL when value === default.
 *   - Boolean default (false): param is omitted when false, set to '1' when true.
 *
 * Returns an object with:
 *   - values: { key: currentValue }
 *   - setters: { setKey: fn }
 *   - reset: () => void — restore all params to defaults
 *
 * Usage:
 *   const { values, setters } = useFilterParams({
 *     severity: 'All Severity',
 *     highRiskOnly: false,
 *   })
 *   const { severity, highRiskOnly } = values
 *   const { setSeverity, setHighRiskOnly } = setters
 */
export function useFilterParams(defaults) {
  const [searchParams, setSearchParams] = useSearchParams()

  // Read current values from URL (or fall back to defaults)
  const values = {}
  for (const [key, def] of Object.entries(defaults)) {
    if (typeof def === 'boolean') {
      values[key] = searchParams.get(key) === '1'
    } else {
      values[key] = searchParams.get(key) ?? def
    }
  }

  // Each setter is a stable function: `setSearchParams` is stable from React Router,
  // and we capture `key`/`def` from the outer for-loop via closure at definition time.
  // No useCallback needed — the function identity is recreated each render, which is
  // fine because setSearchParams is already stable and these are not passed to memo'd children.
  const setters = {}
  for (const [key, def] of Object.entries(defaults)) {
    const Name = key.charAt(0).toUpperCase() + key.slice(1)
    setters[`set${Name}`] = (value) => {
      setSearchParams(prev => {
        const isDefault = typeof def === 'boolean' ? !value : value === def
        if (isDefault) {
          prev.delete(key)
        } else {
          prev.set(key, typeof def === 'boolean' ? '1' : value)
        }
        return prev
      }, { replace: true })
    }
  }

  // `keysRef` captures the key names once on mount — they never change at runtime.
  // Using a ref avoids including `defaults` (new object each render) in a useCallback dep.
  const keysRef = useRef(Object.keys(defaults))

  const reset = useCallback(() => {
    setSearchParams(prev => {
      for (const key of keysRef.current) {
        prev.delete(key)
      }
      return prev
    }, { replace: true })
  }, [setSearchParams])  // setSearchParams is stable; keysRef never changes

  return { values, setters, reset }
}
```

- [ ] **Step 2: Commit**
```bash
git add src/hooks/useFilterParams.js
git commit -m "feat: add useFilterParams hook for URL-driven filter state"
```

---

## Task 4: Create `src/components/navigation/Breadcrumbs.jsx`

**Files:**
- Create: `src/components/navigation/Breadcrumbs.jsx`

Full breadcrumb component. Reads `useLocation` + `useParams`. Resolves segment labels from `ROUTE_META`. Renders clickable parents, non-clickable current. Handles `:alertId` / `:assetId` detail segments by showing a shortened ID.

- [ ] **Step 1: Create the file**

```jsx
// src/components/navigation/Breadcrumbs.jsx
import { Link, useLocation, useParams } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { ROUTE_META } from '../../config/navigation.js'
import { cn } from '../../lib/utils.js'

/**
 * Breadcrumbs — renders the full path hierarchy as a breadcrumb trail.
 *
 * /admin/alerts              →  Orbyx  /  Alerts
 * /admin/alerts/ALT-001      →  Orbyx  /  Alerts  /  ALT-001
 * /admin/inventory/ast-xyz   →  Orbyx  /  Inventory  /  ast-xyz
 *
 * The "Orbyx" root crumb is never a link (it IS the app).
 * Parent crumbs are Links. Current crumb is plain text.
 */
export function Breadcrumbs() {
  const { pathname } = useLocation()
  const params       = useParams()

  // Build segments: ['admin', 'alerts', 'ALT-001']
  const segments = pathname.replace(/\/$/, '').split('/').filter(Boolean)

  // Build crumb list: { label, to? }
  const crumbs = []
  let pathSoFar = ''

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    pathSoFar += `/${seg}`

    // Is this segment a dynamic param value? (appears in useParams values)
    const isParam = Object.values(params).includes(seg)

    let label
    if (isParam) {
      // Show the ID shortened to 12 chars max
      label = seg.length > 14 ? `${seg.slice(0, 12)}…` : seg
    } else {
      label = ROUTE_META[seg] ?? seg
    }

    // Skip "admin" as a labeled crumb — we use "Orbyx" as the root label instead
    if (seg === 'admin') {
      crumbs.push({ label: 'Orbyx', to: null })
      continue
    }

    const isLast = i === segments.length - 1
    crumbs.push({ label, to: isLast ? null : pathSoFar })
  }

  if (crumbs.length === 0) return null

  return (
    <nav aria-label="breadcrumb" className="flex items-center gap-1 min-w-0">
      {crumbs.map((crumb, i) => (
        <span key={i} className="flex items-center gap-1 min-w-0">
          {i > 0 && (
            <ChevronRight size={12} strokeWidth={2} className="text-gray-300 shrink-0" />
          )}
          {crumb.to ? (
            <Link
              to={crumb.to}
              className={cn(
                'text-sm text-gray-400 hover:text-gray-600 transition-colors duration-100',
                'leading-none whitespace-nowrap shrink-0',
              )}
            >
              {crumb.label}
            </Link>
          ) : (
            <span className={cn(
              'text-sm leading-none truncate',
              i === crumbs.length - 1
                ? 'font-semibold text-gray-700'
                : 'text-gray-400',
            )}>
              {crumb.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  )
}
```

- [ ] **Step 2: Commit**
```bash
git add src/components/navigation/Breadcrumbs.jsx
git commit -m "feat: add Breadcrumbs component with dynamic route resolution"
```

---

## Task 5: Update `src/admin/shell/Topbar.jsx`

**Files:**
- Modify: `src/admin/shell/Topbar.jsx`

Replace the static `Breadcrumb` function with the new `Breadcrumbs` component. Add a `TenantSelector` dropdown using `useTenant`.

- [ ] **Step 1: Read current file** (already done — see summary)

- [ ] **Step 2: Replace imports + Breadcrumb + add TenantSelector**

Replace the entire file content with:

```jsx
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
```

- [ ] **Step 3: Commit**
```bash
git add src/admin/shell/Topbar.jsx
git commit -m "feat: add TenantSelector + Breadcrumbs to Topbar"
```

---

## Task 6: Update `src/admin/shell/AppSidebar.jsx`

**Files:**
- Modify: `src/admin/shell/AppSidebar.jsx:1-93`

Remove the inlined icon imports + `PINNED` + `NAV` constants. Import them from `config/navigation.js` instead.

- [ ] **Step 1: Replace imports + constants section**

Replace lines 1–93 (the imports and the NAV/PINNED declarations) with:

```jsx
import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/utils.js'
import { ChevronRight } from 'lucide-react'
import { NAV, PINNED } from '../../config/navigation.js'
```

All other code in the file (NavItem component, AppSidebar component) stays unchanged.

- [ ] **Step 2: Verify no lingering icon imports** — all icons are now sourced from `config/navigation.js`

- [ ] **Step 3: Commit**
```bash
git add src/admin/shell/AppSidebar.jsx
git commit -m "refactor: import NAV/PINNED from config/navigation.js"
```

---

## Task 7: Update `src/index.jsx` — add detail routes + TenantProvider

**Files:**
- Modify: `src/index.jsx`

Add `TenantProvider` wrapper. Add detail routes for Alerts and Inventory (and stub routes for Runtime, Lineage, Policies, Cases — rendered by existing pages until detail views are built).

- [ ] **Step 1: Update the file**

```jsx
// src/index.jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { TenantProvider }  from './context/TenantContext.jsx'
import App                 from './App.jsx'
import { AppShell as DashboardLayout } from './admin/shell/AppShell.jsx'
import Overview      from './admin/pages/Overview.jsx'
import Dashboard     from './admin/pages/Dashboard.jsx'
import Posture       from './admin/pages/Posture.jsx'
import Alerts        from './admin/pages/Alerts.jsx'
import Inventory     from './admin/pages/Inventory.jsx'
import Runtime       from './admin/pages/Runtime.jsx'
import Policies      from './admin/pages/Policies.jsx'
import Lineage       from './admin/pages/Lineage.jsx'
import Simulation    from './admin/pages/Simulation.jsx'
import Cases         from './admin/pages/Cases.jsx'
import Automation    from './admin/pages/Automation.jsx'
import Integrations  from './admin/pages/Integrations.jsx'
import Identity      from './admin/pages/Identity.jsx'
import Data          from './admin/pages/Data.jsx'
import Placeholder   from './admin/pages/Placeholder.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <TenantProvider>
        <Routes>
          {/* Chat UI */}
          <Route path="/" element={<App />} />

          {/* Admin UI */}
          <Route path="/admin" element={<DashboardLayout />}>

            <Route index element={<Navigate to="overview" replace />} />

            {/* ── Command center ── */}
            <Route path="overview"     element={<Overview />} />

            {/* ── Monitor ── */}
            <Route path="dashboard"    element={<Dashboard />} />
            <Route path="posture"      element={<Posture />} />
            <Route path="alerts"       element={<Alerts />} />
            <Route path="alerts/:alertId" element={<Alerts />} />

            {/* ── Discover ── */}
            <Route path="inventory"    element={<Inventory />} />
            <Route path="inventory/:assetId" element={<Inventory />} />
            <Route path="identity"     element={<Identity />} />
            <Route path="data"         element={<Data />} />

            {/* ── Protect ── */}
            <Route path="runtime"      element={<Runtime />} />
            <Route path="runtime/:sessionId" element={<Runtime />} />
            <Route path="policies"     element={<Policies />} />
            <Route path="policies/:policyId" element={<Policies />} />
            <Route path="lineage"      element={<Lineage />} />
            <Route path="lineage/:sessionId" element={<Lineage />} />

            {/* ── Validate ── */}
            <Route path="simulation"   element={<Simulation />} />
            <Route path="cases"        element={<Cases />} />
            <Route path="cases/:caseId" element={<Cases />} />
            <Route path="automation"   element={<Automation />} />

            {/* ── Platform ── */}
            <Route path="integrations" element={<Integrations />} />
            <Route path="settings"     element={<Placeholder title="Settings" description="Tenant configuration, thresholds, and notifications." />} />
          </Route>

          {/* Any unknown path → Overview */}
          <Route path="*" element={<Navigate to="/admin/overview" replace />} />
        </Routes>
      </TenantProvider>
    </BrowserRouter>
  </React.StrictMode>
)
```

> **Note:** Detail routes reuse the same page component. Each page reads `useParams()` to detect if a detail ID is present and renders either the list or the detail panel. This is the cheapest implementation — no new files, just param-awareness in the existing page.

- [ ] **Step 2: Commit**
```bash
git add src/index.jsx
git commit -m "feat: add TenantProvider + detail routes for alerts, inventory, runtime, lineage, policies, cases"
```

---

## Task 8: Refactor `src/admin/pages/Alerts.jsx`

**Files:**
- Modify: `src/admin/pages/Alerts.jsx:848-855` (useState filter declarations)
- Modify: `src/admin/pages/Alerts.jsx` (handleSelectAlert, filtered, AlertsFilterBar props)

Migrate all 7 filter `useState` calls to `useFilterParams`. Row selection uses `useParams` to read `:alertId` and `useNavigate` to write it.

- [ ] **Step 1: Add imports at the top of the file**

Locate the existing imports block. Add:
```jsx
import { useNavigate, useParams } from 'react-router-dom'
import { useFilterParams } from '../../hooks/useFilterParams.js'
```

- [ ] **Step 2: Replace the useState block at lines 848–855**

Remove:
```jsx
const [selected,     setSelected]     = useState(null)
const [search,       setSearch]       = useState('')
const [severity,     setSeverity]     = useState('All Severity')
const [status,       setStatus]       = useState('All Status')
const [assetType,    setAssetType]    = useState('All Types')
const [timeRange,    setTimeRange]    = useState('Last 24h')
const [highRiskOnly, setHighRiskOnly] = useState(false)
```

Replace with:
```jsx
const { alertId }  = useParams()
const navigate     = useNavigate()

const { values, setters } = useFilterParams({
  search:      '',
  severity:    'All Severity',
  status:      'All Status',
  assetType:   'All Types',
  timeRange:   'Last 24h',
  highRiskOnly: false,
})
const { search, severity, status, assetType, timeRange, highRiskOnly } = values
const { setSearch, setSeverity, setStatus, setAssetType, setTimeRange, setHighRiskOnly } = setters

// Selection is derived from URL param, not local state
const selected = MOCK_ALERTS.find(a => a.id === alertId) ?? null
```

- [ ] **Step 3: Replace handleSelectAlert**

Remove:
```jsx
const handleSelectAlert = (alert) => {
  setSelected(prev => prev?.id === alert?.id ? null : alert)
}
```

Replace with:
```jsx
const handleSelectAlert = (alert) => {
  if (alert?.id === alertId) {
    navigate('/admin/alerts', { replace: true })
  } else {
    navigate(`/admin/alerts/${alert.id}`, { replace: true })
  }
}
```

- [ ] **Step 4: Verify AlertsFilterBar props still match** — same prop names, no change needed there.

- [ ] **Step 5: Commit**
```bash
git add src/admin/pages/Alerts.jsx
git commit -m "feat: migrate Alerts filters to useFilterParams + deep link selected alert via URL"
```

---

## Task 9: Refactor `src/admin/pages/Inventory.jsx`

**Files:**
- Modify: `src/admin/pages/Inventory.jsx:608-615` (useState filter declarations)

Migrate all 7 `useState` declarations to `useFilterParams` — this includes `activeTab` (as `tab`), `view`, `search`, `provider`, `risk`, `policy`, and `selected` (replaced by URL param). Row selection uses `useParams` + `useNavigate`.

- [ ] **Step 1: Add imports at the top of the file**

```jsx
import { useNavigate, useParams } from 'react-router-dom'
import { useFilterParams } from '../../hooks/useFilterParams.js'
```

- [ ] **Step 2: Replace the useState block at lines 608–615**

Remove:
```jsx
const [activeTab, setActiveTab] = useState('agents')
const [view,      setView]      = useState('table')
const [search,    setSearch]    = useState('')
const [provider,  setProvider]  = useState('All Providers')
const [risk,      setRisk]      = useState('All Risk')
const [policy,    setPolicy]    = useState('All Coverage')
const [selected,  setSelected]  = useState(null)
```

Replace with:
```jsx
const { assetId } = useParams()
const navigate    = useNavigate()

const { values, setters } = useFilterParams({
  tab:      'agents',
  view:     'table',
  search:   '',
  provider: 'All Providers',
  risk:     'All Risk',
  policy:   'All Coverage',
})
const { tab: activeTab, view, search, provider, risk, policy } = values
const { setTab, setView, setSearch, setProvider, setRisk, setPolicy } = setters

// Selection from URL
const rawAllAssets = Object.values(ASSETS).flat()
const selected = rawAllAssets.find(a => a.id === assetId) ?? null
```

- [ ] **Step 3: Replace handleTabChange**

Remove:
```jsx
const handleTabChange = (tab) => {
  setActiveTab(tab)
  setSelected(null)
}
```

Replace with:
```jsx
const handleTabChange = (tab) => {
  setTab(tab)
  // Clear selected asset when switching tabs
  if (assetId) navigate('/admin/inventory', { replace: true })
}
```

- [ ] **Step 4: Replace row-click handler (wherever setSelected is called in table/card click handlers)**

Find any `onClick` that calls `setSelected(asset)` or similar. Replace with:
```jsx
onClick={() => {
  if (asset.id === assetId) {
    navigate('/admin/inventory', { replace: true })
  } else {
    navigate(`/admin/inventory/${asset.id}`, { replace: true })
  }
}}
```

- [ ] **Step 5: Commit**
```bash
git add src/admin/pages/Inventory.jsx
git commit -m "feat: migrate Inventory filters to useFilterParams + deep link selected asset via URL"
```

---

## Task 10: Build Verification

**Files:** none created

- [ ] **Step 1: Run the dev server and check for console errors**
```bash
cd /sessions/wizardly-happy-cori/mnt/AISPM/ui && npm run dev 2>&1 | head -40
```
Expected: `Local: http://localhost:5173/` with no build errors.

- [ ] **Step 2: Verify breadcrumbs render correctly**

Navigate to each of these URLs and confirm the breadcrumb trail is correct:
- `/admin/overview` → `Orbyx / Overview`
- `/admin/alerts` → `Orbyx / Alerts`
- `/admin/alerts/ALT-001` → `Orbyx / Alerts / ALT-001`
- `/admin/inventory` → `Orbyx / Inventory`
- `/admin/inventory/some-id` → `Orbyx / Inventory / some-id`

- [ ] **Step 3: Verify URL filter state**

On Alerts page, change severity filter to "Critical". Confirm URL becomes `?severity=Critical`. Refresh the page. Confirm filter is still "Critical".

On Inventory page, switch to "pipelines" tab. Confirm URL becomes `?tab=pipelines`. Refresh. Confirm still on pipelines tab.

- [ ] **Step 4: Verify tenant selector**

Open TenantSelector dropdown. Select "Staging". Confirm URL gains `?tenant=staging`. Refresh. Confirm "Staging" is still selected.

- [ ] **Step 5: Commit verification result**
```bash
git commit --allow-empty -m "chore: navigation architecture verified working"
```
