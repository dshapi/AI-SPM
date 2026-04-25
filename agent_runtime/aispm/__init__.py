"""aispm — agent-side SDK for the AI-SPM agent runtime control plane.

Customer agents ``import aispm`` to talk to the four wires the platform
exposes:

  * ``aispm.chat.subscribe() / reply() / history()``  — Kafka chat I/O
  * ``aispm.mcp.call("web_fetch", ...)``               — MCP tools over HTTP
  * ``aispm.llm.complete(messages=...)``               — OpenAI-compat LLM proxy
  * ``aispm.get_secret("MY_KEY")``                     — per-agent secrets
  * ``aispm.ready()``                                  — lifecycle handshake
  * ``aispm.log("step", trace=...)``                   — structured lineage

Connection info is read from env vars at import time. The controller
(spm-api's ``agent_controller.spawn_agent_container``) injects these
when it spawns the container — see Phase 1's spawn helper for the
canonical list. Customers MUST NOT override them.

Per spec § 8 the no-env-vars rule applies to *customer* config. The
seven values listed below are infrastructure wiring; they're injected
by the controller, not configured in the Configure tab.
"""
from __future__ import annotations

import os

# ─── Connection info (injected at container start) ─────────────────────────

AGENT_ID:       str = os.environ.get("AGENT_ID",       "")
TENANT_ID:      str = os.environ.get("TENANT_ID",      "t1")
MCP_URL:        str = os.environ.get("MCP_URL",        "")
MCP_TOKEN:      str = os.environ.get("MCP_TOKEN",      "")
LLM_BASE_URL:   str = os.environ.get("LLM_BASE_URL",   "")
LLM_API_KEY:    str = os.environ.get("LLM_API_KEY",    "")
KAFKA_BOOTSTRAP_SERVERS: str = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "",
)

# spm-api base URL — used by ``secrets.get_secret()`` and
# ``lifecycle.ready()`` to reach back to the controller. Defaults to the
# in-compose hostname; tests / non-default deploys override.
CONTROLLER_URL: str = os.environ.get(
    "CONTROLLER_URL", "http://spm-api:8092",
)


# ─── Public API surface ────────────────────────────────────────────────────
#
# Submodules are imported here so customers can write
# ``aispm.chat.subscribe()`` instead of ``aispm.chat.chat.subscribe()``.
# ``get_secret`` and ``ready`` are re-exported at the top level because
# spec § 8 documents them as ``aispm.get_secret(...)`` / ``aispm.ready()``.
#
# We import the submodules eagerly (rather than on first use) so any
# import-time side effects — env reads, kafka client construction —
# fire predictably at agent startup, before ``main()`` runs.
from . import chat, lifecycle, llm, log, mcp, secrets, types  # noqa: E402, F401
from .lifecycle import ready                                  # noqa: E402, F401
from .secrets   import get_secret                             # noqa: E402, F401

__all__ = [
    # Connection info
    "AGENT_ID",
    "TENANT_ID",
    "MCP_URL",
    "MCP_TOKEN",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "KAFKA_BOOTSTRAP_SERVERS",
    "CONTROLLER_URL",
    # Submodules
    "chat",
    "lifecycle",
    "llm",
    "log",
    "mcp",
    "secrets",
    "types",
    # Top-level helpers
    "get_secret",
    "ready",
]
