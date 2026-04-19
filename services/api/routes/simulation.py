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

from platform_shared.policy_explainer import PolicyExplainer as _PolicyExplainer
_explainer = _PolicyExplainer()


def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


async def _ws_emit(session_id: str, event_type: str, payload: dict) -> None:
    """
    Send a simulation event directly to the browser via the WS ConnectionManager.

    This bypasses Kafka entirely so events flow even when the broker is
    unavailable.  Kafka publishing (if producer != None) is handled separately
    and is additive — both paths can run simultaneously without duplication
    because the frontend dedups by event_type+timestamp.
    """
    try:
        import ws.session_ws as _sw
        manager = getattr(_sw, "_manager", None)
        if manager is None:
            return
        event = {
            "session_id":     session_id,
            "event_type":     event_type,
            "source_service": "api-simulation",
            "correlation_id": "",
            "timestamp":      _now(),
            "payload":        payload,
        }
        await manager.broadcast(session_id, event)
    except Exception as exc:
        log.warning("_ws_emit error event_type=%s error=%s", event_type, exc)


# ── Request schemas ──────────────────────────────────────────────────────────

class SinglePromptSimRequest(BaseModel):
    prompt: str
    session_id: str
    execution_mode: str = "live"
    attack_type: str = "custom"


class GarakConfig(BaseModel):
    profile: str = "default"
    probes: list[str] = []
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
    """Run prompt through PSS; emit simulation events via WS (direct) and Kafka."""
    t0 = datetime.datetime.utcnow()

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
    if app_mod is None:
        log.error("simulation: app module not found")
        return
    pss = getattr(app_mod, "_pss", None)
    producer = getattr(app_mod, "_producer", None)

    from platform_shared.simulation_events import (
        publish_started, publish_blocked, publish_allowed,
        publish_completed, publish_error,
    )

    # ── started ──────────────────────────────────────────────────────────────
    await _ws_emit(session_id, "simulation.started", {
        "prompt": prompt,
        "attack_type": attack_type,
        "execution_mode": execution_mode,
    })
    if producer:
        publish_started(producer, session_id=session_id, prompt=prompt,
                        attack_type=attack_type, execution_mode=execution_mode)

    try:
        if pss is None or execution_mode == "hypothetical":
            await _ws_emit(session_id, "simulation.allowed", {
                "response_preview": "[hypothetical — not screened]",
            })
            await _ws_emit(session_id, "simulation.completed", {
                "summary": {"result": "allowed", "mode": "hypothetical"},
            })
            if producer:
                publish_allowed(producer, session_id=session_id,
                                response_preview="[hypothetical — not screened]")
                publish_completed(producer, session_id=session_id,
                                  summary={"result": "allowed", "mode": "hypothetical"})
            return

        from security import ScreeningContext
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
            await _ws_emit(session_id, "simulation.blocked", blocked_payload)
            if producer:
                publish_blocked(
                    producer,
                    session_id=session_id,
                    categories=result.categories,
                    decision_reason=result.reason or "blocked",
                    correlation_id=correlation_id,
                    explanation=_explanation.get("explanation") if _explanation else None,
                )
        else:
            await _ws_emit(session_id, "simulation.allowed", {
                "response_preview": "",
                "correlation_id":   correlation_id,
            })
            if producer:
                publish_allowed(producer, session_id=session_id,
                                response_preview="",
                                correlation_id=correlation_id)

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
        await _ws_emit(session_id, "simulation.completed", {"summary": completed_summary})
        if producer:
            publish_completed(producer, session_id=session_id, summary=completed_summary)

    except Exception as exc:
        log.exception("simulation single prompt error session_id=%s", session_id)
        await _ws_emit(session_id, "simulation.error", {"error_message": str(exc)})
        if producer:
            publish_error(producer, session_id=session_id, error_message=str(exc))


async def _run_garak(session_id: str, garak_config: GarakConfig,
                     execution_mode: str) -> None:
    """Iterate Garak probes; emit per-probe simulation events.

    Every event is sent via _ws_emit (direct WS path, no Kafka dependency)
    AND optionally via Kafka if a producer is available.  This mirrors the
    pattern in _run_single_prompt and is the fix for the 'stuck running'
    regression: previously all events were gated on `if producer:`, so
    without Kafka the frontend never received a terminal event and
    `running` stayed True forever.
    """
    # Same startup race guard as _run_single_prompt — see that function.
    await _ws_wait_for_connection(session_id)

    app_mod = sys.modules.get("app")
    producer = getattr(app_mod, "_producer", None) if app_mod else None

    from platform_shared.simulation_events import (
        publish_started, publish_progress, publish_allowed,
        publish_completed, publish_error,
    )

    probes = garak_config.probes or ["default_probe"]
    total = len(probes)

    # ── started ───────────────────────────────────────────────────────────────
    await _ws_emit(session_id, "simulation.started", {
        "attack_type":    "garak",
        "execution_mode": execution_mode,
        "total_probes":   total,
        "profile":        garak_config.profile,
    })
    if producer:
        publish_started(producer, session_id=session_id, prompt="",
                        attack_type="garak", execution_mode=execution_mode)

    try:
        for i, probe in enumerate(probes, start=1):
            corr = str(uuid.uuid4())

            # progress — one per probe
            await _ws_emit(session_id, "simulation.progress", {
                "step":       i,
                "total":      total,
                "message":    f"Running probe: {probe}",
                "probe_name": probe,
                "correlation_id": corr,
            })
            if producer:
                publish_progress(producer, session_id=session_id,
                                 step=i, total=total,
                                 message=f"Running probe: {probe}",
                                 probe_name=probe,
                                 correlation_id=corr)

            # TODO: call real Garak probe runner here
            await _ws_emit(session_id, "simulation.allowed", {
                "response_preview": f"[probe {probe} stub]",
                "correlation_id":   corr,
            })
            if producer:
                publish_allowed(producer, session_id=session_id,
                                response_preview=f"[probe {probe} stub]",
                                correlation_id=corr)

        # ── completed ─────────────────────────────────────────────────────────
        summary = {"probes_run": total, "profile": garak_config.profile}
        await _ws_emit(session_id, "simulation.completed", {"summary": summary})
        if producer:
            publish_completed(producer, session_id=session_id, summary=summary)

    except Exception as exc:
        log.exception("simulation garak error session_id=%s", session_id)
        await _ws_emit(session_id, "simulation.error", {"error_message": str(exc)})
        if producer:
            publish_error(producer, session_id=session_id, error_message=str(exc))


# ── Route handlers ───────────────────────────────────────────────────────────

@router.post("/simulate/single")
async def simulate_single(req: SinglePromptSimRequest,
                           background_tasks: BackgroundTasks):
    """Run a single prompt through the security pipeline and stream events."""
    background_tasks.add_task(
        _run_single_prompt,
        session_id=req.session_id,
        prompt=req.prompt,
        attack_type=req.attack_type,
        execution_mode=req.execution_mode,
    )
    return {"session_id": req.session_id, "status": "started"}


@router.post("/simulate/garak")
async def simulate_garak(req: GarakSimRequest,
                          background_tasks: BackgroundTasks):
    """Start a Garak scan and stream per-probe events."""
    background_tasks.add_task(
        _run_garak,
        session_id=req.session_id,
        garak_config=req.garak_config,
        execution_mode=req.execution_mode,
    )
    return {"session_id": req.session_id, "status": "started"}
