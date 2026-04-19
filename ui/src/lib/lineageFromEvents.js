/**
 * lib/lineageFromEvents.js
 * ─────────────────────────
 * Pure function: SimulationEvent[] → LineageGraph
 *
 * LineageGraph shape
 * ──────────────────
 * {
 *   nodes: LineageNode[]
 *   edges: LineageEdge[]
 * }
 *
 * LineageNode shape (matches NODE_CFG keys in Lineage.jsx)
 * ──────────────────
 * { id, type, label, sub, risk, flagged }
 * type is one of: 'prompt' | 'context' | 'rag' | 'model' | 'tool' | 'policy' | 'output'
 *
 * LineageEdge shape
 * ──────────────────
 * { id, from, to, type, label }
 * type is one of: 'data' | 'sensitive' | 'tool' | 'policy' | 'output'
 */
import { EVENT_TYPES } from './eventSchema.js'

/**
 * @param {import('./eventSchema.js').SimulationEvent[]} events
 * @returns {{ nodes: object[], edges: object[] }}
 */
export function lineageFromEvents(events) {
  if (!events || events.length === 0) return { nodes: [], edges: [] }

  const nodeMap = new Map()   // id → node
  const edges   = []
  let   toolIdx = 0

  function addNode(id, type, label, sub, risk = 'Low', flagged = false) {
    if (!nodeMap.has(id)) {
      nodeMap.set(id, { id, type, label, sub, risk, flagged })
    } else {
      const n = nodeMap.get(id)
      if (flagged) n.flagged = true
      if (_riskLevel(risk) > _riskLevel(n.risk)) n.risk = risk
      if (sub) n.sub = sub
    }
  }

  function addEdge(from, to, type, label) {
    const id = `${from}-${to}`
    if (!edges.find(e => e.id === id)) {
      edges.push({ id, from, to, type, label })
    }
  }

  for (const event of events) {
    const d = event.details || {}

    switch (event.event_type) {
      case EVENT_TYPES.SESSION_STARTED:
      case EVENT_TYPES.SESSION_CREATED:
        addNode('prompt', 'prompt', 'User Prompt',
          d.prompt ? `"${String(d.prompt).slice(0, 40)}…"` : 'Prompt received')
        break

      case EVENT_TYPES.CONTEXT_RETRIEVED: {
        const count = Array.isArray(d.retrieved_contexts)
          ? d.retrieved_contexts.length
          : (d.context_count ?? 0)
        addNode('context', 'context', 'Session Context', `${count} context item${count !== 1 ? 's' : ''}`)
        addEdge('prompt', 'context', 'data', 'context')
        break
      }

      case EVENT_TYPES.RISK_ENRICHED:
      case EVENT_TYPES.RISK_CALCULATED: {
        const score = d.posture_score ?? d.risk_score ?? 0
        const risk  = score >= 0.8 ? 'Critical' : score >= 0.5 ? 'High' : score >= 0.3 ? 'Medium' : 'Low'
        addNode('model', 'model', 'LLM Processing', `Risk: ${Math.round(score * 100)}`, risk, score >= 0.8)
        if (nodeMap.has('context')) addEdge('context', 'model', 'data', 'context')
        else addEdge('prompt', 'model', 'data', 'prompt')
        break
      }

      case EVENT_TYPES.AGENT_TOOL_PLANNED:
      case EVENT_TYPES.TOOL_INVOKED:
      case EVENT_TYPES.TOOL_COMPLETED: {
        const toolName = d.tool_name || `Tool ${toolIdx + 1}`
        const toolId   = `tool-${toolName.replace(/\s+/g, '-').toLowerCase()}`
        if (!nodeMap.has(toolId)) toolIdx++
        addNode(toolId, 'tool', `Tool: ${toolName}`, d.status || 'invoked')
        addEdge('model', toolId, 'tool', 'tool call')
        break
      }

      case EVENT_TYPES.TOOL_APPROVAL_REQUIRED: {
        const toolName = d.tool_name || 'Tool'
        const toolId   = `tool-${toolName.replace(/\s+/g, '-').toLowerCase()}`
        addNode(toolId, 'tool', `Tool: ${toolName}`, 'approval required', 'Medium', true)
        if (!edges.find(e => e.to === toolId)) addEdge('model', toolId, 'tool', 'tool call')
        break
      }

      case EVENT_TYPES.POLICY_ALLOWED:
      case EVENT_TYPES.POLICY_ESCALATED:
      case EVENT_TYPES.POLICY_BLOCKED: {
        const isBlock    = event.event_type === EVENT_TYPES.POLICY_BLOCKED
        const isEscalate = event.event_type === EVENT_TYPES.POLICY_ESCALATED
        const risk       = isBlock ? 'Critical' : isEscalate ? 'High' : 'Low'
        const sub        = d.reason || d.policy_version || (isBlock ? 'BLOCKED' : isEscalate ? 'ESCALATED' : 'ALLOWED')
        addNode('policy', 'policy', 'Policy Gate', sub, risk, isBlock || isEscalate)
        const fromId = nodeMap.has('model') ? 'model' : 'prompt'
        addEdge(fromId, 'policy', 'policy', 'policy eval')
        break
      }

      case EVENT_TYPES.OUTPUT_GENERATED:
      case EVENT_TYPES.OUTPUT_SCANNED: {
        const sub = d.pii_redacted ? 'Redacted · ' : ''
        addNode('output', 'output', 'Output',
          `${sub}${d.response_latency_ms ? `${d.response_latency_ms}ms` : 'generated'}`)
        const fromId = nodeMap.has('policy') ? 'policy'
          : nodeMap.has('model') ? 'model' : 'prompt'
        addEdge(fromId, 'output', 'output', 'gated')
        break
      }

      case EVENT_TYPES.SESSION_BLOCKED: {
        addNode('policy', 'policy', 'Policy Gate', d.reason || 'Blocked', 'Critical', true)
        if (!edges.find(e => e.to === 'policy')) {
          const fromId = nodeMap.has('model') ? 'model' : 'prompt'
          addEdge(fromId, 'policy', 'policy', 'policy eval')
        }
        break
      }

      default:
        break
    }
  }

  return { nodes: Array.from(nodeMap.values()), edges }
}

// ── Layout helpers ────────────────────────────────────────────────────────────

// Static pixel positions per node type.
// Designed for NW=55, NH=28, CW=790, CH=300 canvas (matches Lineage.jsx).
const _LAYOUT = {
  prompt:  { cx: 65,  cy: 150 },
  context: { cx: 210, cy: 78  },
  rag:     { cx: 210, cy: 222 },
  model:   { cx: 380, cy: 150 },
  tool:    { cx: 520, cy: 72  },
  policy:  { cx: 570, cy: 228 },
  output:  { cx: 710, cy: 150 },
}

const _NW = 55   // node half-width

/**
 * Assign SVG cx/cy coordinates to nodes for rendering.
 * Multiple tool nodes stack vertically (60px apart).
 *
 * @param {object[]} nodes — from lineageFromEvents
 * @returns {object[]} nodes with cx, cy added
 */
export function assignCoords(nodes) {
  let toolCount = 0
  return nodes.map(n => {
    let pos = _LAYOUT[n.type] ?? { cx: 400, cy: 150 }
    if (n.type === 'tool') {
      pos = { cx: _LAYOUT.tool.cx, cy: _LAYOUT.tool.cy + toolCount * 60 }
      toolCount++
    }
    return { ...n, ...pos }
  })
}

/**
 * Generate SVG bezier path strings for edges.
 * Connects right port of source node to left port of target node.
 *
 * @param {object[]} edges — from lineageFromEvents
 * @param {Map<string, object>} nodeById — id → positioned node (with cx, cy)
 * @returns {object[]} edges with path added
 */
export function assignEdgePaths(edges, nodeById) {
  return edges.map(edge => {
    const from = nodeById.get(edge.from)
    const to   = nodeById.get(edge.to)
    if (!from || !to) return { ...edge, path: '' }
    const x1 = from.cx + _NW, y1 = from.cy
    const x2 = to.cx   - _NW, y2 = to.cy
    const cp = Math.abs(x2 - x1) * 0.4
    return { ...edge, path: `M ${x1} ${y1} C ${x1 + cp} ${y1}, ${x2 - cp} ${y2}, ${x2} ${y2}` }
  })
}

// ── Private helpers ───────────────────────────────────────────────────────────
function _riskLevel(r) {
  return { Low: 0, Medium: 1, High: 2, Critical: 3 }[r] ?? 0
}
