"""
consumers/topic_resolver.py
────────────────────────────
Resolves which Kafka topics the WebSocket bridge consumer should subscribe to.

Two formats are supported, controlled by the KAFKA_TOPIC_FORMAT env var:

  prefixed  (default)
    Topics follow the platform convention: cpm.{tenant_id}.{name}
    Example: cpm.t1.raw, cpm.t1.posture_enriched, cpm.t1.decision, cpm.t1.audit
    This is the current production format returned by platform_shared.topics.

  flat
    Legacy / single-tenant deployments where topics have no tenant prefix.
    Example: raw_events, posture_events, enforcement_actions, audit_export
    Enable by setting KAFKA_TOPIC_FORMAT=flat.

Tenant list is read from KAFKA_WS_TENANTS (comma-separated, default "t1").
Additional topics can be injected via KAFKA_WS_EXTRA_TOPICS (comma-separated).

Evolution note:
  As deployments move from multi-tenant fan-out to per-tenant clusters the
  topic names will simplify ("raw" instead of "cpm.t1.raw").  Switching
  KAFKA_TOPIC_FORMAT=flat is sufficient to track that change without a code
  change.  The WsEvent.source_service field is inferred from topic name in
  both modes so the browser contract stays identical.
"""
from __future__ import annotations

import logging
import os
from typing import List

from platform_shared.topics import topics_for_tenant

log = logging.getLogger("api.consumers.topic_resolver")

# ── Environment knobs ─────────────────────────────────────────────────────────

TOPIC_FORMAT = os.getenv("KAFKA_TOPIC_FORMAT", "prefixed").lower()
WS_TENANTS_ENV = os.getenv("KAFKA_WS_TENANTS", "t1")
EXTRA_TOPICS_ENV = os.getenv("KAFKA_WS_EXTRA_TOPICS", "")

# Subset of platform topics relevant to live session monitoring:
#   raw            → prompt received, pre-screen
#   posture_enriched → risk calculation
#   decision       → policy outcome
#   audit          → compliance events
_RELEVANT_PLATFORM_TOPICS = ("raw", "posture_enriched", "decision", "audit")

# Flat-format equivalents (legacy / single-tenant)
_FLAT_TOPICS = [
    "raw_events",
    "posture_events",
    "enforcement_actions",
    "audit_export",
]


def configured_tenants() -> List[str]:
    """Parse KAFKA_WS_TENANTS into a list of tenant IDs."""
    return [t.strip() for t in WS_TENANTS_ENV.split(",") if t.strip()]


def resolve_topics(tenant_ids: List[str] | None = None) -> List[str]:
    """
    Return the deduplicated list of Kafka topics to subscribe to.

    Parameters
    ----------
    tenant_ids : optional override; uses KAFKA_WS_TENANTS env var if None.
    """
    tenants = tenant_ids if tenant_ids is not None else configured_tenants()

    if TOPIC_FORMAT == "flat":
        topics = list(_FLAT_TOPICS)
    else:
        topics = []
        for tid in tenants:
            t = topics_for_tenant(tid)
            for attr in _RELEVANT_PLATFORM_TOPICS:
                topics.append(getattr(t, attr))

    # Inject any operator-specified extras
    for extra in EXTRA_TOPICS_ENV.split(","):
        extra = extra.strip()
        if extra:
            topics.append(extra)

    unique = list(dict.fromkeys(topics))  # preserve order, deduplicate
    log.info(
        "topic_resolver format=%s tenants=%s topics=%s",
        TOPIC_FORMAT, tenants, unique,
    )
    return unique


def infer_source_service(topic: str) -> str:
    """
    Infer which microservice produced a message from the topic name.
    Used to populate WsEvent.source_service when the message body
    does not include a source_service field.
    """
    t = topic.lower()
    if "raw" in t:
        return "api"
    if "posture" in t or "enriched" in t:
        return "posture-engine"
    if "decision" in t or "enforcement" in t:
        return "policy-engine"
    if "audit" in t:
        return "audit-service"
    if "memory" in t:
        return "memory-service"
    if "tool" in t:
        return "tool-executor"
    return "unknown"
