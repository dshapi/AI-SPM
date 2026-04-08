import { useRef, useState, useEffect } from 'react'
import { Search, LayoutDashboard, TriangleAlert, FileCheck2, Activity } from 'lucide-react'
import clsx from 'clsx'

/**
 * SearchInput — global command palette / search with results dropdown.
 *
 * Behaviour:
 *   • Controlled input, dropdown opens on focus
 *   • Filters mock results as the user types
 *   • Closes on Escape, on outside click, or when an item is selected
 *   • onMouseDown + preventDefault on the dropdown prevents the input from
 *     blurring before an item click fires (classic React focus-loss problem)
 *
 * Visual tokens:
 *   container   h-9 w-80 rounded-lg border
 *   focused     border-blue-500 ring-2 ring-blue-500/20 bg-white
 *   idle        border-gray-200 bg-gray-50 hover:border-gray-300
 *   dropdown    w-[400px] bg-white border-gray-200 rounded-xl shadow-lg z-40
 */

// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_GROUPS = [
  {
    group: 'Assets',
    icon: LayoutDashboard,
    items: [
      { id: 'a1', label: 'gpt-4-turbo',        sub: 'OpenAI · Production · Active'        },
      { id: 'a2', label: 'claude-sonnet-4-6',  sub: 'Anthropic · Production · Active'     },
      { id: 'a3', label: 'llama-3-70b',        sub: 'Meta · Staging · Under Review'       },
    ],
  },
  {
    group: 'Alerts',
    icon: TriangleAlert,
    items: [
      { id: 'al1', label: 'Prompt injection on lim-agent-prod', sub: 'High · 2m ago'       },
      { id: 'al2', label: 'PII exposure on ai-workflow-02',     sub: 'Medium · 15m ago'    },
    ],
  },
  {
    group: 'Policies',
    icon: FileCheck2,
    items: [
      { id: 'p1', label: 'Block unsafe model output',  sub: 'OPA · Active · 4 rules' },
      { id: 'p2', label: 'Prompt injection guard',     sub: 'OPA · Active · 2 rules' },
    ],
  },
  {
    group: 'Sessions',
    icon: Activity,
    items: [
      { id: 's1', label: 'Session 4a92bc · t-1',  sub: 'gpt-4-turbo · 3 events · 2m ago'  },
      { id: 's2', label: 'Session 7f01ee · t-2',  sub: 'mixtral-8x7b · 1 event · 8m ago'  },
    ],
  },
]

function filterGroups(query) {
  if (!query.trim()) return MOCK_GROUPS
  const q = query.toLowerCase()
  return MOCK_GROUPS
    .map(g => ({
      ...g,
      items: g.items.filter(
        item =>
          item.label.toLowerCase().includes(q) ||
          item.sub.toLowerCase().includes(q)
      ),
    }))
    .filter(g => g.items.length > 0)
}

// ── Component ────────────────────────────────────────────────────────────────

export default function SearchInput() {
  const [query, setQuery]   = useState('')
  const [open, setOpen]     = useState(false)
  const inputRef            = useRef(null)
  const dropdownRef         = useRef(null)

  const groups = filterGroups(query)
  const total  = groups.reduce((n, g) => n + g.items.length, 0)

  // ── Outside click ──────────────────────────────────────────────────────────
  useEffect(() => {
    function onMouseDown(e) {
      if (
        !inputRef.current?.contains(e.target) &&
        !dropdownRef.current?.contains(e.target)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [])

  // ── Keyboard (Escape) ──────────────────────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape' && open) {
        setOpen(false)
        inputRef.current?.blur()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  function selectItem() {
    setOpen(false)
    setQuery('')
    inputRef.current?.blur()
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="relative">

      {/* ── Input ──────────────────────────────────────────────────────────── */}
      <div
        className={clsx(
          'relative flex items-center h-10 w-80 rounded-lg border transition-all duration-150',
          open
            ? 'bg-white border-blue-500 ring-2 ring-blue-500/20'
            : 'bg-gray-50 border-gray-200 hover:border-gray-300'
        )}
      >
        {/* Search icon */}
        <Search
          size={15}
          strokeWidth={2}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none shrink-0"
        />

        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => setOpen(true)}
          placeholder="Search assets, alerts, policies…"
          className="h-full w-full bg-transparent pl-9 pr-[4.5rem] text-[13px] text-gray-700 placeholder-gray-400 outline-none"
        />

        {/* ⌘K hint — hidden when focused so it doesn't crowd the typing area */}
        {!open && (
          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center gap-0.5 pointer-events-none">
            <kbd className="text-[10px] font-medium text-gray-400 bg-gray-100 border border-gray-200 rounded px-1 py-0.5 leading-none">⌘</kbd>
            <kbd className="text-[10px] font-medium text-gray-400 bg-gray-100 border border-gray-200 rounded px-1 py-0.5 leading-none">K</kbd>
          </span>
        )}
      </div>

      {/* ── Dropdown ───────────────────────────────────────────────────────── */}
      {open && (
        <div
          ref={dropdownRef}
          // Prevents blur from firing on the input when clicking inside dropdown
          onMouseDown={e => e.preventDefault()}
          className="animate-dropdown absolute top-full left-0 mt-2 w-[420px] bg-white border border-gray-200 rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.08),0_1px_4px_rgba(0,0,0,0.04)] z-40 overflow-hidden"
        >
          {groups.length === 0 ? (

            /* Empty state */
            <div className="px-4 py-10 text-center">
              <Search size={24} className="mx-auto text-gray-300 mb-3" strokeWidth={1.5} />
              <p className="text-[13px] font-medium text-gray-500">No results for "{query}"</p>
              <p className="text-[12px] text-gray-400 mt-1">Try a different search term</p>
            </div>

          ) : (

            /* Results */
            <div className="max-h-[480px] overflow-y-auto">
              {groups.map(g => {
                const GroupIcon = g.icon
                return (
                  <div key={g.group}>

                    {/* Group header */}
                    <div className="flex items-center gap-2 px-4 py-2 bg-gray-50 border-b border-gray-100">
                      <GroupIcon size={12} className="text-gray-400" strokeWidth={2} />
                      <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-gray-400">
                        {g.group}
                      </span>
                    </div>

                    {/* Result rows */}
                    {g.items.map(item => (
                      <button
                        key={item.id}
                        onClick={selectItem}
                        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-blue-50/50 transition-colors duration-100 text-left border-b border-gray-50 last:border-0"
                      >
                        {/* Icon chip */}
                        <div className="flex items-center justify-center w-7 h-7 rounded-md bg-gray-100 shrink-0">
                          <GroupIcon size={13} className="text-gray-500" strokeWidth={1.75} />
                        </div>
                        {/* Text */}
                        <div className="flex-1 min-w-0">
                          <p className="text-[13px] font-medium text-gray-800 truncate">{item.label}</p>
                          <p className="text-[11px] text-gray-400 truncate mt-0.5">{item.sub}</p>
                        </div>
                      </button>
                    ))}

                  </div>
                )
              })}
            </div>

          )}

          {/* Footer */}
          {groups.length > 0 && (
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 bg-gray-50">
              <span className="text-[11px] text-gray-400">
                {total} result{total !== 1 ? 's' : ''}
              </span>
              <div className="flex items-center gap-3 text-[11px] text-gray-400">
                <span className="flex items-center gap-1">
                  <kbd className="bg-white border border-gray-200 rounded px-1 py-0.5 text-[10px] font-medium">↑↓</kbd>
                  Navigate
                </span>
                <span className="flex items-center gap-1">
                  <kbd className="bg-white border border-gray-200 rounded px-1 py-0.5 text-[10px] font-medium">↵</kbd>
                  Select
                </span>
                <span className="flex items-center gap-1">
                  <kbd className="bg-white border border-gray-200 rounded px-1 py-0.5 text-[10px] font-medium">Esc</kbd>
                  Close
                </span>
              </div>
            </div>
          )}

        </div>
      )}

    </div>
  )
}
