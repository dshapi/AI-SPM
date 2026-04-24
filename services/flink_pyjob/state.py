"""
CEPDetector — Flink KeyedProcessFunction that maintains all per-user
sliding-window and session state.

State organisation. Flink keyBy is (tenant_id, user_id). State is split
into TWO scopes under the user-keyed operator:

  USER-scoped:
    short_events:    ListState[Tuple[long, str]]   — (ts_s, event_id_short)
    long_events:     ListState[Tuple[long, str]]   — (ts_s, event_id_short)
    blocked_today:   ValueState[int]               — counter, daily TTL

  SESSION-scoped. Implemented as ``MapState[session_id → json-payload]``,
  sub-keyed by session_id so each session has its own slice under the
  user-keyed operator. JSON-encoded because PyFlink's MapState value
  typing is awkward for List[T]:
    session_signals: MapState[str, str]   — value=JSON list[str] (set semantics)
    drift_history:   MapState[str, str]   — value=JSON list[float], bounded
    posture_history: MapState[str, str]   — value=JSON list[float], bounded

Implementation notes:

  - Sliding windows use ListState[Tuple[ts, id]] + eviction in the
    process method (Flink has no native sorted set).
  - Session signals use a JSON-encoded list[str] in MapState (no native
    set type; membership is enforced in user code on append).
  - Expiry uses Flink state TTL config + size truncation. Per-session
    sub-entries get per-entry TTL via StateTtlConfig on the MapState
    descriptor, so a stale session ages out without leaking.

OUTPUT envelope shape: matches platform_shared.models.AuditEvent EXACTLY
(component / correlation_id / severity in {info,warning,critical}, etc.)
so the downstream consumer (api / orchestrator) can deserialize via that
model without special-casing this producer.

PyFlink imports are deferred to method bodies / TYPE_CHECKING so the
unit tests for `_evict_old_events` can run in any pytest environment
without apache-flink installed.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Iterable, List, Tuple, TYPE_CHECKING

from services.flink_pyjob.detection import (
    build_alert_payload,
    determine_alert_level,
)
from platform_shared.risk import is_critical_combination, map_ttps

# alert_level → AuditEvent.severity (Literal["info","warning","critical"]).
# critical/high → critical, medium/low → warning, ok → info.
_SEVERITY_BY_LEVEL = {
    "critical": "critical",
    "high":     "critical",
    "medium":   "warning",
    "low":      "warning",
    "ok":       "info",
}

if TYPE_CHECKING:
    from pyflink.datastream import KeyedProcessFunction, RuntimeContext
    _Base = KeyedProcessFunction
else:
    try:
        from pyflink.datastream import KeyedProcessFunction as _Base
    except ImportError:
        # Allow `import services.flink_pyjob.state` in environments where
        # PyFlink isn't installed (notably CI's pure-logic test job).
        # The class still defines `_evict_old_events` for unit tests.
        class _Base:  # type: ignore[no-redef]
            pass

log = logging.getLogger("flink-pyjob.cep")

# Window + history sizing — match platform_shared/config defaults
_SHORT_WINDOW_SEC = 120
_LONG_WINDOW_SEC = 3600
_SESSION_HISTORY_SIZE = 20
_POSTURE_HISTORY_SIZE = 20


class CEPDetector(_Base):
    """
    Per-user CEP state machine. One instance per task slot per key group.
    Flink shards by key (user_id), so each user's state lives in exactly
    one parallel instance.
    """

    # ── Pure helper (testable without a running Flink cluster) ───────────────

    @staticmethod
    def _evict_old_events(
        events: Iterable[Tuple[int, str]], ts_now: int, window_sec: int
    ) -> List[Tuple[int, str]]:
        """Keep only events with ts > ts_now - window_sec."""
        cutoff = ts_now - window_sec
        return [(ts, eid) for (ts, eid) in events if ts > cutoff]

    # ── Flink lifecycle ──────────────────────────────────────────────────────

    def open(self, runtime_context: "RuntimeContext") -> None:
        # Lazy imports so this module can be imported without PyFlink.
        from pyflink.common import Time, Types
        from pyflink.datastream.state import (
            ListStateDescriptor,
            MapStateDescriptor,
            StateTtlConfig,
            ValueStateDescriptor,
        )

        ttl_one_day = (
            StateTtlConfig.new_builder(Time.days(1))
            .set_update_type(StateTtlConfig.UpdateType.OnCreateAndWrite)
            .set_state_visibility(StateTtlConfig.StateVisibility.NeverReturnExpired)
            .build()
        )

        short_desc = ListStateDescriptor(
            "short_events", Types.TUPLE([Types.LONG(), Types.STRING()])
        )
        short_desc.enable_time_to_live(ttl_one_day)
        self._short_events = runtime_context.get_list_state(short_desc)

        long_desc = ListStateDescriptor(
            "long_events", Types.TUPLE([Types.LONG(), Types.STRING()])
        )
        long_desc.enable_time_to_live(ttl_one_day)
        self._long_events = runtime_context.get_list_state(long_desc)

        # Session-scoped state is keyed by session_id underneath the
        # user-keyed Flink operator. Value is a JSON string holding the
        # per-session payload (list[str] for signals, list[float] for
        # drift / posture). See module docstring for the parity rationale.
        sigs_desc = MapStateDescriptor(
            "session_signals_by_sid", Types.STRING(), Types.STRING()
        )
        sigs_desc.enable_time_to_live(ttl_one_day)
        self._session_signals = runtime_context.get_map_state(sigs_desc)

        drift_desc = MapStateDescriptor(
            "drift_history_by_sid", Types.STRING(), Types.STRING()
        )
        drift_desc.enable_time_to_live(ttl_one_day)
        self._drift_history = runtime_context.get_map_state(drift_desc)

        posture_desc = MapStateDescriptor(
            "posture_history_by_sid", Types.STRING(), Types.STRING()
        )
        posture_desc.enable_time_to_live(ttl_one_day)
        self._posture_history = runtime_context.get_map_state(posture_desc)

        blocked_desc = ValueStateDescriptor("blocked_today", Types.INT())
        blocked_desc.enable_time_to_live(ttl_one_day)
        self._blocked_today = runtime_context.get_state(blocked_desc)

    # ── The hot path — called once per posture_enriched event ────────────────

    def process_element(self, value, ctx):
        """
        ``value`` is a JSON-deserialised PostureEnrichedEvent. Yields a
        single JSON envelope string. Routing to security-vs-audit happens
        in the downstream pipeline (cep_job.py) by inspecting
        ``event_type``.
        """
        ts_s = int(value["ts"]) // 1000
        event_id = str(value["event_id"])
        session_id = str(value["session_id"])
        signals = list(value.get("signals") or [])
        behavioral = list(value.get("behavioral_signals") or [])
        all_signals_in = signals + behavioral
        has_signals = bool(signals)
        intent_drift = float(value.get("intent_drift_score", 0.0))
        posture_score = float(value.get("posture_score", 0.0))

        # ── Update sliding windows (USER-scoped) ─────────────────────────────
        short_now: List[Tuple[int, str]] = list(self._short_events.get() or [])
        long_now: List[Tuple[int, str]] = list(self._long_events.get() or [])
        if has_signals:
            short_now.append((ts_s, event_id[:8]))
            long_now.append((ts_s, event_id[:8]))
        short_now = self._evict_old_events(short_now, ts_s, _SHORT_WINDOW_SEC)
        long_now = self._evict_old_events(long_now, ts_s, _LONG_WINDOW_SEC)
        self._short_events.update(short_now)
        self._long_events.update(long_now)
        short_count = len(short_now)
        long_count = len(long_now)

        # ── Accumulate session signals (SESSION-scoped — set semantics) ──────
        # JSON-encoded list in MapState[session_id] with dedupe in code
        # (MapState has no native set type).
        prev_sigs_json = self._session_signals.get(session_id)
        existing_sigs: List[str] = json.loads(prev_sigs_json) if prev_sigs_json else []
        if all_signals_in:
            seen = set(existing_sigs)
            for sig in all_signals_in:
                if sig not in seen:
                    existing_sigs.append(sig)
                    seen.add(sig)
            self._session_signals.put(session_id, json.dumps(existing_sigs))
        all_session_signals = list(existing_sigs)

        # ── Drift history (SESSION-scoped, bounded to last N) ────────────────
        prev_drift_json = self._drift_history.get(session_id)
        drift_now: List[float] = json.loads(prev_drift_json) if prev_drift_json else []
        drift_now.append(intent_drift)
        drift_now = drift_now[-_SESSION_HISTORY_SIZE:]
        self._drift_history.put(session_id, json.dumps(drift_now))
        avg_drift = sum(drift_now) / len(drift_now) if drift_now else 0.0

        # ── Posture history + trend (SESSION-scoped, bounded to last 20) ─────
        prev_post_json = self._posture_history.get(session_id)
        post_now: List[float] = json.loads(prev_post_json) if prev_post_json else []
        post_now.append(posture_score)
        post_now = post_now[-_POSTURE_HISTORY_SIZE:]
        self._posture_history.put(session_id, json.dumps(post_now))
        if len(post_now) < 2:
            posture_trend = {
                "trend": "stable", "avg": posture_score, "max": posture_score
            }
        else:
            avg = sum(post_now) / len(post_now)
            recent_avg = sum(post_now[-5:]) / min(len(post_now), 5)
            if recent_avg > avg * 1.20:
                trend = "increasing"
            elif recent_avg < avg * 0.80:
                trend = "decreasing"
            else:
                trend = "stable"
            posture_trend = {
                "trend": trend,
                "avg": round(avg, 4),
                "max": round(max(post_now), 4),
            }

        # ── TTPs + critical combo ────────────────────────────────────────────
        cep_ttps_in = list(value.get("cep_ttps") or [])
        all_ttps = list(set(cep_ttps_in + map_ttps(all_session_signals)))
        critical_combo = is_critical_combination(all_session_signals)

        # ── Determine alert level via the shared cascade ─────────────────────
        alert_level = determine_alert_level(
            short_count=short_count,
            long_count=long_count,
            avg_drift=avg_drift,
            posture_trend=posture_trend,
            all_signals=all_session_signals,
            has_signals=has_signals,
        )

        # ── Build payload + emit a single envelope ───────────────────────────
        details = build_alert_payload(
            short_count=short_count,
            long_count=long_count,
            all_signals=all_session_signals,
            ttps=all_ttps,
            critical_combo=critical_combo,
            avg_drift=avg_drift,
            posture_trend=posture_trend,
            posture_score=posture_score,
            alert_level=alert_level,
        )

        # Envelope MUST match platform_shared.models.AuditEvent
        # (component, correlation_id, severity ∈ {info,warning,critical}).
        # See module docstring for parity contract.
        envelope = {
            "ts":             int(time.time() * 1000),
            "tenant_id":      value["tenant_id"],
            "component":      "flink-pyjob-cep",
            "event_type":     f"cep_{alert_level}" if alert_level != "ok" else "cep_ok",
            "event_id":       event_id,
            "principal":      value["user_id"],
            "session_id":     value["session_id"],
            "correlation_id": event_id,
            "details":        details,
            "severity":       _SEVERITY_BY_LEVEL[alert_level],
            "ttp_codes":      all_ttps,
        }

        if alert_level in ("critical", "high"):
            log.warning(
                "CEP %s alert: user=%s ttps=%s drift=%.2f",
                alert_level, value["user_id"], all_ttps, avg_drift,
            )

        yield json.dumps(envelope, sort_keys=True)
