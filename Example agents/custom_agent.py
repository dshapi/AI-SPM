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

    try:
        resp = await aispm.llm.complete(messages=messages)
        text = resp.text or "(empty reply)"
    except Exception as e:                                           # noqa: BLE001
        aispm.log("custom: llm failed", trace=msg.id, error=str(e))
        text = f"(agent error: {e})"

    await aispm.chat.reply(msg.session_id, text)
    aispm.log("custom: replied", trace=msg.id, chars=len(text))


async def main() -> None:
    await aispm.ready()
    aispm.log("custom_agent ready", agent_id=aispm.AGENT_ID)
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle(msg))


if __name__ == "__main__":
    asyncio.run(main())
