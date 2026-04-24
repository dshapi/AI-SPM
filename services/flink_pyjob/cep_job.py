"""
PyFlink CEP job — main entry point.

Flow:

  posture_enriched (Kafka source)
      -> JSON parse
      -> keyBy (tenant_id, user_id)
      -> CEPDetector (KeyedProcessFunction with managed state)
      -> Kafka sink (single audit topic — see sinks.py docstring)

Topology decisions:
  - Source uses earliest offset on first deploy, then committed offsets.
    Group ID is stable so a job restart resumes from where it left off.
  - keyBy uses a composite ``tenant|user`` so a single TaskManager slot
    sees all of one user's events.
  - State backend, checkpointing, restart strategy come from
    ``flink/flink-conf.yaml`` — DON'T duplicate that here, env config wins.

Topics:
  - source: ``cpm.<tenant>.posture_enriched`` for each tenant in
    CEP_TENANT_IDS (comma-separated env var).
  - sink:   ``cpm.<tenant>.audit`` (default). Override with
            CEP_AUDIT_TOPIC_SUFFIX=audit_shadow for shadow-run parity
            checks before rolling out CEP rule changes.

  Multi-tenant note: this v1 runs ONE job per tenant. The submit script
  iterates CEP_TENANT_IDS and submits a job per tenant so per-tenant
  scaling and savepoints stay independent. A future v2 can use a
  Flink dynamic source for cross-tenant fan-in.
"""
from __future__ import annotations

import json
import logging
import os
import sys

from services.flink_pyjob.sinks import build_audit_sink
from services.flink_pyjob.state import CEPDetector

log = logging.getLogger("flink-pyjob.cep_job")


def _key_selector(value: dict) -> str:
    """Composite key so each user's events route to one parallel slot."""
    return f"{value['tenant_id']}|{value['user_id']}"


def _parse_json(raw: str) -> dict | None:
    """Return None for malformed records so the topology can filter them out
    instead of crashing the whole job on one bad message."""
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        log.warning("dropping malformed posture_enriched event: %s", exc)
        return None


def build_pipeline(env, *, tenant_id: str, bootstrap_servers: str,
                   sink_topic_suffix: str) -> None:
    """
    Wire one tenant's source -> detector -> sink onto the given
    StreamExecutionEnvironment. Called by main() once per tenant.
    """
    # Lazy imports so this module imports clean for unit tests.
    from pyflink.common import Types, WatermarkStrategy
    from pyflink.common.serialization import SimpleStringSchema
    from pyflink.datastream.connectors.kafka import (
        KafkaOffsetResetStrategy,
        KafkaOffsetsInitializer,
        KafkaSource,
    )

    source_topic = f"cpm.{tenant_id}.posture_enriched"
    sink_topic = f"cpm.{tenant_id}.{sink_topic_suffix}"

    # Resume from committed offsets (= what this consumer-group has
    # already processed). On first launch with no committed offset
    # yet — or after a Kafka log retention truncation — fall back to
    # the EARLIEST available offset so we don't silently skip
    # historical traffic during the shadow run.
    #
    # NOTE: committed_offsets() takes a KafkaOffsetResetStrategy enum
    # value, NOT another KafkaOffsetsInitializer. Passing the latter
    # blows up with `AttributeError: 'KafkaOffsetsInitializer' object
    # has no attribute '_to_j_offset_reset_strategy'`.
    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_topics(source_topic)
        .set_group_id(f"flink-cep-pyjob-{tenant_id}")
        .set_starting_offsets(
            KafkaOffsetsInitializer.committed_offsets(
                KafkaOffsetResetStrategy.EARLIEST
            )
        )
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    raw_stream = env.from_source(
        source,
        WatermarkStrategy.no_watermarks(),
        f"posture-enriched-{tenant_id}",
    )

    parsed = (
        raw_stream
        .map(_parse_json, output_type=Types.PICKLED_BYTE_ARRAY())
        .filter(lambda v: v is not None)
        .name(f"parse-json-{tenant_id}")
    )

    detected = (
        parsed
        .key_by(_key_selector)
        .process(CEPDetector(), output_type=Types.STRING())
        .name(f"cep-detector-{tenant_id}")
    )

    detected.sink_to(build_audit_sink(
        bootstrap_servers=bootstrap_servers,
        topic=sink_topic,
        transactional_id_prefix=f"flink-cep-pyjob-{tenant_id}",
    )).name(f"audit-sink-{tenant_id}")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka-broker:9092")
    tenant_csv = os.environ.get("CEP_TENANT_IDS", "t1")
    sink_suffix = os.environ.get("CEP_AUDIT_TOPIC_SUFFIX", "audit")

    tenant_ids = [t.strip() for t in tenant_csv.split(",") if t.strip()]
    if not tenant_ids:
        log.error("no tenants in CEP_TENANT_IDS — refusing to start")
        return 2

    log.info(
        "starting flink-pyjob-cep: tenants=%s bootstrap=%s sink_suffix=%s",
        tenant_ids, bootstrap, sink_suffix,
    )

    # Lazy import the env so tests can import this module without PyFlink.
    from pyflink.datastream import StreamExecutionEnvironment

    env = StreamExecutionEnvironment.get_execution_environment()

    # Checkpoint config comes from flink-conf.yaml; we just request that
    # checkpointing be enabled. The interval, mode, and backend are set
    # cluster-side so ops can tune without code changes.
    env.enable_checkpointing(10_000)  # 10s — overrideable via -p in submit.sh

    for tid in tenant_ids:
        build_pipeline(
            env,
            tenant_id=tid,
            bootstrap_servers=bootstrap,
            sink_topic_suffix=sink_suffix,
        )

    env.execute("flink-pyjob-cep")
    return 0


if __name__ == "__main__":
    sys.exit(main())
