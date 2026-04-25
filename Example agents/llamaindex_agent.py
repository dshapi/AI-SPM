"""llamaindex_agent.py — pick agent_type=llamaindex in the Register dialog.

Demonstrates the LlamaIndex chat-engine idiom: in-memory document index
+ retrieval over a stuffed corpus, with the LLM call routed through the
platform's OpenAI-compatible proxy.

If LlamaIndex isn't installed in the customer image we fall back to a
hand-rolled retrieval path so the example still demonstrates the
*shape* of a LlamaIndex agent (retrieve → stuff → ask LLM). That keeps
the file runnable on the bare runtime image during smoke-testing.
"""
from __future__ import annotations

import asyncio

import aispm


# A tiny static "knowledge base" — replace with your own corpus or with
# LlamaIndex's loaders (SimpleDirectoryReader, etc.) in production.
DOCS: list[str] = [
    "AI-SPM is an AI security posture management platform.",
    "Agents are uploaded as a single Python file and run inside a "
    "sandboxed container with no outbound network except the "
    "platform-provided MCP and LLM proxies.",
    "Each agent's chat traffic flows through prompt-guard, a policy "
    "decider, and output-guard before reaching either the customer or "
    "the LLM.",
]


def _retrieve(query: str, k: int = 2) -> list[str]:
    """Tiny BM25-ish term-overlap retrieval — good enough for a demo
    and runs without any extra deps."""
    q = {t.lower() for t in query.split() if len(t) > 2}
    scored = sorted(
        DOCS,
        key=lambda d: -sum(1 for t in q if t in d.lower()),
    )
    return scored[:k]


try:
    from llama_index.core import VectorStoreIndex, Document
    from llama_index.core.settings import Settings
    from llama_index.llms.openai_like import OpenAILike

    Settings.llm = OpenAILike(
        api_base=aispm.LLM_BASE_URL,
        api_key=aispm.LLM_API_KEY,
        model="gpt-4o-mini",
        is_chat_model=True,
    )
    _index = VectorStoreIndex.from_documents([Document(text=d) for d in DOCS])
    _query_engine = _index.as_query_engine(similarity_top_k=2)

    async def _ask(question: str) -> str:
        # LlamaIndex's query engine is sync — push to a thread so we
        # don't block the event loop while the embedding call runs.
        return str(await asyncio.to_thread(_query_engine.query, question))

except Exception:   # noqa: BLE001 — fall back if llama_index isn't installed

    async def _ask(question: str) -> str:
        snippets = "\n".join(f"- {d}" for d in _retrieve(question))
        resp = await aispm.llm.complete(messages=[
            {"role": "system",
             "content": "Answer the user's question using ONLY the snippets "
                        "below. If unsure say 'I don't know'."},
            {"role": "user",
             "content": f"{question}\n\nSnippets:\n{snippets}"},
        ])
        return resp.text or "(empty reply)"


async def handle(msg) -> None:
    aispm.log("llamaindex: received", trace=msg.id, session=msg.session_id)
    try:
        text = await _ask(msg.text)
    except Exception as e:                                           # noqa: BLE001
        aispm.log("llamaindex: error", trace=msg.id, error=str(e))
        text = f"(agent error: {e})"
    await aispm.chat.reply(msg.session_id, text)
    aispm.log("llamaindex: replied", trace=msg.id, chars=len(text))


async def main() -> None:
    await aispm.ready()
    aispm.log("llamaindex_agent ready", agent_id=aispm.AGENT_ID)
    async for msg in aispm.chat.subscribe():
        asyncio.create_task(handle(msg))


if __name__ == "__main__":
    asyncio.run(main())
