/**
 * InventoryBreakdown — Registered models by provider.
 *
 * Design tokens:
 *   card header  → border-b border-gray-100 pb-4 mb-5
 *   panel title  → text-sm font-semibold text-gray-900
 *   panel sub    → text-xs text-gray-400 mt-0.5
 *   bar track    → h-1.5 bg-gray-100 rounded-full
 *   bar fill     → bg-blue-500 (consistent with TopRisks)
 *   badge        → text-[11px] font-semibold px-2 py-0.5 rounded-md w-20
 *   count        → text-[12px] font-semibold text-gray-600 tabular-nums
 */

const PROVIDERS = [
  { name: 'OpenAI',    models: 5, badge: 'bg-green-50  text-green-700  border border-green-200'  },
  { name: 'Anthropic', models: 3, badge: 'bg-blue-50   text-blue-700   border border-blue-200'   },
  { name: 'Meta',      models: 2, badge: 'bg-gray-100  text-gray-600   border border-gray-200'   },
  { name: 'Mistral',   models: 1, badge: 'bg-purple-50 text-purple-700 border border-purple-200' },
  { name: 'Groq',      models: 1, badge: 'bg-orange-50 text-orange-700 border border-orange-200' },
]

const MAX_MODELS = Math.max(...PROVIDERS.map(p => p.models))

const STATUS = [
  { label: 'Approved',     count: 8, dot: 'bg-emerald-500' },
  { label: 'Under Review', count: 3, dot: 'bg-yellow-400'  },
  { label: 'Blocked',      count: 1, dot: 'bg-red-500'     },
]

export default function InventoryBreakdown() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm hover:border-gray-300 transition-colors duration-150 h-full flex flex-col">

      {/* ── Panel header ─────────────────────────────────────────── */}
      <div className="border-b border-gray-100 pb-4 mb-5">
        <p className="text-sm font-semibold text-gray-900">Inventory Breakdown</p>
        <p className="text-xs text-gray-400 mt-0.5">Registered models by provider</p>
      </div>

      {/* ── Provider rows ─────────────────────────────────────────── */}
      <div className="flex flex-col gap-3.5 flex-1 justify-between">
        {PROVIDERS.map(p => (
          <div key={p.name} className="flex items-center gap-3">
            <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-md w-[72px] text-center shrink-0 ${p.badge}`}>
              {p.name}
            </span>
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${(p.models / MAX_MODELS) * 100}%` }}
              />
            </div>
            <span className="text-[12px] font-semibold text-gray-500 tabular-nums w-4 text-right shrink-0">
              {p.models}
            </span>
          </div>
        ))}
      </div>

      {/* ── Status footer ─────────────────────────────────────────── */}
      <div className="mt-5 pt-4 border-t border-gray-100 flex items-center justify-between">
        {STATUS.map(s => (
          <div key={s.label} className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.dot}`} />
            <span className="text-[12px] text-gray-500">{s.label}</span>
            <span className="text-[12px] font-bold text-gray-700 tabular-nums ml-0.5">{s.count}</span>
          </div>
        ))}
      </div>

    </div>
  )
}
