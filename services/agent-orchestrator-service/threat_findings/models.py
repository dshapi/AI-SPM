from __future__ import annotations
import json
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import ThreatFindingORM
from threat_findings.schemas import FindingRecord

logger = logging.getLogger(__name__)


def _orm_to_record(row: ThreatFindingORM) -> FindingRecord:
    return FindingRecord(
        id=row.id,
        batch_hash=row.batch_hash,
        title=row.title,
        severity=row.severity,
        description=row.description,
        evidence=json.loads(row.evidence),
        ttps=json.loads(row.ttps),
        tenant_id=row.tenant_id,
        status=row.status,
        created_at=row.created_at,
        closed_at=row.closed_at,
    )


class ThreatFindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_batch_hash(self, batch_hash: str) -> Optional[FindingRecord]:
        stmt = select(ThreatFindingORM).where(ThreatFindingORM.batch_hash == batch_hash)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _orm_to_record(row) if row else None

    async def insert(self, rec: FindingRecord) -> None:
        orm = ThreatFindingORM(
            id=rec.id,
            batch_hash=rec.batch_hash,
            title=rec.title,
            severity=rec.severity,
            description=rec.description,
            evidence=json.dumps(rec.evidence),
            ttps=json.dumps(rec.ttps),
            tenant_id=rec.tenant_id,
            status=rec.status,
            created_at=rec.created_at,
            closed_at=rec.closed_at,
        )
        self._session.add(orm)
        await self._session.commit()
