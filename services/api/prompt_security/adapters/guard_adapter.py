"""
security.adapters.guard_adapter
─────────────────────────────────
Async adapter for the Llama Guard 3 classification service.

Design
------
The adapter encapsulates the HTTP call, timeout handling, and fail-closed
logic.  It can be constructed either with a live URL (production) or with an
injectable ``guard_fn`` callable (testing / alternative backends).

Verdict policy
--------------
Trust the guard's own ``verdict`` field. The historical "any S1–S15 cat
forces block" rule was too aggressive — Llama Guard 3 routinely tags
benign one-word replies (``yes``, ``ok``) with a category like S2 while
itself returning ``verdict: "allow"`` and a low score. We only escalate
``allow → block`` when the score is above ``GUARD_BLOCK_SCORE`` (env-
tunable; default 0.6) AND there's at least one unsafe category. Pure
``allow`` with a category but a low score now passes — categories alone
are informational, not a kill-switch.

Short-input bypass
------------------
Inputs shorter than ``GUARD_MIN_TEXT_LEN`` chars (default 8) skip the
guard entirely. Conversational replies like ``yes`` / ``no`` / ``thanks``
have too little signal for the guard to reason about and produce noisy
categorisations.

Fail-closed contract:
  - HTTP timeout           → ("block", 0.5, ["timeout"])
  - Any other exception    → ("block", 0.5, ["unavailable"])
  - HTTP 4xx/5xx from guard→ ("block", 0.5, ["unavailable"])
  - Disabled guard model   → ("allow", 0.0, [])
  - Input shorter than min → ("allow", 0.0, [])
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Coroutine, List, Optional, Tuple

import httpx

log = logging.getLogger("security.guard_adapter")

# All Llama Guard 3 unsafe categories S1–S15
_ALL_UNSAFE: frozenset[str] = frozenset(f"S{i}" for i in range(1, 16))

_GUARD_BLOCK_SCORE  = float(os.environ.get("GUARD_BLOCK_SCORE",  "0.6"))
_GUARD_MIN_TEXT_LEN = int(os.environ.get("GUARD_MIN_TEXT_LEN", "8"))

# Type alias for the guard callable signature
GuardFn = Callable[[str], Coroutine[None, None, Tuple[str, float, List[str]]]]


class LlamaGuardAdapter:
    """
    Calls the Llama Guard 3 service and returns a normalised (verdict, score, categories).

    Parameters
    ----------
    guard_url : str | None
        Full base URL of the guard model service, e.g. "http://guard-model:8200".
        Ignored when *guard_fn* is provided.
    enabled : bool
        If False the adapter always returns ("allow", 0.0, []).
    timeout : float
        HTTP timeout in seconds (default 3.0).
    guard_fn : async callable | None
        Optional override: replaces the HTTP call entirely.  Signature must be
        ``async (prompt: str) -> (verdict, score, categories)``.
        Primarily for dependency injection in tests — allows existing patches
        of module-level functions to flow through.
    """

    def __init__(
        self,
        guard_url: Optional[str] = None,
        *,
        enabled: bool = True,
        timeout: float = 3.0,
        guard_fn: Optional[GuardFn] = None,
    ) -> None:
        self._url     = guard_url
        self._enabled = enabled
        self._timeout = timeout
        self._guard_fn = guard_fn   # injectable override (used in app.py wiring)

    async def evaluate(self, prompt: str) -> Tuple[str, float, List[str]]:
        """
        Classify *prompt* via Llama Guard 3.

        Returns
        -------
        (verdict, score, categories) where verdict is "allow" | "block".
        """
        # ── 1. Disabled / no URL ──────────────────────────────────────────
        if not self._enabled:
            return "allow", 0.0, []

        # ── 2. Injectable override (for test wiring) ──────────────────────
        if self._guard_fn is not None:
            return await self._guard_fn(prompt)

        if not self._url:
            log.warning("LlamaGuardAdapter: guard_url not set — failing CLOSED")
            return "block", 0.5, ["unavailable"]

        # ── 2b. Short-input bypass ────────────────────────────────────────
        # Conversational acks ("yes", "ok", "thanks") trip Llama Guard's
        # category model in a way that doesn't reflect actual risk; skip
        # the guard for inputs below the configured min length.
        if len((prompt or "").strip()) < _GUARD_MIN_TEXT_LEN:
            return "allow", 0.0, []

        # ── 3. Live HTTP call ─────────────────────────────────────────────
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/screen",
                    json={"text": prompt, "context": "user_input"},
                )
                resp.raise_for_status()
                data       = resp.json()
                verdict    = data.get("verdict", "block")    # fail-closed default
                score      = float(data.get("score", 1.0))
                categories = data.get("categories", [])

                # Only escalate "allow" → "block" when the guard's own
                # score is above the configured threshold AND a category
                # is present. Categories alone with a low score are
                # informational ("this touched on X") and shouldn't kill
                # the request — that produced false positives like
                # blocking the literal word "yes" tagged as S2.
                if (
                    verdict == "allow"
                    and categories
                    and set(categories) & _ALL_UNSAFE
                    and score >= _GUARD_BLOCK_SCORE
                ):
                    log.info(
                        "LlamaGuard: escalating allow→block on score=%.2f "
                        "categories=%s (threshold=%.2f)",
                        score, categories, _GUARD_BLOCK_SCORE,
                    )
                    verdict = "block"

                return verdict, score, categories

        except httpx.TimeoutException:
            log.warning("Llama Guard timeout — failing CLOSED")
            return "block", 0.5, ["timeout"]
        except Exception as exc:
            log.warning("Llama Guard unavailable: %s — failing CLOSED", exc)
            return "block", 0.5, ["unavailable"]
