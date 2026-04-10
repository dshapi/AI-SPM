"""
Memory Service — scoped key-value store with integrity verification.

Namespaces:
  session   — short TTL, per-session, standard scopes
  longterm  — long TTL, cross-session, elevated scopes
  system    — platform-internal, spm:admin only

All writes produce a SHA-256 hash stored alongside the value.
All reads verify the hash — returns integrity_ok=False if tampered.
Deletes are soft (tombstone) to preserve audit trail.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
import time
import redis
from platform_shared.base_service import ConsumerService
from platform_shared.config import get_settings
from platform_shared.models import MemoryRequest, MemoryResult, MemoryNamespace
from platform_shared.topics import topics_for_tenant
from platform_shared.opa_client import get_opa_client
from platform_shared.audit import emit_audit, emit_security_alert
from platform_shared.kafka_utils import safe_send, send_event

log = logging.getLogger("memory-service")
settings = get_settings()

_UNSAFE_CONTENT_RE = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions"
    r"|developer\s+message"
    r"|system\s+prompt"
    r"|act\s+as\s+if"
    r"|pretend\s+you\s+are"
    r"|new\s+instructions?\s*:"
    r"|override\s+(your\s+)?instructions?"
    r"|disregard\s+(the\s+)?context"
    r"|forget\s+everything)",
    re.IGNORECASE,
)

_TTL_MAP = {
    MemoryNamespace.SESSION: lambda: settings.memory_session_ttl,
    MemoryNamespace.LONGTERM: lambda: settings.memory_longterm_ttl,
    MemoryNamespace.SYSTEM: lambda: settings.memory_system_ttl,
}


def _get_redis() -> redis.Redis:
    kwargs = {"host": settings.redis_host, "port": settings.redis_port, "decode_responses": True}
    if settings.redis_password:
        kwargs["password"] = settings.redis_password
    return redis.Redis(**kwargs)


def _store_key(tenant_id: str, user_id: str, namespace: str, key: str) -> str:
    return f"mem:{tenant_id}:{user_id}:{namespace}:{key}"


def _hash_key(sk: str) -> str:
    return f"{sk}:sha256"


def _tombstone_key(sk: str) -> str:
    return f"{sk}:tombstone"


def _meta_key(sk: str) -> str:
    return f"{sk}:meta"


def _compute_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MemoryService(ConsumerService):
    service_name = "memory-service"

    def __init__(self):
        t = topics_for_tenant("t1")
        super().__init__([t.memory_request, t.freeze_control], "cpm-memory")
        self._redis = _get_redis()
        self._opa = get_opa_client()

    def _opa_check(self, req: MemoryRequest) -> dict:
        return self._opa.eval(
            "/v1/data/spm/memory/allow",
            {
                "operation": req.operation,
                "namespace": req.namespace,
                "posture_score": req.posture_score,
                "signals": req.metadata.get("signals", []),
                "auth_context": req.auth_context.model_dump(),
            },
        )

    def _read(self, req: MemoryRequest, sk: str) -> MemoryResult:
        r = self._redis

        # Check tombstone
        if r.exists(_tombstone_key(sk)):
            return MemoryResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                operation=req.operation, namespace=req.namespace,
                status="not_found", reason="key was deleted",
            )

        raw = r.get(sk)
        if raw is None:
            return MemoryResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                operation=req.operation, namespace=req.namespace,
                status="not_found", reason="key not found",
            )

        stored_hash = r.get(_hash_key(sk))
        integrity_ok = stored_hash == _compute_hash(raw) if stored_hash else False

        if not integrity_ok:
            emit_security_alert(
                req.tenant_id, self.service_name, "memory_integrity_violation",
                ttp_codes=["AML.T0048"],
                event_id=req.event_id, principal=req.user_id,
                session_id=req.session_id,
                details={"namespace": req.namespace, "hash_mismatch": True},
            )

        return MemoryResult(
            event_id=req.event_id, tenant_id=req.tenant_id,
            user_id=req.user_id, session_id=req.session_id,
            operation=req.operation, namespace=req.namespace,
            status="ok", value=raw, reason="ok",
            memory_risk=0.0 if integrity_ok else 0.30,
            integrity_ok=integrity_ok,
        )

    def _write(self, req: MemoryRequest, sk: str) -> MemoryResult:
        value = req.value or ""

        # Content safety check
        if _UNSAFE_CONTENT_RE.search(value):
            emit_security_alert(
                req.tenant_id, self.service_name, "memory_injection_attempt",
                ttp_codes=["AML.T0051.000"],
                event_id=req.event_id, principal=req.user_id,
                session_id=req.session_id,
                details={"namespace": req.namespace},
            )
            return MemoryResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                operation=req.operation, namespace=req.namespace,
                status="denied", reason="unsafe content detected in write value",
                memory_risk=0.60,
            )

        # TTL from namespace
        ttl = _TTL_MAP.get(req.namespace, lambda: settings.memory_session_ttl)()
        if req.ttl_override:
            ttl = min(req.ttl_override, ttl)  # never extend beyond namespace max

        content_hash = _compute_hash(value)
        meta = json.dumps({
            "written_at": int(time.time()),
            "written_by": req.user_id,
            "namespace": req.namespace,
            "posture_score_at_write": req.posture_score,
        })

        pipe = self._redis.pipeline()
        pipe.set(sk, value, ex=ttl)
        pipe.set(_hash_key(sk), content_hash, ex=ttl)
        pipe.set(_meta_key(sk), meta, ex=ttl)
        pipe.execute()

        return MemoryResult(
            event_id=req.event_id, tenant_id=req.tenant_id,
            user_id=req.user_id, session_id=req.session_id,
            operation=req.operation, namespace=req.namespace,
            status="ok", value=value, reason="write ok",
            integrity_ok=True,
        )

    def _delete(self, req: MemoryRequest, sk: str) -> MemoryResult:
        tombstone_ttl = settings.memory_longterm_ttl

        pipe = self._redis.pipeline()
        pipe.delete(sk)
        pipe.delete(_hash_key(sk))
        pipe.set(
            _tombstone_key(sk),
            json.dumps({"deleted_at": int(time.time()), "deleted_by": req.user_id}),
            ex=tombstone_ttl,
        )
        pipe.execute()

        return MemoryResult(
            event_id=req.event_id, tenant_id=req.tenant_id,
            user_id=req.user_id, session_id=req.session_id,
            operation=req.operation, namespace=req.namespace,
            status="ok", reason="soft-deleted",
        )

    def _list(self, req: MemoryRequest) -> MemoryResult:
        """List all keys in a namespace for this user (for admin/debugging)."""
        pattern = f"mem:{req.tenant_id}:{req.user_id}:{req.namespace}:*"
        # Exclude hash, tombstone, meta keys
        all_keys = [
            k for k in self._redis.scan_iter(pattern)
            if not any(k.endswith(s) for s in (":sha256", ":tombstone", ":meta"))
        ]
        return MemoryResult(
            event_id=req.event_id, tenant_id=req.tenant_id,
            user_id=req.user_id, session_id=req.session_id,
            operation=req.operation, namespace=req.namespace,
            status="ok", reason="list ok",
            keys=[k.split(":")[-1] for k in all_keys],
        )

    def handle(self, payload: dict) -> None:
        if "scope" in payload:
            return  # freeze control

        req = MemoryRequest(**payload)
        topics = topics_for_tenant(req.tenant_id)

        # OPA access check
        opa_result = self._opa_check(req)
        if opa_result.get("decision") != "allow":
            mem = MemoryResult(
                event_id=req.event_id, tenant_id=req.tenant_id,
                user_id=req.user_id, session_id=req.session_id,
                operation=req.operation, namespace=req.namespace,
                status="denied", reason=opa_result.get("reason", "denied"),
                memory_risk=0.50,
            )
        else:
            sk = _store_key(req.tenant_id, req.user_id, req.namespace, req.key)
            if req.operation == "read":
                mem = self._read(req, sk)
            elif req.operation == "write":
                mem = self._write(req, sk)
            elif req.operation == "delete":
                mem = self._delete(req, sk)
            elif req.operation == "list":
                mem = self._list(req)
            else:
                mem = MemoryResult(
                    event_id=req.event_id, tenant_id=req.tenant_id,
                    user_id=req.user_id, session_id=req.session_id,
                    operation=req.operation, namespace=req.namespace,
                    status="error", reason=f"unknown operation: {req.operation}",
                )

        send_event(
            self.producer, topics.memory_result, mem,
            event_type="memory.result",
            source_service="memory-service",
        )

        emit_audit(
            req.tenant_id, self.service_name, "memory_op",
            event_id=req.event_id, principal=req.user_id,
            session_id=req.session_id,
            correlation_id=req.event_id,
            details={
                "operation": req.operation,
                "namespace": req.namespace,
                "status": mem.status,
                "integrity_ok": mem.integrity_ok,
            },
        )


if __name__ == "__main__":
    MemoryService().run()
