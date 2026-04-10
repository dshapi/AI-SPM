"""
SPM Aggregator — Kafka consumer that writes posture snapshots to PostgreSQL
and triggers enforcement when model risk threshold is exceeded.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
import requests
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("spm-aggregator")

# Prometheus metrics (initialized in main())
_enforce_count    = None
_snapshot_lag     = None
_risk_score       = None
_coverage_pct     = None
_last_snapshot_ts = None

# ── Config ────────────────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP      = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")
TENANTS              = [t.strip() for t in os.getenv("TENANTS", "t1").split(",") if t.strip()]
SPM_DB_URL           = os.getenv("SPM_DB_URL", "postgresql://spm_rw:spmpass@spm-db:5432/spm")
SPM_API_URL          = os.getenv("SPM_API_URL", "http://spm-api:8092")
BLOCK_THRESHOLD      = float(os.getenv("SPM_MODEL_BLOCK_THRESHOLD", "0.85"))
SNAPSHOT_INTERVAL    = int(os.getenv("SPM_SNAPSHOT_INTERVAL_SEC", "300"))
ENFORCEMENT_WINDOW   = int(os.getenv("SPM_ENFORCEMENT_WINDOW", "3"))
REDIS_URL            = os.getenv("REDIS_URL", "redis://redis:6379/0")
_SPM_JWT_ENV         = os.getenv("SPM_SERVICE_JWT", "")  # fallback if Redis not available


def get_service_jwt() -> str:
    """Fetch service JWT from Redis spm:service_token, fall back to env var."""
    try:
        import redis as redis_lib
        r = redis_lib.from_url(REDIS_URL, decode_responses=True)
        token = r.get("spm:service_token")
        if token:
            return token
    except Exception:
        pass
    return _SPM_JWT_ENV


# ── Helpers ───────────────────────────────────────────────────────────────────

def bucket_ts(ts: datetime, interval_sec: int = SNAPSHOT_INTERVAL) -> datetime:
    """Floor timestamp to N-second bucket."""
    epoch = ts.timestamp()
    return datetime.fromtimestamp((epoch // interval_sec) * interval_sec, tz=timezone.utc)


def derive_event_id(tenant_id: str, event_type: str, timestamp: str) -> str:
    return hashlib.sha256(f"{tenant_id}{event_type}{timestamp}".encode()).hexdigest()[:36]


# ── DB helpers (synchronous psycopg2 for consumer loop) ──────────────────────

def get_db_conn():
    return psycopg2.connect(SPM_DB_URL)


def upsert_snapshot(conn, model_id: Optional[str], tenant_id: str,
                    snapshot_at: datetime, metrics: Dict) -> None:
    sql = """
    INSERT INTO posture_snapshots
        (model_id, tenant_id, snapshot_at, request_count, block_count,
         escalation_count, avg_risk_score, max_risk_score, intent_drift_avg, ttp_hit_count)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (model_id, tenant_id, snapshot_at) DO UPDATE SET
        request_count    = posture_snapshots.request_count    + EXCLUDED.request_count,
        block_count      = posture_snapshots.block_count      + EXCLUDED.block_count,
        escalation_count = posture_snapshots.escalation_count + EXCLUDED.escalation_count,
        avg_risk_score   = (posture_snapshots.avg_risk_score * posture_snapshots.request_count
                           + EXCLUDED.avg_risk_score * EXCLUDED.request_count) /
                           NULLIF(posture_snapshots.request_count + EXCLUDED.request_count, 0),
        max_risk_score   = GREATEST(posture_snapshots.max_risk_score, EXCLUDED.max_risk_score),
        intent_drift_avg = (posture_snapshots.intent_drift_avg + EXCLUDED.intent_drift_avg) / 2,
        ttp_hit_count    = posture_snapshots.ttp_hit_count + EXCLUDED.ttp_hit_count
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            model_id, tenant_id, snapshot_at,
            metrics.get("request_count", 1),
            metrics.get("block_count", 0),
            metrics.get("escalation_count", 0),
            metrics.get("avg_risk_score", 0.0),
            metrics.get("max_risk_score", 0.0),
            metrics.get("intent_drift_avg", 0.0),
            metrics.get("ttp_hit_count", 0),
        ))
    conn.commit()


def get_rolling_avg(conn, model_id: Optional[str], tenant_id: str,
                    window: int = ENFORCEMENT_WINDOW) -> Optional[float]:
    """Return rolling average of avg_risk_score over last N non-empty snapshots."""
    sql = """
    SELECT avg_risk_score FROM posture_snapshots
    WHERE (model_id = %s OR (%s IS NULL AND model_id IS NULL))
      AND tenant_id = %s
    ORDER BY snapshot_at DESC, id DESC LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (model_id, model_id, tenant_id, window))
        rows = cur.fetchall()
    if not rows:
        return None
    return sum(r[0] for r in rows) / len(rows)


def mirror_audit_event(conn, event: Dict) -> None:
    """
    Mirror CPM audit event to audit_export (append-only).

    session_id is extracted from the event if present so it can be
    stored as a first-class column for efficient per-session queries.
    The DB schema should include: session_id VARCHAR(64) NULL.
    If the column does not yet exist, the INSERT gracefully falls back
    to the payload-only variant.
    """
    event_id = event.get("event_id") or derive_event_id(
        event.get("tenant_id", ""), event.get("event_type", ""), str(event.get("ts", ""))
    )
    ts = datetime.fromtimestamp(event.get("ts", time.time() * 1000) / 1000, tz=timezone.utc)

    # Extract session_id — present on all pipeline events, optional on pure audit
    session_id: Optional[str] = event.get("session_id") or event.get("details", {}).get("session_id")

    sql = """
    INSERT INTO audit_export (event_id, tenant_id, event_type, actor, session_id, timestamp, payload)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (event_id) DO NOTHING
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                event_id,
                event.get("tenant_id", ""),
                event.get("event_type", ""),
                event.get("principal"),
                session_id,
                ts,
                psycopg2.extras.Json(event),
            ))
        conn.commit()
    except Exception:
        # Graceful fallback for deployments where session_id column doesn't exist yet
        conn.rollback()
        sql_legacy = """
        INSERT INTO audit_export (event_id, tenant_id, event_type, actor, timestamp, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (event_id) DO NOTHING
        """
        with conn.cursor() as cur:
            cur.execute(sql_legacy, (
                event_id,
                event.get("tenant_id", ""),
                event.get("event_type", ""),
                event.get("principal"),
                ts,
                psycopg2.extras.Json(event),
            ))
        conn.commit()
        log.debug("audit_export written without session_id column (schema not yet migrated)")


# ── Enforcement ───────────────────────────────────────────────────────────────

def trigger_enforcement(model_id: str) -> None:
    """Call spm-api to enforce block on model. Retries 3 times."""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{SPM_API_URL}/internal/enforce/{model_id}",
                headers={"Authorization": f"Bearer {get_service_jwt()}"},
                timeout=10.0,
            )
            if resp.status_code in (200, 409):  # 409 = already enforced
                log.info("Enforcement triggered for model_id=%s", model_id)
                if _enforce_count:
                    _enforce_count.labels(action="block", tenant_id="").inc()
                return
            log.warning("Enforcement returned %d for model_id=%s", resp.status_code, model_id)
        except Exception as e:
            log.warning("Enforcement attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    log.error("Enforcement failed after 3 attempts for model_id=%s", model_id)


# ── Message processing ────────────────────────────────────────────────────────

def process_posture_enriched(conn, msg: Dict) -> None:
    model_id   = msg.get("model_id")
    tenant_id  = msg.get("tenant_id", "unknown")
    session_id = msg.get("session_id")          # now present via send_event() envelope
    ts         = datetime.fromtimestamp(msg.get("ts", time.time() * 1000) / 1000, tz=timezone.utc)
    snap_at    = bucket_ts(ts)

    decision  = msg.get("decision", "allow")
    is_block  = 1 if decision == "block" else 0
    is_escal  = 1 if decision == "escalate" else 0

    upsert_snapshot(conn, model_id, tenant_id, snap_at, {
        "request_count":    1,
        "block_count":      is_block,
        "escalation_count": is_escal,
        "avg_risk_score":   msg.get("posture_score", 0.0),
        "max_risk_score":   msg.get("posture_score", 0.0),
        "intent_drift_avg": msg.get("intent_drift_score", 0.0),
        "ttp_hit_count":    len(msg.get("cep_ttps", [])),
    })

    if _snapshot_lag:
        global _last_snapshot_ts
        _last_snapshot_ts = time.time()
        _snapshot_lag.set(0)

    if _risk_score:
        _risk_score.labels(
            model_id=model_id or "unknown",
            tenant_id=tenant_id,
        ).set(msg.get("posture_score", 0.0))

    if model_id:
        rolling = get_rolling_avg(conn, model_id, tenant_id)
        if rolling is not None and rolling > BLOCK_THRESHOLD:
            log.warning(
                "Model risk threshold exceeded: model_id=%s tenant=%s rolling_avg=%.3f",
                model_id, tenant_id, rolling
            )
            trigger_enforcement(model_id)


# ── Main consumer loop ────────────────────────────────────────────────────────

def build_topics() -> List[str]:
    from platform_shared.topics import topics_for_tenant, GlobalTopics
    topics = []
    for t in TENANTS:
        tt = topics_for_tenant(t)
        topics.extend([tt.posture_enriched, tt.decision, tt.tool_result, tt.audit])
    topics.append(GlobalTopics().MODEL_EVENTS)
    return topics


def wait_for_kafka(max_wait: int = 120) -> KafkaConsumer:
    topics = build_topics()
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            consumer = KafkaConsumer(
                *topics,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id="spm-aggregator",
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            )
            log.info("Kafka connected, subscribed to %d topics", len(topics))
            return consumer
        except NoBrokersAvailable:
            log.info("Waiting for Kafka...")
            time.sleep(5)
    raise RuntimeError("Kafka unavailable after %ds" % max_wait)


def main() -> None:
    log.info("SPM Aggregator starting — tenants=%s", TENANTS)

    # Start Prometheus metrics server on :9091
    from prometheus_client import start_http_server, Gauge, Counter
    global _enforce_count, _snapshot_lag, _last_snapshot_ts
    _snapshot_lag  = Gauge("spm_snapshot_lag_seconds",   "Seconds since last snapshot write")
    _enforce_count = Counter("spm_enforcement_actions_total", "Enforcement actions taken",
                             ["action", "tenant_id"])
    global _risk_score
    _risk_score    = Gauge("spm_model_risk_score", "Latest posture risk score",
                           ["model_id", "tenant_id"])
    global _coverage_pct
    _coverage_pct  = Gauge("spm_compliance_coverage_pct", "NIST AI RMF compliance coverage %",
                           ["function"])

    # Initialise counters with 0 so Prometheus always has a series
    for action in ("block", "escalate", "allow"):
        for t in TENANTS:
            _enforce_count.labels(action=action, tenant_id=t).inc(0)

    # Initialise snapshot lag — update every 15s in background
    _last_snapshot_ts = time.time()
    _snapshot_lag.set(0)

    start_http_server(9091)
    log.info("Prometheus metrics server started on :9091")

    # Background thread: refresh compliance coverage every 30s
    import threading
    def _refresh_coverage(db_conn):
        while True:
            try:
                with db_conn.cursor() as cur:
                    cur.execute("""
                        SELECT function,
                               ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'satisfied')
                                     / NULLIF(COUNT(*), 0), 1) AS pct
                        FROM compliance_evidence
                        GROUP BY function
                    """)
                    rows = cur.fetchall()
                    total_satisfied = 0
                    total_count = 0
                    for func, pct in rows:
                        _coverage_pct.labels(function=func).set(float(pct or 0))
                    cur.execute("""
                        SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'satisfied')
                                     / NULLIF(COUNT(*), 0), 1)
                        FROM compliance_evidence
                    """)
                    overall = cur.fetchone()[0]
                    _coverage_pct.labels(function="OVERALL").set(float(overall or 0))
                    db_conn.commit()
            except Exception as exc:
                log.warning("Coverage refresh failed: %s", exc)
                try:
                    db_conn.rollback()
                except Exception:
                    pass
            time.sleep(30)

    cov_conn = get_db_conn()
    t = threading.Thread(target=_refresh_coverage, args=(cov_conn,), daemon=True)
    t.start()
    log.info("Compliance coverage refresh thread started")

    # Background thread: update snapshot lag gauge every 15s
    def _update_lag():
        while True:
            if _snapshot_lag and _last_snapshot_ts:
                _snapshot_lag.set(time.time() - _last_snapshot_ts)
            time.sleep(15)
    threading.Thread(target=_update_lag, daemon=True).start()

    conn = None

    # Wait for DB
    for attempt in range(20):
        try:
            conn = get_db_conn()
            log.info("PostgreSQL connected")
            break
        except Exception as e:
            log.info("Waiting for DB... (%s)", e)
            time.sleep(3)
    if conn is None:
        log.error("Could not connect to DB — exiting")
        sys.exit(1)

    consumer = wait_for_kafka()

    log.info("SPM Aggregator running")
    for msg in consumer:
        try:
            data = msg.value
            topic = msg.topic

            if "posture_enriched" in topic:
                process_posture_enriched(conn, data)
            elif topic.endswith(".audit"):
                mirror_audit_event(conn, data)
            # decision and tool_result contribute to posture via posture_enriched for now

        except Exception as e:
            log.error("Error processing message from %s: %s", msg.topic, e, exc_info=True)
            try:
                conn.rollback()
            except Exception:
                pass
            # Reconnect on connection errors
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn = get_db_conn()
            except Exception:
                log.error("DB reconnection failed")


if __name__ == "__main__":
    main()
