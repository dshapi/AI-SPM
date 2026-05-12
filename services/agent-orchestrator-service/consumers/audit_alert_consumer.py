"""
consumers/audit_alert_consumer.py
──────────────────────────────────
Kafka consumer that drains cpm.<tenant>.audit events with severity
"warning" or "critical" into the audit_alerts table.

Lifecycle
─────────
Started in main.py:lifespan alongside the lineage consumer.
Missing broker on startup is non-fatal — consumer goes LOG-ONLY mode.
Per-message errors are caught and logged; one bad row never blocks the topic.

Deduplication
─────────────
The AuditAlertORM table has a UniqueConstraint on (event_type, session_id, ts).
On conflict the existing row is silently skipped — makes the consumer idempotent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

_ALERT_SEVERITIES = frozenset({"warning", "critical"})


class AuditAlertConsumer:
    """
    Subscribes to audit topics for all configured tenants and persists
    warning/critical events to AuditAlertORM.

    Construction does NOT open a Kafka connection; that happens in start().
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        tenants:           List[str],
        group_id:          str = "orchestrator-audit-alert-consumer",
        session_factory,
    ) -> None:
        self._bootstrap       = bootstrap_servers
        self._tenants         = tenants
        self._group_id        = group_id
        self._session_factory = session_factory

        self._consumer: Optional[object] = None
        self._task:     Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._available  = False

    def _topics(self) -> List[str]:
        return [f"cpm.{t}.audit" for t in self._tenants]

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(self, env: dict) -> None:
        severity = (env.get("severity") or "").lower()
        if severity not in _ALERT_SEVERITIES:
            return

        from db.models import AuditAlertORM  # local import avoids circular
        from sqlalchemy.exc import IntegrityError

        ts_raw = env.get("ts") or env.get("timestamp")
        ts: Optional[datetime] = None
        if ts_raw:
            try:
                if isinstance(ts_raw, (int, float)):
                    ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                else:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(tz=timezone.utc)

        row = AuditAlertORM(
            event_type=str(env.get("event_type") or env.get("type") or "unknown"),
            severity=severity,
            component=str(env.get("component") or env.get("service") or ""),
            principal=str(env.get("user_id") or env.get("principal") or ""),
            session_id=str(env.get("session_id") or ""),
            tenant_id=str(env.get("tenant_id") or "global"),
            details=json.dumps(env.get("details") or env.get("payload") or {}),
            status="new",
            ts=ts,
        )

        async with self._session_factory() as db:
            try:
                db.add(row)
                await db.commit()
            except IntegrityError:
                await db.rollback()
                logger.debug(
                    "audit_alert_consumer dedup skip event_type=%s session_id=%s ts=%s",
                    row.event_type, row.session_id, row.ts,
                )
            except Exception as exc:
                await db.rollback()
                logger.warning(
                    "audit_alert_consumer persist failed event_type=%s err=%s",
                    row.event_type, exc,
                )

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def _connect(self) -> None:
        from aiokafka import AIOKafkaConsumer
        topics = self._topics()
        if not topics:
            logger.warning("audit_alert_consumer: no tenants configured — skipping")
            return
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers       = self._bootstrap,
            group_id                = self._group_id,
            value_deserializer      = lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset       = "earliest",
            enable_auto_commit      = True,
            auto_commit_interval_ms = 1000,
            session_timeout_ms      = 30_000,
            heartbeat_interval_ms   = 10_000,
        )
        await consumer.start()
        self._consumer  = consumer
        self._available = True
        logger.info("audit_alert_consumer connected topics=%s", topics)

    async def _teardown_consumer(self) -> None:
        self._available = False
        if self._consumer is not None:
            try:
                await self._consumer.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._consumer = None

    # ── Consume loop ──────────────────────────────────────────────────────────

    async def _consume_loop(self) -> None:
        retry_delay = 5
        while not self._stop_event.is_set():
            try:
                if not self._available:
                    await self._connect()
                async for msg in self._consumer:  # type: ignore[union-attr]
                    if self._stop_event.is_set():
                        break
                    try:
                        await self._persist(msg.value)
                    except Exception as exc:
                        logger.warning("audit_alert_consumer msg error: %s", exc)
                retry_delay = 5
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("audit_alert_consumer connection error: %s — retry in %ss", exc, retry_delay)
                await self._teardown_consumer()
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("audit_alert_consumer starting for tenants=%s", self._tenants)
        try:
            await self._connect()
        except Exception as exc:
            logger.warning(
                "audit_alert_consumer: broker unavailable at startup (%s) — running in LOG-ONLY mode",
                exc,
            )
        self._task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._teardown_consumer()
        logger.info("audit_alert_consumer stopped")
