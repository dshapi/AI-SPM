# Agent chat streams as a single chunk, not token-by-token

**Filed:** 2026-04-29
**Status:** known gap, deferred — bundle with the Kafka-bridge work
([runtime-page-chat-sessions.md](./runtime-page-chat-sessions.md))
since both touch the chat round-trip path.
**Severity:** UX — chat works, but the user waits for the full reply
before seeing anything. Long replies feel broken.

---

## Symptom

When the user chats with a custom agent in the UI, the assistant's reply
appears all at once after a noticeable pause. Other LLM products
(claude.ai, ChatGPT) stream token-by-token with sub-second
time-to-first-token; ours has zero TTFT visibility because nothing
renders until the full reply is buffered.

## Current data flow (single-chunk)

```
UI (POST /agents/{id}/chat)
   │
   ▼
spm-api  agent_chat.chat_endpoint
   │     produces to Kafka topics.chat_in (one message: full prompt)
   ▼
Kafka cpm.t1.chat_in
   │
   ▼
Agent pod (custom agent.py)
   │ 1. Receives full prompt from chat_in
   │ 2. Calls spm-llm-proxy /v1/chat/completions
   │    → currently NON-streaming: waits for the full completion
   │ 3. Produces the full response to chat_out (one message)
   ▼
Kafka cpm.t1.chat_out
   │
   ▼
spm-api consumes from chat_out (full reply in one frame)
   │
   ▼
UI gets one SSE event with the full reply
```

Two boundaries buffer the full reply before any token reaches the user:

1. **Agent → spm-llm-proxy call** is non-streaming.
2. **Agent → Kafka `chat_out`** publishes a single record with the
   final string.

## Target data flow (streaming)

```
UI (chat over SSE / WebSocket — already supported on the receive side)
   ▲
   │ token chunks arrive incrementally, rendered as they come
   │
spm-api  agent_chat.chat_endpoint
   ▲     consumes chat_out_chunks, forwards each to the open SSE/WS
   │
Kafka cpm.t1.chat_out_chunks  (or reuse cpm.t1.chat_out with a chunk schema)
   ▲     each Kafka record is one delta:
   │       { type: "delta", text: "...", index: N, session_id, trace_id }
   │     followed by:
   │       { type: "done",  finish_reason: "stop", session_id, trace_id }
   │
Agent pod
   │ 1. Receives full prompt from chat_in (unchanged)
   │ 2. Calls spm-llm-proxy with `stream: true`
   │ 3. For each SSE chunk: produces a delta to chat_out_chunks
   │ 4. On stream close: produces a `done` marker
   ▼
spm-llm-proxy /v1/chat/completions stream=true
   (already OpenAI-compatible — Ollama backend supports streaming
    out of the box)
```

## Pieces to change

### 1. `services/spm_api/agent_chat.py` — server side of the SSE

Currently the endpoint reads the *complete* `chat_out` message and
returns it as a single SSE event. New behavior:

- Subscribe to `cpm.t1.chat_out_chunks` filtered by `session_id`.
- For each `delta` record, emit `event: delta\ndata: {"text": "..."}`
  on the SSE stream immediately.
- On `done`, emit `event: done\ndata: {...}` and close the stream.
- Existing `_save_message(role="assistant")` happens once at `done` —
  with the concatenated full text — so the DB still has the canonical
  reply.

### 2. Custom agent runtime — `agent_runtime/aispm/llm.py`

The runtime's `complete()` already speaks OpenAI-compat. Add a
`stream()` async generator:

```python
async def stream(messages, *, model=None, max_tokens=None, **kw):
    body = {
        "model": model or _DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        async with c.stream("POST", f"{_BASE_URL}/chat/completions",
                             json=body, headers=headers) as r:
            _raise_for_status_with_detail(r)
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    return
                obj = json.loads(data)
                delta = obj["choices"][0]["delta"].get("content")
                if delta:
                    yield delta
```

### 3. Custom agent — `agent_runtime/aispm/chat.py`

Replace the single `producer.send(chat_out, full_reply)` with a loop
over `llm.stream()`:

```python
async for chunk in llm.stream(messages, ...):
    await producer.send_and_wait(
        topics.chat_out_chunks,
        value={
            "type": "delta",
            "session_id": session_id,
            "trace_id": trace_id,
            "text": chunk,
            "index": idx,
        },
        key=session_id.encode(),
    )
    idx += 1

await producer.send_and_wait(
    topics.chat_out_chunks,
    value={"type": "done", "session_id": session_id, "trace_id": trace_id},
    key=session_id.encode(),
)
```

### 4. Topic registry — `platform_shared/topics.py`

Add a per-tenant chunk topic. Single-partition keyed by `session_id`
to preserve order:

```python
@dataclass
class TenantTopics:
    ...
    chat_out_chunks: str  # cpm.<tenant>.chat_out_chunks
```

The startup-orchestrator already auto-creates every topic listed in
the registry, so adding one entry there is enough — no Kafka
admin step needed.

### 5. UI — `ui/src/admin/api/spm.js` chat fetch

The UI's chat handler already supports SSE for the simulator stream
(`event: delta` / `event: done`). Mirror that contract for the agent
chat: switch from `await fetch(...).json()` to an `EventSource` (or
`fetch` + `ReadableStream` reader) and append `delta.text` to the
displayed message as it arrives.

### 6. Audit topic stays unchanged

Audit / lineage events still go to `cpm.t1.audit` once per chat turn,
not per chunk. The Runtime page (after option C lands) will see one
session row per chat turn — chunks are an implementation detail of
the transport, not a separate event class.

## Why bundle with option C (Runtime-page bridge)?

Both touch the same boundary (`agent_chat.py` + agent runtime's
chat loop) and both want to be tested with the same end-to-end
"send a chat, watch the dashboard" workflow. Doing them in one PR
means:

- One round of agent-image rebuilds.
- One round of integration tests for the chat path.
- The Kafka-bridge consumer (option C) already has to listen to the
  audit topic; while we're adding consumers to
  agent-orchestrator-service we can also add a chunk-aggregator that
  collects deltas → final-reply (useful for logging long completions
  to `session_events.payload` without storing every token).

## Risks / things to think through before implementing

- **Order preservation across partitions.** If `chat_out_chunks` has
  multiple partitions, the consumer can interleave deltas from
  different sessions but MUST not reorder deltas within a session.
  Keying by `session_id` solves this — Kafka guarantees per-key order
  within a partition, and a key always lands on the same partition.

- **Backpressure.** A slow UI client should not stall the agent's
  Kafka producer. The producer's `acks=1` + reasonable buffer size
  should handle this; the consumer-side SSE just drops the connection
  if the client falls too far behind (Existing `ws_buffer_full —
  dropping oldest` log-warn pattern from spm-api applies here too —
  reuse the same pattern).

- **Cancellation.** If the user closes the chat tab mid-stream, the
  agent should stop calling the LLM (don't waste tokens). The chat
  endpoint can publish a `cancel` marker on `chat_in` for the
  matching `session_id`; the agent listens on `chat_in` for both
  user messages and cancellation events.

- **Backwards compatibility.** Old agents (built before the streaming
  contract) will keep producing single-chunk replies on `chat_out`.
  Keep the old code path alive in spm-api for one release: if the
  first event on `chat_out_chunks` doesn't arrive within ~1s, fall
  back to consuming `chat_out` for that session_id.

## Out of scope for this commit

- Implementation — deferred.
- UI redesign — chat UI keeps the same shape, just renders deltas
  incrementally.
- Token-level cost accounting per chunk — the LLM proxy already
  reports usage in the final SSE event from upstream; carry that
  through the `done` marker, no per-chunk accounting needed.

## References

- `services/spm_api/agent_chat.py` — current chat endpoint
- `agent_runtime/aispm/llm.py:complete()` — current non-streaming
  call to spm-llm-proxy
- `agent_runtime/aispm/chat.py` — chat loop on the agent side
- `platform_shared/topics.py` — Kafka topic registry
- `services/spm_llm_proxy/main.py` — proxy already passes `stream:
  true` through to Ollama / Anthropic / Groq when callers ask for it
- `ui/src/admin/api/spm.js` — chat fetch
- [runtime-page-chat-sessions.md](./runtime-page-chat-sessions.md) —
  sibling gap; bundle PRs.
