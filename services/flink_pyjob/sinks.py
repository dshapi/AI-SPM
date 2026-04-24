"""
Kafka sink builders for the PyFlink CEP job.

Single sink, single topic. ``platform_shared/audit.py`` writes BOTH
security alerts and audit events to ``cpm.<tenant>.audit``. The
downstream router (api / orchestrator) distinguishes by ``severity``
field on the envelope, not by topic.

The destination topic is parameterized by CEP_AUDIT_TOPIC_SUFFIX
(default ``audit``). For a future shadow run — e.g., before rolling
out a CEP rule rewrite — set the suffix to ``audit_shadow`` so the
job writes to a side topic without polluting the live audit stream.

PyFlink imports are deferred so this module imports clean in
environments without apache-flink (e.g. CI's pure-logic test job).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyflink.datastream.connectors.kafka import KafkaSink


def build_audit_sink(
    bootstrap_servers: str,
    topic: str,
    transactional_id_prefix: str = "flink-cep-pyjob",
) -> "KafkaSink":
    """
    Build a single KafkaSink for the per-event envelope produced by
    CEPDetector. Uses EXACTLY_ONCE delivery so a job restart from
    checkpoint doesn't duplicate audit writes.

    Args:
        bootstrap_servers: Comma-separated Kafka bootstrap list, e.g.
            ``"kafka-broker:9092"``.
        topic: Destination topic — typically ``"cpm.<tenant>.audit"``.
            For shadow-run parity checks, pass
            ``"cpm.<tenant>.audit_shadow"``.
        transactional_id_prefix: Stable prefix for Kafka transactional
            IDs. Must NOT change across job restarts or the broker will
            see "new" producers and fence the in-flight transactions.
    """
    # Lazy imports — see module docstring.
    from pyflink.common import Duration
    from pyflink.common.serialization import SimpleStringSchema
    from pyflink.datastream.connectors.base import DeliveryGuarantee
    from pyflink.datastream.connectors.kafka import (
        KafkaRecordSerializationSchema,
        KafkaSink,
    )

    serializer = (
        KafkaRecordSerializationSchema.builder()
        .set_topic(topic)
        .set_value_serialization_schema(SimpleStringSchema())
        .build()
    )

    return (
        KafkaSink.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_record_serializer(serializer)
        .set_delivery_guarantee(DeliveryGuarantee.EXACTLY_ONCE)
        .set_transactional_id_prefix(transactional_id_prefix)
        # Match Kafka broker's transaction.max.timeout.ms (default 15min).
        # Flink checkpoint interval is 10s so this is comfortably above.
        .set_property("transaction.timeout.ms", str(14 * 60 * 1000))
        .build()
    )
