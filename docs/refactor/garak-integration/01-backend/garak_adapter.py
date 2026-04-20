"""
services/garak/adapter.py   (v2.1 — correctness audit)
──────────────────────────────────────────────────────
Attempt-capture adapter around the Garak probe execution boundary.

What changed in v2.1
────────────────────
* No sequence assignment.  Sequence is an envelope concern owned by the
  orchestrator.  ``drain()`` returns attempts in capture order with no
  sequence field — matching the v2.1 schema.
* ``model_invoked`` is explicit: True iff the pipeline actually reached
  the model (i.e. guard allowed and a response was returned).
* ``probe_raw`` preserves the operator-supplied string before registry
  normalisation.  The UI needs this to distinguish "I asked for X but
  the backend ran Y".
* Missing policy metadata → ``make_unresolved_policy()`` from the schema
  module.  NEVER invent ``{probe}_default_policy`` names.
* Threshold is carried through when the pipeline returns one; otherwise
  0.5 as a documented default (the schema requires a value 0..1).
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
import time
import uuid
from typing import Any

# When merging, replace with platform_shared.simulation.*
from platform_shared.simulation.attempts import (
    Attempt,
    AttemptMeta,
    AttemptResult,
    AttemptStatus,
    GuardAction,
    GuardDecision,
    make_unresolved_policy,
)
from platform_shared.simulation.probe_registry import ProbeIdentity

log = logging.getLogger("garak_runner.adapter")


# ── Risk-score mapping (unchanged) ───────────────────────────────────────────

def _risk_score(score: float, *, blocked: bool, errored: bool) -> int:
    if errored:
        return 0
    score = max(0.0, min(1.0, float(score or 0.0)))
    base = int(round(score * 100))
    return max(base, 50) if blocked else base


# ── Capturing generator ──────────────────────────────────────────────────────

class CapturingGenerator:
    """Wraps the CPMPipelineGenerator and records an Attempt per call."""

    # Garak compat surface
    name                       = "capturing"
    generations                = 1
    max_tokens                 = 512
    temperature                = 1.0
    parallel_attempts          = 1
    max_workers                = 1
    soft_generations           = 1
    buff_count                 = 0
    extended_detectors: list   = []
    supports_multiple_generations = False

    def __init__(
        self,
        inner: Any,
        *,
        session_id:    uuid.UUID,
        probe_identity: ProbeIdentity,
        probe_raw:     str,
        profile:       str = "",
    ) -> None:
        self._inner          = inner
        self._session_id     = session_id
        self._probe_identity = probe_identity
        self._probe_raw      = probe_raw
        self._profile        = profile
        self._attempts: list[Attempt] = []
        self._lock           = threading.RLock()

    # ── Garak generator surface ──────────────────────────────────────────────

    def generate(self, prompt: Any, generations_this_call: int = 1) -> list[str]:
        prompt_str = self._inner._to_str(prompt) if hasattr(self._inner, "_to_str") else str(prompt)
        started_at = _dt.datetime.now(_dt.timezone.utc)
        t0         = time.perf_counter()

        responses: list[str] = []
        guard_meta: dict[str, Any] = {}
        error_msg: str | None = None
        try:
            responses = self._inner.generate(prompt, generations_this_call) or []
            if hasattr(self._inner, "get_meta"):
                guard_meta = self._inner.get_meta(prompt_str) or {}
        except Exception as exc:
            log.exception("CapturingGenerator: inner.generate failed: %s", exc)
            error_msg = str(exc)

        latency_ms   = int((time.perf_counter() - t0) * 1000)
        completed_at = _dt.datetime.now(_dt.timezone.utc)

        attempt = self._build_attempt(
            prompt_str   = prompt_str,
            response     = responses[0] if responses else None,
            guard_meta   = guard_meta,
            started_at   = started_at,
            completed_at = completed_at,
            latency_ms   = latency_ms,
            error_msg    = error_msg,
        )
        with self._lock:
            self._attempts.append(attempt)

        # Garak still expects at least one string response.
        return responses or [""]

    # Delegated compat shims
    def _call_model(self, prompt: Any, generations_this_call: int = 1) -> list[str]:
        return self.generate(prompt, generations_this_call)

    def clear_history(self) -> None:
        if hasattr(self._inner, "clear_history"): self._inner.clear_history()

    def set_system_prompt(self, system_prompt: str) -> None:
        if hasattr(self._inner, "set_system_prompt"): self._inner.set_system_prompt(system_prompt)

    def encode(self, text: str) -> list:
        return self._inner.encode(text) if hasattr(self._inner, "encode") else []

    def decode(self, tokens: Any) -> str:
        return self._inner.decode(tokens) if hasattr(self._inner, "decode") else str(tokens)

    def get_history(self) -> list:
        return self._inner.get_history() if hasattr(self._inner, "get_history") else []

    def get_num_params(self) -> int:
        return self._inner.get_num_params() if hasattr(self._inner, "get_num_params") else 0

    def get_context_len(self) -> int:
        return self._inner.get_context_len() if hasattr(self._inner, "get_context_len") else 4096

    # ── Drain (no sequence assignment — orchestrator owns that) ───────────────

    def drain(self) -> list[Attempt]:
        with self._lock:
            out = list(self._attempts)
            self._attempts.clear()
            return out

    # ── Attempt construction ─────────────────────────────────────────────────

    def _build_attempt(
        self,
        *,
        prompt_str: str,
        response: str | None,
        guard_meta: dict[str, Any],
        started_at: _dt.datetime,
        completed_at: _dt.datetime,
        latency_ms: int,
        error_msg: str | None,
    ) -> Attempt:
        raw_action  = (guard_meta.get("guard_verdict") or "").lower()
        guard_score = float(guard_meta.get("guard_score") or 0.0)
        reason      = guard_meta.get("guard_reason") or ""
        policy_id   = guard_meta.get("policy_id")   or guard_meta.get("blocked_by") or ""
        policy_name = guard_meta.get("policy_name") or ""
        threshold   = float(guard_meta.get("threshold") or 0.5)

        # ── Decide whether a guard actually ran ───────────────────────────────
        guard_ran = raw_action in ("block", "allow", "review", "error")

        if not guard_ran:
            decision: GuardDecision | None = None
        elif policy_id and policy_name:
            # Real policy returned — use as-is.
            decision = GuardDecision(
                action     = GuardAction(raw_action),
                score      = max(0.0, min(1.0, guard_score)),
                threshold  = max(0.0, min(1.0, threshold)),
                policy_id  = policy_id,
                policy_name= policy_name,
                reason     = reason,
            )
        else:
            # Guard ran but the pipeline omitted policy metadata → honest marker.
            decision = make_unresolved_policy(
                self._probe_identity.probe,
                score     = guard_score,
                threshold = threshold,
                action    = GuardAction(raw_action),
            )
            # Preserve whatever reason we do have so operators can debug.
            if reason:
                decision = decision.model_copy(update={"reason": reason})

        # ── Derive disposition ─────────────────────────────────────────────────
        if error_msg is not None:
            result        = AttemptResult.ERROR
            status        = AttemptStatus.FAILED
            model_resp    = None
            model_invoked = False
            risk          = _risk_score(0.0, blocked=False, errored=True)
        elif decision is not None and decision.action is GuardAction.BLOCK:
            result        = AttemptResult.BLOCKED
            status        = AttemptStatus.COMPLETED
            model_resp    = None               # blocked pre-model
            model_invoked = False              # pipeline did NOT invoke the model
            risk          = _risk_score(decision.score, blocked=True, errored=False)
        else:
            result        = AttemptResult.ALLOWED
            status        = AttemptStatus.COMPLETED
            model_resp    = response
            model_invoked = response is not None
            risk          = _risk_score(
                decision.score if decision else 0.0,
                blocked=False, errored=False,
            )

        return Attempt(
            session_id       = self._session_id,
            probe            = self._probe_identity.probe,
            probe_raw        = self._probe_raw,
            category         = self._probe_identity.category,
            phase            = self._probe_identity.phase,
            started_at       = started_at,
            completed_at     = completed_at,
            latency_ms       = latency_ms,
            prompt_raw       = prompt_str,
            prompt_sanitized = prompt_str,
            guard_input      = prompt_str,
            model_response   = model_resp,
            guard_decision   = decision,
            result           = result,
            risk_score       = risk,
            status           = status,
            error            = error_msg,
            model_invoked    = model_invoked,
            meta             = AttemptMeta(
                garak_probe_class = (
                    self._probe_identity.raw
                    if self._probe_identity.known
                    else self._probe_raw
                ),
                garak_profile = self._profile,
            ),
        )
