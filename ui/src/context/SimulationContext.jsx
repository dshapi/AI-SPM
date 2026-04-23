/**
 * context/SimulationContext.jsx
 * ──────────────────────────────
 * Shared React context for simulation state across routes.
 *
 * IMPORTANT: useSimulationState() must be invoked in EXACTLY ONE PLACE
 * (AppShell) so that all routes see the same state. Pages should consume
 * via useSimulationContext() — they MUST NOT call useSimulationState()
 * locally, because hooks don't share state across call sites and any local
 * instance will be invisible to the rest of the app.
 *
 * Provider value shape:
 *   {
 *     simEvents:       SimulationEvent[]   // convenience pass-through
 *     simState:        SimulationState     // full lifecycle state
 *     startSimulation: (config) => Promise // kicks off a run + opens WS
 *     resetSimulation: () => void          // clears events back to idle
 *   }
 */
import { createContext, useContext } from 'react'

const _noop = () => {}

/**
 * @type {React.Context<{
 *   simEvents:       import('../lib/eventSchema.js').SimulationEvent[],
 *   simState:        object,
 *   startSimulation: Function,
 *   resetSimulation: Function,
 * }>}
 */
export const SimulationContext = createContext({
  simEvents:           [],
  simState:            { simEvents: [], status: 'idle', steps: [], partialResults: [], finalResults: null, sessionId: null, connectionStatus: 'idle' },
  startSimulation:     _noop,
  resetSimulation:     _noop,
  subscribeToSession:  _noop,
  unsubscribeFromSession: _noop,
  loadSessionEvents:   _noop,
})

/** Convenience hook — use inside any admin route component */
export function useSimulationContext() {
  return useContext(SimulationContext)
}
