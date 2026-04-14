"""
threathunting_ai/collectors/tool_misuse_collector.py
────────────────────────────────────────────────────
Detect tool misuse patterns in audit logs via SQL-driven analysis.

Patterns:
  1. High frequency tool use (>20 calls/hour per actor)
  2. Rapid tool chaining (>5 calls within 60 seconds per session)
  3. High blocked tool ratio (>30% blocked, minimum 5 calls per actor)

Read-only. Uses existing Postgres connection. Deterministic.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

TENANT_ID = "t1"


class ToolMisuseCollector:
    """Detect tool misuse via SQL-driven patterns from audit_export."""

    def collect(self) -> List[Dict[str, Any]]:
        """
        Scan audit log for tool misuse patterns.
        Combines results from 3 detection patterns.
        Returns [] if Postgres is unavailable (non-fatal).
        """
        try:
            import tools.postgres_tool as pt
            if pt._connection_factory is None:
                logger.debug("tool_misuse_collector: Postgres not initialised — skipping")
                return []
        except Exception:
            return []

        results: List[Dict[str, Any]] = []

        # Run all 3 patterns and combine results
        results.extend(self._check_high_frequency())
        results.extend(self._check_rapid_chaining())
        results.extend(self._check_blocked_ratio())

        return results

    def _check_high_frequency(self) -> List[Dict[str, Any]]:
        """
        Pattern 1: High frequency tool use (>20 calls/hour per actor).
        """
        try:
            import tools.postgres_tool as pt
            conn = pt._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT actor, COUNT(*) as cnt
                        FROM audit_export
                        WHERE tenant_id = %s
                          AND event_type = 'tool.request'
                          AND timestamp > NOW() - INTERVAL '1 hour'
                        GROUP BY actor
                        HAVING COUNT(*) > 20
                        """,
                        (TENANT_ID,),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("tool_misuse_collector: _check_high_frequency query failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            # Handle both dict-like rows (from real DB) and tuple rows
            if isinstance(row, dict):
                actor = row.get("actor")
                cnt = row.get("cnt")
            else:
                actor, cnt = row

            finding = {
                "type": "high_frequency_tool_use",
                "severity": "high",
                "asset": actor,
                "description": f"Actor {actor} made {cnt} tool calls in the last hour (threshold: 20)",
                "anomalous": True,
                "evidence": [{"actor": actor, "tool_call_count": cnt}],
                "scan_type": "tool_misuse",
            }
            results.append(finding)

        return results

    def _check_rapid_chaining(self) -> List[Dict[str, Any]]:
        """
        Pattern 2: Rapid tool chaining (>5 tool calls within 60 seconds per session).
        Groups by session_id and 1-minute buckets.
        """
        try:
            import tools.postgres_tool as pt
            conn = pt._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT session_id, MIN(timestamp) as burst_start, COUNT(*) as burst_count
                        FROM audit_export
                        WHERE tenant_id = %s
                          AND event_type = 'tool.request'
                          AND timestamp > NOW() - INTERVAL '1 hour'
                        GROUP BY session_id, date_trunc('minute', timestamp)
                        HAVING COUNT(*) > 5
                        """,
                        (TENANT_ID,),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("tool_misuse_collector: _check_rapid_chaining query failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            # Handle both dict-like rows (from real DB) and tuple rows
            if isinstance(row, dict):
                session_id = row.get("session_id")
                burst_start = row.get("burst_start")
                burst_count = row.get("burst_count")
            else:
                session_id, burst_start, burst_count = row

            finding = {
                "type": "rapid_tool_chaining",
                "severity": "high",
                "asset": session_id,
                "description": f"Session {session_id} chained {burst_count} tool calls within 60 seconds (threshold: 5)",
                "anomalous": True,
                "evidence": [{"session_id": session_id, "burst_count": burst_count, "burst_start": str(burst_start)}],
                "scan_type": "tool_misuse",
            }
            results.append(finding)

        return results

    def _check_blocked_ratio(self) -> List[Dict[str, Any]]:
        """
        Pattern 3: High blocked tool ratio (>30% of tool calls blocked, minimum 5 calls per actor).
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
                            COUNT(*) FILTER (WHERE event_type = 'enforcement_block') as blocked,
                            COUNT(*) FILTER (WHERE event_type = 'tool.request') as total,
                            ROUND(
                                COUNT(*) FILTER (WHERE event_type = 'enforcement_block')::numeric /
                                NULLIF(COUNT(*) FILTER (WHERE event_type = 'tool.request'), 0) * 100, 1
                            ) as block_ratio
                        FROM audit_export
                        WHERE tenant_id = %s
                          AND event_type IN ('tool.request', 'enforcement_block')
                          AND timestamp > NOW() - INTERVAL '1 hour'
                        GROUP BY actor
                        HAVING COUNT(*) FILTER (WHERE event_type = 'tool.request') >= 5
                           AND COUNT(*) FILTER (WHERE event_type = 'enforcement_block')::numeric /
                               NULLIF(COUNT(*) FILTER (WHERE event_type = 'tool.request'), 0) > 0.30
                        """,
                        (TENANT_ID,),
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("tool_misuse_collector: _check_blocked_ratio query failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            # Handle both dict-like rows (from real DB) and tuple rows
            if isinstance(row, dict):
                actor = row.get("actor")
                blocked = row.get("blocked")
                total = row.get("total")
                block_ratio = row.get("block_ratio")
            else:
                actor, blocked, total, block_ratio = row

            finding = {
                "type": "high_blocked_tool_ratio",
                "severity": "critical",
                "asset": actor,
                "description": f"Actor {actor} has {block_ratio}% of tool calls blocked (threshold: 30%, minimum 5 calls)",
                "anomalous": True,
                "evidence": [{"actor": actor, "blocked_count": blocked, "total_calls": total, "block_ratio": block_ratio}],
                "scan_type": "tool_misuse",
            }
            results.append(finding)

        return results


# ── Module-level API (matches all other collectors) ───────────────────────────
def collect() -> list:
    """Module-level shim — wraps ToolMisuseCollector for scan_registry."""
    return ToolMisuseCollector().collect()
