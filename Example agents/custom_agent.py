"""custom_agent.py — pick agent_type=custom in the Register dialog.

Bare-bones happy path: subscribe to chat, fetch fresh context via the
platform MCP, ask the LLM, reply. No frameworks. Easiest baseline for
verifying the platform plumbing end-to-end.

Conversation memory
───────────────────
Every user/agent turn is persisted to ``agent_chat_messages`` by the
platform's chat pipeline. Before each LLM call we fetch the last N
turns via ``aispm.chat.history(session_id, limit=...)`` and replay
them as ``role: user|assistant`` messages so the model remembers
context across turns. Without this the agent would happily forget
the user's name between back-to-back messages.
"""
import asyncio

import aispm


HISTORY_LIMIT = 20  # turns to include — tune for context window vs. cost


async def _build_history_messages(session_id):
    """Fetch the persisted conversation and shape it into the LLM
    message list. Returns ``[]`` on the first turn or if the history
    endpoint is unreachable — the agent stays usable in degraded mode."""
    try:
        prior = await aispm.chat.history(session_id, limit=HISTORY_LIMIT)
    except Exception as e:                                           # noqa: BLE001
        aispm.log("custom: history fetch failed", session=session_id, error=str(e))
        return []
    out = []
    for h in prior:
        # HistoryEntry.role is one of "user" | "agent"; LLM expects
        # "user" | "assistant".
        role = "assistant" if h.role == "agent" else "user"
        out.append({"role": role, "content": h.text})
    return out


async def handle(msg) -> None:
    aispm.log("custom: received", trace=msg.id, session=msg.session_id)
    try:
        ctx = await aispm.mcp.call("web_fetch", query=msg.text, max_results=3)
    except Exception as e:                                           # noqa: BLE001
        aispm.log("custom: web_fetch failed", trace=msg.id, error=str(e))
        ctx = {"results": []}

    raw_results = ctx.get("results") or []
    snippet_lines = [
        f"[{i+1}] {r.get('title','(no title)')} ({r.get('url','')})\n"
        f"    {r.get('content','')[:500]}"
        for i, r in enumerate(raw_results)
    ]
    have_snippets = bool(snippet_lines)
    snippets = "\n\n".join(snippet_lines) if have_snippets else "(none)"

    history = await _build_history_messages(msg.session_id)

    # Aggressive system prompt: Claude likes to disclaim "I don't have
    # real-time data" by default. We tell it explicitly that the
    # `Live web search results` block IS that real-time data, and it
    # must use it instead of refusing.
    if have_snippets:
        sys_prompt = (
            "You are a concise research assistant with conversational "
            "memory and a built-in web-search tool. The user's message "
            "below is followed by 'Live web search results' — these are "
            "fresh results from a Tavily search executed milliseconds ago, "
            "not training data. ALWAYS use these results to answer the "
            "user's question. Do NOT say you lack internet access or "
            "real-time data — you have both. Cite results inline as [1], "
            "[2] etc. Use the prior conversation turns for continuity."
        )
    else:
        sys_prompt = (
            "You are a concise assistant with conversational memory. The "
            "web-search tool returned no results for this turn (or the "
            "tool was unavailable), so answer from training knowledge — "
            "and when you're unsure or the topic needs current data, say "
            "so plainly. Use the prior conversation turns for continuity."
        )

    messages = [
        {"role": "system", "content": sys_prompt},
        *history,
        {"role": "user",
         "content": (f"{msg.text}\n\n"
                      f"Live web search results:\n{snippets}")},
    ]
    aispm.log("custom: llm call", trace=msg.id,
              history_turns=len(history), total_msgs=len(messages))

    # Streaming reply path — each token from the LLM is published to
    # chat.out as a `delta` record the moment it arrives, and spm-api
    # forwards it to the UI as one SSE token. The user sees output
    # within ~200ms of pressing Send instead of waiting for the full
    # reply to buffer.
    #
    # The `done` marker is emitted automatically when the `async with`
    # block exits — even if the LLM call raises. trace_id from the
    # inbound ChatMessage is plumbed through so audit/lineage stitches
    # the reply back to the user's turn.
    try:
        async with aispm.chat.stream(msg.session_id,
                                      trace_id=msg.trace_id) as out:
            async for chunk in aispm.llm.stream(messages=messages):
                await out.write(chunk)
    except Exception as e:                                           # noqa: BLE001
        aispm.log("custom: llm failed", trace=msg.id, error=str(e))
        # The stream context above already emitted the `done` marker
        # with finish_reason="error" via __aexit__, so spm-api closes
        # the SSE cleanly. We just need to let the user see the cause —
        # send one more reply with the error string.
        await aispm.chat.reply(
            msg.session_id,
            f"(agent error: {e})",
            trace_id=msg.trace_id,
        )
        return

    aispm.log("custom: replied", trace=msg.id)


async def main() -> None:
    await aispm.ready()
    aispm.log("custom_agent ready", agent_id=aispm.AGENT_ID)
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle(msg))


if __name__ == "__main__":
    asyncio.run(main())
