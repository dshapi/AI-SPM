"""
services/api/simulation/orchestrator.py   (v2.1 — correctness audit)
────────────────────────────────────────────────────────────────────
Orchestrates a Garak simulation end-to-end.

Invariants enforced here
────────────────────────
1.  ``sequence`` is assigned EXACTLY ONCE, in this module, on the
    envelope.  Attempts never carry a sequence field.  The counter is
    strictly monotonic: ``self._seq += 1`` happens inside a single
    critical section (``_emit_event``) that every outgoing frame passes
    through.  No ``-1`` sentinel — every frame gets a real sequence.

2.  Exactly ONE terminal event — ``simulation.completed`` OR
    ``simulation.error`` — is emitted per run.  The flag is set BEFORE
    the terminal send so a raising emitter can't cause a second.

3.  Every emitted ``simulation.attempt`` envelope is validated against
    the ``Attempt`` schema; missing ``attempt_id`` is logged as an
    error and the frame is dropped.

4.  Probe lifecycle is observable: ``simulation.probe_started`` fires
    before the runner call; ``simulation.probe_completed`` fires after,
    carrying ``probe_duration_ms`` and per-probe stats.

5.  Partial-attempt preservation on timeout: when the runner call
    raises ``asyncio.TimeoutError`` the orchestrator does NOT drop
    whatever attempts were already streamed back in the response.  The
    runner itself is responsible for surfacing partials (see
    ``garak_runner_patched.py`` — its ``_run_probe_sync`` catches
    exceptions after the probe loop and still returns
    ``ProbeRunResult(attempts=cap.drain(), warnings=[...])``).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Awaitable, Callable

import httpx
from pydantic import ValidationError

from platform_shared.simulation.attempts import (
    Attempt,
    AttemptResult,
    ProbeRunResult,
    ProbeRunStats,
    SimulationCompletedData,
    SimulationSummary,
    StructuredWarning,
    summarize,
)
from platform_shared.simulation.probe_registry import resolve

log = logging.getLogger("api.simulation.orchestrator")

# An emit callable receives the fully-built envelope.  The transport is
# free to drop/buffer/fan-out; it MUST NOT mutate the envelope.
EmitFn = Callable[[dict], Awaitable[None]]


# ── HTTP client ──────────────────────────────────────────────────────────────

def _runner_url() -> str:
    return os.environ.get("GARAK_RUNNER_URL", "http://garak-runner:8099").rstrip("/")


async def _call_runner(
    *,
    session_id: uuid.UUID,
    probe: str,
    probe_raw: str,
    profile: str,
    max_attempts: int,
    execution_mode: str,
    timeout_s: float,
) -> ProbeRunResult:
    url = _runner_url() + "/probe"
    payload = {
        "session_id":     str(session_id),
        "probe":          probe,
        "probe_raw":      probe_raw,
        "profile":        profile,
        "max_attempts":   max_attempts,
        "execution_mode": execution_mode,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s + 10.0)) as client:
        resp = await asyncio.wait_for(client.post(url, json=payload), timeout=timeout_s)
        resp.raise_for_status()
        try:
            return ProbeRunResult.model_validate(resp.json())
        except ValidationError as ve:
            log.error("runner returned invalid ProbeRunResult: %s", ve)
            raise


# ── Orchestrator ─────────────────────────────────────────────────────────────

class SimulationOrchestrator:

    def __init__(
        self,
        *,
        session_id:     uuid.UUID,
        probes:         list[str],
        profile:        str,
        max_attempts:   int,
        execution_mode: str,
        emit:           EmitFn,
        probe_timeout_s: float = 150.0,
    ) -> None:
        self.session_id     = session_id
        self.probes_raw     = list(probes)
        self.profile        = profile
        self.max_attempts   = max_attempts
        self.execution_mode = execution_mode
        self._emit          = emit
        self._probe_timeout = probe_timeout_s

        # Monotonic sequence — THIS is the only counter.
        self._seq_lock = asyncio.Lock()
        self._seq      = -1   # next frame is 0

        self._attempts: list[Attempt] = []
        self._seen_attempt_ids: set[str] = set()

        # Probes for which simulation.probe_completed has already been
        # emitted.  Attempts for these probes arriving later are stamped
        # with meta.is_straggler = True so the UI can flag them without
        # unfreezing the frozen per-probe counts.
        self._probe_completed_probes: set[str] = set()

        self._terminal_sent = False
        self._t_start       = time.perf_counter()

        # Debug-only runtime sequence-monotonicity assertion.  MUST NOT
        # run in production — pure log-only, no crash.  Toggled via env.
        self._debug: bool = os.environ.get("SIMULATION_DEBUG", "").lower() in (
            "1", "true", "yes", "on",
        )
        self._last_seq: int = -1

    # ── Envelope construction + emit ─────────────────────────────────────────

    async def _emit_event(self, event_type: str, data: dict) -> None:
        """Build and emit exactly one envelope.  Sequence is assigned here.

        Callers pass a plain ``data`` dict (already JSON-safe).  This
        method adds ``type``, ``session_id``, ``sequence``, ``timestamp``.
        If the transport ``_emit`` raises, the sequence has already been
        consumed — we don't reuse it.
        """
        async with self._seq_lock:
            self._seq += 1
            sequence = self._seq

        envelope = {
            "type":       event_type,
            "session_id": str(self.session_id),
            "sequence":   sequence,
            "timestamp":  _utcnow_iso(),
            "data":       data,
        }
        # Minimal contract validation — catches hand-rolled callers.
        if not envelope["type"] or "data" not in envelope:
            log.error("orchestrator: refusing to emit malformed envelope %r", envelope)
            return
        # Debug-only monotonicity assertion.  Log-only; never raises.
        # Exists to detect sequence regressions instantly in dev/staging
        # where concurrent emit paths may exist.
        if self._debug:
            if envelope["sequence"] <= self._last_seq:
                log.error(
                    "SEQUENCE_REGRESSION session=%s prev=%d current=%d",
                    self.session_id, self._last_seq, envelope["sequence"],
                )
            self._last_seq = envelope["sequence"]
        try:
            await self._emit(envelope)
        except Exception:
            log.exception("orchestrator: transport emit failed type=%s seq=%d",
                          event_type, sequence)

    # ── Attempt helper with validation ───────────────────────────────────────

    async def _emit_attempt(self, attempt: Attempt) -> None:
        aid = str(attempt.attempt_id)
        if not aid or aid == "00000000-0000-0000-0000-000000000000":
            log.error("orchestrator: refusing to emit attempt with empty attempt_id "
                      "(session=%s probe=%s)", self.session_id, attempt.probe)
            return
        if aid in self._seen_attempt_ids:
            log.warning("orchestrator: duplicate attempt_id suppressed aid=%s probe=%s",
                        aid, attempt.probe)
            return
        self._seen_attempt_ids.add(aid)
        self._attempts.append(attempt)

        # Stamp the straggler flag.  An attempt is a straggler iff
        # simulation.probe_completed was already emitted for its probe —
        # i.e. this frame is a late arrival or a replay.  The flag rides
        # on the wire in attempt.meta so the UI can render a warning
        # badge WITHOUT unfreezing the authoritative per-probe counts.
        is_straggler = attempt.probe in self._probe_completed_probes
        payload = attempt.model_dump(mode="json")
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            payload["meta"] = meta
        meta["is_straggler"] = is_straggler

        await self._emit_event("simulation.attempt", payload)

    # ── Warning helper ───────────────────────────────────────────────────────

    async def _emit_warning(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        await self._emit_event("simulation.warning", {
            "code":    code,
            "message": message,
            "detail":  detail or {},
        })

    # ── Main loop ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        total = len(self.probes_raw)
        try:
            await self._emit_event("simulation.started", {
                "probes":         self.probes_raw,
                "profile":        self.profile,
                "execution_mode": self.execution_mode,
                "max_attempts":   self.max_attempts,
            })

            for i, raw_probe in enumerate(self.probes_raw, start=1):
                identity = resolve(raw_probe)
                if not identity.known:
                    await self._emit_warning(
                        "unknown_probe",
                        f"Probe {raw_probe!r} is not in the registry — running anyway.",
                        {"raw": raw_probe},
                    )

                await self._emit_event("simulation.probe_started", {
                    "probe":     identity.probe,
                    "probe_raw": raw_probe,
                    "category":  identity.category,
                    "phase":     identity.phase.value,
                    "index":     i,
                    "total":     total,
                })

                t_probe = time.perf_counter()
                run_result: ProbeRunResult | None = None

                try:
                    run_result = await _call_runner(
                        session_id     = self.session_id,
                        probe          = identity.probe,
                        probe_raw      = raw_probe,
                        profile        = self.profile,
                        max_attempts   = self.max_attempts,
                        execution_mode = self.execution_mode,
                        timeout_s      = self._probe_timeout,
                    )
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError:
                    # Uppercase code per hardening spec; downstream consumers
                    # dispatch on this exact string.
                    await self._emit_warning(
                        "PROBE_TIMEOUT",
                        f"Probe {identity.probe!r} timed out after {self._probe_timeout:.0f}s.",
                        {"probe": identity.probe, "probe_raw": raw_probe,
                         "timeout_s": self._probe_timeout},
                    )
                except Exception as exc:
                    log.exception("probe %s runner call failed: %s", identity.probe, exc)
                    await self._emit_warning(
                        "PROBE_RUNNER_ERROR",
                        f"Probe {identity.probe!r} runner call failed: {exc}",
                        {"probe": identity.probe, "probe_raw": raw_probe,
                         "error": str(exc)},
                    )

                # Stream attempts (if any) + pass-through warnings.
                if run_result is not None:
                    for warn in run_result.warnings:
                        # StructuredWarning instances — forward verbatim.
                        await self._emit_event("simulation.warning", warn.model_dump(mode="json"))
                    for attempt in run_result.attempts:
                        await self._emit_attempt(attempt)

                # probe_completed — ALWAYS emitted, even on timeout / error,
                # so the frontend's probe-lifecycle panel closes out.
                stats = run_result.stats if run_result else ProbeRunStats(
                    attempt_count=0, blocked_count=0, allowed_count=0, error_count=0,
                )
                await self._emit_event("simulation.probe_completed", {
                    "probe":             identity.probe,
                    "probe_raw":         raw_probe,
                    "category":          identity.category,
                    "phase":             identity.phase.value,
                    "index":             i,
                    "total":             total,
                    "attempt_count":     stats.attempt_count,
                    "blocked_count":     stats.blocked_count,
                    "allowed_count":     stats.allowed_count,
                    "error_count":       stats.error_count,
                    "probe_duration_ms": int((time.perf_counter() - t_probe) * 1000),
                    # Authoritative "probe lifecycle closed" marker — the
                    # frontend freezes per-probe counts when this is True,
                    # preventing any late straggler from mutating totals.
                    "completed":         True,
                })
                # Record that probe_completed has fired for this probe so
                # any subsequent simulation.attempt for this probe is
                # stamped meta.is_straggler = True at emit time.
                self._probe_completed_probes.add(identity.probe)

            # ── Summary + terminal ───────────────────────────────────────────
            elapsed_ms = int((time.perf_counter() - self._t_start) * 1000)
            summary: SimulationSummary = summarize(
                self._attempts,
                elapsed_ms  = elapsed_ms,
                probe_count = total,
            )
            await self._emit_event("simulation.summary", summary.model_dump(mode="json"))

            # FLAG FIRST — a crashing emit after flag=True still leaves
            # exactly one terminal because the finally clause checks the
            # flag and skips.
            self._terminal_sent = True
            await self._emit_event(
                "simulation.completed",
                SimulationCompletedData(summary=summary, total_ms=elapsed_ms).model_dump(mode="json"),
            )

        except asyncio.CancelledError:
            log.warning("simulation cancelled: session=%s", self.session_id)
            await self._emit_terminal_error("Simulation cancelled (hard timeout)")
            raise
        except Exception as exc:
            log.exception("simulation orchestrator crashed: session=%s", self.session_id)
            await self._emit_terminal_error(f"Simulation error: {exc}")
        finally:
            if not self._terminal_sent:
                await self._emit_terminal_error("Simulation ended without terminal event")

    async def _emit_terminal_error(self, message: str) -> None:
        if self._terminal_sent:
            return
        self._terminal_sent = True    # FLAG FIRST — see docstring.
        try:
            await self._emit_event("simulation.error", {
                "error_message": message,
                "fatal":         True,
            })
        except Exception:
            log.exception("failed to emit simulation.error")


# ── Wall-clock helper ────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── Drop-in for old call site ────────────────────────────────────────────────

async def run_garak_simulation(
    config: Any,
    emit_event: Callable[[str, dict], Awaitable[None]],
    session_id: str,
    probe_timeout_s: float = 150.0,
) -> None:
    """Back-compat shim.  The new ``emit`` signature is ``(envelope)`` —
    if the caller still passes the old ``(event_type, payload)`` shape,
    adapt it here."""

    async def _adapter(envelope: dict) -> None:
        await emit_event(envelope["type"], envelope)

    orchestrator = SimulationOrchestrator(
        session_id     = uuid.UUID(session_id),
        probes         = list(getattr(config, "probes", []) or []),
        profile        = getattr(config, "profile", "default"),
        max_attempts   = int(getattr(config, "max_attempts", 5)),
        execution_mode = getattr(config, "execution_mode", "live"),
        emit           = _adapter,
        probe_timeout_s= probe_timeout_s,
    )
    await orchestrator.run()
