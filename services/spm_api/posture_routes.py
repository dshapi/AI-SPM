"""
SPM API — Posture module routes.

Surfaces the `posture_snapshots` table (seeded by seed_db.py with 30 daily
rows on first boot) so the UI Posture page has real numbers to display
instead of rendering hardcoded JS constants.

Endpoints:
    GET  /posture/snapshots        — list snapshots, ordered by snapshot_at ASC
    GET  /posture/summary          — top-of-page KPI rollup over a window

Both endpoints accept:
    ?days=N         (default 30) — how many days back to include
    ?tenant_id=X    (default "global") — platform-wide rollup is tenant_id="global"
                                         and model_id IS NULL
    ?model_id=UUID  optional — restrict to a specific model's history; otherwise
                               returns the platform aggregate (model_id IS NULL)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spm.db.models import PostureSnapshot
from spm.db.session import get_db

# verify_jwt is exposed by app.py — same lazy-import dance as
# integrations_routes.py so this module is importable in tests where
# only the route module is loaded without spinning up the full app.
import importlib

log = logging.getLogger(__name__)


def _app_module():
    return importlib.import_module("app")


def verify_jwt(authorization=None):
    return _app_module().verify_jwt(authorization=authorization)


router = APIRouter(prefix="/posture", tags=["posture"])


# ── Response models ─────────────────────────────────────────────────────


class SnapshotOut(BaseModel):
    """One daily aggregate row — mirrors the DB schema 1:1."""

    snapshot_at: datetime
    request_count: int
    block_count: int
    escalation_count: int
    avg_risk_score: float
    max_risk_score: float
    intent_drift_avg: float
    ttp_hit_count: int


class SummaryOut(BaseModel):
    """Top-of-page KPI rollup over the requested window.

    Computed from the underlying SnapshotOut rows server-side so the UI
    doesn't have to repeat the math (and so the same numbers can be
    consumed by other clients without duplicating logic).
    """

    window_days: int
    snapshot_count: int = Field(description="how many snapshots are in the window — should equal min(days, len(seed))")
    total_requests: int
    total_blocks: int
    total_escalations: int
    total_ttp_hits: int
    avg_risk_score: float = Field(description="average of avg_risk_score across the window")
    max_risk_score: float = Field(description="max of max_risk_score across the window")
    avg_intent_drift: float
    block_rate_pct: float = Field(description="blocks / requests * 100, 0 if no requests")
    latest_snapshot_at: Optional[datetime] = None
    earliest_snapshot_at: Optional[datetime] = None


# ── Endpoints ──────────────────────────────────────────────────────────


def _scope_clause(tenant_id: str, model_id: Optional[UUID]):
    """Common WHERE clause: tenant scope plus model scope (NULL = platform aggregate)."""
    clauses = [PostureSnapshot.tenant_id == tenant_id]
    if model_id is None:
        clauses.append(PostureSnapshot.model_id.is_(None))
    else:
        clauses.append(PostureSnapshot.model_id == model_id)
    return and_(*clauses)


@router.get("/snapshots", response_model=List[SnapshotOut])
async def list_snapshots(
    days: int = Query(30, ge=1, le=365, description="how many days back to include"),
    tenant_id: str = Query("global"),
    model_id: Optional[UUID] = Query(None, description="omit for platform aggregate"),
    db: AsyncSession = Depends(get_db),
    _claims: Dict[str, Any] = Depends(verify_jwt),
):
    """Daily snapshots ordered by `snapshot_at` ASC.

    Sized for charting (sparklines, 30-day trends). Empty result is valid —
    means seeding hasn't run yet or the window is outside seeded data.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        select(PostureSnapshot)
        .where(_scope_clause(tenant_id, model_id))
        .where(PostureSnapshot.snapshot_at >= cutoff)
        .order_by(PostureSnapshot.snapshot_at.asc())
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        SnapshotOut(
            snapshot_at=r.snapshot_at,
            request_count=int(r.request_count or 0),
            block_count=int(r.block_count or 0),
            escalation_count=int(r.escalation_count or 0),
            avg_risk_score=float(r.avg_risk_score or 0.0),
            max_risk_score=float(r.max_risk_score or 0.0),
            intent_drift_avg=float(r.intent_drift_avg or 0.0),
            ttp_hit_count=int(r.ttp_hit_count or 0),
        )
        for r in rows
    ]


@router.get("/summary", response_model=SummaryOut)
async def summary(
    days: int = Query(30, ge=1, le=365),
    tenant_id: str = Query("global"),
    model_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    _claims: Dict[str, Any] = Depends(verify_jwt),
):
    """KPI rollup over the requested window.

    Designed for the top-of-page KPI strip on the Posture page. Returns
    well-defined zeros if no snapshots exist in the window so the UI can
    render numerically without null-checking every field.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    scope = _scope_clause(tenant_id, model_id)

    # Aggregate in one round-trip rather than fetching all rows and folding
    # in Python — for 30 rows the difference is moot, but a future scaling
    # path (per-model 365-day windows) would multiply this.
    agg_q = (
        select(
            func.count().label("snap_count"),
            func.coalesce(func.sum(PostureSnapshot.request_count), 0).label("total_req"),
            func.coalesce(func.sum(PostureSnapshot.block_count), 0).label("total_blk"),
            func.coalesce(func.sum(PostureSnapshot.escalation_count), 0).label("total_esc"),
            func.coalesce(func.sum(PostureSnapshot.ttp_hit_count), 0).label("total_ttp"),
            func.coalesce(func.avg(PostureSnapshot.avg_risk_score), 0.0).label("avg_risk"),
            func.coalesce(func.max(PostureSnapshot.max_risk_score), 0.0).label("max_risk"),
            func.coalesce(func.avg(PostureSnapshot.intent_drift_avg), 0.0).label("avg_drift"),
            func.min(PostureSnapshot.snapshot_at).label("earliest"),
            func.max(PostureSnapshot.snapshot_at).label("latest"),
        )
        .where(scope)
        .where(PostureSnapshot.snapshot_at >= cutoff)
    )
    row = (await db.execute(agg_q)).one()

    total_req = int(row.total_req or 0)
    total_blk = int(row.total_blk or 0)
    block_rate = round((total_blk / total_req) * 100, 2) if total_req > 0 else 0.0

    return SummaryOut(
        window_days=days,
        snapshot_count=int(row.snap_count or 0),
        total_requests=total_req,
        total_blocks=total_blk,
        total_escalations=int(row.total_esc or 0),
        total_ttp_hits=int(row.total_ttp or 0),
        avg_risk_score=round(float(row.avg_risk or 0.0), 3),
        max_risk_score=round(float(row.max_risk or 0.0), 3),
        avg_intent_drift=round(float(row.avg_drift or 0.0), 3),
        block_rate_pct=block_rate,
        latest_snapshot_at=row.latest,
        earliest_snapshot_at=row.earliest,
    )
