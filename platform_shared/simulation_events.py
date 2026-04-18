"""
platform_shared/simulation_events.py
─────────────────────────────────────
Typed publisher helpers for Simulation Builder events.

All helpers emit to `cpm.{tenant_id}.simulation.events` using the
standard send_event() envelope so the WS bridge forwards them to any
browser connected on that session_id.

Wire format (payload fields):
  simulation.started    prompt, attack_type, execution_mode
  simulation.progress   step, total, message, probe_name (optional)
  simulation.blocked    categories, decision_reason, correlation_id
  simulation.allowed    response_preview, correlation_id
  simulation.completed  summary dict
  simulation.error      error_message
"""
from __future__ import annotations

import datetime
from typing import Any

from platform_shared.kafka_utils import send_event
from platform_shared.topics import topics_for_tenant


def _topic(tenant_id: str) -> str:
    return topics_for_tenant(tenant_id).simulation_events


def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


class _SimPayload:
    """
    Minimal Pydantic-like object accepted by send_event().

    send_event() calls model.model_dump() if present, falling back to
    dict(model).  We implement model_dump() to return the payload dict
    directly so it merges cleanly into the Kafka envelope.
    """
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self.payload


def _emit(producer, tenant_id: str, session_id: str, event_type: str,
          payload: dict[str, Any], correlation_id: str = "") -> None:
    topic = _topic(tenant_id)
    model = _SimPayload(payload)
    send_event(
        producer, topic, model,
        event_type=event_type,
        source_service="api-simulation",
        session_id=session_id,
        correlation_id=correlation_id,
    )


def publish_started(
    producer,
    *,
    session_id: str,
    prompt: str,
    attack_type: str,
    execution_mode: str,
    tenant_id: str = "t1",
) -> None:
    _emit(producer, tenant_id, session_id, "simulation.started", {
        "prompt": prompt,
        "attack_type": attack_type,
        "execution_mode": execution_mode,
    })


def publish_progress(
    producer,
    *,
    session_id: str,
    step: int,
    total: int,
    message: str,
    probe_name: str = "",
    tenant_id: str = "t1",
    correlation_id: str = "",
) -> None:
    _emit(producer, tenant_id, session_id, "simulation.progress", {
        "step": step,
        "total": total,
        "message": message,
        "probe_name": probe_name,
    }, correlation_id=correlation_id)


def publish_blocked(
    producer,
    *,
    session_id: str,
    categories: list[str],
    decision_reason: str,
    correlation_id: str = "",
    tenant_id: str = "t1",
    explanation: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "categories": categories,
        "decision_reason": decision_reason,
    }
    if explanation is not None:
        payload["explanation"] = explanation
    _emit(producer, tenant_id, session_id, "simulation.blocked",
          payload, correlation_id=correlation_id)


def publish_allowed(
    producer,
    *,
    session_id: str,
    response_preview: str = "",
    correlation_id: str = "",
    tenant_id: str = "t1",
) -> None:
    _emit(producer, tenant_id, session_id, "simulation.allowed", {
        "response_preview": response_preview,
    }, correlation_id=correlation_id)


def publish_completed(
    producer,
    *,
    session_id: str,
    summary: dict[str, Any],
    tenant_id: str = "t1",
) -> None:
    _emit(producer, tenant_id, session_id, "simulation.completed", {"summary": summary})


def publish_error(
    producer,
    *,
    session_id: str,
    error_message: str,
    tenant_id: str = "t1",
) -> None:
    _emit(producer, tenant_id, session_id, "simulation.error", {"error_message": error_message})
