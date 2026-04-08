/**
 * TopRisksPanel — Datadog-style ranked risk list.
 *
 * Design tokens:
 *   card header  → border-b border-gray-100 pb-4 mb-5
 *   panel title  → text-sm font-semibold text-gray-900
 *   panel sub    → text-xs text-gray-400 mt-0.5
 *   bar track    → h-1.5 bg-gray-100 rounded-full
 *   bar fill     → bg-blue-500 (normalised to max count)
 */

const RISKS = [
  { icon: '⚡', label: 'Prompt Injection',    count: 18 },
  { icon: '🔓', label: 'Auth Bypass Attempt', count: 11 },
  { icon: '📤', label: 'PII Exfiltration',    count: 9  },
  { icon: '🚫', label: 'Model Gate Block',    count: 7  },
  { icon: '🔁', label: 'Rate Limit Exceeded', count: 4  },
]

const MAX = Math.max(...RISKS.map(r => r.count))

export default function TopRisksPanel() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm hover:border-gray-300 transition-colors duration-150 h-full flex flex-col">

      {/* ── Panel header ─────────────────────────────────────────── */}
      <div className="border-b border-gray-100 pb-4 mb-5">
        <p className="text-sm font-semibold text-gray-900">Top Risks</p>
        <p className="text-xs text-gray-400 mt-0.5">By detection frequency this week</p>
      </div>

      {/* ── Risk rows ─────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 flex-1 justify-between">
        {RISKS.map(r => (
          <div key={r.label}>
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[13px] leading-none" role="img">{r.icon}</span>
                <span className="text-[13px] text-gray-700 font-medium">{r.label}</span>
              </div>
              <span className="text-[12px] font-semibold text-gray-500 tabular-nums">{r.count}</span>
            </div>
            <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${(r.count / MAX) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>

    </div>
  )
}
