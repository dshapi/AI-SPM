"""
app.py
───────
FastAPI entry point for the threat-hunting-agent service.

Responsibilities:
  1. Read config via Settings (pydantic-settings).
  2. Initialise all singletons on startup:
       - Postgres connection factory → postgres_tool
       - Redis client → redis_tool
       - OPA client wrapper → opa_tool
       - Guard model URL → guard_tool
       - Case tool HTTP config → case_tool
       - LangChain agent (ChatGroq + all tools)
       - Kafka consumer (ThreatHuntConsumer)
  3. Expose /health and /ready endpoints.
  4. Expose POST /hunt for manual / test-driven hunts.

The service has no external API consumers (it's purely internal);
the POST /hunt endpoint is for integration tests and ops tooling only.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

import psycopg2
import redis as redis_lib
from fastapi import FastAPI
from pydantic import BaseModel

from config import get_settings
from agent.agent import build_agent, run_hunt
from consumer.kafka_consumer import ThreatHuntConsumer
from consumer.session_poller import SessionPoller
from service.findings_service import FindingsService
from threathunting_ai.scheduler import ThreatHuntingAIScheduler
from tools.postgres_tool import set_connection_factory
from tools.redis_tool import set_redis_client
from tools.opa_tool import set_opa_client
from tools.guard_tool import set_guard_url
from tools.case_tool import configure as configure_case_tool

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("threat_hunting_agent")

SERVICE_NAME = "threat-hunting-agent"
SERVICE_VERSION = "1.0.0"


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info("=== %s v%s starting up ===", SERVICE_NAME, SERVICE_VERSION)

    # -- Postgres ----------------------------------------------------------------
    def _pg_factory():
        return psycopg2.connect(settings.spm_db_url)

    set_connection_factory(_pg_factory)
    logger.info("Postgres connection factory configured: %s", settings.spm_db_url)

    # -- Redis -------------------------------------------------------------------
    r_client = redis_lib.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=False,
    )
    set_redis_client(r_client)
    logger.info("Redis client configured: %s:%d", settings.redis_host, settings.redis_port)

    # -- OPA ---------------------------------------------------------------------
    class _SimpleOpaClient:
        """Thin OPA eval wrapper (no platform_shared dependency)."""
        import requests as _req

        def __init__(self, base_url: str) -> None:
            self._base_url = base_url

        def eval(self, path: str, input_data: dict) -> dict:
            import requests
            try:
                resp = requests.post(
                    f"{self._base_url}{path}",
                    json={"input": input_data},
                    timeout=5.0,
                )
                resp.raise_for_status()
                return resp.json().get("result", {})
            except Exception as exc:
                logger.warning("OPA eval failed path=%s: %s", path, exc)
                return {"decision": "block", "reason": "OPA unavailable"}

    set_opa_client(_SimpleOpaClient(settings.opa_url))
    logger.info("OPA client configured: %s", settings.opa_url)

    # -- Guard -------------------------------------------------------------------
    set_guard_url(settings.guard_model_url or None)
    logger.info("Guard model URL: %s", settings.guard_model_url or "regex-fallback")

    # -- Case tool ---------------------------------------------------------------
    configure_case_tool(
        platform_api_url=settings.platform_api_url,
        orchestrator_url=settings.orchestrator_url,
    )
    logger.info("Case tool configured: orchestrator=%s", settings.orchestrator_url)

    # -- Agent -------------------------------------------------------------------
    agent = build_agent(
        groq_api_key=settings.groq_api_key,
        model=settings.hunt_model,
        base_url=settings.groq_base_url,
    )
    app.state.agent = agent
    logger.info("LangChain agent built: model=%s base_url=%s", settings.hunt_model, settings.groq_base_url)

    # -- FindingsService ---------------------------------------------------------
    findings_svc = FindingsService(
        orchestrator_url=settings.orchestrator_url,
        dev_token_url=f"{settings.platform_api_url}/dev-token",
    )
    app.state.findings_svc = findings_svc
    logger.info("FindingsService configured: orchestrator=%s", settings.orchestrator_url)

    # -- Hunt callbacks ----------------------------------------------------------
    def _hunt(tenant_id: str, events: list) -> dict:
        return run_hunt(app.state.agent, tenant_id, events)

    def _persist(tenant_id: str, finding: dict) -> None:
        findings_svc.persist_finding(finding, tenant_id)

    # -- Session poller (proactive) ----------------------------------------------
    # Polls /api/v1/sessions every 30 s so the agent fires even when sessions
    # are created directly via the AISPM admin UI (not via Kafka).
    poller = SessionPoller(
        orchestrator_url=settings.orchestrator_url,
        dev_token_url=f"{settings.platform_api_url}/dev-token",
        hunt_agent=_hunt,
        persist_fn=_persist,
        poll_interval_sec=settings.hunt_batch_window_sec,
    )
    poller.start()
    app.state.poller = poller
    logger.info(
        "SessionPoller started: tenant=t1 interval=%ds",
        settings.hunt_batch_window_sec,
    )

    # -- Kafka consumer (reactive, secondary feed — non-fatal if unavailable) ----
    # The SessionPoller is the primary findings path. Kafka adds reactive
    # event-driven triggers but the service runs correctly without it.
    consumer = ThreatHuntConsumer(
        kafka_bootstrap=settings.kafka_bootstrap_servers,
        hunt_agent=_hunt,
        batch_window_sec=settings.hunt_batch_window_sec,
        queue_max=settings.hunt_queue_max,
        persist_fn=_persist,
    )
    try:
        consumer.start()
        logger.info(
            "Kafka consumer started: tenant=t1 window=%ds",
            settings.hunt_batch_window_sec,
        )
    except Exception as kafka_exc:
        logger.warning(
            "Kafka consumer failed to start (non-fatal — SessionPoller is primary): %s",
            kafka_exc,
        )
    app.state.consumer = consumer

    # -- ThreatHunting AI scheduler (continuous proactive scans) ----------------
    threathunting_ai_scheduler = ThreatHuntingAIScheduler(
        hunt_agent=_hunt,
        persist_fn=_persist,
        scan_interval_sec=settings.threathunting_ai_interval_sec,
    )
    threathunting_ai_scheduler.start()
    app.state.threathunting_ai_scheduler = threathunting_ai_scheduler
    logger.info(
        "ThreatHuntingAI scheduler started: interval=%ds",
        settings.threathunting_ai_interval_sec,
    )

    logger.info("=== %s ready ===", SERVICE_NAME)
    yield

    # -- Teardown ----------------------------------------------------------------
    logger.info("=== %s shutting down ===", SERVICE_NAME)
    poller.stop()
    consumer.stop()
    threathunting_ai_scheduler.stop()
    logger.info("=== %s stopped ===", SERVICE_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────

class HuntRequest(BaseModel):
    tenant_id: str
    events: List[Dict[str, Any]]


class HuntResponse(BaseModel):
    tenant_id: str
    summary: str
    event_count: int


# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    application = FastAPI(
        title="Threat Hunting Agent",
        description=(
            "Autonomous AI-SPM threat-hunting service. "
            "Consumes Kafka events, runs a LangChain ReAct agent, "
            "and creates threat findings in the orchestrator."
        ),
        version=SERVICE_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    @application.get("/health", tags=["Observability"], summary="Liveness probe")
    async def health() -> dict:
        return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

    @application.get("/ready", tags=["Observability"], summary="Readiness probe")
    async def ready(request_obj=None) -> dict:
        return {"status": "ready", "service": SERVICE_NAME}

    @application.post(
        "/hunt",
        response_model=HuntResponse,
        tags=["Hunting"],
        summary="Trigger a manual threat hunt",
    )
    async def manual_hunt(req: HuntRequest, request_obj=None) -> HuntResponse:
        """
        Run a synchronous threat hunt over a supplied event batch.
        Intended for integration tests and ops tooling — not exposed externally.
        """
        app_ref = application  # use closure
        finding = run_hunt(app_ref.state.agent, req.tenant_id, req.events)
        # finding is now a dict; use title as summary for HuntResponse
        summary = finding.get("title", str(finding)) if isinstance(finding, dict) else str(finding)
        return HuntResponse(
            tenant_id=req.tenant_id,
            summary=summary,
            event_count=len(req.events),
        )

    return application


app = create_app()
