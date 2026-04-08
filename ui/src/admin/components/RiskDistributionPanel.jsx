/**
 * RiskDistributionPanel — SVG donut chart + vertical legend.
 *
 * Design tokens:
 *   card header  → border-b border-gray-100 pb-4 mb-5
 *   panel title  → text-sm font-semibold text-gray-900
 *   panel sub    → text-xs text-gray-400 mt-0.5
 *   legend dot   → w-2 h-2 rounded-full
 *   legend label → text-[13px] text-gray-600
 *   legend count → text-[13px] font-semibold tabular-nums
 */

const SEGMENTS = [
  { label: 'Critical', count: 2,  color: '#ef4444', textColor: 'text-red-500'    },
  { label: 'High',     count: 4,  color: '#f97316', textColor: 'text-orange-500' },
  { label: 'Medium',   count: 9,  color: '#eab308', textColor: 'text-yellow-500' },
  { label: 'Low',      count: 12, color: '#22c55e', textColor: 'text-green-500'  },
]

const TOTAL = SEGMENTS.reduce((s, r) => s + r.count, 0)
const R   = 52   // outer radius
const r   = 33   // inner radius (donut hole)
const CX  = 64
const CY  = 64
const GAP = 0.025

function polarToXY(cx, cy, radius, angleRad) {
  return {
    x: cx + radius * Math.cos(angleRad - Math.PI / 2),
    y: cy + radius * Math.sin(angleRad - Math.PI / 2),
  }
}

function buildArcPath(cx, cy, outerR, innerR, startAngle, endAngle) {
  const s1 = polarToXY(cx, cy, outerR, startAngle + GAP)
  const e1 = polarToXY(cx, cy, outerR, endAngle   - GAP)
  const s2 = polarToXY(cx, cy, innerR, endAngle   - GAP)
  const e2 = polarToXY(cx, cy, innerR, startAngle + GAP)
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0
  return [
    `M ${s1.x} ${s1.y}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${e1.x} ${e1.y}`,
    `L ${s2.x} ${s2.y}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${e2.x} ${e2.y}`,
    'Z',
  ].join(' ')
}

export default function RiskDistributionPanel() {
  let cursor = 0
  const arcs = SEGMENTS.map(seg => {
    const fraction = seg.count / TOTAL
    const start = cursor * 2 * Math.PI
    const end   = (cursor + fraction) * 2 * Math.PI
    cursor += fraction
    return { ...seg, path: buildArcPath(CX, CY, R, r, start, end) }
  })

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm hover:border-gray-300 transition-colors duration-150 h-full flex flex-col">

      {/* ── Panel header ─────────────────────────────────────────── */}
      <div className="border-b border-gray-100 pb-4 mb-5">
        <p className="text-sm font-semibold text-gray-900">Risk Distribution</p>
        <p className="text-xs text-gray-400 mt-0.5">{TOTAL} models by highest risk tier</p>
      </div>

      {/* ── Donut + legend ───────────────────────────────────────── */}
      <div className="flex items-center gap-8 flex-1">

        {/* SVG donut */}
        <div className="shrink-0">
          <svg width="128" height="128" viewBox="0 0 128 128">
            {arcs.map(a => (
              <path key={a.label} d={a.path} fill={a.color} />
            ))}
            {/* Centre total */}
            <text
              x={CX} y={CY - 7}
              textAnchor="middle"
              fontSize="20" fontWeight="700"
              fill="#111827"
            >
              {TOTAL}
            </text>
            <text
              x={CX} y={CY + 9}
              textAnchor="middle"
              fontSize="9" fontWeight="600"
              fill="#9ca3af"
              letterSpacing="0.06em"
            >
              MODELS
            </text>
          </svg>
        </div>

        {/* Legend */}
        <div className="flex flex-col gap-3.5 flex-1">
          {SEGMENTS.map(s => (
            <div key={s.label} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: s.color }}
                />
                <span className="text-[13px] text-gray-600">{s.label}</span>
              </div>
              <span className={`text-[13px] font-semibold tabular-nums ${s.textColor}`}>
                {s.count}
              </span>
            </div>
          ))}
        </div>

      </div>
    </div>
  )
}
