"""aispm — agent-side SDK for the AI-SPM agent runtime control plane.

Customer agents ``import aispm`` to talk to the four wires the platform
exposes:

  * ``aispm.chat.subscribe() / reply() / history()``  — Kafka chat I/O
  * ``aispm.mcp.call("web_fetch", ...)``               — MCP tools over HTTP
  * ``aispm.llm.complete(messages=...)``               — OpenAI-compat LLM proxy
  * ``aispm.get_secret("MY_KEY")``                     — per-agent secrets
  * ``aispm.ready()``                                  — lifecycle handshake
  * ``aispm.log("step", trace=...)``                   — structured lineage

DB-backed bootstrap
───────────────────
The SDK reads its connection info from the **controller** (which reads
the DB), not from container env vars. Three identity-bootstrap values
must come in as env vars because we have nothing to authenticate with
otherwise:

    AGENT_ID         — the agent's UUID, also our identity
    MCP_TOKEN        — the bearer that proves we are this agent
    CONTROLLER_URL   — where to reach spm-api

Everything else (``TENANT_ID``, ``MCP_URL``, ``LLM_BASE_URL``,
``LLM_API_KEY``, ``KAFKA_BOOTSTRAP_SERVERS``) is fetched on first import
from ``GET ${CONTROLLER_URL}/agents/${AGENT_ID}/bootstrap`` and exposed
as module-level constants for back-compat with code that already reads
them as ``aispm.MCP_URL`` etc.

If the bootstrap call fails (controller unreachable, expired token,
agent not found) the SDK falls back to env vars for the same names —
that keeps ``pytest`` runs and the smoke harness working without
spinning up a controller.
"""
from __future__ import annotations

import logging
import os
from typing import Dict

_boot_log = logging.getLogger("aispm.bootstrap")


# ─── Identity-bootstrap (the only env vars we read) ───────────────────────

AGENT_ID:        str = os.environ.get("AGENT_ID",       "")
MCP_TOKEN:       str = os.environ.get("MCP_TOKEN",      "")
CONTROLLER_URL:  str = os.environ.get(
    "CONTROLLER_URL", "http://spm-api:8092",
)


# ─── Connection bundle (filled from the DB-backed /bootstrap call) ─────────
#
# Defaults are empty strings; the call below populates them. Tests that
# don't have a controller can monkey-patch these or set the matching env
# vars before importing — the fallback path picks them up.

TENANT_ID:               str = ""
MCP_URL:                 str = ""
LLM_BASE_URL:            str = ""
LLM_API_KEY:             str = ""
KAFKA_BOOTSTRAP_SERVERS: str = ""


def _fetch_bootstrap_from_controller() -> Dict[str, str]:
    """Synchronously fetch the agent's connection bundle from spm-api.

    Returns ``{}`` on any failure — caller decides what to do (we fall
    back to env vars). Kept blocking so it runs at module-import time
    *before* any asyncio loop is set up; the agent's ``main()`` is not
    yet running so a 1–2s blocking call here is fine.

    All status output goes through ``print(..., flush=True)`` (not
    ``logging``) so ``docker logs`` reliably captures it — Python's
    default logging config in a fresh container drops WARNING below
    propagation if no handlers are attached.
    """
    if not (AGENT_ID and CONTROLLER_URL and MCP_TOKEN):
        print(
            f"[aispm.bootstrap] skipped — identity env not set "
            f"(AGENT_ID={'set' if AGENT_ID else 'EMPTY'}, "
            f"CONTROLLER_URL={'set' if CONTROLLER_URL else 'EMPTY'}, "
            f"MCP_TOKEN={'set' if MCP_TOKEN else 'EMPTY'})",
            flush=True,
        )
        return {}
    try:
        import httpx  # local import — keeps base image slim if unused
    except Exception as e:
        print(f"[aispm.bootstrap] httpx import failed: {e}", flush=True)
        return {}
    url = f"{CONTROLLER_URL.rstrip('/')}/agents/{AGENT_ID}/bootstrap"
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {MCP_TOKEN}"},
            timeout=5.0,
        )
        if r.status_code != 200:
            print(
                f"[aispm.bootstrap] controller {url} returned "
                f"HTTP {r.status_code}: {r.text[:200]}",
                flush=True,
            )
            return {}
        data = r.json()
        out = {str(k): ("" if v is None else str(v)) for k, v in data.items()}
        print(
            "[aispm.bootstrap] OK — "
            f"tenant={out.get('tenant_id','')!r} "
            f"mcp={out.get('mcp_url','')!r} "
            f"llm={out.get('llm_base_url','')!r} "
            f"kafka={out.get('kafka_bootstrap_servers','')!r}",
            flush=True,
        )
        return out
    except Exception as e:                                 # noqa: BLE001
        print(f"[aispm.bootstrap] {url} unreachable: {type(e).__name__}: {e}",
              flush=True)
        return {}


def _hydrate_from_bootstrap() -> None:
    """Populate the module-level connection constants.

    Order of precedence:
      1. Value from the controller's /bootstrap response (DB-backed).
      2. Value from the matching environment variable (tests / dev).
      3. Empty string.
    """
    global TENANT_ID, MCP_URL, LLM_BASE_URL, LLM_API_KEY, KAFKA_BOOTSTRAP_SERVERS
    bundle = _fetch_bootstrap_from_controller()

    def _pick(bundle_key: str, env_key: str) -> str:
        v = bundle.get(bundle_key) or os.environ.get(env_key) or ""
        return v.strip()

    TENANT_ID               = _pick("tenant_id",               "TENANT_ID")
    MCP_URL                 = _pick("mcp_url",                 "MCP_URL")
    LLM_BASE_URL            = _pick("llm_base_url",            "LLM_BASE_URL")
    LLM_API_KEY             = _pick("llm_api_key",             "LLM_API_KEY")
    KAFKA_BOOTSTRAP_SERVERS = _pick(
        "kafka_bootstrap_servers", "KAFKA_BOOTSTRAP_SERVERS",
    )


# Run the bootstrap eagerly at import time so submodule imports below
# (which read these constants while constructing httpx / kafka clients)
# see populated values.
_hydrate_from_bootstrap()

# Loud diagnostic print — first thing the operator sees in `docker logs
# agent-<id>`. If any of MCP_URL / LLM_BASE_URL / KAFKA_BOOTSTRAP_SERVERS
# are empty, the agent will crash a few lines later when
# chat.subscribe() / mcp.call() / llm.complete() try to connect. Surface
# that here, plainly, before main() even runs.
print(
    "[aispm] config: "
    f"AGENT_ID={AGENT_ID!r} "
    f"TENANT_ID={TENANT_ID!r} "
    f"MCP_URL={MCP_URL!r} "
    f"LLM_BASE_URL={LLM_BASE_URL!r} "
    f"KAFKA={KAFKA_BOOTSTRAP_SERVERS!r} "
    f"CONTROLLER_URL={CONTROLLER_URL!r}",
    flush=True,
)
_missing = [n for n, v in (
    ("MCP_URL", MCP_URL),
    ("LLM_BASE_URL", LLM_BASE_URL),
    ("KAFKA_BOOTSTRAP_SERVERS", KAFKA_BOOTSTRAP_SERVERS),
) if not v]
if _missing:
    print(
        "[aispm] WARNING: missing config values: "
        f"{', '.join(_missing)} — this agent will crash when those "
        "wires are exercised. Check that GET /agents/{id}/bootstrap "
        "returned them.",
        flush=True,
    )


# ─── Public API surface ────────────────────────────────────────────────────
#
# Submodules are imported here so customers can write
# ``aispm.chat.subscribe()`` instead of ``aispm.chat.chat.subscribe()``.
# ``get_secret`` and ``ready`` are re-exported at the top level because
# spec § 8 documents them as ``aispm.get_secret(...)`` / ``aispm.ready()``.
from . import chat, lifecycle, llm, mcp, secrets, types  # noqa: E402, F401
from . import log as _log_module                          # noqa: E402  — submodule
from .lifecycle import ready                              # noqa: E402, F401
from .log       import log                                # noqa: E402, F401  — function
from .secrets   import get_secret                         # noqa: E402, F401
# Customers may have written either ``aispm.log("msg")`` (the function,
# per spec § 8) or ``aispm.log.log("msg")`` (sub-module access). The
# function-form takes precedence because it's the documented public
# API; the sub-module form keeps working via ``aispm._log_module`` if
# anyone needs to introspect the module itself.

__all__ = [
    # Identity-bootstrap (env vars)
    "AGENT_ID",
    "MCP_TOKEN",
    "CONTROLLER_URL",
    # DB-backed connection bundle
    "TENANT_ID",
    "MCP_URL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "KAFKA_BOOTSTRAP_SERVERS",
    # Submodules
    "chat",
    "lifecycle",
    "llm",
    "log",          # the function — see _log_module for the submodule
    "mcp",
    "secrets",
    "types",
    # Top-level helpers
    "get_secret",
    "ready",
]
