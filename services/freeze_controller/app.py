"""
Freeze Controller — authenticated control-plane endpoint.

Requires: valid RS256 JWT + spm:admin role.
Supports: freeze/unfreeze of tenant, user, or session scope.
Supports: optional expiry (auto-unfreeze after N seconds).
"""
from __future__ import annotations
import logging
import time
import uuid
from typing import Optional

import redis
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from platform_shared.config import get_settings
from platform_shared.models import FreezeControlEvent, HealthStatus, ServiceInventory
from platform_shared.kafka_utils import build_producer, safe_send
from platform_shared.topics import topics_for_tenant
from platform_shared.security import extract_bearer_token, validate_jwt_token, require_admin_role
from platform_shared.audit import emit_audit

log = logging.getLogger("freeze-controller")
settings = get_settings()
_start_time = time.time()
_producer = None


def _get_producer():
    global _producer
    if _producer is None:
        _producer = build_producer()
    return _producer


def _get_redis() -> redis.Redis:
    kwargs = {"host": settings.redis_host, "port": settings.redis_port, "decode_responses": True}
    if settings.redis_password:
        kwargs["password"] = settings.redis_password
    return redis.Redis(**kwargs)


app = FastAPI(title="CPM Freeze Controller v3", version="3.0.0")


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class FreezeRequest(BaseModel):
    tenant_id: str
    scope: str             # tenant | user | session
    target: str            # tenant_id  OR  tenant_id:user_id  OR  session_id
    action: str            # freeze | unfreeze
    reason: str
    expires_in_seconds: Optional[int] = None  # auto-unfreeze after N seconds


class FreezeStatusResponse(BaseModel):
    tenant_id: str
    scope: str
    target: str
    frozen: bool
    expires_at: Optional[int]


# ─────────────────────────────────────────────────────────────────────────────
# Internal state helpers
# ─────────────────────────────────────────────────────────────────────────────

def _freeze_redis_key(scope: str, target: str) -> str:
    if scope == "tenant":
        return f"freeze:{target}:tenant"
    if scope == "user":
        return f"freeze:{target}"
    if scope == "session":
        return f"freeze:session:{target}"
    raise ValueError(f"Unknown scope: {scope}")


def _set_freeze_state(scope: str, target: str, action: str, expires_in: Optional[int]) -> None:
    r = _get_redis()
    key = _freeze_redis_key(scope, target)
    flag = "true" if action == "freeze" else "false"
    if expires_in and action == "freeze":
        r.set(key, flag, ex=expires_in)
    else:
        r.set(key, flag)
        if action == "unfreeze":
            r.delete(key)  # clean up entirely on unfreeze


def _get_freeze_state(scope: str, target: str) -> tuple[bool, Optional[int]]:
    r = _get_redis()
    key = _freeze_redis_key(scope, target)
    val = r.get(key)
    ttl = r.ttl(key)
    frozen = val == "true"
    expires_at = int(time.time()) + ttl if ttl > 0 else None
    return frozen, expires_at


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthStatus)
def health():
    return HealthStatus(
        status="ok",
        service="freeze_controller",
        version="3.0.0",
        checks={"kafka": True, "redis": True},
        uptime_seconds=int(time.time() - _start_time),
    )


@app.get("/inventory", response_model=ServiceInventory)
def inventory():
    return ServiceInventory(
        service="cpm-freeze-controller",
        version="3.0.0",
        dependencies=["kafka", "redis"],
        capabilities=["freeze_tenant", "freeze_user", "freeze_session", "auto_expiry"],
        environment=settings.environment,
    )


@app.post("/freeze")
def freeze(req: FreezeRequest, authorization: str = Header(None)):
    # Authentication + authorization
    token = extract_bearer_token(authorization)
    claims = validate_jwt_token(token)
    require_admin_role(claims)
    issued_by = claims.get("sub", "unknown")

    # Validate scope
    if req.scope not in ("tenant", "user", "session"):
        raise HTTPException(status_code=400, detail=f"Invalid scope: {req.scope}")
    if req.action not in ("freeze", "unfreeze"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {req.action}")

    # Apply to Redis immediately (consumers also receive via Kafka)
    _set_freeze_state(req.scope, req.target, req.action, req.expires_in_seconds)

    # Emit Kafka event for all consumers to process
    freeze_id = str(uuid.uuid4())
    expires_at = int(time.time()) + req.expires_in_seconds if req.expires_in_seconds else None
    event = FreezeControlEvent(
        scope=req.scope,
        target=req.target,
        action=req.action,
        reason=req.reason,
        ts=int(time.time() * 1000),
        issued_by=issued_by,
        expires_at=expires_at,
        freeze_id=freeze_id,
    )

    topics = topics_for_tenant(req.tenant_id)
    success = safe_send(_get_producer(), topics.freeze_control, event.model_dump())

    emit_audit(
        req.tenant_id, "freeze-controller", f"freeze_{req.action}",
        principal=issued_by,
        severity="warning" if req.action == "freeze" else "info",
        details={
            "scope": req.scope,
            "target": req.target,
            "reason": req.reason,
            "expires_at": expires_at,
            "freeze_id": freeze_id,
            "kafka_sent": success,
        },
    )

    log.info(
        "Freeze %s: scope=%s target=%s by=%s reason=%s",
        req.action, req.scope, req.target, issued_by, req.reason,
    )

    return {
        "status": "ok",
        "freeze_id": freeze_id,
        "action": req.action,
        "scope": req.scope,
        "target": req.target,
        "expires_at": expires_at,
    }


@app.get("/freeze/status")
def freeze_status(
    scope: str,
    target: str,
    authorization: str = Header(None),
):
    token = extract_bearer_token(authorization)
    claims = validate_jwt_token(token)
    require_admin_role(claims)

    frozen, expires_at = _get_freeze_state(scope, target)
    return FreezeStatusResponse(
        tenant_id=claims.get("tenant_id", "unknown"),
        scope=scope,
        target=target,
        frozen=frozen,
        expires_at=expires_at,
    )
