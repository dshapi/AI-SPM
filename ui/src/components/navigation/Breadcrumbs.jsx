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
      // Show the ID shortened to 14 chars max
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
