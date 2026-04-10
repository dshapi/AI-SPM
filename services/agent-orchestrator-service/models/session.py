"""
models/session.py
─────────────────
SQLite persistence layer using SQLAlchemy 2.0 async ORM.

SessionRecord  — the internal domain dataclass (never exported to routers).
SessionRepository — thin async repository; one instance per request,
                    constructed with an injected AsyncSession.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentSessionORM

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Domain model (internal — never exported to routers)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionRecord:
    session_id: str
    agent_id: str
    user_id: str
    tenant_id: Optional[str]
    prompt_hash: str
    tools: List[str]
    context: Dict[str, Any]
    status: str
    risk_score: float
    risk_tier: str
    risk_signals: List[str]
    policy_decision: str
    policy_reason: str
    policy_version: str
    trace_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────────────

class SessionRepository:
    """
    Thin async repository over the agent_sessions table.
    Receives an AsyncSession per request — no shared connection state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write ──────────────────────────────────────────────────────────

    async def insert(self, rec: SessionRecord) -> None:
        orm = AgentSessionORM(
            id=str(rec.session_id),
            user_id=rec.user_id,
            agent_id=rec.agent_id,
            tenant_id=rec.tenant_id,
            status=rec.status,
            risk_score=rec.risk_score,
            decision=rec.policy_decision,
            prompt_hash=rec.prompt_hash,
            risk_tier=rec.risk_tier,
            risk_signals=json.dumps(rec.risk_signals),
            tools=json.dumps(rec.tools),
            context=json.dumps(rec.context),
            policy_reason=rec.policy_reason,
            policy_version=rec.policy_version,
            trace_id=rec.trace_id,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
        )
        self._session.add(orm)
        await self._session.commit()
        logger.debug("Inserted agent_session id=%s", rec.session_id)

    async def update_status(self, session_id: str, status: str) -> None:
        now = datetime.now(timezone.utc)
        await self._session.execute(
            update(AgentSessionORM)
            .where(AgentSessionORM.id == session_id)
            .values(status=status, updated_at=now)
        )
        await self._session.commit()

    # ── Read ───────────────────────────────────────────────────────────

    async def get_by_id(self, session_id: str) -> Optional[SessionRecord]:
        result = await self._session.execute(
            select(AgentSessionORM).where(AgentSessionORM.id == session_id)
        )
        orm = result.scalar_one_or_none()
        return _orm_to_record(orm) if orm else None

    async def list_by_agent(
        self, agent_id: str, limit: int = 50
    ) -> List[SessionRecord]:
        result = await self._session.execute(
            select(AgentSessionORM)
            .where(AgentSessionORM.agent_id == agent_id)
            .order_by(AgentSessionORM.created_at.desc())
            .limit(limit)
        )
        return [_orm_to_record(row) for row in result.scalars()]


# ─────────────────────────────────────────────────────────────────────────────
# Mapping helper
# ─────────────────────────────────────────────────────────────────────────────

def _orm_to_record(orm: AgentSessionORM) -> SessionRecord:
    return SessionRecord(
        session_id=orm.id,
        agent_id=orm.agent_id,
        user_id=orm.user_id,
        tenant_id=orm.tenant_id,
        prompt_hash=orm.prompt_hash,
        tools=json.loads(orm.tools),
        context=json.loads(orm.context),
        status=orm.status,
        risk_score=orm.risk_score,
        risk_tier=orm.risk_tier,
        risk_signals=json.loads(orm.risk_signals),
        policy_decision=orm.decision,
        policy_reason=orm.policy_reason,
        policy_version=orm.policy_version,
        trace_id=orm.trace_id,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )
