"""Agent ↔ controller lifecycle handshake.

The Phase 1 controller used a hardcoded 5-second sleep before flipping
``runtime_state`` to ``running`` — fine for a smoke test, brittle for
real agents that take variable amounts of time to bootstrap (LangChain
loaders, model warmups, etc.).

Phase 2 replaces it with an explicit handshake:

  1. The container starts; the loader imports ``aispm`` and runs the
     customer's ``main()``.
  2. Customer calls ``await aispm.ready()`` once initialisation is done.
  3. The SDK POSTs to ``spm-api`` at ``/api/spm/agents/{id}/ready``;
     the controller updates the row to ``runtime_state=running`` and
     stamps ``last_seen_at``.
  4. The controller's ``deploy_agent`` poll sees the transition and
     returns to the upload-flow caller.

Idempotent: customers can call ``ready()`` multiple times (e.g. after
hot-reloading config) without breaking anything.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import Awaitable, Callable, Optional

import httpx

from . import (
    AGENT_ID       as _AGENT_ID,
    CONTROLLER_URL as _CONTROLLER_URL,
    MCP_TOKEN      as _MCP_TOKEN,
)

log = logging.getLogger(__name__)

# Short timeout — the controller's /ready handler is a single DB UPDATE.
_READY_TIMEOUT_S = 5.0


async def ready() -> None:
    """Notify the controller this agent is initialised and ready to
    consume chat messages.

    Failures are logged but never raised — the controller has its own
    deploy-time poll loop that will eventually time out with a clearer
    error message; we don't want a transient handshake failure to
    crash an otherwise-healthy agent.
    """
    if not _AGENT_ID:
        print("[aispm.ready] AGENT_ID env var not set; skipping handshake",
              flush=True)
        return

    # NB: NO ``/api/spm`` prefix — that's added by the Vite/Traefik
    # proxy in front of the browser. The agent container talks
    # directly to spm-api, which mounts the routes at ``/agents/...``
    # (see services/spm_api/agent_routes.py).
    url = f"{_CONTROLLER_URL}/agents/{_AGENT_ID}/ready"
    # The /ready endpoint authenticates the caller with the agent's
    # own mcp_token (proves we're the agent the controller just
    # spawned). Without it the controller answers 401 and the row
    # never flips to running.
    headers = {"Authorization": f"Bearer {_MCP_TOKEN}"} if _MCP_TOKEN else {}
    print(f"[aispm.ready] POST {url} (auth={'yes' if _MCP_TOKEN else 'NO'})",
          flush=True)
    try:
        async with httpx.AsyncClient(timeout=_READY_TIMEOUT_S) as c:
            r = await c.post(url, headers=headers)
        print(f"[aispm.ready] response {r.status_code}", flush=True)
        if r.status_code >= 400:
            print(f"[aispm.ready] controller returned {r.status_code} — "
                  f"{r.text[:200]}", flush=True)
    except httpx.HTTPError as e:
        print(f"[aispm.ready] handshake FAILED: {type(e).__name__}: {e}",
              flush=True)


# ─── Signal handling ───────────────────────────────────────────────────────

def install_signal_handlers(
    stop_callback: Callable[[], Awaitable[None]],
) -> None:
    """Wire SIGTERM / SIGINT to *stop_callback* so the agent can drain
    in-flight messages cleanly inside Docker's 10-second grace window.

    The callback is awaited from the running loop. If the loop isn't
    available (e.g. installation happens before ``asyncio.run``), we
    fall back to a synchronous wrapper that just creates a task at
    handler-fire time.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop yet — register a signal handler that schedules
        # the coroutine on whatever loop is current at fire-time.
        def _sync_wrap(*_args):
            try:
                asyncio.run(stop_callback())
            except RuntimeError:
                pass
        for s in (signal.SIGTERM, signal.SIGINT):
            signal.signal(s, _sync_wrap)
        return

    def _sched():
        loop.create_task(stop_callback())

    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(s, _sched)
