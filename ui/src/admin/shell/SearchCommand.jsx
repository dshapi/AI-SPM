import { useState, useRef, useCallback } from 'react'
import { Search } from 'lucide-react'
import { cn } from '../../lib/utils.js'
import { useClickOutside } from '../../hooks/useClickOutside.js'

// ── Mock data ─────────────────────────────────────────────────────────────────
const GROUPS = [
  {
    key: 'assets',
    label: 'Assets',
    items: [
      { id: 'a1', title: 'gpt-4-turbo',      sub: 'OpenAI · Production'   },
      { id: 'a2', title: 'claude-sonnet-4-6', sub: 'Anthropic · Staging'   },
      { id: 'a3', title: 'llama-3-70b',       sub: 'Meta · Development'    },
    ],
  },
  {
    key: 'alerts',
    label: 'Alerts',
    items: [
      { id: 'b1', title: 'Prompt injection detected', sub: 'gpt-4-turbo · 2m ago'   },
      { id: 'b2', title: 'Output PII exposure',       sub: 'claude-sonnet · 15m ago' },
    ],
  },
  {
    key: 'policies',
    label: 'Policies',
    items: [
      { id: 'c1', title: 'No PII in responses', sub: 'Active · v3'    },
      { id: 'c2', title: 'Rate limit guardrail', sub: 'Active · v1'   },
    ],
  },
  {
    key: 'sessions',
    label: 'Sessions',
    items: [
      { id: 'd1', title: 'Session #4821', sub: '5m ago'  },
      { id: 'd2', title: 'Session #4820', sub: '12m ago' },
    ],
  },
]

function filterGroups(q) {
  if (!q.trim()) return GROUPS
  const lq = q.toLowerCase()
  return GROUPS.map(g => ({
    ...g,
    items: g.items.filter(
      it => it.title.toLowerCase().includes(lq) || it.sub.toLowerCase().includes(lq),
    ),
  })).filter(g => g.items.length > 0)
}

// ── Component ─────────────────────────────────────────────────────────────────
export function SearchCommand() {
  const [query, setQuery]   = useState('')
  const [open, setOpen]     = useState(false)
  const containerRef        = useRef(null)
  const inputRef            = useRef(null)

  const close = useCallback(() => { setOpen(false); setQuery('') }, [])
  useClickOutside(containerRef, close)

  const groups = filterGroups(query)

  return (
    <div ref={containerRef} className="relative">

      {/* ── Input ── */}
      <div
        className={cn(
          'relative flex items-center h-10 w-72 rounded-lg border transition-all duration-150',
          open
            ? 'bg-white border-blue-500 ring-2 ring-blue-500/15 shadow-sm'
            : 'bg-gray-50 border-gray-200 hover:border-gray-300',
        )}
      >
        {/* Search icon */}
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
          <Search size={14} strokeWidth={2} />
        </span>

        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder="Search…"
          autoComplete="off"
          onFocus={() => setOpen(true)}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') { close(); inputRef.current?.blur() }
          }}
          className="w-full h-full pl-9 pr-3 bg-transparent text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none"
        />

        {/* ⌘K hint — hidden when focused */}
        {!open && (
          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-gray-300 pointer-events-none select-none">
            ⌘K
          </span>
        )}
      </div>

      {/* ── Dropdown ── */}
      {open && (
        <div
          className="animate-dropdown absolute top-full left-0 mt-1.5 w-[420px] bg-white border border-gray-200 rounded-xl shadow-[0_4px_24px_rgba(0,0,0,0.08),0_1px_4px_rgba(0,0,0,0.04)] z-50 overflow-hidden"
          onMouseDown={e => e.preventDefault()} // prevent blur-before-click
        >
          {groups.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-gray-400">No results for "{query}"</p>
          ) : (
            <div className="max-h-[380px] overflow-y-auto py-2">
              {groups.map(group => (
                <div key={group.key}>
                  <p className="px-4 py-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-gray-400">
                    {group.label}
                  </p>
                  {group.items.map(item => (
                    <button
                      key={item.id}
                      onClick={close}
                      className="w-full flex items-start gap-3 px-4 py-2.5 hover:bg-gray-50 transition-colors duration-100 text-left"
                    >
                      {/* Icon chip */}
                      <span className="w-7 h-7 rounded-md bg-gray-100 flex items-center justify-center shrink-0 mt-0.5">
                        <Search size={12} strokeWidth={2} className="text-gray-400" />
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-800 leading-snug truncate">{item.title}</p>
                        <p className="text-xs text-gray-400 leading-snug truncate">{item.sub}</p>
                      </div>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* Footer hint */}
          <div className="border-t border-gray-100 px-4 py-2 flex items-center gap-3">
            <span className="text-[11px] text-gray-300">↑↓ navigate</span>
            <span className="text-[11px] text-gray-300">↵ open</span>
            <span className="text-[11px] text-gray-300">Esc close</span>
          </div>
        </div>
      )}
    </div>
  )
}
