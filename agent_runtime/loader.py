"""Phase 2 entrypoint for the agent runtime container.

Replaces the Phase 1 stub. Steps:

  1. Import ``aispm`` so its module-level constants populate from env.
  2. ``exec_module`` the customer's ``/agent/agent.py`` so its
     top-level statements run (imports, decorators, registrations).
  3. If the customer file has a top-level ``main`` callable, call it.
     Async ``main()`` is awaited via ``asyncio.run``.

Why call main() ourselves?
──────────────────────────
Customer agents typically end with::

    if __name__ == "__main__":
        asyncio.run(main())

When we load via ``importlib.util.spec_from_file_location``, the
module's ``__name__`` is ``"agent"`` — NOT ``"__main__"``. So that
guard skips, ``main()`` never runs, and the loader exits with status 0
because there's nothing left to do. The container vanishes silently.

By detecting and calling ``main`` ourselves, we accept BOTH styles —
agents with the ``__main__`` guard AND agents that simply define
``async def main()`` — without forcing the customer to remove the
guard from their development copy.

Loader-side error handling
──────────────────────────
Uncaught exceptions in customer code are caught here, logged through
``aispm.log`` (so they land in lineage), and the loader exits with
code 1 — Docker's ``restart_policy=on-failure`` then kicks in (see
``spawn_agent_container``). Code 0 means main() completed normally,
which usually only happens for one-shot agents; long-running chat
agents loop forever via ``async for msg in aispm.chat.subscribe()``.
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
import traceback

# Importing aispm has side effects — it reads env vars into module-
# level constants. Must happen BEFORE the customer's agent.py is
# imported, since the customer code does `import aispm` and expects
# constants to already be populated.
import aispm  # noqa: F401

AGENT_FILE = "/agent/agent.py"


def _run_customer_main(mod) -> None:
    """If the customer module defined a top-level ``main`` callable,
    invoke it. Async functions are wrapped in ``asyncio.run``.

    No-op if ``main`` is missing — covers agents that did all the
    interesting work inside their import-time top-level statements
    (uncommon but valid).
    """
    main_fn = getattr(mod, "main", None)
    if main_fn is None:
        print("[loader] no top-level main() in agent.py — exiting cleanly",
              flush=True)
        return

    if not callable(main_fn):
        print(f"[loader] 'main' in agent.py is not callable: {type(main_fn)!r}",
              file=sys.stderr, flush=True)
        return

    if inspect.iscoroutinefunction(main_fn):
        print("[loader] running async main()", flush=True)
        asyncio.run(main_fn())
    else:
        print("[loader] running sync main()", flush=True)
        result = main_fn()
        # If a sync main returned a coroutine (e.g. customer wrote
        # `def main(): return some_async_thing()`), drive it.
        if inspect.iscoroutine(result):
            asyncio.run(result)


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
        _run_customer_main(mod)
    except Exception:
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
