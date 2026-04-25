"""Phase 1 stub entrypoint for the agent runtime container.

The Phase 1 backend can spawn agent containers and verify the
spawn pathway end-to-end without yet shipping the ``aispm`` SDK.
This stub:

  1. Echoes the env vars the controller injected (AGENT_ID, MCP_URL,
     LLM_BASE_URL, KAFKA_BOOTSTRAP_SERVERS, …) so logs from
     ``docker logs agent-{id}`` show the wiring is correct.
  2. Stays alive for ~10 minutes so orchestration tests can observe
     the container in ``running`` state.

Phase 2 replaces this with the real loader that imports
``/agent/agent.py`` (bind-mounted), exposes the ``aispm`` SDK, and
hands control to the customer's ``async def main()``.
"""
from __future__ import annotations

import os
import sys
import time

EXPECTED_ENV = (
    "AGENT_ID",
    "TENANT_ID",
    "MCP_URL",
    "MCP_TOKEN",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "KAFKA_BOOTSTRAP_SERVERS",
)


def _redact(name: str, value: str) -> str:
    """Print full env values except secrets — never log MCP_TOKEN /
    LLM_API_KEY in cleartext. Phase 2 lineage logging keeps the same
    redaction shape."""
    if name in {"MCP_TOKEN", "LLM_API_KEY"}:
        if not value:
            return "<empty>"
        return f"{value[:4]}…{value[-4:]} ({len(value)} chars)"
    return value or "<unset>"


def main() -> int:
    print("[stub-runtime] Phase 1 stub starting", flush=True)
    for name in EXPECTED_ENV:
        val = os.environ.get(name, "")
        print(f"[stub-runtime] {name}={_redact(name, val)}", flush=True)
    sys.stdout.flush()

    # Stay running so docker reports `running` long enough for orchestration
    # tests to observe state. 10 minutes is plenty for any reasonable
    # smoke test, after which the controller's stop_agent should fire
    # and replace this with a graceful exit.
    time.sleep(600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
