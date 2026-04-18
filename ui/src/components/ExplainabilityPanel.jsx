import { useState } from 'react'

/**
 * ExplainabilityPanel.jsx
 * ────────────────────────
 * Renders structured policy explanation with collapsible technical details.
 *
 * Props
 * ─────
 *   event       SimulationEvent | null — the selected timeline event
 *               explanation is derived from event.details.explanation
 */

const RISK_CFG = {
  critical: { bg: '#fef2f2', border: '#fecaca', badge: '#ef4444', label: 'Critical' },
  high:     { bg: '#fff7ed', border: '#fed7aa', badge: '#f97316', label: 'High'     },
  medium:   { bg: '#fefce8', border: '#fde68a', badge: '#d97706', label: 'Medium'   },
  low:      { bg: '#f0fdf4', border: '#bbf7d0', badge: '#22c55e', label: 'Low'      },
}

const DEFAULT_RISK = RISK_CFG.medium

function RiskBadge({ level }) {
  const cfg = RISK_CFG[level?.toLowerCase()] ?? DEFAULT_RISK
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: 999,
      background: cfg.badge,
      color: '#fff',
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: '0.04em',
      textTransform: 'uppercase',
    }}>
      {cfg.label}
    </span>
  )
}

function Section({ label, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        fontSize: 10,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        color: '#9ca3af',
        marginBottom: 4,
      }}>
        {label}
      </div>
      {children}
    </div>
  )
}

export function ExplainabilityPanel({ event }) {
  const explanation = event?.details?.explanation ?? null
  const [detailsOpen, setDetailsOpen] = useState(false)

  if (!event && !explanation) {
    return (
      <div style={{ padding: '24px 16px', textAlign: 'center' }}>
        <p style={{ color: '#9ca3af', fontSize: 13 }}>
          Click a Timeline event to see its explanation.
        </p>
      </div>
    )
  }

  if (!explanation) {
    return (
      <div style={{ padding: '24px 16px', textAlign: 'center' }}>
        <p style={{ color: '#9ca3af', fontSize: 13 }}>
          No explanation available for this event.
        </p>
      </div>
    )
  }

  const riskCfg = RISK_CFG[explanation.risk_level?.toLowerCase()] ?? DEFAULT_RISK

  return (
    <div style={{ padding: '16px 0' }}>

      {/* Title + risk badge */}
      <div style={{
        background: riskCfg.bg,
        border: `1px solid ${riskCfg.border}`,
        borderRadius: 8,
        padding: '12px 14px',
        marginBottom: 16,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 12,
      }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#111827', flex: 1 }}>
          {explanation.title}
        </div>
        <RiskBadge level={explanation.risk_level} />
      </div>

      {/* Reason */}
      <Section label="Why it was blocked">
        <p style={{ fontSize: 13, color: '#374151', lineHeight: 1.6, margin: 0 }}>
          {explanation.reason}
        </p>
      </Section>

      {/* Matched signal */}
      {explanation.matched_signal && (
        <Section label="Matched signal">
          <div style={{
            background: '#f9fafb',
            border: '1px solid #e5e7eb',
            borderLeft: '3px solid #ef4444',
            borderRadius: 6,
            padding: '8px 12px',
            fontFamily: 'monospace',
            fontSize: 12,
            color: '#dc2626',
            wordBreak: 'break-all',
          }}>
            {explanation.matched_signal}
          </div>
        </Section>
      )}

      {/* Impact */}
      <Section label="Risk mitigated">
        <p style={{ fontSize: 13, color: '#374151', lineHeight: 1.6, margin: 0 }}>
          {explanation.impact}
        </p>
      </Section>

      {/* Technical details (collapsible) */}
      {explanation.technical_details && (
        <Section label="">
          <button
            type="button"
            onClick={() => setDetailsOpen(o => !o)}
            style={{
              background: 'none',
              border: '1px solid #e5e7eb',
              borderRadius: 6,
              padding: '6px 12px',
              fontSize: 12,
              color: '#6b7280',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span>{detailsOpen ? '▾' : '▸'}</span>
            Technical Details
          </button>
          {detailsOpen && (
            <div style={{
              background: '#f9fafb',
              border: '1px solid #e5e7eb',
              borderRadius: 6,
              padding: '10px 12px',
              marginTop: 8,
              fontSize: 12,
              color: '#374151',
            }}>
              {Object.entries(explanation.technical_details)
                .filter(([, v]) => v !== null && v !== undefined)
                .map(([k, v]) => (
                  <div key={k} style={{ marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, color: '#6b7280', marginRight: 6 }}>
                      {k}:
                    </span>
                    <span>
                      {Array.isArray(v) ? v.join(', ') : String(v)}
                    </span>
                  </div>
                ))
              }
            </div>
          )}
        </Section>
      )}

    </div>
  )
}
