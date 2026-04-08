/**
 * AccentPillar — 6px vertical brand strip on the far left of the viewport.
 *
 * Positioned as a flex child (not fixed) so it participates in the layout
 * naturally without z-index management. The parent <DashboardLayout> is
 * h-screen overflow-hidden, so this div always fills the full viewport height.
 *
 * Color: blue-600 — same accent used throughout the design system
 * (active nav items, KPI trend arrows, bar fills).
 */
export default function AccentPillar() {
  return (
    <div className="w-1.5 shrink-0 bg-blue-600 h-full" aria-hidden="true" />
  )
}
