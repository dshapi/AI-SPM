"""
threathunting_ai/collectors/runtime_collector.py
──────────────────────────────────────────────────
Detect anomalous runtime patterns by querying the audit log.

Detects:
  1. High-frequency events from the same actor in the last hour
  2. Enforcement block clusters (session accumulating 3+ blocks in 1 hour)
  3. Session storm (actor creating 5+ distinct sessions in 10 minutes)

Read-only. Uses existing Postgres connection. Deterministic.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

TENANT_ID = "t1"
_HIGH_FREQUENCY_THRESHOLD = 5   # events/hour per actor


class RuntimeCollector:
    """Detect anomalous runtime patterns via SQL-driven analysis from audit_export."""

    def collect(self) -> List[Dict[str, Any]]:
        """
        Scan audit log for anomalous runtime patterns.
        Combines results from 3 detection patterns.
        Returns [] if Postgres is unavailable (non-fatal).
        """
        try:
            import tools.postgres_tool as pt
            if pt._connection_factory is None:
                logger.debug("runtime_collector: Postgres not initialised — skipping")
                return []
        except Exception:
            return []

        results: List[Dict[str, Any]] = []

        # Run all 3 patterns and combine results
        results.extend(self._check_high_frequency_actor())
        results.extend(self._check_enforcement_block_clusters())
        results.extend(self._check_session_storm())

        return results

    def _check_high_frequency_actor(self) -> List[Dict[str, Any]]:
        """
        Pattern 1: High frequency events from the same actor in the last hour.
        """
        try:
            import tools.postgres_tool as pt
            conn = pt._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            actor,
                            COUNT(*) AS event_count,
                            MAX(timestamp)::text AS last_seen
                        FROM audit_export
                        WHERE tenant_id = %s
                          AND timestamp >= NOW() - INTERVAL '1 hour'
                          AND actor IS NOT NULL
                          AND actor != ''
                        GROUP BY actor
                        HAVING COUNT(*) >= %s
                        ORDER BY event_count DESC
                        LIMIT 20
                        """,
                        (TENANT_ID, _HIGH_FREQUENCY_THRESHOLD),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("runtime_collector: _check_high_frequency_actor query failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            # Handle both dict-like rows (from real DB) and tuple rows
            if isinstance(row, dict):
                actor = row.get("actor")
                event_count = row.get("event_count")
                last_seen = row.get("last_seen")
            else:
                actor, event_count, last_seen = row

            finding = {
                "type": "anomalous_pattern",
                "pattern": "high_frequency_actor",
                "severity": "high",
                "asset": actor,
                "description": (
                    f"Actor '{actor}' generated {event_count} events in the last hour "
                    f"(threshold: {_HIGH_FREQUENCY_THRESHOLD})."
                ),
                "anomalous": True,
                "evidence": [{"actor": actor, "event_count": event_count, "last_seen": str(last_seen)}],
                "scan_type": "runtime_anomaly",
            }
            results.append(finding)

        return results

    def _check_enforcement_block_clusters(self) -> List[Dict[str, Any]]:
        """
        Pattern 2: Session accumulating enforcement blocks (3+ blocks within 1 hour).
        """
        try:
            import tools.postgres_tool as pt
            conn = pt._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT session_id, COUNT(*) as block_count, MIN(timestamp)::text as first_block
                        FROM audit_export
                        WHERE tenant_id = %s
                          AND event_type = 'enforcement_block'
                          AND timestamp > NOW() - INTERVAL '1 hour'
                        GROUP BY session_id
                        HAVING COUNT(*) >= 3
                        """,
                        (TENANT_ID,),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("runtime_collector: _check_enforcement_block_clusters query failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            # Handle both dict-like rows (from real DB) and tuple rows
            if isinstance(row, dict):
                session_id = row.get("session_id")
                block_count = row.get("block_count")
                first_block = row.get("first_block")
            else:
                session_id, block_count, first_block = row

            if session_id is None:   # skip malformed/wrong-shaped rows
                continue

            finding = {
                "type": "enforcement_block_cluster",
                "pattern": "enforcement_block_cluster",
                "severity": "high",
                "asset": session_id,
                "description": f"Session {session_id} accumulated {block_count} enforcement blocks in 1 hour (threshold: 3)",
                "anomalous": True,
                "evidence": [{"session_id": session_id, "block_count": block_count, "first_block": str(first_block)}],
                "scan_type": "runtime_anomaly",
            }
            results.append(finding)

        return results

    def _check_session_storm(self) -> List[Dict[str, Any]]:
        """
        Pattern 3: Actor creating unusually high number of new sessions in 10 minutes (5+ sessions).
        """
        try:
            import tools.postgres_tool as pt
            conn = pt._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT actor, COUNT(DISTINCT session_id) as session_count
                        FROM audit_export
                        WHERE tenant_id = %s
                          AND event_type = 'prompt.received'
                          AND timestamp > NOW() - INTERVAL '10 minutes'
                        GROUP BY actor
                        HAVING COUNT(DISTINCT session_id) >= 5
                        """,
                        (TENANT_ID,),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("runtime_collector: _check_session_storm query failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            # Handle both dict-like rows (from real DB) and tuple rows
            if isinstance(row, dict):
                actor = row.get("actor")
                session_count = row.get("session_count")
            else:
                actor, session_count = row

            if session_count is None:   # skip malformed/wrong-shaped rows
                continue

            finding = {
                "type": "session_storm",
                "pattern": "session_storm",
                "severity": "critical",
                "asset": actor,
                "description": f"Actor '{actor}' created {session_count} new sessions in the last 10 minutes (threshold: 5)",
                "anomalous": True,
                "evidence": [{"actor": actor, "session_count": session_count}],
                "scan_type": "runtime_anomaly",
            }
            results.append(finding)

        return results


# ── Backward-compatible module-level API ──────────────────────────────────────
def collect() -> list:
    """Module-level shim — wraps RuntimeCollector for backward compatibility."""
    return RuntimeCollector().collect()

