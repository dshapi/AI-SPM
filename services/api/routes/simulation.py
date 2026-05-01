"""
routes/simulation.py
─────────────────────
Simulation endpoints.

POST /api/simulate/single   — run one prompt through the security pipeline
POST /api/simulate/garak    — start a Garak probe scan

Both endpoints:
- Accept a client-generated session_id (frontend creates UUID and connects WS first)
- Schedule the actual work as a BackgroundTask
- Return { session_id, status: "started" } immediately

Event flow:
  frontend POST ──► route returns session_id
  background task ──► publish_started ──► Kafka ──► WS bridge ──► browser
                  ──► screen/probe  ──► publish_blocked|allowed
                  ──► publish_completed | publish_error
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import sys
import uuid

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

log = logging.getLogger("api.simulation")
router = APIRouter()

# WS connection wait timeout — configurable for high-latency environments.
# Default 10s covers ~99% of real-world network conditions.
# The original 2.0s was too short for 4G/intercontinental connections.
_WS_WAIT_TIMEOUT_S: float = float(os.environ.get("WS_WAIT_TIMEOUT_S", "10.0"))

# Hard upper bound for the total simulation runtime. If the coroutine hangs
# (dead PSS, stuck probe, etc.) we force-emit `simulation.error` so the
# frontend never waits forever on its own watchdog alone.
#
# Sizing model: the budget is derived from the per-probe budget that the
# garak runner already enforces (PROBE_TIMEOUT_S, default 300s) times the
# number of probes a typical run can request, plus a small fixed overhead
# for setup/teardown and event publication. Both PROBE_TIMEOUT_S and
# SIM_MAX_PROBES are env-overridable so operators can dial the budget
# tighter for short feedback loops or wider for long-running campaigns.
#
# Defaults: 300s × 6 probes + 60s = 1860s (≈ 31 min). Plenty for a Full
# Kill Chain run while still cancelling truly stuck simulations.
_PROBE_TIMEOUT_S:     float = float(os.environ.get("PROBE_TIMEOUT_S",   "300.0"))
_SIM_MAX_PROBES:      int   = int(os.environ.get("SIM_MAX_PROBES",      "6"))
_SIM_HARD_OVERHEAD_S: float = float(os.environ.get("SIM_HARD_OVERHEAD_S", "60.0"))
_SIM_HARD_TIMEOUT_S:  float = float(os.environ.get(
    "SIM_HARD_TIMEOUT_S",
    str(_PROBE_TIMEOUT_S * _SIM_MAX_PROBES + _SIM_HARD_OVERHEAD_S),
))

from platform_shared.policy_explainer import PolicyExplainer as _PolicyExplainer
_explainer = _PolicyExplainer()


def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


async def _ws_emit(
    session_id: str,
    event_type: str,
    payload: dict,
    *,
    timestamp: str | None = None,
    correlation_id: str = "",
) -> str:
    """
    Send a simulation event directly to the browser via the WS ConnectionManager
    AND publish it to the global lineage Kafka topic for durable persistence.

    Returns the ISO-8601 timestamp actually stamped on the event so callers
    that also mirror the same event to Kafka (publish_*) can reuse it —
    otherwise the two paths stamp independent timestamps, the frontend
    dedup key (event_type:correlation_id:timestamp) fails to collide, and
    the browser renders every event twice.

    Persistence rationale: without persisting simulation events the Replay
    button on the Lineage page cannot reconstruct the graph after the
    in-memory ConnectionManager log evicts the session.  We publish to
    GlobalTopics.LINEAGE_EVENTS; the orchestrator's lineage_consumer drains
    the topic and writes session_events using the SAME persistence call the
    legacy HTTP endpoint used, so the persisted row is byte-identical and
    the rendered graph is unchanged.
    """
    ts = timestamp or _now()
    try:
        import ws.session_ws as _sw
        manager = getattr(_sw, "_manager", None)
        if manager is not None:
            event = {
                "session_id":     session_id,
                "event_type":     event_type,
                "source_service": "api-simulation",
                "correlation_id": correlation_id,
                "timestamp":      ts,
                "payload":        payload,
            }
            await manager.broadcast(session_id, event)
    except Exception as exc:
        log.warning("_ws_emit error event_type=%s error=%s", event_type, exc)

    # Durable path — Kafka publish (best-effort, fire-and-forget).
    # Producer is fetched lazily from the api app module so simulation runs
    # share the singleton with the chat path. KafkaProducer.send is
    # non-blocking; we offload the flush+wait to a thread executor so the
    # simulation pipeline is never stalled by broker latency.
    try:
        from platform_shared.lineage_events import publish_lineage_event
        app_mod = sys.modules.get("app")
        producer = getattr(app_mod, "_producer", None) if app_mod else None
        if producer is None and app_mod is not None:
            try:
                producer = app_mod.get_producer()
            except Exception:
                producer = None
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: publish_lineage_event(
                producer,
                session_id     = session_id,
                event_type     = event_type,
                payload        = payload,
                timestamp      = ts,
                correlation_id = correlation_id or None,
                agent_id       = "sim-agent",
                user_id        = "sim-user",
                tenant_id      = "t1",
                source         = "api-simulation",
            ),
        )
    except Exception as exc:
        log.warning("_ws_emit lineage publish schedule failed event_type=%s err=%s",
                    event_type, exc)
    return ts


# ── Request schemas ──────────────────────────────────────────────────────────

class SinglePromptSimRequest(BaseModel):
    prompt: str
    session_id: str
    execution_mode: str = "live"
    attack_type: str = "custom"


class GarakConfig(BaseModel):
    profile: str = "default"
    probes: list[str] = []
    # Restored 3 → 10 after ADR 0001 parallelism (task #25) + prompt cap
    # (task #27) shipped.  Garak now fans out 8 attempts concurrently
    # through the CPM pipeline AND caps probe.prompts at
    # max_attempts × GARAK_PROMPT_OVERSAMPLE (default 4 = 40 prompts),
    # so encoding.InjectBase64 first-yields in ~2-7s instead of timing
    # out.  10 reported attempts fits comfortably in the 60s
    # PROBE_TIMEOUT_S budget.
    max_attempts: int = 10


class GarakSimRequest(BaseModel):
    session_id: str
    execution_mode: str = "live"
    garak_config: GarakConfig = GarakConfig()


# ── Background workers ───────────────────────────────────────────────────────

async def _ws_wait_for_connection(session_id: str, timeout_s: float | None = None) -> None:
    """
    Block (via asyncio.sleep) until *session_id* has an active WS connection
    registered in ConnectionManager, or until *timeout_s* seconds elapse.

    This guards against the startup race where the browser initiates the WS
    upgrade and the POST /simulate/single concurrently.  FastAPI's
    BackgroundTasks run immediately after the response is sent, which can
    beat the WS handshake: ConnectionManager.broadcast() silently drops events
    for sessions with no registered connections, so the terminal event never
    reaches the browser and `running` stays True forever.
    """
    if timeout_s is None:
        timeout_s = _WS_WAIT_TIMEOUT_S
    import ws.session_ws as _sw
    manager = getattr(_sw, "_manager", None)
    if manager is None:
        return                              # no WS layer — nothing to wait for
    poll_interval = 0.1
    elapsed = 0.0
    while elapsed < timeout_s:
        if session_id in manager.active_session_ids:
            return                          # connection registered — safe to emit
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    log.warning(
        "simulation: WS connection not established after %.1fs for session %s — "
        "proceeding anyway (events may be lost if client is not connected)",
        timeout_s, session_id,
    )


async def _run_single_prompt(session_id: str, prompt: str, attack_type: str,
                              execution_mode: str) -> None:
    """Run prompt through PSS; emit simulation events via WS (direct) and Kafka.

    Correctness guarantees (critical for the frontend pipeline):

      * EXACTLY ONE of `simulation.completed` OR `simulation.error` is always
        emitted, even if PSS crashes, the WS layer drops, or an inner
        `_ws_emit` raises.  This is enforced by the `try/finally` below plus
        a local `terminal_sent` flag.
      * The whole coroutine is wrapped by `_run_with_hard_timeout` which
        cancels and emits `simulation.error` if runtime exceeds
        `SIM_HARD_TIMEOUT_S`.  This prevents zombie background tasks from
        holding open a session forever.  The default is derived from
        PROBE_TIMEOUT_S × SIM_MAX_PROBES + SIM_HARD_OVERHEAD_S — see the
        config block at the top of this file.
    """
    t0 = datetime.datetime.utcnow()
    terminal_sent = False   # set to True once completed/error is emitted

    # Wait for the browser's WS connection to be registered before emitting
    # any events.  Without this guard the background task races ahead of the
    # WS handshake and all events are silently dropped by ConnectionManager.
    await _ws_wait_for_connection(session_id)

    t_ws = datetime.datetime.utcnow()
    log.info(
        "simulation: WS ready session=%s ws_wait_ms=%d",
        session_id,
        int((t_ws - t0).total_seconds() * 1000),
    )

    app_mod = sys.modules.get("app")
    pss = getattr(app_mod, "_pss", None) if app_mod else None
    producer = getattr(app_mod, "_producer", None) if app_mod else None

    from platform_shared.simulation_events import (
        publish_started, publish_blocked, publish_allowed,
        publish_completed, publish_error,
    )

    # ── started ──────────────────────────────────────────────────────────────
    # One timestamp, two paths — see _ws_emit docstring and task #13 fix C.
    ts_started = await _ws_emit(session_id, "simulation.started", {
        "prompt": prompt,
        "attack_type": attack_type,
        "execution_mode": execution_mode,
    })
    if producer:
        publish_started(producer, session_id=session_id, prompt=prompt,
                        attack_type=attack_type, execution_mode=execution_mode,
                        timestamp=ts_started)

    try:
        if app_mod is None:
            raise RuntimeError("app module not found — simulation aborted")

        if pss is None or execution_mode == "hypothetical":
            ts_allowed = await _ws_emit(session_id, "simulation.allowed", {
                "response_preview": "[hypothetical — not screened]",
            })
            completed_summary = {"result": "allowed", "mode": "hypothetical"}
            ts_done = await _ws_emit(session_id, "simulation.completed",
                                     {"summary": completed_summary})
            terminal_sent = True
            if producer:
                publish_allowed(producer, session_id=session_id,
                                response_preview="[hypothetical — not screened]",
                                timestamp=ts_allowed)
                publish_completed(producer, session_id=session_id,
                                  summary=completed_summary,
                                  timestamp=ts_done)
            return

        from prompt_security import ScreeningContext
        ctx = ScreeningContext(
            session_id=session_id,
            user_id="sim-user",
            tenant_id="t1",
        )
        t_pss_start = datetime.datetime.utcnow()
        result = await pss.evaluate(prompt, ctx)
        t_pss_end = datetime.datetime.utcnow()
        log.info(
            "simulation: PSS complete session=%s pss_ms=%d is_blocked=%s",
            session_id,
            int((t_pss_end - t_pss_start).total_seconds() * 1000),
            result.is_blocked,
        )

        correlation_id = str(uuid.uuid4())
        _eval_start = t_pss_end

        # Build explanation for blocked events
        _policy_event = {
            "categories":     result.categories,
            "blocked_by":     getattr(result, "blocked_by", None),
            "reason":         result.reason or "",
            "input_fragment": prompt[:200],
            "decision":       "deny" if result.is_blocked else "allow",
        }
        _explanation = _explainer.explain(_policy_event) if result.is_blocked else None

        if result.is_blocked:
            blocked_payload = {
                "categories":      result.categories,
                "decision_reason": result.reason or "blocked",
                "correlation_id":  correlation_id,
            }
            if _explanation:
                blocked_payload["explanation"] = _explanation.get("explanation")
            ts_term = await _ws_emit(session_id, "simulation.blocked",
                                     blocked_payload,
                                     correlation_id=correlation_id)
            if producer:
                publish_blocked(
                    producer,
                    session_id=session_id,
                    categories=result.categories,
                    decision_reason=result.reason or "blocked",
                    correlation_id=correlation_id,
                    explanation=_explanation.get("explanation") if _explanation else None,
                    timestamp=ts_term,
                )
        else:
            ts_term = await _ws_emit(session_id, "simulation.allowed", {
                "response_preview": "",
                "correlation_id":   correlation_id,
            }, correlation_id=correlation_id)
            if producer:
                publish_allowed(producer, session_id=session_id,
                                response_preview="",
                                correlation_id=correlation_id,
                                timestamp=ts_term)

            # ── Lineage: emit the downstream pipeline stages so the graph
            # shows the full canonical chain (prompt → risk → policy → llm →
            # output) when the prompt is allowed. A simulation does NOT
            # actually invoke a real LLM — these events describe what the
            # live pipeline WOULD do, giving users the full lineage view.
            _guard_score = (
                result.signals.get("guard_score", 0.0)
                if hasattr(result, "signals") else 0.0
            )
            await _ws_emit(session_id, "risk.calculated", {
                "risk_score":     _guard_score,
                "guard_score":    _guard_score,
                "correlation_id": correlation_id,
            }, correlation_id=correlation_id)
            await _ws_emit(session_id, "llm.invoked", {
                "provider":       "simulation",
                "model":          "simulated",
                "correlation_id": correlation_id,
            }, correlation_id=correlation_id)
            await _ws_emit(session_id, "output.generated", {
                "output_length":   0,
                "pii_redacted":    False,
                "secrets_found":   False,
                "simulated":       True,
                "correlation_id":  correlation_id,
            }, correlation_id=correlation_id)

        _eval_ms = int((datetime.datetime.utcnow() - _eval_start).total_seconds() * 1000)
        _total_ms = int((datetime.datetime.utcnow() - t0).total_seconds() * 1000)
        completed_summary = {
            "result":      "blocked" if result.is_blocked else "allowed",
            "categories":  result.categories,
            "duration_ms": _eval_ms,
        }
        log.info(
            "simulation: complete session=%s total_ms=%d result=%s",
            session_id, _total_ms, completed_summary["result"],
        )
        ts_done = await _ws_emit(session_id, "simulation.completed",
                                  {"summary": completed_summary})
        terminal_sent = True
        if producer:
            publish_completed(producer, session_id=session_id,
                              summary=completed_summary,
                              timestamp=ts_done)

    except asyncio.CancelledError:
        # The outer hard-timeout wrapper is tearing us down. Emit error and
        # let the cancellation propagate so the task actually stops.
        log.warning("simulation: cancelled session_id=%s", session_id)
        try:
            ts_err = await _ws_emit(
                session_id, "simulation.error",
                {"error_message": "Simulation cancelled (hard timeout)"},
            )
            if producer:
                publish_error(producer, session_id=session_id,
                              error_message="Simulation cancelled (hard timeout)",
                              timestamp=ts_err)
            terminal_sent = True
        finally:
            raise

    except Exception as exc:
        log.exception("simulation single prompt error session_id=%s", session_id)
        try:
            ts_err = await _ws_emit(session_id, "simulation.error",
                                     {"error_message": str(exc)})
            if producer:
                publish_error(producer, session_id=session_id,
                              error_message=str(exc), timestamp=ts_err)
            terminal_sent = True
        except Exception:
            log.exception("simulation: failed to emit error event session_id=%s",
                          session_id)

    finally:
        # LAST-RESORT safety net: if we somehow got here without emitting a
        # terminal event, emit simulation.error so the frontend never hangs.
        if not terminal_sent:
            log.warning("simulation: no terminal emitted — injecting fallback error session_id=%s",
                        session_id)
            try:
                ts_fb = await _ws_emit(
                    session_id, "simulation.error",
                    {"error_message": "Simulation ended without terminal event"},
                )
                if producer:
                    publish_error(producer, session_id=session_id,
                                  error_message="Simulation ended without terminal event",
                                  timestamp=ts_fb)
            except Exception:
                log.exception("simulation: fallback terminal emit failed session_id=%s",
                              session_id)


async def _run_garak(session_id: str, garak_config: GarakConfig,
                     execution_mode: str) -> None:
    """Delegate probe execution to garak_runner.run_garak_simulation.

    This function owns three concerns that belong at the transport layer:
      1. WS connection wait — ensures the browser is listening before we emit.
      2. emit_event adapter — fans each event to both the direct WS path and
         the optional Kafka mirror so both consumers stay in sync.
      3. Outer error safety — if garak_runner itself raises before its own
         try/finally (e.g., import failure), we emit a fallback error so the
         frontend never hangs in ``running`` state.

    Terminal guarantee:
      garak_runner.run_garak_simulation guarantees EXACTLY ONE terminal event
      (simulation.completed OR simulation.error) internally.
      _run_with_hard_timeout provides an additional outer safety net.
    """
    # Same startup race guard as _run_single_prompt — see that function.
    await _ws_wait_for_connection(session_id)

    app_mod = sys.modules.get("app")
    producer = getattr(app_mod, "_producer", None) if app_mod else None

    from platform_shared.simulation_events import (
        publish_started, publish_progress, publish_allowed, publish_blocked,
        publish_completed, publish_error,
    )

    async def emit_event(event_type: str, payload: dict) -> None:
        """Fan-out: WS direct (always) + Kafka mirror (when producer available).

        Both paths MUST carry the same ISO-8601 timestamp, otherwise the
        frontend's dedup key (event_type+correlation_id+timestamp) fails to
        collide and every event renders twice — see task #13 fix C.

        lineage.node has no Kafka publisher yet — it is forwarded to the WS
        layer only and silently ignored by the frontend state machine (unknown
        event types are not dispatched by useSimulationState).
        """
        corr = payload.get("correlation_id", "")
        ts = await _ws_emit(session_id, event_type, payload,
                            correlation_id=corr)
        if not producer:
            return
        if event_type == "simulation.started":
            publish_started(producer, session_id=session_id, prompt="",
                            attack_type="garak", execution_mode=execution_mode,
                            timestamp=ts)
        elif event_type == "simulation.progress":
            publish_progress(producer, session_id=session_id,
                             step=payload.get("step", 0),
                             total=payload.get("total", 0),
                             message=payload.get("message", ""),
                             probe_name=payload.get("probe_name", ""),
                             correlation_id=corr,
                             timestamp=ts)
        elif event_type == "simulation.allowed":
            publish_allowed(producer, session_id=session_id,
                            response_preview=payload.get("response_preview", ""),
                            correlation_id=corr,
                            timestamp=ts)
        elif event_type == "simulation.blocked":
            publish_blocked(producer, session_id=session_id,
                            categories=payload.get("categories", []),
                            decision_reason=payload.get("decision_reason", ""),
                            correlation_id=corr,
                            timestamp=ts)
        elif event_type == "simulation.completed":
            publish_completed(producer, session_id=session_id,
                              summary=payload.get("summary", {}),
                              timestamp=ts)
        elif event_type == "simulation.error":
            publish_error(producer, session_id=session_id,
                          error_message=payload.get("error_message", ""),
                          timestamp=ts)

    # garak_runner owns the probe loop, event mapping, and terminal guarantee.
    # If the import itself fails (e.g., syntax error in garak_runner), the
    # exception bubbles to _run_with_hard_timeout which emits a safety-net error.
    from garak_runner import run_garak_simulation
    await run_garak_simulation(garak_config, emit_event, session_id)


# ── Hard-timeout wrapper ─────────────────────────────────────────────────────

async def _run_with_hard_timeout(session_id: str, coro, label: str) -> None:
    """
    Run *coro* but kill it if it exceeds SIM_HARD_TIMEOUT_S and force-emit
    simulation.error so the WS stream always reaches a terminal event.

    `coro` is awaited once; on timeout we cancel it and synthesise an error
    event in case the inner coroutine never got a chance to emit one
    (it usually will, via its own CancelledError handler).

    For ANY uncaught exception from the worker we also emit simulation.error.
    The worker's own try/finally usually handles this, but it cannot catch
    exceptions raised BEFORE the try block (e.g., top-level imports of
    platform_shared.simulation_events failing, or _ws_wait_for_connection
    raising). Without this safety net those paths would leave the frontend
    hung waiting for a terminal event that never arrives.
    """
    try:
        await asyncio.wait_for(coro, timeout=_SIM_HARD_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.error("simulation: %s hard timeout session_id=%s timeout_s=%.1f",
                  label, session_id, _SIM_HARD_TIMEOUT_S)
        try:
            await _ws_emit(session_id, "simulation.error", {
                "error_message": f"Simulation exceeded hard timeout of {_SIM_HARD_TIMEOUT_S}s",
            })
        except Exception:
            log.exception("simulation: failed to emit timeout error session_id=%s",
                          session_id)
    except Exception as exc:
        # Any uncaught exception bubbled from the worker — the worker itself
        # should have emitted simulation.error, but if it raised before its
        # own try/finally (e.g., import failure, WS-wait crash), no terminal
        # would have fired. Emit one here as a last-resort safety net.
        log.exception("simulation: %s worker raised uncaught session_id=%s",
                      label, session_id)
        try:
            await _ws_emit(session_id, "simulation.error", {
                "error_message": f"Simulation aborted: {exc}",
            })
        except Exception:
            log.exception("simulation: failed to emit uncaught-error session_id=%s",
                          session_id)


# ── Route handlers ───────────────────────────────────────────────────────────

@router.post("/simulate/single")
async def simulate_single(req: SinglePromptSimRequest,
                           background_tasks: BackgroundTasks):
    """Run a single prompt through the security pipeline and stream events."""
    coro = _run_single_prompt(
        session_id=req.session_id,
        prompt=req.prompt,
        attack_type=req.attack_type,
        execution_mode=req.execution_mode,
    )
    background_tasks.add_task(
        _run_with_hard_timeout, req.session_id, coro, "single-prompt"
    )
    return {"session_id": req.session_id, "status": "started"}


@router.post("/simulate/garak")
async def simulate_garak(req: GarakSimRequest,
                          background_tasks: BackgroundTasks):
    """Start a Garak scan and stream per-probe events."""
    coro = _run_garak(
        session_id=req.session_id,
        garak_config=req.garak_config,
        execution_mode=req.execution_mode,
    )
    background_tasks.add_task(
        _run_with_hard_timeout, req.session_id, coro, "garak"
    )
    return {"session_id": req.session_id, "status": "started"}
