/**
 * context/SimulationContext.jsx
 * ──────────────────────────────
 * Shared React context for simulation state across routes.
 * Provides simEvents to Lineage, Alerts, and any other consumer
 * without prop drilling through the router.
 */
import { createContext, useContext } from 'react'

/**
 * @type {React.Context<{ simEvents: import('../lib/eventSchema.js').SimulationEvent[] }>}
 */
export const SimulationContext = createContext({ simEvents: [] })

/** Convenience hook — use inside any admin route component */
export function useSimulationContext() {
  return useContext(SimulationContext)
}
