/**
 * TimelineNode.jsx
 * ─────────────────
 * Single clickable simulation event row in the Timeline.
 *
 * Props
 * ─────
 *   event           SimulationEvent
 *   selected        boolean — true if this event is currently selected
 *   onSelect        (event) => void — called when node is clicked
 *   riskScore       number | null — 0–100 (passed from parent, derived via STAGE_RISK)
 */

const STAGE_STYLE = {
  blocked:     { bg: '#fef2f2', border: '#ef4444', dot: '#ef4444', label: 'BLOCKED'     },
  allowed:     { bg: '#f0fdf4', border: '#22c55e', dot: '#22c55e', label: 'ALLOWED'     },
  error:       { bg: '#fff7ed', border: '#f97316', dot: '#f97316', label: 'ERROR'       },
  probe_error: { bg: '#fff7ed', border: '#f97316', dot: '#f97316', label: 'PROBE ERROR' },
  started:     { bg: '#eff6ff', border: '#3b82f6', dot: '#3b82f6', label: 'START'       },
  progress:    { bg: '#fafafa', border: '#d1d5db', dot: '#9ca3af', label: 'PROBE'       },
  completed:   { bg: '#f9fafb', border: '#d1d5db', dot: '#9ca3af', label: 'DONE'        },
}
const DEFAULT_STYLE = { bg: '#f9fafb', border: '#d1d5db', dot: '#9ca3af', label: '—' }

function riskColor(score) {
  if (score == null) return '#9ca3af'
  if (score >= 80) return '#ef4444'
  if (score >= 50) return '#f97316'
  return '#22c55e'
}

export function TimelineNode({ event, selected, onSelect, riskScore = null }) {
  const s = STAGE_STYLE[event.stage] ?? DEFAULT_STYLE
  const hasExplanation = !!event.details?.explanation

  return (
    <div
      onClick={() => onSelect(event)}
      title={hasExplanation ? (event.details.explanation.title || event.event_type) : event.event_type}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        padding: '8px 12px',
        cursor: 'pointer',
        background: s.bg,
        borderRadius: 6,
        borderLeft: `3px solid ${s.border}`,
        outline: selected ? '2px solid #6366f1' : 'none',
        outlineOffset: 1,
        transition: 'outline 0.1s, background 0.1s',
        userSelect: 'none',
      }}
    >
      {/* Stage dot */}
      <div style={{
        width: 7,
        height: 7,
        borderRadius: '50%',
        background: s.dot,
        marginTop: 4,
        flexShrink: 0,
      }} />

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: s.border, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            {s.label}
          </span>
          {hasExplanation && (
            <span style={{ fontSize: 9, color: '#6366f1', fontWeight: 600 }}>🔍</span>
          )}
        </div>

        <div style={{ fontSize: 12, color: '#374151', marginTop: 2, fontWeight: 500 }}>
          {event.event_type}
        </div>

        {event.details?.message && (
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
            {event.details.message}
          </div>
        )}

        {event.details?.categories?.length > 0 && (
          <div style={{ fontSize: 11, color: '#dc2626', marginTop: 2 }}>
            {event.details.categories.join(', ')}
          </div>
        )}

        {event.details?.probe_name && (
          <div style={{ fontSize: 10, color: '#8b5cf6', marginTop: 2 }}>
            probe: {event.details.probe_name}
          </div>
        )}
      </div>

      {/* Right side: risk score + time */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flexShrink: 0 }}>
        {riskScore != null && (
          <span style={{ fontSize: 11, fontWeight: 700, color: riskColor(riskScore) }}>
            {riskScore}
          </span>
        )}
        <span style={{ fontSize: 10, color: '#9ca3af', whiteSpace: 'nowrap' }}>
          {event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''}
        </span>
      </div>
    </div>
  )
}
