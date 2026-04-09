"""
main.py
────────
FastAPI application entry point for agent-orchestrator-service.

Responsibilities
────────────────
1. Build the FastAPI app with lifespan management.
2. Initialise all singletons (DB, Kafka, RiskEngine, PolicyClient)
   and store them on app.state for dependency injection.
3. Register routers.
4. Add middleware:
   - Trace ID injection (every request gets a UUID correlation ID)
   - Structured request logging
   - Global exception handler
5. Expose health + readiness endpoints.

Run locally
───────────
    uvicorn main:app --reload --port 8094

Or via Docker:
    docker build -t agent-orchestrator .
    docker run -p 8094:8094 agent-orchestrator
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from clients.policy_client import PolicyClient
from events.publisher import EventPublisher
from events.store import EventStore
from models.session import SessionRepository
from routers import sessions as sessions_router
from services.risk_engine import RiskEngine

# ─────────────────────────────────────────────────────────────────────────────
# Logging configuration
# ─────────────────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)-35s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("agent_orchestrator")


# ─────────────────────────────────────────────────────────────────────────────
# Settings (read from environment — override with .env + python-dotenv)
# ─────────────────────────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP    = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
DB_PATH            = os.getenv("DB_PATH", "agent_orchestrator.db")
SERVICE_NAME       = "agent-orchestrator-service"
SERVICE_VERSION    = "1.0.0"

try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.debug("Loaded .env file")
except ImportError:
    pass   # python-dotenv is optional


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: startup / shutdown
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Initialise shared resources on startup, tear them down on shutdown.
    All objects stored on app.state are available in dependencies via
    `request.app.state.<name>`.
    """
    logger.info("=== %s v%s starting up ===", SERVICE_NAME, SERVICE_VERSION)

    # -- Database ------------------------------------------------------------
    repo = SessionRepository(db_path=DB_PATH)
    await repo.connect()
    app.state.session_repo = repo

    # -- In-memory event store -----------------------------------------------
    store = EventStore(max_events_per_session=500)
    app.state.event_store = store

    # -- Kafka publisher (degrades gracefully if broker unavailable) ---------
    publisher = EventPublisher(bootstrap_servers=KAFKA_BOOTSTRAP, store=store)
    await publisher.start()
    app.state.event_publisher = publisher

    # -- Stateless services (constructed once, reused across requests) -------
    app.state.risk_engine   = RiskEngine()
    app.state.policy_client = PolicyClient()

    # ── LLM Client (optional — disabled gracefully if key not set) -────────
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_model   = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    if llm_api_key:
        from clients.llm_client import LLMClient
        app.state.llm_client = LLMClient(api_key=llm_api_key, model=llm_model)
        logger.info("LLMClient initialised: model=%s", llm_model)
    else:
        app.state.llm_client = None
        logger.info("LLM_API_KEY not set — LLM execution step disabled")

    # ── Guard + Output scanner → PromptProcessor ───────────────────────────
    guard_url   = os.getenv("GUARD_MODEL_URL", "")
    llm_scan_en = os.getenv("GUARD_LLM_SCAN_ENABLED", "false").lower() == "true"

    from clients.guard_client import GuardClient
    from clients.output_scanner import OutputScanner
    from services.prompt_processor import PromptProcessor

    guard_client   = GuardClient(base_url=guard_url or None)
    output_scanner = OutputScanner(
        guard_base_url=guard_url or None,
        llm_scan_enabled=llm_scan_en,
    )
    app.state.prompt_processor = PromptProcessor(
        guard_client=guard_client,
        output_scanner=output_scanner,
    )
    logger.info(
        "PromptProcessor initialised: guard_url=%s llm_scan=%s",
        guard_url or "regex-fallback",
        llm_scan_en,
    )

    logger.info("=== %s ready ===", SERVICE_NAME)
    yield

    # -- Teardown ------------------------------------------------------------
    logger.info("=== %s shutting down ===", SERVICE_NAME)
    await publisher.stop()
    await repo.close()
    logger.info("=== %s stopped ===", SERVICE_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Orchestrator Service",
        description=(
            "Central execution engine for AI agent sessions. "
            "Handles JWT auth, risk scoring, policy evaluation, "
            "session persistence, and Kafka event publishing."
        ),
        version=SERVICE_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Trace ID + RBAC access-log middleware ──────────────────────────────
    @app.middleware("http")
    async def trace_and_access_log_middleware(request: Request, call_next) -> Response:
        """
        Single middleware that:
          1. Assigns a correlation / trace ID to every request.
          2. After the response, emits a structured access-log line
             that includes the caller's user_id, roles, and groups
             (extracted from request.state.identity if auth ran successfully).
        """
        trace_id = (
            request.headers.get("X-Trace-ID")
            or request.headers.get("X-Request-ID")
            or str(uuid.uuid4())
        )
        request.state.trace_id = trace_id
        # Pre-set identity to None; get_current_identity will populate it
        request.state.identity = None

        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Trace-ID"] = trace_id

        # Extract identity if auth ran (populated by get_current_identity)
        identity = getattr(request.state, "identity", None)
        user_id  = identity.user_id  if identity else "anonymous"
        roles    = identity.roles     if identity else []
        groups   = identity.groups    if identity else []

        logger.info(
            "ACCESS %s %s %d %.1fms | user=%s roles=%s groups=%s | trace=%s",
            request.method, request.url.path,
            response.status_code, elapsed_ms,
            user_id, roles, groups, trace_id,
        )
        return response

    # ── Global validation error handler ────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger.warning("Validation error trace=%s errors=%s", trace_id, exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request body failed validation",
                    "trace_id": trace_id,
                    "details": exc.errors(),
                }
            },
        )

    # ── Catch-all handler ───────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger.exception("Unhandled exception trace=%s: %s", trace_id, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "trace_id": trace_id,
                }
            },
        )

    # ── Routers ─────────────────────────────────────────────────────────────
    app.include_router(sessions_router.router)

    # ── Health endpoints ────────────────────────────────────────────────────
    @app.get("/health", tags=["Observability"], summary="Liveness probe")
    async def health() -> dict:
        return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

    @app.get("/ready", tags=["Observability"], summary="Readiness probe")
    async def ready(request: Request) -> dict:
        db_ok = hasattr(request.app.state, "session_repo")
        store: EventStore = getattr(request.app.state, "event_store", None)
        return {
            "status": "ready" if db_ok else "not_ready",
            "db": "connected" if db_ok else "disconnected",
            "kafka": "connected" if request.app.state.event_publisher._available else "log_only",
            "event_store": {
                "sessions_tracked": store.session_count() if store else 0,
                "total_events": store.total_event_count() if store else 0,
            },
        }

    return app


app = create_app()
