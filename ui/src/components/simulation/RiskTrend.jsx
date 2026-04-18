/**
 * RiskTrend.jsx
 * ─────────────
 * SVG polyline chart showing risk score over simulation event sequence.
 *
 * Props
 * ─────
 *   events  SimulationEvent[]  — ordered simulation events
 *   live    boolean            — true while simulation is running (shows pulse)
 *
 * Risk scoring:
 *   Uses event.details.risk_score if present (0–100).
 *   Falls back to STAGE_RISK by event stage.
 */

/** Fallback risk score per stage when backend doesn't send risk_score */
const STAGE_RISK = {
  started:   10,
  progress:  50,
  blocked:   90,
  allowed:   30,
  error:     70,
  completed: 10,
}

function deriveRiskScore(event) {
  const explicit = event.details?.risk_score
  if (typeof explicit === 'number') return Math.min(100, Math.max(0, explicit))
  return STAGE_RISK[event.stage] ?? 50
}

const CHART_H    = 72
const CHART_W    = 400   // viewBox width; scales to container via width="100%"
const PAD_X      = 20
const PAD_Y      = 8
const INNER_H    = CHART_H - PAD_Y * 2
const INNER_W    = CHART_W - PAD_X * 2

function scoreToY(score) {
  // score 100 → top (PAD_Y), score 0 → bottom (CHART_H - PAD_Y)
  return PAD_Y + INNER_H * (1 - score / 100)
}

function indexToX(i, total) {
  if (total <= 1) return PAD_X + INNER_W / 2
  return PAD_X + (i / (total - 1)) * INNER_W
}

function riskColor(score) {
  if (score >= 80) return '#ef4444'   // red-500
  if (score >= 50) return '#f97316'   // orange-500
  return '#22c55e'                    // green-500
}

export function RiskTrend({ events = [], live = false }) {
  const scored = events.map(e => deriveRiskScore(e))

  if (scored.length === 0) {
    return (
      <div style={{
        height: CHART_H,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#9ca3af',
        fontSize: 12,
      }}>
        No data yet
      </div>
    )
  }

  const points = scored.map((s, i) =>
    `${indexToX(i, scored.length)},${scoreToY(s)}`
  ).join(' ')

  const lastScore = scored[scored.length - 1]
  const lastX = indexToX(scored.length - 1, scored.length)
  const lastY = scoreToY(lastScore)
  const lineColor = riskColor(lastScore)

  return (
    <div style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        width="100%"
        height={CHART_H}
        style={{ display: 'block', overflow: 'visible' }}
      >
        {/* Threshold lines */}
        <line
          x1={PAD_X} y1={scoreToY(80)} x2={CHART_W - PAD_X} y2={scoreToY(80)}
          stroke="#fca5a5" strokeWidth={0.8} strokeDasharray="3 3"
        />
        <line
          x1={PAD_X} y1={scoreToY(50)} x2={CHART_W - PAD_X} y2={scoreToY(50)}
          stroke="#fcd34d" strokeWidth={0.8} strokeDasharray="3 3"
        />

        {/* Threshold labels */}
        <text x={PAD_X - 2} y={scoreToY(80) + 3} fontSize={7} fill="#ef4444" textAnchor="end">80</text>
        <text x={PAD_X - 2} y={scoreToY(50) + 3} fontSize={7} fill="#f59e0b" textAnchor="end">50</text>

        {/* Area fill under the line */}
        {scored.length > 1 && (
          <polygon
            points={`${points} ${indexToX(scored.length - 1, scored.length)},${CHART_H - PAD_Y} ${PAD_X},${CHART_H - PAD_Y}`}
            fill={lineColor}
            fillOpacity={0.08}
          />
        )}

        {/* Main polyline */}
        <polyline
          points={points}
          fill="none"
          stroke={lineColor}
          strokeWidth={1.75}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Data point dots */}
        {scored.map((s, i) => (
          <circle
            key={i}
            cx={indexToX(i, scored.length)}
            cy={scoreToY(s)}
            r={2.5}
            fill={riskColor(s)}
            stroke="white"
            strokeWidth={1}
          />
        ))}

        {/* Live pulse on last point */}
        {live && (
          <circle
            cx={lastX}
            cy={lastY}
            r={5}
            fill="none"
            stroke={lineColor}
            strokeWidth={1}
            opacity={0.5}
          >
            <animate attributeName="r" from="4" to="10" dur="1.2s" repeatCount="indefinite" />
            <animate attributeName="opacity" from="0.6" to="0" dur="1.2s" repeatCount="indefinite" />
          </circle>
        )}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, fontSize: 10, color: '#9ca3af', marginTop: 4 }}>
        <span style={{ color: '#ef4444' }}>── High (≥80)</span>
        <span style={{ color: '#f97316' }}>── Med (≥50)</span>
        <span style={{ color: '#22c55e' }}>── Low</span>
        {live && <span style={{ color: '#6366f1', marginLeft: 'auto' }}>● Live</span>}
      </div>
    </div>
  )
}
