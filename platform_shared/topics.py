"""
Kafka topic registry — deterministic topic names per tenant.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantTopics:
    raw: str
    retrieved: str
    posture_enriched: str
    decision: str
    memory_request: str
    memory_result: str
    tool_request: str
    tool_result: str
    tool_observation: str
    final_response: str
    freeze_control: str
    audit: str
    # Secondary sink used for shadow-run parity checks before rolling out
    # CEP rule changes. Inert by default; the PyFlink job only writes to
    # it when CEP_AUDIT_TOPIC_SUFFIX=audit_shadow.
    audit_shadow: str
    approval_request: str
    approval_result: str
    simulation_events: str

    def all_topics(self) -> list[str]:
        return [
            self.raw, self.retrieved, self.posture_enriched,
            self.decision, self.memory_request, self.memory_result,
            self.tool_request, self.tool_result, self.tool_observation,
            self.final_response, self.freeze_control, self.audit,
            self.audit_shadow,
            self.approval_request, self.approval_result,
            self.simulation_events,
        ]


def topics_for_tenant(tenant_id: str) -> TenantTopics:
    p = f"cpm.{tenant_id}"
    return TenantTopics(
        raw=f"{p}.raw",
        retrieved=f"{p}.retrieved",
        posture_enriched=f"{p}.posture_enriched",
        decision=f"{p}.decision",
        memory_request=f"{p}.memory_request",
        memory_result=f"{p}.memory_result",
        tool_request=f"{p}.tool_request",
        tool_result=f"{p}.tool_result",
        tool_observation=f"{p}.tool_observation",
        final_response=f"{p}.final_response",
        freeze_control=f"{p}.freeze_control",
        audit=f"{p}.audit",
        audit_shadow=f"{p}.audit_shadow",
        approval_request=f"{p}.approval_request",
        approval_result=f"{p}.approval_result",
        simulation_events=f"{p}.simulation.events",
    )


def all_topics_for_tenants(tenant_ids: list[str]) -> list[str]:
    topics = []
    for tid in tenant_ids:
        topics.extend(topics_for_tenant(tid).all_topics())
    return topics


@dataclass(frozen=True)
class GlobalTopics:
    MODEL_EVENTS:   str = "cpm.global.model_events"
    # UI-lineage events emitted by the api service (chat + simulation) and
    # consumed by the agent-orchestrator for persistence in session_events.
    # Global (not per-tenant) because the orchestrator runs one consumer
    # group across all tenants and we don't want it to subscribe to a
    # dynamic topic list. tenant_id travels in the envelope payload.
    LINEAGE_EVENTS: str = "cpm.global.lineage_events"
