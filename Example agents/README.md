# Example Agents

One ready-to-deploy `agent.py` per `agent_type` enum value. Each file is a
complete, working agent — upload it via the Inventory → Agents → Register
button, pick the matching **Type** from the dropdown, and chat with it
once the runtime flips to **running**.

| File                        | Pick this Type      | What it shows |
|-----------------------------|---------------------|---------------|
| `langchain_agent.py`        | `langchain`         | Off-the-shelf LangChain `AgentExecutor` + `@tool` calling our MCP / LLM proxies |
| `llamaindex_agent.py`       | `llamaindex`        | LlamaIndex chat-engine pattern routed through `aispm.llm` |
| `autogpt_agent.py`          | `autogpt`           | Self-prompting plan → execute → reflect loop, capped at 3 steps per turn |
| `openai_assistant_agent.py` | `openai_assistant`  | Direct OpenAI Assistants-style request shape (system + user + tools), no framework |
| `custom_agent.py`           | `custom`            | Bare `aispm` SDK — minimal happy path, easiest to reason about |

## How to test one

1. Open the UI → **Inventory** → **Agents** tab → **Register Asset**.
2. Drop the `.py` file in.
3. Set **Type** to the matching value from the table above.
4. Click **Register & Deploy**.
5. Wait for runtime state to flip to **running** (~5–15 s on first deploy).
6. Click **Open Chat** and send a question.

All five agents share the same SDK surface (`aispm.ready()`,
`aispm.chat.subscribe()` / `aispm.chat.reply()`, `aispm.mcp.call(...)`,
`aispm.llm.complete(...)`). They differ only in **how** they orchestrate
the LLM call — that's what each `agent_type` is meant to convey to the
operator looking at Inventory.

## What's baked into the runtime image

As of Phase 4.5 the platform-provided runtime image includes:

- `aiokafka`, `httpx`, `pydantic` — SDK transport deps
- `langchain` 0.3.\*, `langchain-openai` 0.2.\* — so
  `langchain_agent.py` works without bringing your own image
- `llama-index-core` 0.11.\*,
  `llama-index-llms-openai-like` 0.2.\* — same for `llamaindex_agent.py`

Customer agents that need additional packages (e.g. a vector DB client,
a domain-specific tool library) currently need to fork the runtime
Dockerfile or wait for the per-agent `requirements.txt` lift planned
for V2. For the five examples here, no extra setup is needed.

## Watching what happens

After you send a chat:

1. The reply streams back into the chat panel.
2. Click **View Detail** in the right-side preview panel → **Activity**
   tab. The timeline (auto-refresh every 5 s) shows:
   - User and agent chat turns
   - `Tool · web_fetch` rows with duration_ms (emitted by spm-mcp)
   - `LLM · <model>` rows with prompt + completion token counts
     (emitted by spm-llm-proxy)

That timeline is the easiest way to see whether `web_fetch` is
actually being called and which model is responding — useful when
debugging why an agent isn't using the search tool the way you
expected.
