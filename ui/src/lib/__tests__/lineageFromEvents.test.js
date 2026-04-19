import { describe, it, expect } from 'vitest'
import { lineageFromEvents, assignCoords, assignEdgePaths } from '../lineageFromEvents.js'
import { EVENT_TYPES } from '../eventSchema.js'

function ev(event_type, details = {}) {
  return { id: `${event_type}:x:ts`, event_type, stage: 'progress', status: 'progress', timestamp: 'ts', details }
}

describe('lineageFromEvents', () => {
  it('returns empty graph for no events', () => {
    const g = lineageFromEvents([])
    expect(g.nodes).toEqual([])
    expect(g.edges).toEqual([])
  })

  it('session.started creates a prompt node', () => {
    const g = lineageFromEvents([ev(EVENT_TYPES.SESSION_STARTED, { prompt: 'hello' })])
    expect(g.nodes.find(n => n.type === 'prompt')).toBeTruthy()
  })

  it('context.retrieved creates a context node', () => {
    const g = lineageFromEvents([
      ev(EVENT_TYPES.SESSION_STARTED),
      ev(EVENT_TYPES.CONTEXT_RETRIEVED, { retrieved_contexts: ['ctx1', 'ctx2'] }),
    ])
    expect(g.nodes.find(n => n.type === 'context')).toBeTruthy()
  })

  it('risk.enriched creates a model node', () => {
    const g = lineageFromEvents([
      ev(EVENT_TYPES.SESSION_STARTED),
      ev(EVENT_TYPES.RISK_ENRICHED),
    ])
    expect(g.nodes.find(n => n.type === 'model')).toBeTruthy()
  })

  it('tool.invoked creates a tool node with label containing tool_name', () => {
    const g = lineageFromEvents([
      ev(EVENT_TYPES.SESSION_STARTED),
      ev(EVENT_TYPES.TOOL_INVOKED, { tool_name: 'sql_query' }),
    ])
    const toolNode = g.nodes.find(n => n.type === 'tool')
    expect(toolNode).toBeTruthy()
    expect(toolNode.label).toMatch(/sql_query/i)
  })

  it('policy.blocked creates a policy node with flagged=true', () => {
    const g = lineageFromEvents([
      ev(EVENT_TYPES.SESSION_STARTED),
      ev(EVENT_TYPES.POLICY_BLOCKED, { reason: 'pii detected' }),
    ])
    const policyNode = g.nodes.find(n => n.type === 'policy')
    expect(policyNode).toBeTruthy()
    expect(policyNode.flagged).toBe(true)
  })

  it('output.generated creates an output node', () => {
    const g = lineageFromEvents([
      ev(EVENT_TYPES.SESSION_STARTED),
      ev(EVENT_TYPES.OUTPUT_GENERATED, { response: 'hello' }),
    ])
    expect(g.nodes.find(n => n.type === 'output')).toBeTruthy()
  })

  it('creates prompt→context edge when both present', () => {
    const g = lineageFromEvents([
      ev(EVENT_TYPES.SESSION_STARTED),
      ev(EVENT_TYPES.CONTEXT_RETRIEVED),
    ])
    expect(g.edges.some(e => e.from === 'prompt' && e.to === 'context')).toBe(true)
  })

  it('creates policy→output edge when both present', () => {
    const g = lineageFromEvents([
      ev(EVENT_TYPES.SESSION_STARTED),
      ev(EVENT_TYPES.POLICY_ALLOWED),
      ev(EVENT_TYPES.OUTPUT_GENERATED),
    ])
    expect(g.edges.some(e => e.from === 'policy' && e.to === 'output')).toBe(true)
  })

  it('is pure — same input same output', () => {
    const events = [ev(EVENT_TYPES.SESSION_STARTED), ev(EVENT_TYPES.POLICY_BLOCKED)]
    expect(lineageFromEvents(events)).toEqual(lineageFromEvents(events))
  })
})

describe('assignCoords', () => {
  it('adds cx and cy to each node based on type', () => {
    const nodes = [{ id: 'prompt', type: 'prompt', label: 'Prompt', sub: '', risk: 'Low', flagged: false }]
    const result = assignCoords(nodes)
    expect(result[0].cx).toBeDefined()
    expect(result[0].cy).toBeDefined()
  })
})

describe('assignEdgePaths', () => {
  it('adds path string to each edge', () => {
    const nodes = [
      { id: 'prompt', type: 'prompt', cx: 65, cy: 150 },
      { id: 'context', type: 'context', cx: 210, cy: 78 },
    ]
    const edges = [{ id: 'prompt-context', from: 'prompt', to: 'context', type: 'data', label: 'context' }]
    const nodeById = new Map(nodes.map(n => [n.id, n]))
    const result = assignEdgePaths(edges, nodeById)
    expect(result[0].path).toBeTruthy()
    expect(result[0].path).toMatch(/^M /)
  })
})
