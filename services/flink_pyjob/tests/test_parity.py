"""
Offline scenario test for the CEP cascade.

``services/flink_pyjob/state.py`` calls into
``services/flink_pyjob/detection.py`` for the alert-level cascade and
payload shape. This test pins that contract at unit-test time without
needing a running Flink cluster.

Approach:

  1. Build a synthetic stream of events.
  2. Reconstruct sliding-window state in pure Python (mirrors what the
     KeyedProcessFunction does at runtime).
  3. Call determine_alert_level + build_alert_payload.
  4. Map alert_level → severity using the SAME table state.py uses.
  5. Assert the resulting (alert_level, severity, details) for each
     scenario.

If a future change to the cascade or payload shape breaks one of these
scenarios, this test fails BEFORE the change ships to the cluster.
"""
from __future__ import annotations

from typing import Any

from services.flink_pyjob.detection import (
    build_alert_payload,
    determine_alert_level,
)
from services.flink_pyjob.state import _SEVERITY_BY_LEVEL
from platform_shared.risk import is_critical_combination, map_ttps


# Defaults match platform_shared/config (settings.cep_short_threshold etc.)
# but pinned inline so the test doesn't depend on env state.
SHORT_THRESHOLD = 5
LONG_THRESHOLD = 15
DRIFT_THRESHOLD = 0.85
SHORT_WINDOW_SEC = 120
LONG_WINDOW_SEC = 3600


def _evict(events: list[tuple[int, str]], ts_now: int, window_sec: int) -> list[tuple[int, str]]:
    cutoff = ts_now - window_sec
    return [(ts, eid) for (ts, eid) in events if ts > cutoff]


def _eval_event(state: dict[str, Any], evt: dict[str, Any]) -> dict[str, Any]:
    """Run one event through the shared cascade. Returns the audit
    payload + severity. Mutates `state` in place (per-user accumulator)."""
    ts_s = int(evt["ts"]) // 1000
    eid = evt["event_id"]
    sigs = list(evt.get("signals") or [])
    behavioral = list(evt.get("behavioral_signals") or [])
    all_in = sigs + behavioral
    has_signals = bool(sigs)
    drift = float(evt.get("intent_drift_score", 0.0))
    posture = float(evt.get("posture_score", 0.0))

    short = state.setdefault("short", [])
    long_ = state.setdefault("long", [])
    if has_signals:
        short.append((ts_s, eid[:8]))
        long_.append((ts_s, eid[:8]))
    short[:] = _evict(short, ts_s, SHORT_WINDOW_SEC)
    long_[:] = _evict(long_, ts_s, LONG_WINDOW_SEC)

    session_set = state.setdefault("session_signals", set())
    for s in all_in:
        session_set.add(s)
    all_session = sorted(session_set)  # sorted so the test is deterministic

    drift_hist = state.setdefault("drift_hist", [])
    drift_hist.append(drift)
    drift_hist[:] = drift_hist[-20:]
    avg_drift = sum(drift_hist) / len(drift_hist) if drift_hist else 0.0

    posture_hist = state.setdefault("posture_hist", [])
    posture_hist.append(posture)
    posture_hist[:] = posture_hist[-20:]
    if len(posture_hist) < 2:
        trend = {"trend": "stable", "avg": posture, "max": posture}
    else:
        avg = sum(posture_hist) / len(posture_hist)
        recent = sum(posture_hist[-5:]) / min(len(posture_hist), 5)
        if recent > avg * 1.20:
            t = "increasing"
        elif recent < avg * 0.80:
            t = "decreasing"
        else:
            t = "stable"
        trend = {"trend": t, "avg": round(avg, 4), "max": round(max(posture_hist), 4)}

    cep_ttps_in = list(evt.get("cep_ttps") or [])
    all_ttps = sorted(set(cep_ttps_in + map_ttps(all_session)))
    critical_combo = is_critical_combination(all_session)

    level = determine_alert_level(
        short_count=len(short),
        long_count=len(long_),
        avg_drift=avg_drift,
        posture_trend=trend,
        all_signals=all_session,
        has_signals=has_signals,
        short_threshold=SHORT_THRESHOLD,
        long_threshold=LONG_THRESHOLD,
        drift_threshold=DRIFT_THRESHOLD,
    )
    details = build_alert_payload(
        short_count=len(short),
        long_count=len(long_),
        all_signals=all_session,
        ttps=all_ttps,
        critical_combo=critical_combo,
        avg_drift=avg_drift,
        posture_trend=trend,
        posture_score=posture,
        alert_level=level,
    )
    return {
        "alert_level": level,
        "severity":    _SEVERITY_BY_LEVEL[level],
        "details":     details,
    }


def _make_event(ts_ms: int, signals: list[str] = None,
                behavioral: list[str] = None, drift: float = 0.0,
                posture: float = 0.0, eid: str = None) -> dict:
    return {
        "ts": ts_ms,
        "tenant_id": "t1",
        "user_id": "u1",
        "session_id": "s1",
        "event_id": eid or f"e{ts_ms}",
        "signals": signals or [],
        "behavioral_signals": behavioral or [],
        "intent_drift_score": drift,
        "posture_score": posture,
        "cep_ttps": [],
    }


class TestParityScenarios:
    """
    Each scenario is a synthetic event stream with a known expected
    final alert_level. If either implementation drifts from the shared
    cascade these will fail.
    """

    def test_burst_to_critical(self):
        """5 events in 120s → short threshold trips → high; with long ≥15 → critical."""
        state = {}
        # 5 events with signals in 60s → short=5, long=5 → high
        results = []
        for i in range(5):
            r = _eval_event(state, _make_event(
                ts_ms=(1_000_000 + i * 10) * 1000,
                signals=["benign"], drift=0.1, posture=0.2,
            ))
            results.append(r)
        # Final event should be high (short=5 ≥ 5, long=5 < 15)
        assert results[-1]["alert_level"] == "high"
        assert results[-1]["severity"] == "critical"

    def test_critical_combo_overrides_thresholds(self):
        state = {}
        r = _eval_event(state, _make_event(
            ts_ms=1_000_000_000,
            signals=["prompt_injection", "exfiltration"],
            drift=0.0, posture=0.0,
        ))
        assert r["alert_level"] == "critical"
        assert r["severity"] == "critical"
        assert r["details"]["critical_combo"] is True

    def test_no_signals_stays_ok(self):
        state = {}
        r = _eval_event(state, _make_event(
            ts_ms=1_000_000_000, signals=[], drift=0.0, posture=0.1,
        ))
        assert r["alert_level"] == "ok"
        assert r["severity"] == "info"

    def test_drift_climbs_to_medium(self):
        state = {}
        # Push drift history above 0.85 average
        for i in range(5):
            r = _eval_event(state, _make_event(
                ts_ms=(1_000_000 + i * 10) * 1000,
                signals=[], drift=0.95, posture=0.1,
            ))
        assert r["alert_level"] == "medium"
        assert r["severity"] == "warning"

    def test_three_signals_returns_low(self):
        state = {}
        # First a single-signal event (so has_signals is True on this event)
        # — the cascade requires has_signals AND len(all_signals) >= 3.
        for i, sig in enumerate(["sig_a", "sig_b", "sig_c"]):
            r = _eval_event(state, _make_event(
                ts_ms=(1_000_000 + i * 10) * 1000,
                signals=[sig], drift=0.0, posture=0.1,
            ))
        assert r["alert_level"] == "low"
        assert r["severity"] == "warning"

    def test_window_eviction_lowers_short_count(self):
        state = {}
        # 5 events at t=0..40s — short=5
        for i in range(5):
            _eval_event(state, _make_event(
                ts_ms=(1_000_000 + i * 10) * 1000,
                signals=["benign"], drift=0.1, posture=0.1,
            ))
        # Now jump 200s into the future — all 5 should evict from
        # short window (120s), only the new event remains
        r = _eval_event(state, _make_event(
            ts_ms=(1_000_000 + 250) * 1000,
            signals=["benign"], drift=0.1, posture=0.1,
        ))
        # short=1 (only the new event), long=6 (within 3600s window)
        assert r["details"]["short_window_count"] == 1
        assert r["details"]["long_window_count"] == 6
        # 1 < 5, 6 < 15, no critical combo, drift low, only 1 signal type
        # → ok
        assert r["alert_level"] == "ok"

    def test_severity_mapping_completeness(self):
        """Every alert_level must have a severity mapping."""
        for lvl in ("critical", "high", "medium", "low", "ok"):
            assert lvl in _SEVERITY_BY_LEVEL
        # And severity must be one of the AuditEvent.severity Literal values
        for sev in _SEVERITY_BY_LEVEL.values():
            assert sev in ("info", "warning", "critical")
