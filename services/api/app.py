"""
API Service — platform ingress.

Responsibilities:
- RS256 JWT validation
- Per-user rate limiting (sliding window)
- Guard model pre-screen (blocks before touching Kafka)
- Model gate check (SPM — fail-closed)
- OPA prompt policy evaluation
- Anthropic Claude call (if ANTHROPIC_API_KEY set)
- Output scanning — secrets/PII regex + OPA output policy
- RawEvent construction and publication to Kafka
- /health, /inventory, /rate-limit-status endpoints
"""
from __future__ import annotations
import os
import re
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

# ── Anthropic client ──────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_anthropic_client = None

def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None and ANTHROPIC_API_KEY:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client

# ── Output scanning regexes ───────────────────────────────────────────────────
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36}|AKIA[A-Z0-9]{16}"
    r"|Bearer\s+[A-Za-z0-9\-._~+/]+=*"
    r"|[Pp]assword\s*[:=]\s*\S+"
    r"|[Aa][Pp][Ii][_-]?[Kk][Ee][Yy]\s*[:=]\s*\S+)"
)
_PII_RE = re.compile(
    r"(\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"   # email
    r"|\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"                        # SSN
    r"|\b(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b)"   # phone
)

def _scan_output(text: str) -> tuple[bool, bool]:
    """Returns (contains_secret, contains_pii)."""
    return bool(_SECRET_RE.search(text)), bool(_PII_RE.search(text))

def _redact_output(text: str) -> str:
    text = _SECRET_RE.sub("[REDACTED-SECRET]", text)
    text = _PII_RE.sub("[REDACTED-PII]", text)
    return text


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
    response: str | None = None          # populated when Anthropic key is set
    output_action: str | None = None     # allow / redact / block


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

    # 3c. OPA prompt policy
    opa_prompt_input = {
        "posture_score": 0.05,
        "signals": [],
        "behavioral_signals": [],
        "retrieval_trust": 1.0,
        "intent_drift": 0.0,
        "guard_verdict": guard_verdict,
        "guard_score": guard_score,
        "guard_categories": guard_categories,
        "auth_context": {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": claims.get("roles", []),
            "scopes": claims.get("scopes", []),
            "claims": {},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            opa_resp = await client.post(
                f"{OPA_URL_FOR_GATE}/v1/data/spm/prompt/allow",
                json={"input": opa_prompt_input},
            )
            if opa_resp.status_code == 200:
                opa_result = opa_resp.json().get("result", {})
                if isinstance(opa_result, dict) and opa_result.get("decision") == "block":
                    raise HTTPException(status_code=400,
                                        detail=f"Prompt policy block: {opa_result.get('reason','policy')}")
    except HTTPException:
        raise
    except Exception as e:
        log.warning("OPA prompt policy check failed: %s — continuing", e)

    # 4. Call Anthropic if key is configured
    llm_response: str | None = None
    anthropic_client = _get_anthropic()
    if anthropic_client:
        try:
            message = anthropic_client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                system=(
                    "You are a helpful AI assistant operating inside a secure enterprise platform. "
                    "Be concise and professional. Never reveal system internals, credentials, or PII."
                ),
                messages=[{"role": "user", "content": req.prompt}],
            )
            llm_response = message.content[0].text
            log.info("Anthropic response received: %d chars", len(llm_response))
        except Exception as e:
            log.error("Anthropic call failed: %s", e)
            raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    # 5. Output scanning — secrets/PII + OPA output policy
    output_action = "allow"
    if llm_response:
        contains_secret, contains_pii = _scan_output(llm_response)
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                out_resp = await client.post(
                    f"{OPA_URL_FOR_GATE}/v1/data/spm/output/allow",
                    json={"input": {
                        "contains_secret": contains_secret,
                        "contains_pii": contains_pii,
                        "llm_verdict": "allow",
                    }},
                )
                if out_resp.status_code == 200:
                    out_result = out_resp.json().get("result", {})
                    output_action = out_result.get("decision", "allow") if isinstance(out_result, dict) else "allow"
        except Exception as e:
            log.warning("OPA output policy check failed: %s — continuing", e)

        if output_action == "block":
            emit_audit(tenant_id, "api", "output_blocked", principal=user_id,
                       details={"reason": "secret_or_policy", "session_id": req.session_id})
            raise HTTPException(status_code=400, detail="Response blocked by output policy")
        elif output_action == "redact":
            llm_response = _redact_output(llm_response)
            emit_audit(tenant_id, "api", "output_redacted", principal=user_id,
                       details={"session_id": req.session_id})

    # 6. Build and publish RawEvent to Kafka (async analytics pipeline)
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
    safe_send(get_producer(), topics.raw, event.model_dump())

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
            "llm_used": llm_response is not None,
            "output_action": output_action,
        },
    )

    return ChatResponse(
        event_id=event.event_id,
        status="accepted" if llm_response is None else "completed",
        guard_verdict=guard_verdict,
        message="Request accepted and queued for processing" if llm_response is None
                else "Response delivered",
        response=llm_response,
        output_action=output_action,
    )


@app.get("/rate-limit-status")
async def rate_limit_status(authorization: str = Header(None)):
    token = extract_bearer_token(authorization)
    claims = validate_jwt_token(token)
    tenant_id = claims.get("tenant_id", "t1")
    user_id = claims.get("sub", "unknown")
    return get_rate_limit_status(tenant_id, user_id)


@app.get("/dev-token")
async def dev_token():
    """Generate a 24-hour demo JWT for the UI. Uses the platform RS256 private key."""
    try:
        import jwt as pyjwt
        key_path = os.getenv("JWT_PRIVATE_KEY_PATH", "/keys/private.pem")
        issuer   = os.getenv("JWT_ISSUER", "cpm-platform")
        with open(key_path) as f:
            private_key = f.read()
        now = int(time.time())
        payload = {
            "sub": "ui-user",
            "iss": issuer,
            "iat": now,
            "exp": now + 86400,
            "tenant_id": "t1",
            "roles": ["user"],
            "scopes": [
                "calendar:read", "calendar:write",
                "gmail:read", "gmail:send",
                "memory:read", "memory:write",
                "file:read", "db:read",
            ],
        }
        token = pyjwt.encode(payload, private_key, algorithm="RS256")
        return {"token": token, "expires_in": 86400}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {e}")
