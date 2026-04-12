from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import ThreatFindingORM
from threat_findings.schemas import FindingFilter, FindingRecord

logger = logging.getLogger(__name__)


def _json_loads_safe(value: Optional[str], default):
    """Safely decode a JSON string; return `default` on None or error."""
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _coerce_list(value) -> list:
    """Ensure a value is always a list.

    Handles legacy rows where `evidence` was stored as a bare dict or
    non-list JSON value instead of an array.  Any non-list is wrapped in
    a one-element list so Pydantic's List[Any] field never rejects it.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _orm_to_record(row: ThreatFindingORM) -> FindingRecord:
    return FindingRecord(
        id=row.id,
        batch_hash=row.batch_hash,
        title=row.title,
        severity=row.severity,
        description=row.description,
        evidence=_coerce_list(_json_loads_safe(row.evidence, [])),
        ttps=_coerce_list(_json_loads_safe(row.ttps, [])),
        tenant_id=row.tenant_id,
        status=row.status,
        created_at=row.created_at,
        closed_at=row.closed_at,
        # New fields
        timestamp=row.timestamp,
        confidence=row.confidence,
        risk_score=row.risk_score,
        hypothesis=row.hypothesis,
        asset=row.asset,
        environment=row.environment,
        correlated_events=_json_loads_safe(row.correlated_events, None),
        correlated_findings=_json_loads_safe(row.correlated_findings, None),
        triggered_policies=_json_loads_safe(row.triggered_policies, None),
        policy_signals=_json_loads_safe(row.policy_signals, None),
        recommended_actions=_json_loads_safe(row.recommended_actions, None),
        should_open_case=bool(row.should_open_case) if row.should_open_case is not None else False,
        case_id=row.case_id,
        source=row.source,
        updated_at=row.updated_at,
        is_proactive=bool(row.is_proactive) if row.is_proactive is not None else False,
        # ── Prioritization fields ─────────────────────────────────────────
        dedup_key=row.dedup_key,
        occurrence_count=int(row.occurrence_count) if row.occurrence_count is not None else 1,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        group_id=row.group_id,
        group_size=int(row.group_size) if row.group_size is not None else 1,
        priority_score=row.priority_score,
        suppressed=bool(row.suppressed) if row.suppressed is not None else False,
    )


class ThreatFindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_dedup_key(self, dedup_key: str) -> Optional[FindingRecord]:
        stmt = select(ThreatFindingORM).where(ThreatFindingORM.dedup_key == dedup_key)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _orm_to_record(row) if row else None

    async def get_by_batch_hash(self, batch_hash: str) -> Optional[FindingRecord]:
        stmt = select(ThreatFindingORM).where(ThreatFindingORM.batch_hash == batch_hash)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _orm_to_record(row) if row else None

    async def get_by_id(self, finding_id: str) -> Optional[FindingRecord]:
        stmt = select(ThreatFindingORM).where(ThreatFindingORM.id == finding_id)
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
            evidence=json.dumps(rec.evidence if rec.evidence is not None else []),
            ttps=json.dumps(rec.ttps if rec.ttps is not None else []),
            tenant_id=rec.tenant_id,
            status=rec.status,
            created_at=rec.created_at,
            closed_at=rec.closed_at,
            # New fields
            timestamp=rec.timestamp,
            confidence=rec.confidence,
            risk_score=rec.risk_score,
            hypothesis=rec.hypothesis,
            asset=rec.asset,
            environment=rec.environment,
            correlated_events=json.dumps(rec.correlated_events) if rec.correlated_events is not None else None,
            correlated_findings=json.dumps(rec.correlated_findings) if rec.correlated_findings is not None else None,
            triggered_policies=json.dumps(rec.triggered_policies) if rec.triggered_policies is not None else None,
            policy_signals=json.dumps(rec.policy_signals) if rec.policy_signals is not None else None,
            recommended_actions=json.dumps(rec.recommended_actions) if rec.recommended_actions is not None else None,
            should_open_case=rec.should_open_case,
            case_id=rec.case_id,
            source=rec.source,
            updated_at=rec.updated_at,
            is_proactive=rec.is_proactive,
            # ── Prioritization fields ────────────────────────────────────
            dedup_key=rec.dedup_key,
            occurrence_count=rec.occurrence_count,
            first_seen=rec.first_seen,
            last_seen=rec.last_seen,
            group_id=rec.group_id,
            group_size=rec.group_size,
            priority_score=rec.priority_score,
            suppressed=rec.suppressed,
        )
        self._session.add(orm)
        await self._session.commit()

    def _apply_filters(self, stmt, filters: FindingFilter):
        """Apply all filter conditions to a statement."""
        if filters.severity:
            stmt = stmt.where(ThreatFindingORM.severity == filters.severity)
        if filters.status:
            stmt = stmt.where(ThreatFindingORM.status == filters.status)
        if filters.asset:
            stmt = stmt.where(ThreatFindingORM.asset == filters.asset)
        if filters.tenant_id:
            stmt = stmt.where(ThreatFindingORM.tenant_id == filters.tenant_id)
        if filters.has_case is True:
            stmt = stmt.where(ThreatFindingORM.case_id.isnot(None))
        if filters.has_case is False:
            stmt = stmt.where(ThreatFindingORM.case_id.is_(None))
        if filters.from_ts:
            stmt = stmt.where(ThreatFindingORM.created_at >= filters.from_ts)
        if filters.to_ts:
            stmt = stmt.where(ThreatFindingORM.created_at <= filters.to_ts)
        if filters.min_risk_score is not None:
            stmt = stmt.where(ThreatFindingORM.risk_score >= filters.min_risk_score)
        return stmt

    async def list_findings(self, filters: FindingFilter) -> List[FindingRecord]:
        stmt = self._apply_filters(select(ThreatFindingORM), filters)
        # Suppress filter — exclude suppressed findings unless caller opts in
        if not filters.include_suppressed:
            stmt = stmt.where(
                (ThreatFindingORM.suppressed == False) | (ThreatFindingORM.suppressed.is_(None))  # noqa: E712
            )
        # Sorting — default to priority_score DESC, then created_at DESC as tiebreaker
        if filters.sort_by == "risk_score":
            stmt = stmt.order_by(ThreatFindingORM.risk_score.desc().nullslast())
        elif filters.sort_by == "timestamp":
            stmt = stmt.order_by(ThreatFindingORM.timestamp.desc().nullslast())
        elif filters.sort_by == "created_at":
            stmt = stmt.order_by(ThreatFindingORM.created_at.desc())
        else:
            # Default: priority_score DESC (NULLs last), then created_at DESC
            stmt = stmt.order_by(
                ThreatFindingORM.priority_score.desc().nullslast(),
                ThreatFindingORM.created_at.desc(),
            )
        stmt = stmt.limit(filters.limit).offset(filters.offset)
        result = await self._session.execute(stmt)
        return [_orm_to_record(row) for row in result.scalars()]

    async def count_findings(self, filters: FindingFilter) -> int:
        stmt = self._apply_filters(
            select(func.count()).select_from(ThreatFindingORM), filters
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def update_status(self, finding_id: str, new_status: str) -> None:
        stmt = (
            update(ThreatFindingORM)
            .where(ThreatFindingORM.id == finding_id)
            .values(
                status=new_status,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def attach_case(self, finding_id: str, case_id: str) -> None:
        stmt = (
            update(ThreatFindingORM)
            .where(ThreatFindingORM.id == finding_id)
            .values(case_id=case_id)
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def update_priority_fields(self, rec: FindingRecord) -> None:
        """Persist prioritization fields after a post-insert engine run."""
        await self._session.execute(
            update(ThreatFindingORM)
            .where(ThreatFindingORM.id == rec.id)
            .values(
                dedup_key=rec.dedup_key,
                priority_score=rec.priority_score,
                suppressed=rec.suppressed,
                first_seen=rec.first_seen,
                last_seen=rec.last_seen,
                occurrence_count=rec.occurrence_count,
                group_id=rec.group_id,
                group_size=rec.group_size,
            )
        )
        await self._session.commit()
