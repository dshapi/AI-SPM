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

import logging
import sys
import uuid

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

log = logging.getLogger("api.simulation")
router = APIRouter()


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

async def _run_single_prompt(session_id: str, prompt: str, attack_type: str,
                              execution_mode: str) -> None:
    """Run prompt through PSS; emit simulation events to Kafka."""
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

    if producer:
        publish_started(producer, session_id=session_id, prompt=prompt,
                        attack_type=attack_type, execution_mode=execution_mode)

    try:
        if pss is None or execution_mode == "hypothetical":
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
        result = await pss.evaluate(prompt, ctx)

        correlation_id = str(uuid.uuid4())
        if result.is_blocked:
            if producer:
                publish_blocked(producer, session_id=session_id,
                                categories=result.categories,
                                decision_reason=result.reason or "blocked",
                                correlation_id=correlation_id)
        else:
            if producer:
                publish_allowed(producer, session_id=session_id,
                                response_preview="",
                                correlation_id=correlation_id)

        if producer:
            publish_completed(producer, session_id=session_id, summary={
                "result": "blocked" if result.is_blocked else "allowed",
                "categories": result.categories,
            })

    except Exception as exc:
        log.exception("simulation single prompt error session_id=%s", session_id)
        if producer:
            publish_error(producer, session_id=session_id, error_message=str(exc))


async def _run_garak(session_id: str, garak_config: GarakConfig,
                     execution_mode: str) -> None:
    """Iterate Garak probes; emit per-probe simulation events."""
    app_mod = sys.modules.get("app")
    producer = getattr(app_mod, "_producer", None) if app_mod else None

    from platform_shared.simulation_events import (
        publish_started, publish_progress, publish_allowed,
        publish_completed, publish_error,
    )

    probes = garak_config.probes or ["default_probe"]
    total = len(probes)

    if producer:
        publish_started(producer, session_id=session_id, prompt="",
                        attack_type="garak", execution_mode=execution_mode)

    try:
        for i, probe in enumerate(probes, start=1):
            if producer:
                publish_progress(producer, session_id=session_id,
                                 step=i, total=total,
                                 message=f"Running probe: {probe}",
                                 probe_name=probe)

            # TODO: call real Garak probe runner here
            corr = str(uuid.uuid4())
            if producer:
                publish_allowed(producer, session_id=session_id,
                                response_preview=f"[probe {probe} stub]",
                                correlation_id=corr)

        if producer:
            publish_completed(producer, session_id=session_id, summary={
                "probes_run": total,
                "profile": garak_config.profile,
            })

    except Exception as exc:
        log.exception("simulation garak error session_id=%s", session_id)
        if producer:
            publish_error(producer, session_id=session_id, error_message=str(exc))


# ── Route handlers ───────────────────────────────────────────────────────────

@router.post("/api/simulate/single")
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


@router.post("/api/simulate/garak")
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
