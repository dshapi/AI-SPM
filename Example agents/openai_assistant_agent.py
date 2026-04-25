"""openai_assistant_agent.py — pick agent_type=openai_assistant.

OpenAI Assistants-style agent shape using only the platform's
OpenAI-compatible LLM proxy and MCP — no SDK lock-in.

The LLM is prompted to either reply directly or emit a structured
tool_call ({"name":"web_fetch","arguments":{...}}). When the loop sees
a tool_call it runs the platform MCP tool and appends the result back
into the conversation as a tool message, exactly as an Assistant
threads loop would. Capped at 3 hops per turn so it can't run away.
"""
from __future__ import annotations

import asyncio
import json

import aispm


MAX_HOPS = 3

# Tool catalog shown to the LLM. We only expose web_fetch in this demo,
# but the same loop scales to any number of MCP tools.
TOOL_CATALOG = [
    {
        "name": "web_fetch",
        "description": "Fetch fresh web search results for a query.",
        "parameters": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 3},
            },
        },
    },
]

SYSTEM = (
    "You are an OpenAI Assistant-style helper. You can either:\n"
    "  • reply to the user directly in plain text, OR\n"
    "  • request a tool call by replying with EXACTLY a JSON object of "
    'shape {"name":"<tool>","arguments":{...}} and nothing else.\n'
    f"Available tools:\n{json.dumps(TOOL_CATALOG, indent=2)}"
)


async def _llm(messages: list[dict]) -> str:
    resp = await aispm.llm.complete(messages=messages)
    return (resp.text or "").strip()


def _maybe_parse_tool_call(reply: str) -> dict | None:
    if not reply.startswith("{"):
        return None
    try:
        obj = json.loads(reply)
    except Exception:
        return None
    if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
        return obj
    return None


async def _run_tool(call: dict) -> str:
    name = call.get("name")
    args = call.get("arguments") or {}
    if name != "web_fetch":
        return f"(unknown tool: {name})"
    try:
        ctx = await aispm.mcp.call("web_fetch", **args)
    except Exception as e:                                           # noqa: BLE001
        return f"(web_fetch failed: {e})"
    return "\n".join(
        f"- {r.get('title','(no title)')}: {r.get('content','')[:300]}"
        for r in (ctx.get("results") or [])
    ) or "(no results)"


async def handle(msg) -> None:
    aispm.log("openai_assistant: received", trace=msg.id, session=msg.session_id)
    history: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": msg.text},
    ]

    final = ""
    try:
        for hop in range(MAX_HOPS):
            reply = await _llm(history)
            call = _maybe_parse_tool_call(reply)
            if call is None:
                final = reply
                break

            aispm.log(
                "openai_assistant: tool_call",
                trace=msg.id, hop=hop, tool=call.get("name"),
            )
            tool_result = await _run_tool(call)
            # Echo the assistant's tool request and the tool result back
            # into history so the next hop can see them — same shape the
            # Assistants threads loop uses internally.
            history.append({"role": "assistant", "content": reply})
            history.append({
                "role": "user",
                "content": f"tool_result({call.get('name')}):\n{tool_result}",
            })
        else:
            # MAX_HOPS exhausted with no plain-text answer — ask once more
            # with a tightened instruction to wrap up.
            final = await _llm(history + [{
                "role": "system",
                "content": "Stop calling tools and produce the final answer now.",
            }])
    except Exception as e:                                           # noqa: BLE001
        aispm.log("openai_assistant: error", trace=msg.id, error=str(e))
        final = f"(agent error: {e})"

    await aispm.chat.reply(msg.session_id, final or "(empty reply)")
    aispm.log("openai_assistant: replied", trace=msg.id, chars=len(final))


async def main() -> None:
    await aispm.ready()
    aispm.log("openai_assistant_agent ready", agent_id=aispm.AGENT_ID)
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle(msg))


if __name__ == "__main__":
    asyncio.run(main())
