/**
 * Explainability.jsx
 * ──────────────────
 * Wrapper tab component that renders the ExplainabilityPanel for a
 * selected simulation event. Shows an empty state when no event is selected.
 *
 * Props
 * ─────
 *   selectedEvent  SimulationEvent | null — event clicked in the Timeline
 */
import { Info }                from 'lucide-react'
import { ExplainabilityPanel } from '../ExplainabilityPanel.jsx'
import { EmptyState }          from './EmptyState.jsx'

export function ExplainabilityTab({ selectedEvent }) {
  if (!selectedEvent) {
    return (
      <div className="p-4">
        <EmptyState
          icon={Info}
          title="No event selected"
          subtitle="Click a Timeline event that has an explanation to view policy reasoning and decision details."
        />
      </div>
    )
  }

  return (
    <div className="p-4">
      <ExplainabilityPanel event={selectedEvent} />
    </div>
  )
}
