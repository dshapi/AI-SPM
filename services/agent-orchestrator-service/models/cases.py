"""
models/cases.py
───────────────
SQLAlchemy persistence layer for agent_cases.

CaseRepository — thin async repository; one instance per request,
                 constructed with an injected AsyncSession.
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from cases.schemas import CaseRecord
from db.models import CaseORM

logger = logging.getLogger(__name__)


def _orm_to_record(row: CaseORM) -> CaseRecord:
    return CaseRecord(
        case_id=row.case_id,
        session_id=row.session_id,
        reason=row.reason,
        summary=row.summary,
        risk_score=row.risk_score,
        decision=row.decision,
        status=row.status,
        created_at=row.created_at,
    )


def _record_to_orm(rec: CaseRecord) -> CaseORM:
    return CaseORM(
        case_id=rec.case_id,
        session_id=rec.session_id,
        reason=rec.reason,
        summary=rec.summary,
        risk_score=rec.risk_score,
        decision=rec.decision,
        status=rec.status,
        created_at=rec.created_at,
    )


class CaseRepository:
    """
    Thin async repository over the agent_cases table.
    Receives an AsyncSession per request — no shared connection state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, record: CaseRecord) -> None:
        """Persist a new case record."""
        self._session.add(_record_to_orm(record))
        await self._session.commit()
        logger.debug("Inserted case case_id=%s", record.case_id)

    async def get_by_id(self, case_id: str) -> Optional[CaseRecord]:
        """Return a case by primary key, or None if not found."""
        result = await self._session.execute(
            select(CaseORM).where(CaseORM.case_id == case_id)
        )
        row = result.scalar_one_or_none()
        return _orm_to_record(row) if row else None

    async def list_all(self, limit: int = 200) -> List[CaseRecord]:
        """Return all cases sorted newest-first."""
        result = await self._session.execute(
            select(CaseORM)
            .order_by(CaseORM.created_at.desc())
            .limit(limit)
        )
        return [_orm_to_record(row) for row in result.scalars()]

    async def count(self) -> int:
        """Return total number of stored cases."""
        result = await self._session.execute(
            select(func.count()).select_from(CaseORM)
        )
        return result.scalar() or 0
