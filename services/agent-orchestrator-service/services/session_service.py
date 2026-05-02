"""
services/session_service.py
────────────────────────────
SessionService: full pipeline with per-step lifecycle event emission.

Pipeline steps:
  1. prompt.received     — record prompt hash
  2. pre-screen          — guard model content check (optional)
  3. risk.calculated     — multi-dimensional risk scoring
  4. policy.decision     — OPA/local policy evaluation
  5. llm.response        — LLM execution (if allowed, optional)
  6. output.scanned      — PII/secret scan on LLM output (optional)
  7. persist             — write session to database
  8. session.created/blocked — lifecycle event
  9. audit trail         — compliance audit emission
  10. session.completed  — final summary event

The EventStore is queried for read operations; no extra DB round-trips
for the event timeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Coroutine, List, Optional
from uuid import UUID, uuid4


# ─────────────────────────────────────────────────────────────────────────────
# Fire-and-forget helper
# ─────────────────────────────────────────────────────────────────────────────
# Kafka emits, audit writes, and other "tell observers what happened" calls
# don't gate the user's response. Detaching them to background tasks moves
# them off the critical path so the chat round-trip ends as soon as the
# LLM + output scan complete.
#
# Tasks are kept in a module-level set so the event loop can't garbage-collect
# them mid-flight, and exceptions are logged instead of becoming
# "Task exception was never retrieved" warnings.
_BG_TASKS: set[asyncio.Task[Any]] = set()


def _detach(coro: Coroutine[Any, Any, Any], *, name: str) -> None:
    """Schedule a background task and log any exception it raises."""
    task = asyncio.create_task(coro, name=name)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)

    def _log_failure(t: asyncio.Task[Any]) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logging.getLogger(__name__).warning(
                "background task %r failed: %s", name, exc,
            )
    task.add_done_callback(_log_failure)

from clients.policy_client import PolicyClient, PolicyResult
from dependencies.auth import IdentityContext
from events.publisher import EventPublisher
from events.store import EventStore
from models.event import EventRecord, EventRepository
from models.session import SessionRecord, SessionRepository
from schemas.events import (
    EventType,
    PolicyDecisionPayload,
    PromptReceivedPayload,
    RiskCalculatedPayload,
    SessionBlockedPayload,
    SessionCompletedPayload,
    SessionCreatedPayload,
    SessionLifecycleEvent,
)
from schemas.session import (
    CreateSessionRequest,
    PolicyDecision,
    SessionStatus,
    RiskTier,
)
from services.risk_engine import RiskEngine, RiskResult
from services.prompt_processor import PromptProcessor
from services.audit_service import AuditService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Typed result returned to the router
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionCreationResult:
    session_id: UUID
    status: SessionStatus
    risk: RiskResult
    policy: PolicyResult
    created_at: datetime
    duration_ms: float
    event_count: int


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class SessionService:
    """
    Orchestrates the full session-creation pipeline.
    All collaborators are constructor-injected for easy unit testing.
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        policy_client: PolicyClient,
        event_publisher: EventPublisher,
        session_repo: SessionRepository,
        event_store: EventStore,
        llm_client=None,        # LLMClient | MockLLMClient | None
        prompt_processor=None,  # PromptProcessor | None
        event_repo=None,        # EventRepository | None
    ) -> None:
        self._risk       = risk_engine
        self._policy     = policy_client
        self._publisher  = event_publisher
        self._repo       = session_repo
        self._store      = event_store
        self._llm        = llm_client
        self._processor  = prompt_processor
        self._event_repo = event_repo

    # ─────────────────────────────────────────────────────────────────────
    # Create session — full 10-step pipeline
    # ─────────────────────────────────────────────────────────────────────

    async def create_session(
        self,
        request: CreateSessionRequest,
        identity: IdentityContext,
        trace_id: str,
    ) -> SessionCreationResult:
        import hashlib
        t_start = time.perf_counter()
        session_id = uuid4()
        tenant_id = identity.tenant_id or "default"

        # Per-request AuditService bound to caller's tenant
        audit = AuditService(tenant_id=tenant_id)

        # ── Step 1: prompt.received ────────────────────────────────────────
        prompt_hash = hashlib.sha256(request.prompt.encode()).hexdigest()
        await self._publisher.emit_prompt_received(
            payload=PromptReceivedPayload(
                session_id=session_id,
                agent_id=request.agent_id,
                user_id=identity.user_id,
                user_email=identity.email or request.context.get("email"),
                user_name=request.context.get("name"),
                tenant_id=tenant_id,
                prompt_hash=prompt_hash,
                prompt_len=len(request.prompt),
                prompt=request.prompt,
                tools=request.tools,
                context_keys=list(request.context.keys()),
            ),
            correlation_id=trace_id,
        )

        # ── Step 2: pre-screen (guard model) ──────────────────────────────
        guard_verdict = "allow"
        guard_score = 0.0
        if self._processor:
            try:
                pre = await self._processor.pre_screen(request.prompt)
                guard_verdict = pre.verdict
                guard_score = pre.score
                logger.info(
                    "pre_screen session=%s verdict=%s score=%.4f",
                    session_id, guard_verdict, guard_score,
                )
            except Exception as exc:
                logger.warning(
                    "pre_screen failed session=%s: %s — treating as allow",
                    session_id, exc,
                )

        # ── Step 3: risk scoring ───────────────────────────────────────────
        try:
            risk = self._risk.score(
                prompt=request.prompt,
                tools=request.tools,
                agent_id=request.agent_id,
                context=request.context,
                roles=identity.roles,
                scopes=[],
                guard_verdict=guard_verdict,
                guard_score=guard_score,
            )
        except Exception as exc:
            logger.exception(
                "Risk scoring failed session=%s: %s — falling back to MEDIUM",
                session_id, exc,
            )
            risk = RiskResult(
                score=0.5,
                tier=RiskTier.MEDIUM,
                signals=["risk_engine_error"],
                ttps=[],
                prompt_hash="",
            )
        await self._publisher.emit_risk_calculated(
            payload=RiskCalculatedPayload(
                session_id=session_id,
                risk_score=risk.score,
                risk_tier=risk.tier.value,
                signals=risk.signals,
            ),
            correlation_id=trace_id,
        )

        # ── Step 4: policy evaluation ──────────────────────────────────────
        policy = await self._policy.evaluate(
            identity=identity,
            risk=risk,
            agent_id=request.agent_id,
            tools=request.tools,
        )
        await self._publisher.emit_policy_decision(
            payload=PolicyDecisionPayload(
                session_id=session_id,
                decision=policy.decision.value,
                reason=policy.reason,
                policy_version=policy.policy_version,
                risk_score_at_decision=risk.score,
                # Forward named-policy + guard-score attribution from
                # PolicyClient so the Runtime page renders a real policy
                # label + score the rule used, instead of the "Unresolved
                # Policy" + "v1.4.2 Allowed" fallback.
                policy_name=policy.policy_name,
                guard_score=policy.guard_score,
            ),
            correlation_id=trace_id,
        )

        # ── Step 5: LLM execution (only if allowed) ────────────────────────
        llm_text = ""
        if policy.is_allowed and self._llm:
            llm_t0 = time.perf_counter()
            try:
                llm_resp = await self._llm.complete(request.prompt)
                llm_latency_ms = int((time.perf_counter() - llm_t0) * 1000)
                llm_text = llm_resp.text
            except Exception as exc:
                logger.exception("LLM call failed session=%s: %s", session_id, exc)
            else:
                try:
                    await self._publisher.emit_llm_response(
                        session_id=session_id,
                        correlation_id=trace_id,
                        model=llm_resp.model,
                        input_tokens=llm_resp.input_tokens,
                        output_tokens=llm_resp.output_tokens,
                        stop_reason=llm_resp.stop_reason,
                        response_length=len(llm_text),
                        latency_ms=llm_latency_ms,
                    )
                except Exception as exc:
                    logger.warning(
                        "emit_llm_response failed session=%s: %s",
                        session_id, exc,
                    )

        # ── Step 6: output scan (only if LLM ran) ─────────────────────────
        if llm_text and self._processor:
            try:
                post = await self._processor.post_scan_async(llm_text)
                await self._publisher.emit_output_scanned(
                    session_id=session_id,
                    correlation_id=trace_id,
                    verdict=post.verdict,
                    pii_types=post.pii_types,
                    secret_types=post.secret_types,
                    scan_notes=post.scan_notes,
                )
                if post.blocked:
                    logger.warning(
                        "Output blocked session=%s notes=%s", session_id, post.scan_notes
                    )
                    await audit.security_alert(
                        "secret_in_output",
                        ttp_codes=["AML.T0048"],
                        session_id=str(session_id),
                        principal=identity.user_id,
                    )
            except Exception as exc:
                logger.exception(
                    "Output scan failed session=%s: %s — continuing without scan",
                    session_id, exc,
                )

        # ── Step 7: persist session ────────────────────────────────────────
        now = datetime.now(timezone.utc)
        session_status = SessionStatus.BLOCKED if policy.decision == PolicyDecision.BLOCK else SessionStatus.STARTED

        record = SessionRecord(
            session_id=str(session_id),
            agent_id=request.agent_id,
            user_id=identity.user_id,
            tenant_id=tenant_id,
            prompt_hash=prompt_hash,
            tools=request.tools,
            context=request.context,
            status=session_status.value,
            risk_score=risk.score,
            risk_tier=risk.tier.value,
            risk_signals=risk.signals,
            policy_decision=policy.decision.value,
            policy_reason=policy.reason,
            policy_version=policy.policy_version,
            trace_id=trace_id,
            created_at=now,
            updated_at=now,
        )
        await self._repo.insert(record)

        if self._event_repo:
            try:
                import json as _json
                current_events = await self._store.get_events(session_id)
                # EventType is `str, Enum` so .value gives the plain string.
                # e.payload is Dict[str, Any]; json.dumps serialises it to Text.
                event_records = [
                    EventRecord(
                        session_id=str(session_id),
                        event_type=e.event_type.value,
                        payload=_json.dumps(e.payload),
                        timestamp=e.timestamp,
                    )
                    for e in current_events
                ]
                await self._event_repo.bulk_insert(event_records)
                logger.debug(
                    "Persisted %d events for session=%s", len(event_records), session_id
                )
            except Exception as exc:
                logger.warning(
                    "Event persistence failed session=%s: %s — continuing",
                    session_id, exc,
                )

        # ── Step 8: session.created / session.blocked ──────────────────────
        if policy.is_allowed:
            await self._publisher.emit_session_created(
                payload=SessionCreatedPayload(
                    session_id=session_id,
                    agent_id=request.agent_id,
                    user_id=identity.user_id,
                    tenant_id=tenant_id,
                    prompt_hash=prompt_hash,
                    tools=request.tools,
                    risk_score=risk.score,
                    risk_tier=risk.tier.value,
                    policy_decision=policy.decision.value,
                    policy_version=policy.policy_version,
                ),
                correlation_id=trace_id,
                tenant_id=tenant_id,
            )
        else:
            await self._publisher.emit_session_blocked(
                payload=SessionBlockedPayload(
                    session_id=session_id,
                    agent_id=request.agent_id,
                    user_id=identity.user_id,
                    reason=policy.reason,
                    policy_version=policy.policy_version,
                    risk_score=risk.score,
                ),
                correlation_id=trace_id,
            )

        # ── Step 9: audit trail ────────────────────────────────────────────
        await audit.emit(
            "session_lifecycle_complete",
            session_id=str(session_id),
            principal=identity.user_id,
            severity="info" if policy.is_allowed else "warning",
            details={
                "risk_score": risk.score,
                "risk_tier": risk.tier.value,
                "policy_decision": policy.decision.value,
                "guard_verdict": guard_verdict,
            },
        )

        # ── Step 10: session.completed ─────────────────────────────────────
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        events = await self._store.get_events(session_id)
        await self._publisher.emit_session_completed(
            payload=SessionCompletedPayload(
                session_id=session_id,
                final_status=session_status.value,
                policy_decision=policy.decision.value,
                risk_score=risk.score,
                duration_ms=duration_ms,
                event_count=len(events),
            ),
            correlation_id=trace_id,
        )

        logger.info(
            "SessionService pipeline done: session=%s status=%s duration=%dms events=%d",
            session_id, session_status.value, duration_ms, len(events),
        )

        return SessionCreationResult(
            session_id=session_id,
            status=session_status,
            risk=risk,
            policy=policy,
            created_at=now,
            duration_ms=duration_ms,
            event_count=len(events),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Read operations
    # ─────────────────────────────────────────────────────────────────────

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return await self._repo.get_by_id(session_id)

    async def get_events(self, session_id: str) -> List[SessionLifecycleEvent]:
        """
        Return lifecycle events for a session.

        Priority: DB (durable, survives restarts) → in-memory store (active
        sessions mid-flight that have not been persisted yet).
        """
        import json as _json
        from uuid import UUID as _UUID

        # ── DB path (primary) ─────────────────────────────────────────────
        if self._event_repo:
            logger.debug("get_events: querying DB for session_id=%s", session_id)
            try:
                db_records = await self._event_repo.get_by_session_id(session_id)
            except Exception as exc:
                logger.error("get_events: DB query failed session_id=%s err=%s", session_id, exc)
                db_records = []

            logger.info("get_events: DB returned %d records for session_id=%s", len(db_records), session_id)

            if db_records:
                _STATUS_MAP = {
                    "prompt.received":   "received",
                    "risk.calculated":   "scored",
                    "policy.decision":   "decided",
                    "session.created":   "ok",
                    "session.blocked":   "blocked",
                    "session.completed": "completed",
                    "llm.response":      "ok",
                    "output.scanned":    "ok",
                    # Chat runtime — spm-api / spm-mcp / spm-llm-proxy.
                    # All "ok" by default; specific failures override below
                    # via payload.ok introspection.
                    "AgentChatMessage":  "ok",
                    "AgentLLMCall":      "ok",
                    "AgentToolCall":     "ok",
                }

                def _summarise(event_type: str, payload: dict) -> str:
                    if event_type == "prompt.received":
                        prompt = payload.get("prompt", "")
                        if prompt:
                            return prompt[:120]
                        return f"Prompt received ({payload.get('prompt_len', '?')} chars)"
                    if event_type == "risk.calculated":
                        tier  = payload.get("risk_tier", "?")
                        score = payload.get("risk_score", 0)
                        sigs  = ", ".join(payload.get("signals", []))
                        return f"Risk: {tier} ({int(score * 100)}/100){' — ' + sigs if sigs else ''}"
                    if event_type == "policy.decision":
                        dec    = payload.get("decision", "?")
                        reason = payload.get("reason", "")
                        return f"Policy {dec}: {reason}"
                    if event_type == "session.created":
                        return "Session created — pipeline complete"
                    if event_type == "session.blocked":
                        return f"Session blocked: {payload.get('reason', '?')}"
                    if event_type == "session.completed":
                        return f"Session completed ({payload.get('final_status', '?')})"
                    if event_type == "llm.response":
                        return f"LLM responded ({payload.get('output_tokens', '?')} tokens)"
                    if event_type == "output.scanned":
                        return f"Output scanned: {payload.get('verdict', 'ok')}"
                    if event_type == "tool.request":
                        return f"Tool call: {payload.get('tool_name', '?')}"
                    if event_type == "tool.observation":
                        return f"Tool result: {payload.get('tool_name', '?')} → {payload.get('result', '?')}"
                    if event_type == "memory.request":
                        return "Memory read requested"
                    if event_type == "memory.result":
                        return "Memory returned"
                    if event_type == "final.response":
                        return "Final response generated"
                    # ── Chat runtime ────────────────────────────────────
                    if event_type == "AgentChatMessage":
                        role  = (payload.get("role") or "").lower()
                        text  = payload.get("text") or ""
                        prefix = "Agent reply" if role in ("agent", "assistant") \
                                 else "User prompt"
                        if text:
                            snippet = text[:120] + ("…" if len(text) > 120 else "")
                            return f"{prefix}: {snippet}"
                        return prefix
                    if event_type == "AgentLLMCall":
                        model = payload.get("model", "?")
                        ti = payload.get("prompt_tokens")
                        to = payload.get("completion_tokens")
                        usage = ""
                        if ti is not None or to is not None:
                            usage = f" ({ti or '—'} in / {to or '—'} out)"
                        return f"LLM call: {model}{usage}"
                    if event_type == "AgentToolCall":
                        tool   = payload.get("tool", "?")
                        ok     = payload.get("ok", True)
                        dur    = payload.get("duration_ms")
                        verdict = "ok" if ok else "failed"
                        dur_s   = f" — {dur}ms" if dur is not None else ""
                        return f"Tool: {tool} ({verdict}){dur_s}"
                    return event_type

                db_records_sorted = sorted(db_records, key=lambda r: r.timestamp)
                events: List[SessionLifecycleEvent] = []
                for step_idx, rec in enumerate(db_records_sorted, start=1):
                    try:
                        payload = _json.loads(rec.payload) if rec.payload else {}
                    except Exception:
                        payload = {}
                    try:
                        et = EventType(rec.event_type)
                    except ValueError:
                        et = EventType.UNKNOWN
                    status = _STATUS_MAP.get(rec.event_type, "ok")
                    if rec.event_type == "policy.decision":
                        status = payload.get("decision", "decided")
                    try:
                        events.append(SessionLifecycleEvent(
                            event_type=et,
                            session_id=_UUID(session_id),
                            correlation_id=session_id,
                            timestamp=rec.timestamp,
                            step=step_idx,
                            status=status,
                            summary=_summarise(rec.event_type, payload),
                            payload=payload,
                        ))
                    except Exception as exc:
                        logger.error("get_events: failed to build event step=%d type=%s err=%s",
                                     step_idx, rec.event_type, exc)
                logger.info("get_events: returning %d events from DB for session_id=%s", len(events), session_id)
                return events
        else:
            logger.warning("get_events: _event_repo is None, falling back to in-memory store for session_id=%s", session_id)

        # ── In-memory path (active sessions only) ────────────────────────
        mem_events = await self._store.get_events(session_id)
        logger.info("get_events: in-memory store returned %d events for session_id=%s", len(mem_events), session_id)
        return mem_events

    async def list_sessions_for_agent(
        self, agent_id: str, limit: int = 50
    ) -> List[SessionRecord]:
        return await self._repo.list_by_agent(agent_id, limit=limit)

    async def list_all_sessions(self, limit: int = 200) -> List[SessionRecord]:
        return await self._repo.list_all(limit=limit)
