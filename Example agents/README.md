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
