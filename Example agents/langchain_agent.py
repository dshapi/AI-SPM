"""langchain_agent.py — pick agent_type=langchain in the Register dialog.

Uses LangChain's tool-calling AgentExecutor on top of our LLM proxy and
exposes `web_fetch` as a LangChain `@tool` that hits the platform MCP.

Customer requirements.txt for this agent should pin:
    langchain
    langchain-openai
The platform-provided runtime image only ships the SDK + transport deps
to keep the base image small; the SDK loader will surface an ImportError
if those packages aren't installed in the customer image.
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
    """Search the web via the platform MCP (Tavily under the hood)."""
    return await aispm.mcp.call("web_fetch", query=query)


prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a research assistant. Use web_fetch when you need fresh "
     "facts; otherwise answer directly. Be concise."),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

executor = AgentExecutor(
    agent=create_tool_calling_agent(llm, [web_fetch], prompt),
    tools=[web_fetch],
)


async def handle(msg) -> None:
    aispm.log("langchain: received", trace=msg.id, session=msg.session_id)
    try:
        result = await executor.ainvoke({"input": msg.text})
        await aispm.chat.reply(msg.session_id, result["output"])
    except Exception as e:                                           # noqa: BLE001
        aispm.log("langchain: error", trace=msg.id, error=str(e))
        await aispm.chat.reply(msg.session_id, f"(agent error: {e})")


async def main() -> None:
    await aispm.ready()
    aispm.log("langchain_agent ready", agent_id=aispm.AGENT_ID)
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle(msg))


if __name__ == "__main__":
    asyncio.run(main())
