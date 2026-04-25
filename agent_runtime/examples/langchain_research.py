"""LangChain research agent — spec §8 LangChain example.

Demonstrates that the platform's OpenAI-compatible LLM proxy and HTTP
MCP server compose cleanly with off-the-shelf agent frameworks. The
customer's `requirements.txt` for this agent would include
`langchain langchain-openai`; the platform-provided runtime image
ships only the SDK + transport deps to keep the base image small.

Concurrent sessions
───────────────────
The example uses ``asyncio.create_task`` so one slow research request
doesn't block other users.
"""
import asyncio

import aispm
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI


llm = ChatOpenAI(
    base_url=aispm.LLM_BASE_URL,
    api_key=aispm.LLM_API_KEY,
)


@tool
async def web_fetch(query: str) -> str:
    """Search the web via Tavily and return the top results."""
    return await aispm.mcp.call("web_fetch", query=query)


prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a research assistant. Use web_fetch when you "
               "need fresh facts."),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

executor = AgentExecutor(
    agent=create_tool_calling_agent(llm, [web_fetch], prompt),
    tools=[web_fetch],
)


async def handle(msg) -> None:
    """Handle one user message in its own task so concurrent users
    don't block each other."""
    try:
        result = await executor.ainvoke({"input": msg.text})
        await aispm.chat.reply(msg.session_id, result["output"])
    except Exception as e:                       # noqa: BLE001
        aispm.log("agent error", trace=msg.id, error=str(e))
        await aispm.chat.reply(
            msg.session_id, f"(agent error: {e})",
        )


async def main() -> None:
    await aispm.ready()
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle(msg))


if __name__ == "__main__":
    asyncio.run(main())
