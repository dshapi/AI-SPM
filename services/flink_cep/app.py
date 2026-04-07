"""
Flink CEP Companion — behavioral chain detection with MITRE ATLAS TTP mapping.

Consumes posture_enriched events (full signal context).
Maintains per-user state across:
  - Short window (burst): default 120s / 5 events
  - Long window (sustained): default 3600s / 15 events
  - Session cumulative signals: tracks all signals across session
  - Intent drift history: rolling average across session
  - Critical combo detection with immediate alert escalation
"""
from __future__ import annotations
import json
import logging
import time
import redis
from platform_shared.base_service import ConsumerService
from platform_shared.config import get_settings
from platform_shared.models import PostureEnrichedEvent
from platform_shared.topics import topics_for_tenant
from platform_shared.risk import map_ttps, is_critical_combination
from platform_shared.audit import emit_audit, emit_security_alert
from platform_shared.kafka_utils import safe_send

log = logging.getLogger("flink-cep")
settings = get_settings()


def _get_redis() -> redis.Redis:
    kwargs = {"host": settings.redis_host, "port": settings.redis_port, "decode_responses": True}
    if settings.redis_password:
        kwargs["password"] = settings.redis_password
    return redis.Redis(**kwargs)


class CEPState:
    """Manages all per-user/session CEP state in Redis."""

    def __init__(self, r: redis.Redis, tenant_id: str, user_id: str, session_id: str):
        self._r = r
        self._tid = tenant_id
        self._uid = user_id
        self._sid = session_id

    def _key(self, suffix: str) -> str:
        return f"cep:{self._tid}:{self._uid}:{suffix}"

    def _session_key(self, suffix: str) -> str:
        return f"cep:{self._tid}:{self._uid}:{self._sid}:{suffix}"

    def update_event_windows(self, ts_s: int, event_id: str, has_signals: bool) -> tuple[int, int]:
        """Update sliding windows. Returns (short_count, long_count)."""
        if not has_signals:
            short_count = self._r.zcard(self._key("short"))
            long_count = self._r.zcard(self._key("long"))
            return short_count, long_count

        member = f"{ts_s}:{event_id[:8]}"
        pipe = self._r.pipeline()

        # Short window
        sk = self._key("short")
        pipe.zadd(sk, {member: ts_s})
        pipe.zremrangebyscore(sk, "-inf", ts_s - settings.cep_short_window_sec)
        pipe.expire(sk, settings.cep_short_window_sec + 60)

        # Long window
        lk = self._key("long")
        pipe.zadd(lk, {member: ts_s})
        pipe.zremrangebyscore(lk, "-inf", ts_s - settings.cep_long_window_sec)
        pipe.expire(lk, settings.cep_long_window_sec + 60)

        pipe.execute()
        return self._r.zcard(sk), self._r.zcard(lk)

    def accumulate_session_signals(self, signals: list[str]) -> list[str]:
        """Add new signals to session set. Returns all signals seen in session."""
        key = self._session_key("signals")
        if signals:
            self._r.sadd(key, *signals)
            self._r.expire(key, settings.cep_long_window_sec)
        return list(self._r.smembers(key))

    def update_drift_history(self, drift_score: float) -> float:
        """Append drift score to history. Returns rolling average."""
        key = self._session_key("drift")
        pipe = self._r.pipeline()
        pipe.rpush(key, str(drift_score))
        pipe.ltrim(key, -settings.cep_session_history_size, -1)
        pipe.expire(key, settings.cep_long_window_sec)
        pipe.execute()
        history = [float(x) for x in self._r.lrange(key, 0, -1)]
        return sum(history) / len(history) if history else 0.0

    def update_posture_history(self, posture_score: float) -> dict:
        """Track posture score trend. Returns trend stats."""
        key = self._session_key("posture")
        self._r.rpush(key, str(posture_score))
        self._r.ltrim(key, -20, -1)
        self._r.expire(key, settings.cep_long_window_sec)
        history = [float(x) for x in self._r.lrange(key, 0, -1)]
        if len(history) < 2:
            return {"trend": "stable", "avg": posture_score, "max": posture_score}
        avg = sum(history) / len(history)
        recent_avg = sum(history[-5:]) / min(len(history), 5)
        trend = "increasing" if recent_avg > avg * 1.20 else "decreasing" if recent_avg < avg * 0.80 else "stable"
        return {"trend": trend, "avg": round(avg, 4), "max": round(max(history), 4)}

    def increment_blocked_count(self) -> int:
        """Track how many events have been blocked for this user today."""
        key = self._key("blocks_today")
        count = self._r.incr(key)
        self._r.expire(key, 86400)
        return count


class CEPCompanion(ConsumerService):
    service_name = "flink-cep"

    def __init__(self):
        super().__init__([topics_for_tenant("t1").posture_enriched], "cpm-flink-cep")
        self._redis = _get_redis()

    def handle(self, payload: dict) -> None:
        event = PostureEnrichedEvent(**payload)
        tid, uid, sid = event.tenant_id, event.user_id, event.session_id
        ts_s = event.ts // 1000
        state = CEPState(self._redis, tid, uid, sid)

        # ── Update windows ─────────────────────────────────────────────────
        has_signals = bool(event.signals)
        short_count, long_count = state.update_event_windows(ts_s, event.event_id, has_signals)

        # ── Accumulate session signals ─────────────────────────────────────
        all_signals = state.accumulate_session_signals(event.signals + event.behavioral_signals)

        # ── Intent drift tracking ──────────────────────────────────────────
        avg_drift = state.update_drift_history(event.intent_drift_score)

        # ── Posture trend ──────────────────────────────────────────────────
        posture_trend = state.update_posture_history(event.posture_score)

        # ── TTP mapping ────────────────────────────────────────────────────
        all_ttps = list(set(event.cep_ttps + map_ttps(all_signals)))
        critical_combo = is_critical_combination(all_signals)

        # ── Determine alert level ──────────────────────────────────────────
        alert_level = "ok"

        if critical_combo:
            alert_level = "critical"
        elif (
            short_count >= settings.cep_short_threshold
            and long_count >= settings.cep_long_threshold
        ):
            alert_level = "critical"
        elif short_count >= settings.cep_short_threshold:
            alert_level = "high"
        elif long_count >= settings.cep_long_threshold:
            alert_level = "high"
        elif avg_drift >= settings.cep_intent_drift_threshold:
            alert_level = "medium"
        elif posture_trend["trend"] == "increasing" and posture_trend["avg"] > 0.50:
            alert_level = "medium"
        elif has_signals and len(all_signals) >= 3:
            alert_level = "low"

        event_type = f"cep_{alert_level}" if alert_level != "ok" else "cep_ok"

        details = {
            "short_window_count": short_count,
            "long_window_count": long_count,
            "session_signals": all_signals,
            "ttps": all_ttps,
            "critical_combo": critical_combo,
            "avg_intent_drift": round(avg_drift, 4),
            "posture_trend": posture_trend,
            "posture_score": event.posture_score,
            "alert_level": alert_level,
        }

        if alert_level in ("critical", "high"):
            emit_security_alert(
                tid, self.service_name, event_type,
                ttp_codes=all_ttps,
                event_id=event.event_id,
                principal=uid,
                session_id=sid,
                details=details,
            )
            log.warning(
                "CEP %s alert: user=%s ttps=%s drift=%.2f",
                alert_level, uid, all_ttps, avg_drift,
            )
        else:
            emit_audit(
                tid, self.service_name, event_type,
                event_id=event.event_id, principal=uid,
                session_id=sid,
                severity="warning" if alert_level in ("medium", "low") else "info",
                details=details,
            )


if __name__ == "__main__":
    CEPCompanion().run()
