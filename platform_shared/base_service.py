"""
Base Kafka consumer service — all pipeline workers extend this class.
"""
from __future__ import annotations
import logging
import signal
import threading
import time
from typing import List

log = logging.getLogger(__name__)


class ConsumerService:
    service_name: str = "base"
    service_version: str = "3.0.0"

    def __init__(self, topics: List[str], group_id: str) -> None:
        from platform_shared.kafka_utils import build_consumer, build_producer
        self.topics = topics
        self.group_id = group_id
        self.consumer = build_consumer(topics, group_id)
        self.producer = build_producer()
        self._running = True
        self._message_count = 0
        self._error_count = 0
        self._start_time = time.time()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        def _stop(sig, frame):
            log.info("[%s] Received signal %s — shutting down", self.service_name, sig)
            self._running = False

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

    def handle(self, payload: dict) -> None:
        """Override in subclass — process one Kafka message payload."""
        raise NotImplementedError(f"{self.service_name}.handle() not implemented")

    def on_start(self) -> None:
        """Called once before the poll loop. Override for init logic."""
        pass

    def on_stop(self) -> None:
        """Called after poll loop exits. Override for cleanup."""
        pass

    def run(self) -> None:
        log.info(
            "[%s v%s] starting — topics=%s group=%s",
            self.service_name, self.service_version, self.topics, self.group_id,
        )
        self.on_start()
        try:
            while self._running:
                messages = self.consumer.poll(timeout_ms=500, max_records=50)
                for tp, records in messages.items():
                    for record in records:
                        if not self._running:
                            break
                        try:
                            self.handle(record.value)
                            self._message_count += 1
                        except Exception as exc:
                            self._error_count += 1
                            log.error(
                                "[%s] error processing message topic=%s partition=%d offset=%d: %s",
                                self.service_name, tp.topic, tp.partition, record.offset, exc,
                                exc_info=True,
                            )
        finally:
            log.info(
                "[%s] stopped — processed=%d errors=%d uptime=%.1fs",
                self.service_name, self._message_count, self._error_count,
                time.time() - self._start_time,
            )
            self.on_stop()
            try:
                self.consumer.close()
                self.producer.close()
            except Exception:
                pass

    def stats(self) -> dict:
        return {
            "service": self.service_name,
            "messages_processed": self._message_count,
            "errors": self._error_count,
            "uptime_seconds": round(time.time() - self._start_time, 1),
        }
