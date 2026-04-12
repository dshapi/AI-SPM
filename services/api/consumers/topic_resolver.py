"""
consumers/topic_resolver.py
────────────────────────────
Resolves which Kafka topics the WebSocket bridge consumer should subscribe to.

Two service families produce events that the WS bridge needs to forward:

  1. Legacy pipeline (processor, policy-decider, agent, executor, …)
     Topics follow the platform convention: cpm.{tenant_id}.{name}
     Example: cpm.t1.raw, cpm.t1.posture_enriched, cpm.t1.decision, cpm.t1.audit

  2. agent-orchestrator-service (session lifecycle events)
     Topics: cpm.{tenant}.sessions.prompt_received, cpm.{tenant}.sessions.risk_calculated,
             cpm.{tenant}.sessions.policy_decision, cpm.{tenant}.sessions.created,
             cpm.{tenant}.sessions.blocked, cpm.{tenant}.sessions.completed,
             cpm.{tenant}.sessions.llm_response, cpm.{tenant}.sessions.output_scanned

     These already carry event_type, correlation_id, session_id (as UUID),
     source_service, and an ISO-8601 timestamp in the envelope.data field.

Format modes (KAFKA_TOPIC_FORMAT):

  prefixed  (default)
    Legacy-pipeline topics: cpm.{tenant}.{name}
    Orchestrator topics follow the same cpm.{tenant}.sessions.* pattern.

  flat
    Legacy topics have no tenant prefix: raw_events, posture_events, …
    Orchestrator topics still included as-is.

Tenant list: KAFKA_WS_TENANTS (comma-separated, default "t1")
Extra topics: KAFKA_WS_EXTRA_TOPICS (comma-separated, appended)
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

# Whether to include agent-orchestrator-service topics (default: yes)
INCLUDE_ORCHESTRATOR_TOPICS = os.getenv("KAFKA_WS_INCLUDE_ORCHESTRATOR", "true").lower() != "false"

# Subset of legacy platform topics relevant to live session monitoring
_RELEVANT_PLATFORM_TOPICS = ("raw", "posture_enriched", "decision", "audit")

# Flat-format equivalents (legacy / single-tenant)
_FLAT_TOPICS = [
    "raw_events",
    "posture_events",
    "enforcement_actions",
    "audit_export",
]

# agent-orchestrator-service topics — tenant-scoped (cpm.{tenant}.sessions.*).
# _TENANT matches the publisher's logic: first entry from TENANTS env var.
_TENANT = os.getenv("TENANTS", "t1").split(",")[0].strip()

_ORCHESTRATOR_TOPICS = [
    os.getenv("KAFKA_TOPIC_PROMPT_RECEIVED",   f"cpm.{_TENANT}.sessions.prompt_received"),
    os.getenv("KAFKA_TOPIC_RISK_CALCULATED",   f"cpm.{_TENANT}.sessions.risk_calculated"),
    os.getenv("KAFKA_TOPIC_POLICY_DECISION",   f"cpm.{_TENANT}.sessions.policy_decision"),
    os.getenv("KAFKA_TOPIC_SESSION_CREATED",   f"cpm.{_TENANT}.sessions.created"),
    os.getenv("KAFKA_TOPIC_SESSION_BLOCKED",   f"cpm.{_TENANT}.sessions.blocked"),
    os.getenv("KAFKA_TOPIC_SESSION_COMPLETED", f"cpm.{_TENANT}.sessions.completed"),
    os.getenv("KAFKA_TOPIC_LLM_RESPONSE",      f"cpm.{_TENANT}.sessions.llm_response"),
    os.getenv("KAFKA_TOPIC_OUTPUT_SCANNED",    f"cpm.{_TENANT}.sessions.output_scanned"),
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

    # ── Legacy pipeline topics ────────────────────────────────────────────────
    if TOPIC_FORMAT == "flat":
        topics: List[str] = list(_FLAT_TOPICS)
    else:
        topics = []
        for tid in tenants:
            t = topics_for_tenant(tid)
            for attr in _RELEVANT_PLATFORM_TOPICS:
                topics.append(getattr(t, attr))

    # ── Orchestrator topics ───────────────────────────────────────────────────
    if INCLUDE_ORCHESTRATOR_TOPICS:
        topics.extend(_ORCHESTRATOR_TOPICS)

    # ── Operator-specified extras ─────────────────────────────────────────────
    for extra in EXTRA_TOPICS_ENV.split(","):
        extra = extra.strip()
        if extra:
            topics.append(extra)

    unique = list(dict.fromkeys(topics))  # preserve order, deduplicate
    log.info(
        "topic_resolver format=%s tenants=%s orchestrator=%s topics=%s",
        TOPIC_FORMAT, tenants, INCLUDE_ORCHESTRATOR_TOPICS, unique,
    )
    return unique


def infer_source_service(topic: str) -> str:
    """
    Infer which microservice produced a message from the topic name.
    Used to populate WsEvent.source_service when the message body
    does not include a source_service field.

    With send_event() now enriching all legacy messages, this is only
    needed as a final fallback for topics that were not yet migrated.
    """
    t = topic.lower()
    # Orchestrator topics (cpm.t1.sessions.*)
    if "sessions." in t or "prompt_received" in t or "risk_calculated" in t:
        return "agent-orchestrator"
    if "policy_decision" in t or "sessions.blocked" in t or "sessions.created" in t:
        return "agent-orchestrator"
    if "llm_response" in t or "output_scanned" in t or "sessions.completed" in t:
        return "agent-orchestrator"
    # Legacy pipeline topics
    if "raw" in t:
        return "api"
    if "posture" in t or "enriched" in t:
        return "processor"
    if "decision" in t or "enforcement" in t:
        return "policy-decider"
    if "audit" in t:
        return "audit"
    if "memory" in t:
        return "memory-service"
    if "tool" in t:
        return "tool-parser"
    return "unknown"
