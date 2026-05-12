"""
api/alerts_router.py
─────────────────────
REST endpoints for audit security alerts.

  GET   /api/v1/alerts              — paginated list with filters
  PATCH /api/v1/alerts/{id}/status  — acknowledge or suppress

Auth: audit.read for GET, audit.write for PATCH.
Data is sourced from the audit_alerts table populated by
consumers/audit_alert_consumer.py.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditAlertORM
from dependencies.rbac import require_audit_read, require_audit_write, IdentityContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])

_VALID_STATUSES = frozenset({"new", "acknowledged", "suppressed"})


# ── DB session dependency ──────────────────────────────────────────────────────

async def _get_db(request: Request) -> AsyncSession:
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


# ── Serialiser ────────────────────────────────────────────────────────────────

def _row_to_dict(row: AuditAlertORM) -> dict:
    return {
        "id":         str(row.id),
        "event_type": row.event_type,
        "severity":   row.severity,
        "component":  row.component or "",
        "principal":  row.principal or "",
        "session_id": row.session_id or "",
        "tenant_id":  row.tenant_id,
        "details":    row.details if isinstance(row.details, dict) else {},
        "status":     row.status or "new",
        "ts":         row.ts.isoformat() if row.ts else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── GET /api/v1/alerts ────────────────────────────────────────────────────────

@router.get("")
async def list_alerts(
    severity:   Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    component:  Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    tenant_id:  Optional[str] = Query(None),
    from_time:  Optional[datetime] = Query(None),
    to_time:    Optional[datetime] = Query(None),
    limit:      int = Query(100, ge=1, le=500),
    offset:     int = Query(0, ge=0),
    db: AsyncSession = Depends(_get_db),
    _identity: IdentityContext = Depends(require_audit_read),
):
    """Return paginated audit alerts, newest first."""
    stmt = select(AuditAlertORM).order_by(AuditAlertORM.created_at.desc())

    if severity:
        stmt = stmt.where(AuditAlertORM.severity == severity)
    if event_type:
        stmt = stmt.where(AuditAlertORM.event_type == event_type)
    if component:
        stmt = stmt.where(AuditAlertORM.component == component)
    if status:
        stmt = stmt.where(AuditAlertORM.status == status)
    if tenant_id:
        stmt = stmt.where(AuditAlertORM.tenant_id == tenant_id)
    if from_time:
        stmt = stmt.where(AuditAlertORM.ts >= from_time)
    if to_time:
        stmt = stmt.where(AuditAlertORM.ts <= to_time)

    total_stmt = stmt.with_only_columns(
        AuditAlertORM.id  # type: ignore[arg-type]
    )
    result = await db.execute(stmt.offset(offset).limit(limit))
    rows = result.scalars().all()

    return {
        "items":  [_row_to_dict(r) for r in rows],
        "offset": offset,
        "limit":  limit,
        "count":  len(rows),
    }


# ── PATCH /api/v1/alerts/{id}/status ─────────────────────────────────────────

class AlertStatusUpdate(BaseModel):
    status: str


@router.patch("/{alert_id}/status")
async def update_alert_status(
    alert_id: str,
    body: AlertStatusUpdate,
    db: AsyncSession = Depends(_get_db),
    _identity: IdentityContext = Depends(require_audit_write),
):
    """Acknowledge or suppress an alert."""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Must be one of: {sorted(_VALID_STATUSES)}",
        )

    import uuid as _uuid
    try:
        row = await db.get(AuditAlertORM, _uuid.UUID(alert_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid alert_id format")

    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    row.status = body.status
    await db.commit()
    await db.refresh(row)
    return _row_to_dict(row)
