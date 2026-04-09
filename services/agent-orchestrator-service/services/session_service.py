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

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from clients.policy_client import PolicyClient, PolicyResult
from dependencies.auth import IdentityContext
from events.publisher import EventPublisher
from events.store import EventStore
from models.session import SessionRecord, SessionRepository
from schemas.events import (
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
    ) -> None:
        self._risk      = risk_engine
        self._policy    = policy_client
        self._publisher = event_publisher
        self._repo      = session_repo
        self._store     = event_store
        self._llm       = llm_client
        self._processor = prompt_processor

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
                tenant_id=tenant_id,
                prompt_hash=prompt_hash,
                prompt_len=len(request.prompt),
                tools=request.tools,
                context_keys=list(request.context.keys()),
            ),
            correlation_id=trace_id,
        )

        # ── Step 2: pre-screen (guard model) ──────────────────────────────
        guard_verdict = "allow"
        guard_score = 0.0
        if self._processor:
            pre = await self._processor.pre_screen(request.prompt)
            guard_verdict = pre.verdict
            guard_score = pre.score
            logger.info(
                "pre_screen session=%s verdict=%s score=%.4f",
                session_id, guard_verdict, guard_score,
            )

        # ── Step 3: risk scoring ───────────────────────────────────────────
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
                logger.exception("LLM call failed session=%s: %s", session_id, exc)

        # ── Step 6: output scan (only if LLM ran) ─────────────────────────
        if llm_text and self._processor:
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
        return await self._store.get_events(session_id)

    async def list_sessions_for_agent(
        self, agent_id: str, limit: int = 50
    ) -> List[SessionRecord]:
        return await self._repo.list_by_agent(agent_id, limit=limit)
