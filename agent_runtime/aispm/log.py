"""Structured agent-side logging — emits one JSON line per call to
stdout, where the docker logs shipper picks it up and republishes it
as an ``AgentLog`` lineage event (Phase 4 wires that pipeline; Phase 2
just emits, the events accumulate on disk in the meantime).

Usage:

    aispm.log("starting reasoning step", trace=msg.id, step="plan")

The line is JSON so structured-logging tools (jq, datadog, etc.) can
slice on the field set out of the box. ``agent_id`` and ``tenant_id``
are auto-injected; never include them in **fields.

Token redaction
───────────────
The wrapper actively scrubs any field whose name starts with the
suffix ``_token`` / ``_key`` / ``_secret`` so an absent-minded
``aispm.log("connecting", api_key=secret)`` doesn't ship the secret
to the lineage pipeline. The redacted version still records that the
field existed (replaces the value with ``"<redacted>"``), so debugging
still has a hook.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import AGENT_ID as _AGENT_ID, TENANT_ID as _TENANT_ID

_REDACT_SUFFIXES = ("_token", "_key", "_secret", "_password")


def _redact(fields: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in fields.items():
        if any(k.lower().endswith(suf) for suf in _REDACT_SUFFIXES):
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def log(message: str, *, trace: Optional[str] = None, **fields: Any) -> None:
    """Emit one structured log line.

    *message* is the human-readable summary. *trace* should carry the
    same identifier as the originating ``ChatMessage.id`` /
    ``trace_id`` so downstream lineage can join the agent's reasoning
    steps to the user's turn.
    """
    rec: Dict[str, Any] = {
        "ts":        datetime.now(timezone.utc).isoformat(),
        "agent_id":  _AGENT_ID,
        "tenant_id": _TENANT_ID,
        "msg":       message,
    }
    if trace is not None:
        rec["trace"] = trace
    if fields:
        rec.update(_redact(fields))

    print(json.dumps(rec, default=str), file=sys.stdout, flush=True)
