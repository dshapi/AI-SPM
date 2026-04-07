"""
API Service — platform ingress.

Responsibilities:
- RS256 JWT validation
- Per-user rate limiting (sliding window)
- Guard model pre-screen (blocks before touching Kafka)
- Model gate check (SPM — fail-closed)
- RawEvent construction and publication to Kafka
- /health, /inventory, /rate-limit-status endpoints
"""
from __future__ import annotations
import os
import time
import uuid
import logging
from contextlib import asynccontextmanager

import httpx
import redis as redis_lib
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from platform_shared.config import get_settings
from platform_shared.models import AuthContext, RawEvent, HealthStatus, ServiceInventory
from platform_shared.security import (
    extract_bearer_token,
    validate_jwt_token,
    check_rate_limit,
    get_rate_limit_status,
)
from platform_shared.kafka_utils import build_producer, safe_send
from platform_shared.topics import topics_for_tenant
from platform_shared.audit import emit_audit

log = logging.getLogger("api")
settings = get_settings()
_start_time = time.time()
_producer = None

OPA_URL_FOR_GATE = os.getenv("OPA_URL", "http://opa:8181")
_redis_gate_client = None


def get_producer():
    global _producer
    if _producer is None:
        _producer = build_producer()
    return _producer


def _get_gate_redis():
    global _redis_gate_client
    if _redis_gate_client is None:
        _redis_gate_client = redis_lib.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=True,
        )
    return _redis_gate_client


async def _check_model_gate(model_id: str, tenant_id: str) -> bool:
    """Returns True if model is approved, False if blocked. Fail-closed.
    Uses httpx directly because OPAClient casts boolean OPA results to {} (non-dict).
    """
    if not model_id:
        return True  # backward compat: no model_id = skip gate

    cache_key = f"spm:model_gate:{model_id}:{tenant_id}"
    try:
        cached = _get_gate_redis().get(cache_key)
        if cached is not None:
            return cached == "approved"
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            resp = await client.post(
                f"{OPA_URL_FOR_GATE}/v1/data/model_policy/allow",
                json={"input": {"model_id": model_id, "tenant_id": tenant_id}},
            )
        if resp.status_code != 200:
            return False  # fail-closed
        data = resp.json()
        raw = data.get("result")
        if isinstance(raw, bool):
            allowed = raw
        elif isinstance(raw, dict):
            allowed = raw.get("allowed", False)
        else:
            allowed = False
        try:
            _get_gate_redis().setex(cache_key, 30, "approved" if allowed else "blocked")
        except Exception:
            pass
        return allowed
    except Exception:
        return False  # fail-closed on timeout/network error


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("API service starting...")
    get_producer()  # warm up producer
    yield
    log.info("API service shutting down...")
    if _producer:
        _producer.close()


app = FastAPI(
    title="CPM API v3",
    description="Context Posture Management — Ingress Service",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    prompt: str
    session_id: str
    metadata: dict = {}

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "What meetings do I have today?",
                "session_id": "session-abc-123",
                "metadata": {},
            }
        }


class ChatResponse(BaseModel):
    event_id: str
    status: str
    guard_verdict: str
    message: str = "Request accepted and queued for processing"


# ─────────────────────────────────────────────────────────────────────────────
# Guard model call
# ─────────────────────────────────────────────────────────────────────────────

async def _call_guard_model(prompt: str) -> tuple[str, float, list[str]]:
    """
    Call guard model service.
    Returns (verdict, score, categories).
    Fails open (flag, 0.5) if guard model is unavailable.
    """
    if not settings.guard_model_enabled:
        return "allow", 0.0, []

    try:
        async with httpx.AsyncClient(timeout=settings.guard_model_timeout) as client:
            resp = await client.post(
                f"{settings.guard_model_url}/screen",
                json={"text": prompt, "context": "user_input"},
            )
            resp.raise_for_status()
            data = resp.json()
            return (
                data.get("verdict", "allow"),
                float(data.get("score", 0.0)),
                data.get("categories", []),
            )
    except httpx.TimeoutException:
        log.warning("Guard model timeout — failing open with flag")
        return "flag", 0.5, ["timeout"]
    except Exception as e:
        log.warning("Guard model unavailable: %s — failing open with flag", e)
        return "flag", 0.3, ["unavailable"]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthStatus)
async def health():
    checks = {
        "kafka": True,
        "guard_model": settings.guard_model_enabled,
    }
    try:
        get_producer()
    except Exception:
        checks["kafka"] = False

    return HealthStatus(
        status="ok" if all(checks.values()) else "degraded",
        service="api",
        version="3.0.0",
        checks=checks,
        uptime_seconds=int(time.time() - _start_time),
    )


@app.get("/inventory", response_model=ServiceInventory)
async def inventory():
    return ServiceInventory(
        service="cpm-api",
        version="3.0.0",
        model=None,
        dependencies=["kafka", "redis", "guard_model"],
        capabilities=["ingress", "jwt_validation", "rate_limiting", "guard_gate"],
        environment=settings.environment,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    authorization: str = Header(None),
):
    # 1. JWT validation
    token = extract_bearer_token(authorization)
    claims = validate_jwt_token(token)

    tenant_id: str = claims.get("tenant_id", "t1")
    user_id: str = claims.get("sub", "unknown")

    # 2. Rate limiting
    check_rate_limit(tenant_id, user_id)

    # 3. Guard model pre-screen
    guard_verdict, guard_score, guard_categories = await _call_guard_model(req.prompt)

    if guard_verdict == "block":
        emit_audit(
            tenant_id, "api", "guard_model_block",
            principal=user_id,
            severity="warning",
            details={
                "guard_score": guard_score,
                "categories": guard_categories,
                "prompt_len": len(req.prompt),
                "session_id": req.session_id,
            },
        )
        raise HTTPException(
            status_code=400,
            detail=f"Request blocked by content policy: {', '.join(guard_categories)}",
        )

    # 3b. Model gate (SPM) — fail-closed
    _model_id = os.getenv("LLM_MODEL_ID")
    if _model_id and not await _check_model_gate(_model_id, tenant_id):
        emit_audit(tenant_id, "api", "model_gate_block",
                   principal=user_id,
                   details={"model_id": _model_id, "session_id": req.session_id})
        raise HTTPException(status_code=403,
                            detail={"error": "model_not_approved", "model_id": _model_id})

    # 4. Build and publish RawEvent
    auth_context = AuthContext(
        sub=user_id,
        tenant_id=tenant_id,
        roles=claims.get("roles", []),
        scopes=claims.get("scopes", []),
        claims={k: v for k, v in claims.items()
                if k not in ("sub", "tenant_id", "roles", "scopes")},
        issued_at=claims.get("iat", int(time.time())),
        expires_at=claims.get("exp"),
    )

    event = RawEvent(
        event_id=str(uuid.uuid4()),
        ts=int(time.time() * 1000),
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=req.session_id,
        prompt=req.prompt,
        metadata=req.metadata,
        auth_context=auth_context,
        guard_verdict=guard_verdict,
        guard_score=guard_score,
        guard_categories=guard_categories,
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    topics = topics_for_tenant(tenant_id)
    success = safe_send(get_producer(), topics.raw, event.model_dump())

    if not success:
        raise HTTPException(status_code=503, detail="Event queue unavailable")

    emit_audit(
        tenant_id, "api", "event_ingested",
        event_id=event.event_id,
        principal=user_id,
        session_id=req.session_id,
        details={
            "guard_verdict": guard_verdict,
            "guard_score": guard_score,
            "guard_categories": guard_categories,
            "prompt_len": len(req.prompt),
        },
    )

    return ChatResponse(
        event_id=event.event_id,
        status="accepted",
        guard_verdict=guard_verdict,
    )


@app.get("/rate-limit-status")
async def rate_limit_status(authorization: str = Header(None)):
    token = extract_bearer_token(authorization)
    claims = validate_jwt_token(token)
    tenant_id = claims.get("tenant_id", "t1")
    user_id = claims.get("sub", "unknown")
    return get_rate_limit_status(tenant_id, user_id)
