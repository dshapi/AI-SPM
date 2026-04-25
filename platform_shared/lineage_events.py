"""
platform_shared/lineage_events.py
─────────────────────────────────
Publisher helpers for UI-lineage events on the Kafka transport.

Replaces the previous per-event HTTP dual-write from the api service to the
orchestrator's POST /api/v1/lineage/events endpoint. The api service now
publishes to a single global topic (GlobalTopics.LINEAGE_EVENTS) and the
orchestrator runs one consumer group that drains it into session_events.

Envelope shape — MUST stay byte-identical to LineageEventIngest
───────────────────────────────────────────────────────────────
The Kafka payload is the exact dict the HTTP endpoint accepted, so the
consumer can call the same persistence path as the HTTP handler without
any field renaming. This is the cornerstone of end-result parity:
given the same input event, the persisted EventRecord is identical
whether the event arrived via HTTP or Kafka.

    {
      "session_id":     str,
      "event_type":     str,
      "payload":        dict,
      "timestamp":      str | None    (ISO-8601 UTC, server fills if absent),
      "correlation_id": str | None,
      "agent_id":       str | None,   (parent-session upsert hint)
      "user_id":        str | None,
      "tenant_id":      str | None,
      "source":         str,          (e.g. "api-chat" | "api-simulation")
    }

Best-effort semantics
─────────────────────
publish_lineage_event() returns a bool (True on send success, False on
broker error or producer-None). Callers MUST treat the publish as
fire-and-forget — the WS broadcast is the user-visible hot path; the
Kafka publish only affects Replay/persistence. A False return is logged
but never raised.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from platform_shared.kafka_utils import safe_send
from platform_shared.topics import GlobalTopics

log = logging.getLogger(__name__)


def build_lineage_envelope(
    *,
    session_id:     str,
    event_type:     str,
    payload:        Dict[str, Any],
    timestamp:      Optional[str]  = None,
    correlation_id: Optional[str]  = None,
    agent_id:       Optional[str]  = None,
    user_id:        Optional[str]  = None,
    tenant_id:      Optional[str]  = None,
    source:         str            = "api-chat",
) -> Dict[str, Any]:
    """
    Build the envelope dict shared by the Kafka producer and the consumer's
    HTTP-equivalent persistence call.

    Kept as a standalone pure function so the parity tests can construct an
    envelope identical to what the producer would emit, feed it to the
    consumer's handler, and assert the resulting EventRecord matches the one
    the legacy HTTP endpoint would have produced for the same inputs.
    """
    return {
        "session_id":     session_id,
        "event_type":     event_type,
        "payload":        payload or {},
        "timestamp":      timestamp,
        "correlation_id": correlation_id,
        "agent_id":       agent_id,
        "user_id":        user_id,
        "tenant_id":      tenant_id,
        "source":         source,
    }


def publish_lineage_event(
    producer,
    *,
    session_id:     str,
    event_type:     str,
    payload:        Dict[str, Any],
    timestamp:      Optional[str]  = None,
    correlation_id: Optional[str]  = None,
    agent_id:       Optional[str]  = None,
    user_id:        Optional[str]  = None,
    tenant_id:      Optional[str]  = None,
    source:         str            = "api-chat",
) -> bool:
    """
    Publish one UI-lineage event to the global lineage topic.

    Returns True on send success, False on broker error or when *producer*
    is None (producer-None happens in tests and during early startup before
    KafkaProducer is built; we never raise so the api service hot path is
    never affected).
    """
    if producer is None:
        log.debug("publish_lineage_event: producer is None — skipping (event_type=%s)",
                  event_type)
        return False

    envelope = build_lineage_envelope(
        session_id     = session_id,
        event_type     = event_type,
        payload        = payload,
        timestamp      = timestamp,
        correlation_id = correlation_id,
        agent_id       = agent_id,
        user_id        = user_id,
        tenant_id      = tenant_id,
        source         = source,
    )
    ok = safe_send(producer, GlobalTopics.LINEAGE_EVENTS, envelope)
    if not ok:
        log.warning(
            "lineage publish failed session=%s type=%s — event will not be persisted",
            session_id, event_type,
        )
    return ok


# ─── Agent Runtime Control Plane event types ───────────────────────────────
#
# Customer-uploaded agents emit lifecycle and runtime-activity events that
# flow through the same audit/lineage pipeline as the rest of the platform.
# Each event is a small, frozen-style dataclass with an explicit `to_dict()`
# so callers can hand the payload to publish_lineage_event(payload=...) or
# to the existing audit_events publisher without intermediate translation.
#
# The `ts` field is auto-populated at construction time (UTC ISO-8601 in
# to_dict()). `event_type` is fixed per class so consumers can dispatch on
# it without reflection.

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentDeployedEvent:
    """Emitted once when an agent transitions from upload → deployed."""
    agent_id:  str
    tenant_id: str
    version:   str
    actor:     str
    ts: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": "AgentDeployed",
            "agent_id":   self.agent_id,
            "tenant_id":  self.tenant_id,
            "version":    self.version,
            "actor":      self.actor,
            "ts":         self.ts.isoformat(),
        }


@dataclass
class AgentStartedEvent:
    """Emitted when the controller spawns the container and SDK reports ready."""
    agent_id:  str
    tenant_id: str
    actor:     str
    ts: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": "AgentStarted",
            "agent_id":   self.agent_id,
            "tenant_id":  self.tenant_id,
            "actor":      self.actor,
            "ts":         self.ts.isoformat(),
        }


@dataclass
class AgentStoppedEvent:
    """Emitted on graceful Stop, Crash recovery, or Retire."""
    agent_id:  str
    tenant_id: str
    reason:    str            # "user_stop" | "crash" | "retire"
    actor:     str
    ts: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": "AgentStopped",
            "agent_id":   self.agent_id,
            "tenant_id":  self.tenant_id,
            "reason":     self.reason,
            "actor":      self.actor,
            "ts":         self.ts.isoformat(),
        }


@dataclass
class AgentChatMessageEvent:
    """Emitted for every user→agent or agent→user message after pipeline checks."""
    agent_id:   str
    tenant_id:  str
    session_id: str
    user_id:    str
    role:       str           # "user" | "agent"
    text:       str
    trace_id:   str
    ts: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": "AgentChatMessage",
            "agent_id":   self.agent_id,
            "tenant_id":  self.tenant_id,
            "session_id": self.session_id,
            "user_id":    self.user_id,
            "role":       self.role,
            "text":       self.text,
            "trace_id":   self.trace_id,
            "ts":         self.ts.isoformat(),
        }


@dataclass
class AgentToolCallEvent:
    """Emitted by spm-mcp for every tool invocation made by an agent."""
    agent_id:    str
    tenant_id:   str
    tool:        str
    args:        Dict[str, Any]
    ok:          bool
    duration_ms: int
    trace_id:    str
    ts: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type":  "AgentToolCall",
            "agent_id":    self.agent_id,
            "tenant_id":   self.tenant_id,
            "tool":        self.tool,
            "args":        self.args,
            "ok":          self.ok,
            "duration_ms": self.duration_ms,
            "trace_id":    self.trace_id,
            "ts":          self.ts.isoformat(),
        }


@dataclass
class AgentLLMCallEvent:
    """Emitted by spm-llm-proxy for every LLM call made by an agent."""
    agent_id:           str
    tenant_id:          str
    model:              str
    prompt_tokens:      int
    completion_tokens:  int
    trace_id:           str
    ts: datetime = field(default_factory=_now_utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type":         "AgentLLMCall",
            "agent_id":           self.agent_id,
            "tenant_id":          self.tenant_id,
            "model":              self.model,
            "prompt_tokens":      self.prompt_tokens,
            "completion_tokens":  self.completion_tokens,
            "trace_id":           self.trace_id,
            "ts":                 self.ts.isoformat(),
        }
