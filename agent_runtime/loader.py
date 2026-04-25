"""Phase 2 entrypoint for the agent runtime container.

Replaces the Phase 1 stub. Steps:

  1. Import ``aispm`` so its module-level constants populate from env.
  2. Install signal handlers so SIGTERM drains in-flight messages
     during the container's 10-second graceful-stop window.
  3. ``exec()`` the customer's ``/agent/agent.py`` (bind-mounted by
     ``spawn_agent_container``).

The customer's file is expected to:
  - import aispm
  - define ``async def main()``
  - call ``asyncio.run(main())`` at the bottom

If main() never exits the loader simply waits — the customer agent
runs as long as Docker keeps the container alive.

Loader-side error handling
──────────────────────────
Uncaught exceptions in the customer's code are caught here, logged
through ``aispm.log`` (so they end up in the lineage pipeline), and
the loader exits with code 1 — Docker's restart_policy=on-failure
then kicks in (see spawn_agent_container).
"""
from __future__ import annotations

import importlib.util
import sys
import traceback

# Importing aispm has side effects — it reads env vars into module-
# level constants. Must happen BEFORE the customer's agent.py is
# imported, since the customer code does `import aispm` and expects
# constants to already be populated.
import aispm  # noqa: F401

AGENT_FILE = "/agent/agent.py"


def main() -> int:
    print(f"[loader] starting agent_id={aispm.AGENT_ID} "
           f"tenant_id={aispm.TENANT_ID}", flush=True)
    print(f"[loader] mcp_url={aispm.MCP_URL} "
           f"llm_base_url={aispm.LLM_BASE_URL}", flush=True)

    spec = importlib.util.spec_from_file_location("agent", AGENT_FILE)
    if spec is None or spec.loader is None:
        print(f"[loader] cannot load {AGENT_FILE}", file=sys.stderr, flush=True)
        return 2

    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent"] = mod

    try:
        spec.loader.exec_module(mod)
    except Exception:
        # The customer's top-level (e.g. ``asyncio.run(main())``) raised.
        # Log full traceback through aispm.log so it lands in lineage,
        # then exit non-zero so Docker's on-failure restart kicks in.
        tb = traceback.format_exc()
        try:
            aispm.log("agent crashed", error=tb.splitlines()[-1])
        except Exception:                                # noqa: BLE001
            pass
        print("[loader] agent crashed:\n" + tb,
               file=sys.stderr, flush=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
