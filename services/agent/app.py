"""
Agent Orchestrator — plans tool execution and memory access via OPA intent manifest.
"""
from __future__ import annotations
import logging
import redis
from platform_shared.base_service import ConsumerService
from platform_shared.config import get_settings
from platform_shared.models import (
    DecisionEvent, MemoryRequest, MemoryResult,
    ToolObservation, ToolRequest, FinalResponse, MemoryNamespace,
)
from platform_shared.topics import topics_for_tenant
from platform_shared.opa_client import get_opa_client
from platform_shared.audit import emit_audit
from platform_shared.kafka_utils import safe_send

log = logging.getLogger("agent")
settings = get_settings()


def _get_redis() -> redis.Redis:
    kwargs = {"host": settings.redis_host, "port": settings.redis_port, "decode_responses": True}
    if settings.redis_password:
        kwargs["password"] = settings.redis_password
    return redis.Redis(**kwargs)


class Agent(ConsumerService):
    service_name = "agent"

    def __init__(self):
        t = topics_for_tenant("t1")
        super().__init__(
            [t.decision, t.memory_result, t.tool_observation, t.freeze_control],
            "cpm-agent",
        )
        self._opa = get_opa_client()
        self._redis = _get_redis()

    # ── Freeze state management ───────────────────────────────────────────────

    def _is_frozen(self, tenant_id: str, user_id: str) -> bool:
        r = self._redis
        return (
            r.get(f"freeze:{tenant_id}:{user_id}") == "true"
            or r.get(f"freeze:{tenant_id}:tenant") == "true"
        )

    def _apply_freeze(self, payload: dict) -> None:
        scope = payload.get("scope", "user")
        target = payload.get("target", "")
        action = payload.get("action", "freeze")
        flag = "true" if action == "freeze" else "false"
        r = self._redis

        if scope == "tenant":
            r.set(f"freeze:{target}:tenant", flag)
            log.info("Freeze %s applied to tenant: %s", action, target)
        elif scope == "user":
            parts = target.split(":", 1)
            if len(parts) == 2:
                r.set(f"freeze:{parts[0]}:{parts[1]}", flag)
                log.info("Freeze %s applied to user: %s", action, target)
        elif scope == "session":
            r.set(f"freeze:session:{target}", flag, ex=3600)
            log.info("Freeze %s applied to session: %s", action, target)

    # ── Tool resolution via OPA ───────────────────────────────────────────────

    def _resolve_tool(self, decision: DecisionEvent) -> tuple[str | None, str]:
        """Query OPA agent manifest to determine which tool (if any) to invoke."""
        result = self._opa.eval(
            "/v1/data/spm/agent/resolve_tool",
            {
                "prompt": decision.prompt,
                "posture_score": decision.posture_score,
                "signals": decision.signals,
                "auth_context": decision.auth_context.model_dump(),
            },
        )
        return result.get("tool_name"), result.get("intent", "general")

    # ── Planning ──────────────────────────────────────────────────────────────

    def _plan(self, decision: DecisionEvent) -> tuple:
        """Returns (memory_request, tool_request, final_response) — any can be None."""
        if decision.decision == "block":
            return None, None, FinalResponse(
                event_id=decision.event_id,
                tenant_id=decision.tenant_id,
                user_id=decision.user_id,
                session_id=decision.session_id,
                text="Your request was blocked by posture policy. Please contact your administrator if you believe this is in error.",
                provenance={"reason": decision.reason, "policy_action": decision.action},
                blocked=True,
                reason=decision.reason,
            )

        # Session memory read — always issued
        mem_request = MemoryRequest(
            event_id=decision.event_id,
            tenant_id=decision.tenant_id,
            user_id=decision.user_id,
            session_id=decision.session_id,
            key=f"conv:{decision.user_id}:{decision.session_id}",
            operation="read",
            namespace=MemoryNamespace.SESSION,
            posture_score=decision.posture_score,
            auth_context=decision.auth_context,
            metadata={"signals": decision.signals},
        )

        # Tool resolution via OPA — no string matching in agent
        tool_name, intent = self._resolve_tool(decision)

        if tool_name:
            requires_approval = tool_name in ("gmail.send_email", "file.write", "db.execute")
            tool_request = ToolRequest(
                event_id=decision.event_id,
                tenant_id=decision.tenant_id,
                user_id=decision.user_id,
                session_id=decision.session_id,
                agent_id="cpm-agent-v3",
                tool_name=tool_name,
                tool_args={"source": "agent_planner", "intent": intent},
                posture_score=decision.posture_score,
                signals=decision.signals,
                auth_context=decision.auth_context,
                intent=intent,
                requires_approval=requires_approval,
            )
            return mem_request, tool_request, None

        # No tool: safe summary response
        return mem_request, None, FinalResponse(
            event_id=decision.event_id,
            tenant_id=decision.tenant_id,
            user_id=decision.user_id,
            session_id=decision.session_id,
            text="I reviewed your request. I can provide information but cannot execute privileged actions for this query.",
            provenance={"decision_reason": decision.reason, "intent": intent},
            blocked=False,
        )

    # ── Message dispatch ──────────────────────────────────────────────────────

    def handle(self, payload: dict) -> None:
        # Freeze control
        if "scope" in payload and "action" in payload:
            self._apply_freeze(payload)
            return

        topics = None

        # Decision event — plan execution
        if "decision" in payload:
            decision = DecisionEvent(**payload)
            topics = topics_for_tenant(decision.tenant_id)

            if self._is_frozen(decision.tenant_id, decision.user_id):
                emit_audit(
                    decision.tenant_id, self.service_name, "agent_frozen_skip",
                    event_id=decision.event_id, principal=decision.user_id,
                    session_id=decision.session_id, severity="warning", details={},
                )
                return

            mem, tool, final = self._plan(decision)

            if mem:
                safe_send(self.producer, topics.memory_request, mem.model_dump())
            if tool:
                safe_send(self.producer, topics.tool_request, tool.model_dump())
            if final:
                safe_send(self.producer, topics.final_response, final.model_dump())

            emit_audit(
                decision.tenant_id, self.service_name, "agent_planned",
                event_id=decision.event_id, principal=decision.user_id,
                session_id=decision.session_id,
                details={
                    "tool": tool.tool_name if tool else None,
                    "intent": tool.intent if tool else None,
                    "blocked": final.blocked if final else False,
                },
            )
            return

        # Tool observation — compose final response
        if "observation" in payload:
            obs = ToolObservation(**payload)
            topics = topics_for_tenant(obs.tenant_id)
            notes = obs.sanitization_notes + obs.schema_violations
            text = (
                f"Tool '{obs.tool_name}' completed successfully."
                if obs.observation.get("status") == "ok"
                else f"Tool '{obs.tool_name}' encountered an issue: {obs.observation.get('error', 'unknown error')}"
            )
            final = FinalResponse(
                event_id=obs.event_id,
                tenant_id=obs.tenant_id,
                user_id=obs.user_id,
                session_id=obs.session_id,
                text=text,
                provenance={
                    "tool_name": obs.tool_name,
                    "sanitization_notes": obs.sanitization_notes,
                    "schema_violations": obs.schema_violations,
                },
            )
            safe_send(self.producer, topics.final_response, final.model_dump())
            emit_audit(
                obs.tenant_id, self.service_name, "agent_finalized",
                event_id=obs.event_id, principal=obs.user_id,
                session_id=obs.session_id,
                details={"tool_name": obs.tool_name, "notes": notes},
            )
            return

        # Memory result — log for tracing
        if "operation" in payload and "status" in payload:
            mem = MemoryResult(**payload)
            if not mem.integrity_ok:
                emit_audit(
                    mem.tenant_id, self.service_name, "memory_integrity_failure",
                    event_id=mem.event_id, principal=mem.user_id,
                    session_id=mem.session_id, severity="warning",
                    details={"namespace": mem.namespace, "key": "redacted"},
                )
            return


if __name__ == "__main__":
    Agent().run()
