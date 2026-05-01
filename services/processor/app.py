"""
Posture Processor — fuses all risk dimensions into a single posture score.

Risk dimensions:
1. prompt_risk     — signal-based + weight scoring
2. behavioral_risk — short + long window burst detection
3. identity_risk   — role and scope analysis
4. memory_risk     — placeholder (updated by memory service results)
5. retrieval_trust — provenance + coherence + anomaly
6. guard_risk      — guard model verdict translation
7. intent_drift    — session-level semantic drift detection
"""
from __future__ import annotations
import os
import time
import logging
import redis
from platform_shared.base_service import ConsumerService
from platform_shared.config import get_settings
from platform_shared.models import RetrievedEvent, PostureEnrichedEvent
from platform_shared.topics import topics_for_tenant
from platform_shared.risk import (
    extract_signals,
    score_prompt,
    score_identity,
    compute_retrieval_trust,
    score_guard,
    compute_intent_drift,
    fuse_risks,
    map_ttps,
    is_critical_combination,
)
from platform_shared.audit import emit_audit, emit_security_alert
from platform_shared.kafka_utils import safe_send, send_event

log = logging.getLogger("processor")
settings = get_settings()
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID")


def _get_redis() -> redis.Redis:
    from platform_shared.redis import get_redis_client
    return get_redis_client(decode_responses=True)


class Processor(ConsumerService):
    service_name = "processor"

    def __init__(self):
        super().__init__([topics_for_tenant("t1").retrieved], "cpm-processor")
        self._redis = _get_redis()

    def _behavioral_risk(
        self, tenant_id: str, user_id: str, ts_ms: int
    ) -> tuple[float, list[str]]:
        """
        Dual-window behavioral analysis:
        - Short window (default 2 min): burst detection
        - Long window (default 1 hour): sustained high-volume detection
        Returns (risk_score, behavioral_signal_list).
        """
        now_s = ts_ms // 1000
        short_key = f"proc:{tenant_id}:{user_id}:events:short"
        long_key = f"proc:{tenant_id}:{user_id}:events:long"
        member = f"{now_s}:{id(self)}"

        # Atomic update using pipeline
        pipe = self._redis.pipeline()
        pipe.zadd(short_key, {member: now_s})
        pipe.zremrangebyscore(short_key, "-inf", now_s - settings.cep_short_window_sec)
        pipe.expire(short_key, settings.cep_short_window_sec + 60)
        pipe.zadd(long_key, {member: now_s})
        pipe.zremrangebyscore(long_key, "-inf", now_s - settings.cep_long_window_sec)
        pipe.expire(long_key, settings.cep_long_window_sec + 60)
        pipe.execute()

        short_count = self._redis.zcard(short_key)
        long_count = self._redis.zcard(long_key)

        signals = []
        risk = 0.0

        if short_count >= settings.cep_short_threshold:
            signals.append("burst_detected")
            risk += 0.20
            log.warning(
                "Burst detected: tenant=%s user=%s count=%d window=%ds",
                tenant_id, user_id, short_count, settings.cep_short_window_sec,
            )

        if long_count >= settings.cep_long_threshold:
            signals.append("sustained_high_volume")
            risk += 0.15
            log.warning(
                "Sustained volume: tenant=%s user=%s count=%d window=%ds",
                tenant_id, user_id, long_count, settings.cep_long_window_sec,
            )

        return min(round(risk, 4), 0.40), signals

    def _compute_intent_drift(
        self, tenant_id: str, user_id: str, session_id: str, prompt: str
    ) -> float:
        """
        Compute intent drift relative to session baseline.
        Maintains a rolling history of the last N prompts in Redis.
        """
        history_key = f"proc:{tenant_id}:{user_id}:{session_id}:prompt_history"
        baseline = self._redis.lrange(history_key, 0, settings.cep_session_history_size - 1)
        drift = compute_intent_drift(list(baseline), prompt)

        # Update history (prepend latest)
        pipe = self._redis.pipeline()
        pipe.lpush(history_key, prompt)
        pipe.ltrim(history_key, 0, settings.cep_session_history_size - 1)
        pipe.expire(history_key, settings.cep_long_window_sec)
        pipe.execute()

        return drift

    def handle(self, payload: dict) -> None:
        event = RetrievedEvent(**payload)
        topics = topics_for_tenant(event.tenant_id)

        # ── Risk dimension computation ──────────────────────────────────────
        signals = extract_signals(event.prompt)
        prompt_risk = score_prompt(event.prompt, signals)
        identity_risk = score_identity(
            event.auth_context.roles, event.auth_context.scopes
        )
        behavior_risk, behavior_signals = self._behavioral_risk(
            event.tenant_id, event.user_id, event.ts
        )
        retrieval_score = compute_retrieval_trust(event.retrieved_contexts)
        guard_risk = score_guard(event.guard_verdict, event.guard_score)
        intent_drift = self._compute_intent_drift(
            event.tenant_id, event.user_id, event.session_id, event.prompt
        )

        posture_score = fuse_risks(
            prompt_risk=prompt_risk,
            behavioral_risk=behavior_risk,
            identity_risk=identity_risk,
            memory_risk=0.0,
            retrieval_trust_score=retrieval_score,
            guard_risk=guard_risk,
            intent_drift=intent_drift,
        )

        ttps = map_ttps(signals + behavior_signals)
        critical = is_critical_combination(signals)

        # ── Emit alert for critical signal combos ───────────────────────────
        if critical or posture_score >= 0.80:
            emit_security_alert(
                event.tenant_id, self.service_name, "high_risk_event",
                ttp_codes=ttps,
                event_id=event.event_id,
                principal=event.user_id,
                session_id=event.session_id,
                details={
                    "posture_score": posture_score,
                    "signals": signals,
                    "critical_combo": critical,
                    "ttps": ttps,
                },
            )

        # ── Build enriched event ────────────────────────────────────────────
        enriched = PostureEnrichedEvent(
            event_id=event.event_id,
            ts=event.ts,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            session_id=event.session_id,
            prompt=event.prompt,
            auth_context=event.auth_context,
            metadata=event.metadata,
            retrieved_contexts=event.retrieved_contexts,
            prompt_risk=prompt_risk,
            behavioral_risk=behavior_risk,
            identity_risk=identity_risk,
            memory_risk=0.0,
            retrieval_trust=retrieval_score,
            guard_risk=guard_risk,
            intent_drift_score=intent_drift,
            posture_score=posture_score,
            signals=signals,
            behavioral_signals=behavior_signals,
            cep_ttps=ttps,
            guard_verdict=event.guard_verdict,
            guard_score=event.guard_score,
            guard_categories=event.guard_categories,
            model_id=LLM_MODEL_ID,
        )

        send_event(
            self.producer, topics.posture_enriched, enriched,
            event_type="posture.enriched",
            source_service="processor",
        )

        emit_audit(
            event.tenant_id, self.service_name, "posture_scored",
            event_id=event.event_id, principal=event.user_id,
            session_id=event.session_id,
            correlation_id=event.event_id,
            details={
                "posture_score": posture_score,
                "prompt_risk": prompt_risk,
                "behavioral_risk": behavior_risk,
                "identity_risk": identity_risk,
                "retrieval_trust": retrieval_score,
                "guard_risk": guard_risk,
                "intent_drift": intent_drift,
                "signals": signals,
                "behavioral_signals": behavior_signals,
                "ttps": ttps,
            },
        )


if __name__ == "__main__":
    Processor().run()
