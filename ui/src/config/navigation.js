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
 * Param segments (e.g. :alertId) are resolved dynamically.
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
