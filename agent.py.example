import asyncio

import aispm


async def handle_one_message(msg):
    """Reply to a single user message. Wrapped in its own task so
    multiple users don't block each other."""
    aispm.log("received", trace=msg.id, session=msg.session_id)

    # 1. Web context — short, capped at the operator-configured limit.
    try:
        ctx = await aispm.mcp.call("web_fetch", query=msg.text, max_results=3)
    except Exception as e:
        aispm.log("web_fetch failed", trace=msg.id, error=str(e))
        ctx = {"results": []}

    # 2. Ask the LLM, with the context as a system note.
    context_text = "\n\n".join(
        f"{r.get('title','(no title)')}: {r.get('content','')[:500]}"
        for r in (ctx.get("results") or [])
    ) or "(no fresh context available)"

    try:
        resp = await aispm.llm.complete(messages=[
            {"role": "system",
             "content": "Answer the user's question concisely. "
                        "Cite the snippets below if relevant."},
            {"role": "user",
             "content": f"{msg.text}\n\nContext:\n{context_text}"},
        ])
        text = resp.text or "(empty reply)"
    except Exception as e:
        aispm.log("llm failed", trace=msg.id, error=str(e))
        text = f"(agent error: {e})"

    # 3. Reply on chat.out.
    await aispm.chat.reply(msg.session_id, text)
    aispm.log("replied", trace=msg.id, chars=len(text))


async def main():
    # Tell the controller we're up — flips runtime_state to "running".
    await aispm.ready()
    aispm.log("agent ready", agent_id=aispm.AGENT_ID)

    # Loop over user messages. Each message is handled in its own task
    # so a slow web_fetch / LLM call doesn't block other users.
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle_one_message(msg))


if __name__ == "__main__":
    asyncio.run(main())
