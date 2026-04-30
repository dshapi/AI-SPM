"""
consumers/lineage_consumer.py
─────────────────────────────
Kafka consumer that drains GlobalTopics.LINEAGE_EVENTS into session_events.

Replaces the previous HTTP dual-write from the api service to
POST /api/v1/lineage/events. Same persistence path — see
services/lineage_ingest.py:persist_lineage_event — so the row inserted
into session_events is byte-identical regardless of which transport the
event came in on. The Lineage page (which reads from session_events) is
therefore unaffected.

Implementation
──────────────
Async-native using aiokafka.AIOKafkaConsumer — mirrors the existing
EventPublisher pattern in events/publisher.py (also aiokafka). Runs as a
background asyncio task, not a daemon thread, so we don't need a
run_coroutine_threadsafe bridge — the consume loop already runs on the
same event loop that owns the DB session factory.

Lifecycle
─────────
Started in main.py:lifespan after app.state.db_session_factory exists:
    await consumer.start()
Stopped on shutdown:
    await consumer.stop()

Resilience
──────────
- Missing broker on startup is non-fatal: start() catches and logs, the
  consumer goes into LOG-ONLY mode, app boot continues.
- Per-message persistence errors are caught and logged — one bad row
  must not block the whole topic. The api service has already returned
  to the user and rendered the WebSocket frame; persistence is purely
  for replay-after-LRU-eviction.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from models.event import EventRepository
from models.session import SessionRepository
from services.lineage_ingest import (
    LineageEventInput,
    persist_lineage_event,
)

logger = logging.getLogger(__name__)


class LineageEventConsumer:
    """
    Subscribes to GlobalTopics.LINEAGE_EVENTS and persists each message via
    the shared persist_lineage_event service.

    Construction does NOT open a Kafka connection; that happens in start()
    so a missing broker can't crash app startup.
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic:             str,
        group_id:          str,
        session_factory,                       # async_sessionmaker
    ) -> None:
        self._bootstrap       = bootstrap_servers
        self._topic           = topic
        self._group_id        = group_id
        self._session_factory = session_factory

        self._consumer: Optional["object"] = None  # AIOKafkaConsumer
        self._task:     Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._available  = False

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(self, env: dict) -> None:
        """Run the shared persistence call inside a fresh DB session."""
        try:
            body = LineageEventInput.from_kafka_envelope(env)
        except Exception as exc:
            logger.warning("lineage_consumer dropping malformed envelope=%r err=%s", env, exc)
            return

        async with self._session_factory() as db:
            try:
                await persist_lineage_event(
                    SessionRepository(db),
                    EventRepository(db),
                    body,
                )
            except Exception as exc:
                # Best-effort persistence — log and drop. The api service
                # already returned to the user; retrying on a bad row would
                # block the whole topic. Operators can replay later if needed.
                logger.warning(
                    "lineage_consumer persist failed session=%s type=%s err=%s",
                    body.session_id, body.event_type, exc,
                )

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def _connect(self) -> None:
        """
        Open the AIOKafkaConsumer and join the group.  Raises on failure.

        The consumer is created and torn down per-attempt so a half-open
        client (e.g. broker came back but the existing consumer's TCP
        socket is dead) doesn't poison the next attempt.
        """
        from aiokafka import AIOKafkaConsumer
        consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers       = self._bootstrap,
            group_id                = self._group_id,
            value_deserializer      = lambda m: json.loads(m.decode("utf-8")),
            # earliest so a fresh deployment can drain events buffered while
            # the orchestrator was offline; commits ensure no duplicate work.
            auto_offset_reset       = "earliest",
            enable_auto_commit      = True,
            auto_commit_interval_ms = 1000,
            session_timeout_ms      = 30_000,
            heartbeat_interval_ms   = 10_000,
        )
        await consumer.start()
        self._consumer  = consumer
        self._available = True

    async def _teardown_consumer(self) -> None:
        """Drop the current consumer (if any).  Idempotent."""
        self._available = False
        if self._consumer is not None:
            try:
                await self._consumer.stop()
            except Exception:                                  # noqa: BLE001
                pass
            self._consumer = None

    # ── Run loop ──────────────────────────────────────────────────────────────

    async def _drain(self) -> None:
        """
        Drain messages until the consumer raises or stop_event fires.

        Per-message errors are caught and logged so one bad envelope can't
        break the loop.  A connection-level error (broker restart, network
        blip) is allowed to propagate to the supervisor for reconnect.
        """
        assert self._consumer is not None
        async for msg in self._consumer:
            if self._stop_event.is_set():
                break
            value = msg.value
            if not isinstance(value, dict) \
                    or "session_id" not in value \
                    or "event_type" not in value:
                logger.warning(
                    "lineage_consumer dropping malformed envelope=%r", value,
                )
                continue
            try:
                await self._persist(value)
            except Exception as exc:                            # noqa: BLE001
                logger.warning(
                    "lineage_consumer_msg_err topic=%s offset=%s err=%s",
                    msg.topic, msg.offset, exc,
                )

    async def _supervised_run(self) -> None:
        """
        Outer supervisor loop: connect → drain → on failure, sleep + retry.

        This replaces the previous one-shot `start()` behaviour where a
        broker-unreachable error at app boot permanently demoted the
        consumer to LOG-ONLY mode and silently dropped every chat-lineage
        event for the lifetime of the pod.  Symptom of that bug: chats
        succeed but the Runtime page stays empty because session rows
        never land in agent_sessions.

        Backoff is exponential, capped at 60s.  Reset on each successful
        connection so a long-lived consumer that briefly hiccups doesn't
        get progressively slower to recover.
        """
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                await self._connect()
                logger.info(
                    "lineage_consumer_connected topic=%s group=%s bootstrap=%s",
                    self._topic, self._group_id, self._bootstrap,
                )
                backoff = 1.0
                await self._drain()
                # Clean exit only happens when stop_event is set; loop
                # condition will pick that up and we'll fall through.
            except asyncio.CancelledError:
                logger.info("lineage_consumer_supervisor_cancelled")
                raise
            except Exception as exc:                           # noqa: BLE001
                logger.warning(
                    "lineage_consumer connect/drain failed (%s) — "
                    "retrying in %.1fs", exc, backoff,
                )
                await self._teardown_consumer()
                # Sleep cooperatively so stop() can wake us promptly.
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=backoff,
                    )
                    return                                      # stop signalled
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the supervisor task.  Returns immediately — the actual Kafka
        connection happens in the background, so a missing broker at boot
        no longer blocks app startup OR permanently disables persistence.

        Same external contract as before (caller awaits `start()`); the
        difference is that a startup-time Kafka outage is now recoverable.
        """
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._supervised_run(),
            name="lineage-kafka-consumer-supervisor",
        )
        logger.info(
            "lineage_consumer_supervisor_started topic=%s group=%s "
            "bootstrap=%s", self._topic, self._group_id, self._bootstrap,
        )

    async def stop(self) -> None:
        logger.info("lineage_consumer_stopping")
        self._stop_event.set()

        # Cancel the supervisor; it'll tear down the consumer as it exits.
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):         # noqa: BLE001
                pass
            self._task = None

        # Belt-and-suspenders teardown in case the supervisor exited
        # abnormally and left a consumer dangling.
        await self._teardown_consumer()
        logger.info("lineage_consumer_stopped")
