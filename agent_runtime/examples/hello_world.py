"""Hello-world agent — spec §8 bare-minimum example.

Demonstrates the full SDK surface in ~10 lines:

  - aispm.ready()      — handshake the controller
  - aispm.chat.subscribe()  — async iterator over user messages
  - aispm.mcp.call("web_fetch", ...) — call a platform tool
  - aispm.llm.complete(messages=...) — call the LLM proxy
  - aispm.chat.reply(...) — send the response back to the user

Upload this via POST /api/spm/agents (Phase 1) with deploy_after=true
and chat with it from the UI / API.
"""
import asyncio

import aispm


async def main() -> None:
    await aispm.ready()
    async for msg in aispm.chat.subscribe():
        ctx  = await aispm.mcp.call("web_fetch", query=msg.text)
        resp = await aispm.llm.complete(messages=[
            {"role": "system", "content": "Answer using the context."},
            {"role": "user",   "content": f"{msg.text}\n\nContext: {ctx}"},
        ])
        await aispm.chat.reply(msg.session_id, resp.text)


if __name__ == "__main__":
    asyncio.run(main())
