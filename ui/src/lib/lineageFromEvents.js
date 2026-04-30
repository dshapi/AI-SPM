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

  function addNode(id, type, label, sub, risk = 'Low', flagged = false, details = {}) {
    if (!nodeMap.has(id)) {
      // `details` is a free-form object the side panel renders as
      // labelled rows. Standard keys (rendered with friendly labels):
      //   prompt, response, agentId, agentLabel, userId, userEmail,
      //   model, tokensIn, tokensOut, tool, toolArgs, toolStatus,
      //   durationMs, reason, policyVersion
      nodeMap.set(id, { id, type, label, sub, risk, flagged, details })
    } else {
      const n = nodeMap.get(id)
      if (flagged) n.flagged = true
      if (_riskLevel(risk) > _riskLevel(n.risk)) n.risk = risk
      if (sub) n.sub = sub
      // Merge new details on top of existing ones — later events
      // for the same node id refine the picture (e.g. tool node
      // gets `toolArgs` from the planned event, then `durationMs`
      // and `toolStatus` from the completed event).
      if (details && Object.keys(details).length) {
        n.details = { ...(n.details || {}), ...details }
      }
    }
  }

  // Format an agent_id into something humans can scan in the side panel.
  // Mirrors _formatAgentLabel in Runtime.jsx — duplicated here because
  // this module is pure (no React) and we don't want a circular import.
  function _formatAgentLabel(agentId) {
    if (!agentId) return null
    if (agentId === 'sim-agent' || agentId === 'chat-agent') return agentId
    const m = agentId.match(/^agent-([0-9a-f]{8})[0-9a-f-]+-runtime$/i)
    if (m) return `custom agent-${m[1]}`
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(agentId)) {
      return `custom agent-${agentId.slice(0, 8)}`
    }
    return agentId
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
      case EVENT_TYPES.SESSION_CREATED: {
        // AgentChatMessage events (canonicalised into SESSION_STARTED for
        // role=user) carry the prompt in `text`; legacy session events
        // use `prompt`. Try both.
        const promptText = d.text ?? d.prompt
        const agentId    = d.agent_id ?? event.agent_id
        const userId     = d.user_id  ?? event.user_id
        addNode(
          'prompt',
          'prompt',
          'User Prompt',
          promptText ? `"${String(promptText).slice(0, 40)}…"` : 'Prompt received',
          'Low',
          false,
          {
            prompt:     promptText ?? null,
            agentId:    agentId ?? null,
            agentLabel: _formatAgentLabel(agentId),
            userId:     userId ?? null,
            traceId:    d.trace_id ?? event.correlation_id ?? null,
          },
        )
        break
      }

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
        // AgentLLMCall events (canonicalised here) carry model/token
        // usage in the payload. Capture them for the side panel.
        addNode(
          'model', 'model', 'LLM Processing',
          `Risk: ${Math.round(score * 100)}`,
          risk,
          score >= 0.8,
          {
            model:     d.model ?? null,
            tokensIn:  d.prompt_tokens ?? null,
            tokensOut: d.completion_tokens ?? null,
            riskScore: score,
            agentId:   d.agent_id ?? null,
            agentLabel: _formatAgentLabel(d.agent_id),
          },
        )
        if (nodeMap.has('context')) addEdge('context', 'model', 'data', 'context')
        else addEdge('prompt', 'model', 'data', 'prompt')
        break
      }

      case EVENT_TYPES.AGENT_TOOL_PLANNED:
      case EVENT_TYPES.TOOL_INVOKED:
      case EVENT_TYPES.TOOL_COMPLETED: {
        // AgentToolCall payload uses `tool` (no _name suffix) and carries
        // args + duration_ms + ok. Legacy events use tool_name + status.
        const toolName = d.tool_name || d.tool || `Tool ${toolIdx + 1}`
        const toolId   = `tool-${toolName.replace(/\s+/g, '-').toLowerCase()}`
        if (!nodeMap.has(toolId)) toolIdx++
        const status = d.status || (d.ok === false ? 'failed'
                                  : d.ok === true  ? 'completed'
                                  : 'invoked')
        addNode(
          toolId, 'tool', `Tool: ${toolName}`, status,
          d.ok === false ? 'High' : 'Low',
          d.ok === false,
          {
            tool:       toolName,
            toolArgs:   d.args ?? d.tool_args ?? null,
            toolStatus: status,
            durationMs: d.duration_ms ?? null,
            agentId:    d.agent_id ?? null,
            agentLabel: _formatAgentLabel(d.agent_id),
          },
        )
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

      // LLM invocation — emitted by api-chat right before the model stream is
      // opened (and by simulation runners). Renders a dedicated "LLM Call" node
      // downstream of policy so the graph clearly shows: prompt → … → policy
      //  → llm → output.
      case 'llm.invoked':
      case 'llm.response':
      case EVENT_TYPES.AGENT_RESPONSE_READY: {
        const provider = d.provider || d.model_name || d.model || ''
        const sub      = provider
          ? String(provider)
          : (d.tokens_in != null ? `${d.tokens_in} in / ${d.tokens_out ?? '…'} out` : 'invoked')
        addNode('llm', 'llm', 'LLM Call', sub)
        const fromId = nodeMap.has('policy') ? 'policy'
          : nodeMap.has('model') ? 'model'
          : nodeMap.has('context') ? 'context' : 'prompt'
        addEdge(fromId, 'llm', 'data', 'invoke')
        break
      }

      case EVENT_TYPES.OUTPUT_GENERATED:
      case EVENT_TYPES.OUTPUT_SCANNED: {
        const sub = d.pii_redacted ? 'Redacted · ' : ''
        // AgentChatMessage role=agent canonicalises to OUTPUT_GENERATED;
        // the assistant's reply is in `text`.
        const responseText = d.text ?? d.response ?? null
        addNode(
          'output', 'output', 'Output',
          `${sub}${d.response_latency_ms ? `${d.response_latency_ms}ms` : 'generated'}`,
          'Low',
          false,
          {
            response:   responseText,
            piiRedacted: !!d.pii_redacted,
            latencyMs:  d.response_latency_ms ?? null,
            agentId:    d.agent_id ?? null,
            agentLabel: _formatAgentLabel(d.agent_id),
          },
        )
        // Prefer the most-downstream upstream node we have so the chain reads
        // policy → llm → output when both exist.
        const fromId = nodeMap.has('llm') ? 'llm'
          : nodeMap.has('policy') ? 'policy'
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
//
// Dynamic left-packed layout. Earlier versions used STATIC per-type x-positions
// (prompt at 65, model at 360, policy at 700 …) which left a huge empty gutter
// on the left whenever upstream nodes (prompt / context / model) were missing
// from the event stream — the user reported "graph starts in the middle of the
// canvas, I have to scroll". Now every present node type gets a column index
// based on flow order, and we pack them left-to-right starting at x=65.
//
// Lanes (y-positions) per node type are kept stable so the visual structure
// (context above, RAG below, model centre, policy lower-right, etc.) is
// preserved regardless of which columns are occupied.

const _NW = 55   // node half-width

// Vertical lanes — y positions per node type. These NEVER change; only x is
// computed dynamically.
const _LANE_Y = {
  prompt:  150,
  context: 78,
  rag:     222,
  model:   150,
  tool:    150,   // overridden per-tool below for fan-out
  policy:  230,
  llm:     150,
  output:  150,
}

// Flow order — left-to-right. Tools are interleaved between model and policy
// because tools fan out from the model in the canonical agent pipeline.
const _FLOW_ORDER = ['prompt', 'context', 'rag', 'model', 'tool', 'policy', 'llm', 'output']

// Horizontal spacing knobs.
const _COL_GAP        = 145   // pixels between adjacent column centres
const _LEFT_MARGIN    = 65    // x-position of the first column

// Tool fan-out knobs (when many tools exist they wrap into a second column).
const _TOOL_COL_BASE_Y = 70
const _TOOL_ROW_GAP    = 70
const _TOOLS_PER_COL   = 3

/**
 * Compute (cw, ch) for the canvas given the set of present node types and the
 * tool count. Width grows with the number of occupied columns; height grows
 * only when many tools wrap into multiple rows.
 */
export function graphDimensions(toolCountOrNodes = 0, presentTypes = null) {
  // Backwards-compatible call shape: graphDimensions(toolCount) — derive a
  // sensible default `presentTypes` so existing callers (e.g. tests) keep
  // working without passing the second arg.
  let toolCount, types
  if (Array.isArray(toolCountOrNodes)) {
    // Caller passed nodes[]
    types     = new Set(toolCountOrNodes.map(n => n.type))
    toolCount = toolCountOrNodes.filter(n => n.type === 'tool').length
  } else {
    toolCount = toolCountOrNodes
    types     = presentTypes
      ? new Set(presentTypes)
      : new Set(['prompt', 'context', 'model', 'policy', 'output']) // assume canonical 5-step
    if (toolCount > 0) types.add('tool')
  }

  const colCount = _FLOW_ORDER.filter(t => types.has(t)).length || 1
  // Tool wrapping — extra horizontal slot if 4+ tools.
  const toolWrapCols = toolCount > _TOOLS_PER_COL ? 1 : 0

  const cw = Math.max(
    790,
    _LEFT_MARGIN + (colCount + toolWrapCols - 1) * _COL_GAP + 80,
  )

  const toolRows = Math.min(_TOOLS_PER_COL, Math.max(1, toolCount))
  const toolMaxY = _TOOL_COL_BASE_Y + (toolRows - 1) * _TOOL_ROW_GAP
  const ch = Math.max(300, toolMaxY + 50)

  return { cw, ch, cols: colCount }
}

/**
 * Assign SVG cx/cy coordinates to nodes for rendering.
 *
 * x-positions are computed by walking _FLOW_ORDER and giving each PRESENT
 * type the next column slot. Missing types collapse — no gutters. y-positions
 * come from _LANE_Y so the visual lane structure is preserved.
 *
 * Tools fan out vertically (and wrap to a second column when many) so 6-tool
 * agent flows still fit.
 *
 * @param {object[]} nodes — from lineageFromEvents
 * @returns {object[]} nodes with cx, cy added
 */
export function assignCoords(nodes) {
  const presentTypes = new Set(nodes.map(n => n.type))
  const toolCount    = nodes.filter(n => n.type === 'tool').length

  // Compute x for each present type by left-packing in flow order.
  const colX = {}
  let col = 0
  for (const t of _FLOW_ORDER) {
    if (!presentTypes.has(t)) continue
    colX[t] = _LEFT_MARGIN + col * _COL_GAP
    col++
    // Tools that wrap into 2 columns consume one extra horizontal slot so
    // policy/llm/output don't sit on top of the second tool column.
    if (t === 'tool' && toolCount > _TOOLS_PER_COL) col++
  }

  let toolIdx = 0
  return nodes.map(n => {
    let pos
    if (n.type === 'tool') {
      const subCol = Math.floor(toolIdx / _TOOLS_PER_COL)
      const subRow = toolIdx % _TOOLS_PER_COL
      pos = {
        cx: colX.tool + subCol * _COL_GAP,
        cy: _TOOL_COL_BASE_Y + subRow * _TOOL_ROW_GAP,
      }
      toolIdx++
    } else {
      pos = {
        cx: colX[n.type] ?? _LEFT_MARGIN,
        cy: _LANE_Y[n.type] ?? 150,
      }
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
