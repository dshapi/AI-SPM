"""autogpt_agent.py — pick agent_type=autogpt in the Register dialog.

A tiny self-prompting AutoGPT-style loop:

    1. Plan      — the LLM proposes a short bullet plan.
    2. Execute   — for each plan step the LLM either calls web_fetch
                   or answers from memory, accumulating a scratchpad.
    3. Reflect   — the LLM produces the final answer using the
                   scratchpad as evidence.

Capped at 3 plan-execute iterations per user turn so a runaway agent
can't burn the LLM budget. Output goes back over chat.reply.
"""
from __future__ import annotations

import asyncio
import json

import aispm


MAX_STEPS = 3


SYSTEM_PLAN = (
    "You are an autonomous research agent. The user gave you a task. "
    "Produce a numbered list of at most 3 short steps you'll take to "
    "answer it. Do NOT answer yet — only output the plan."
)
SYSTEM_EXEC = (
    "You are executing one step of a research plan. You can either:\n"
    "  - call the tool web_fetch by replying with EXACTLY this JSON "
    'object: {"tool":"web_fetch","query":"..."}\n'
    "  - or, if the step doesn't need fresh info, answer it directly "
    "in plain text.\n"
    "Reply with ONLY the tool JSON or the plain-text answer."
)
SYSTEM_REFLECT = (
    "You have a scratchpad of step results from your plan. Produce "
    "the final answer to the user's original question. Be concise; "
    "cite specific facts you found."
)


async def _llm(messages: list[dict]) -> str:
    resp = await aispm.llm.complete(messages=messages)
    return (resp.text or "").strip()


async def _maybe_tool(reply: str) -> str:
    """If the LLM asked for web_fetch, run it and return the result; else
    return the LLM's plain-text reply unchanged."""
    if not reply.startswith("{"):
        return reply
    try:
        obj = json.loads(reply)
    except Exception:
        return reply
    if obj.get("tool") != "web_fetch":
        return reply
    query = str(obj.get("query") or "")
    if not query:
        return reply
    try:
        ctx = await aispm.mcp.call("web_fetch", query=query, max_results=3)
    except Exception as e:                                           # noqa: BLE001
        return f"(web_fetch failed: {e})"
    return "\n".join(
        f"- {r.get('title','(no title)')}: {r.get('content','')[:300]}"
        for r in (ctx.get("results") or [])
    ) or "(no results)"


async def handle(msg) -> None:
    aispm.log("autogpt: received", trace=msg.id, session=msg.session_id)
    try:
        plan = await _llm([
            {"role": "system", "content": SYSTEM_PLAN},
            {"role": "user", "content": msg.text},
        ])
        aispm.log("autogpt: plan", trace=msg.id, plan=plan)

        # naive split into steps — drop empty / too-long lines
        steps = [
            s.lstrip("0123456789.- ").strip()
            for s in plan.splitlines()
            if 3 <= len(s.strip()) <= 200
        ][:MAX_STEPS]

        scratchpad: list[str] = []
        for i, step in enumerate(steps, 1):
            raw = await _llm([
                {"role": "system", "content": SYSTEM_EXEC},
                {"role": "user", "content":
                    f"Original task: {msg.text}\nThis step: {step}"},
            ])
            result = await _maybe_tool(raw)
            scratchpad.append(f"[step {i}] {step}\n→ {result[:600]}")
            aispm.log("autogpt: step done", trace=msg.id, step=i)

        final = await _llm([
            {"role": "system", "content": SYSTEM_REFLECT},
            {"role": "user", "content":
                f"Original task: {msg.text}\n\nScratchpad:\n"
                + "\n\n".join(scratchpad)},
        ])
    except Exception as e:                                           # noqa: BLE001
        aispm.log("autogpt: error", trace=msg.id, error=str(e))
        final = f"(agent error: {e})"

    await aispm.chat.reply(msg.session_id, final or "(empty reply)")
    aispm.log("autogpt: replied", trace=msg.id, chars=len(final))


async def main() -> None:
    await aispm.ready()
    aispm.log("autogpt_agent ready", agent_id=aispm.AGENT_ID)
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle(msg))


if __name__ == "__main__":
    asyncio.run(main())
