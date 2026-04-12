"""
tools/postgres_tool.py
───────────────────────
LangChain-compatible tools that query the SPM PostgreSQL database.

Tables queried (from spm/db/migrations/001_initial.sql):
  - audit_export        : append-only audit log (event_id, tenant_id, event_type, actor, timestamp, payload)
  - posture_snapshots   : periodic posture metrics per model / tenant
  - model_registry      : registered AI models with risk tier and status

All tools accept a `tenant_id` arg so the agent is tenant-scoped.
Connection is obtained via a shared psycopg2 connection factory; in tests
this factory is monkeypatched with a fake.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection factory (module-level so tests can patch it)
# ---------------------------------------------------------------------------

_connection_factory: Optional[Callable[[], Any]] = None


def set_connection_factory(factory: Callable[[], Any]) -> None:
    """Inject a connection factory (called once at service startup)."""
    global _connection_factory
    _connection_factory = factory


def _get_conn():
    if _connection_factory is None:
        raise RuntimeError("Postgres connection factory not initialised — call set_connection_factory() first")
    return _connection_factory()


# ---------------------------------------------------------------------------
# Internal query helper
# ---------------------------------------------------------------------------

def _query(sql: str, params: tuple) -> list[dict]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool: query_audit_logs
# ---------------------------------------------------------------------------

def query_audit_logs(
    tenant_id: str,
    event_type: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Retrieve recent audit log entries for a tenant.

    Args:
        tenant_id: The tenant to scope the query to.
        event_type: Optional filter on event_type (exact match).
        actor: Optional filter on actor (exact match).
        limit: Maximum rows to return (default 50, max 200).

    Returns:
        JSON string — list of audit log rows.
    """
    limit = min(limit, 200)

    conditions = ["tenant_id = %s"]
    params: list = [tenant_id]

    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)
    if actor:
        conditions.append("actor = %s")
        params.append(actor)

    where = " AND ".join(conditions)
    sql = f"""
        SELECT event_id, tenant_id, event_type, actor, timestamp, payload
        FROM   audit_export
        WHERE  {where}
        ORDER  BY timestamp DESC
        LIMIT  %s
    """
    params.append(limit)

    try:
        rows = _query(sql, tuple(params))
        # payload is JSONB — psycopg2 returns it as dict already; serialise safely
        for r in rows:
            if isinstance(r.get("payload"), dict):
                r["payload"] = r["payload"]
            if hasattr(r.get("timestamp"), "isoformat"):
                r["timestamp"] = r["timestamp"].isoformat()
        return json.dumps(rows, default=str)
    except Exception as exc:
        logger.exception("query_audit_logs failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Tool: query_posture_history
# ---------------------------------------------------------------------------

def query_posture_history(
    tenant_id: str,
    model_id: Optional[str] = None,
    hours: int = 24,
    limit: int = 100,
) -> str:
    """
    Retrieve posture snapshot history for a tenant (and optionally a specific model).

    Args:
        tenant_id: The tenant to scope the query to.
        model_id: Optional UUID of a specific model to filter on.
        hours: How far back to look (default 24h, max 168h / 7 days).
        limit: Maximum rows to return (default 100, max 500).

    Returns:
        JSON string — list of posture snapshot rows with risk metrics.
    """
    hours = min(hours, 168)
    limit = min(limit, 500)

    conditions = ["ps.tenant_id = %s", "ps.snapshot_at >= NOW() - INTERVAL '%s hours'"]
    params: list = [tenant_id, hours]

    if model_id:
        conditions.append("ps.model_id = %s")
        params.append(model_id)

    where = " AND ".join(conditions)
    sql = f"""
        SELECT
            ps.id,
            ps.model_id,
            ps.tenant_id,
            ps.snapshot_at,
            ps.request_count,
            ps.block_count,
            ps.escalation_count,
            ps.avg_risk_score,
            ps.max_risk_score,
            ps.intent_drift_avg,
            ps.ttp_hit_count,
            mr.name        AS model_name,
            mr.risk_tier   AS model_risk_tier
        FROM posture_snapshots ps
        LEFT JOIN model_registry mr ON mr.model_id = ps.model_id
        WHERE {where}
        ORDER BY ps.snapshot_at DESC
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = _query(sql, tuple(params))
        for r in rows:
            if hasattr(r.get("snapshot_at"), "isoformat"):
                r["snapshot_at"] = r["snapshot_at"].isoformat()
            if r.get("model_id") is not None:
                r["model_id"] = str(r["model_id"])
        return json.dumps(rows, default=str)
    except Exception as exc:
        logger.exception("query_posture_history failed: %s", exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Tool: query_model_registry
# ---------------------------------------------------------------------------

def query_model_registry(
    tenant_id: str,
    risk_tier: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Retrieve AI model registrations for a tenant.

    Args:
        tenant_id: The tenant to scope the query to.
        risk_tier: Optional filter — one of 'minimal', 'limited', 'high', 'unacceptable'.
        status: Optional filter — one of 'registered', 'under_review', 'approved',
                'deprecated', 'retired'.
        limit: Maximum rows to return (default 50, max 200).

    Returns:
        JSON string — list of model registry rows.
    """
    limit = min(limit, 200)

    conditions = ["tenant_id = %s"]
    params: list = [tenant_id]

    if risk_tier:
        conditions.append("risk_tier = %s")
        params.append(risk_tier)
    if status:
        conditions.append("status = %s")
        params.append(status)

    where = " AND ".join(conditions)
    sql = f"""
        SELECT
            model_id::text,
            name,
            version,
            provider,
            purpose,
            risk_tier,
            tenant_id,
            status,
            approved_by,
            approved_at,
            created_at,
            updated_at
        FROM model_registry
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = _query(sql, tuple(params))
        for r in rows:
            for ts_field in ("approved_at", "created_at", "updated_at"):
                if hasattr(r.get(ts_field), "isoformat"):
                    r[ts_field] = r[ts_field].isoformat()
        return json.dumps(rows, default=str)
    except Exception as exc:
        logger.exception("query_model_registry failed: %s", exc)
        return json.dumps({"error": str(exc)})
