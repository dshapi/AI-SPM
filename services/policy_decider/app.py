"""
Policy Decider — evaluates OPA prompt policy and emits DecisionEvent.
"""
from __future__ import annotations
import logging
from platform_shared.base_service import ConsumerService
from platform_shared.models import PostureEnrichedEvent, DecisionEvent
from platform_shared.topics import topics_for_tenant
from platform_shared.opa_client import get_opa_client
from platform_shared.audit import emit_audit
from platform_shared.kafka_utils import safe_send, send_event

log = logging.getLogger("policy-decider")


class PolicyDecider(ConsumerService):
    service_name = "policy-decider"

    def __init__(self):
        super().__init__([topics_for_tenant("t1").posture_enriched], "cpm-policy-decider")
        self._opa = get_opa_client()

    def handle(self, payload: dict) -> None:
        event = PostureEnrichedEvent(**payload)
        topics = topics_for_tenant(event.tenant_id)

        opa_input = {
            "posture_score": event.posture_score,
            "signals": event.signals,
            "behavioral_signals": event.behavioral_signals,
            "retrieval_trust": event.retrieval_trust,
            "intent_drift": event.intent_drift_score,
            "guard_verdict": event.guard_verdict,
            "guard_score": event.guard_score,
            "guard_categories": event.guard_categories,
            "cep_ttps": event.cep_ttps,
            "auth_context": event.auth_context.model_dump(),
        }
        result = self._opa.eval("/v1/data/spm/prompt/allow", opa_input)

        decision = DecisionEvent(
            event_id=event.event_id,
            ts=event.ts,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            session_id=event.session_id,
            prompt=event.prompt,
            auth_context=event.auth_context,
            posture_score=event.posture_score,
            signals=event.signals,
            decision=result.get("decision", "block"),
            reason=result.get("reason", "policy evaluation failed"),
            action=result.get("action", "deny_execution"),
            metadata=event.metadata,
        )

        send_event(
            self.producer, topics.decision, decision,
            event_type="policy.decision",
            source_service="policy-decider",
        )

        emit_audit(
            event.tenant_id, self.service_name, "policy_decision",
            event_id=event.event_id, principal=event.user_id,
            session_id=event.session_id,
            correlation_id=event.event_id,
            severity="warning" if decision.decision == "block" else "info",
            details={
                "decision": decision.decision,
                "reason": decision.reason,
                "posture_score": event.posture_score,
                "action": decision.action,
            },
        )


if __name__ == "__main__":
    PolicyDecider().run()
