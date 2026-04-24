"""
Unit tests for detection.py — pure functions, no Flink runtime.

These tests pin the alert-level cascade so that a rule rewrite can't
silently change classification behavior without failing CI.

The critical-combo test uses a real combination from
platform_shared.risk.CRITICAL_COMBOS so the test fails loudly if that
table is ever rewritten without updating the cascade.
"""
from services.flink_pyjob.detection import (
    build_alert_payload,
    determine_alert_level,
)

# A real entry from CRITICAL_COMBOS — see platform_shared/risk.py:108
REAL_CRITICAL_COMBO = ["prompt_injection", "exfiltration"]


class TestAlertLevelCascade:
    def test_critical_combo_returns_critical(self):
        assert determine_alert_level(
            short_count=0, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=REAL_CRITICAL_COMBO, has_signals=True,
        ) == "critical"

    def test_short_and_long_threshold_returns_critical(self):
        assert determine_alert_level(
            short_count=10, long_count=20, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=["benign_signal"], has_signals=True,
        ) == "critical"

    def test_short_threshold_only_returns_high(self):
        assert determine_alert_level(
            short_count=10, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=["benign_signal"], has_signals=True,
        ) == "high"

    def test_long_threshold_only_returns_high(self):
        assert determine_alert_level(
            short_count=0, long_count=20, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=["benign_signal"], has_signals=True,
        ) == "high"

    def test_drift_above_threshold_returns_medium(self):
        assert determine_alert_level(
            short_count=0, long_count=0, avg_drift=0.95,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=[], has_signals=False,
        ) == "medium"

    def test_increasing_posture_with_high_avg_returns_medium(self):
        assert determine_alert_level(
            short_count=0, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "increasing", "avg": 0.6, "max": 0.7},
            all_signals=[], has_signals=False,
        ) == "medium"

    def test_increasing_posture_with_low_avg_does_not_trip(self):
        # Trend increasing but avg <= 0.50 → no medium escalation
        assert determine_alert_level(
            short_count=0, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "increasing", "avg": 0.3, "max": 0.4},
            all_signals=[], has_signals=False,
        ) == "ok"

    def test_three_or_more_signals_with_signals_flag_returns_low(self):
        assert determine_alert_level(
            short_count=0, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=["sig_a", "sig_b", "sig_c"], has_signals=True,
        ) == "low"

    def test_two_signals_does_not_trip_low(self):
        assert determine_alert_level(
            short_count=0, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=["sig_a", "sig_b"], has_signals=True,
        ) == "ok"

    def test_no_signals_no_thresholds_returns_ok(self):
        assert determine_alert_level(
            short_count=0, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=[], has_signals=False,
        ) == "ok"

    def test_threshold_overrides_are_respected(self):
        # With short_threshold=2, a count of 3 should escalate to high
        assert determine_alert_level(
            short_count=3, long_count=0, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            all_signals=["a"], has_signals=True,
            short_threshold=2,
        ) == "high"


class TestBuildAlertPayload:
    def test_includes_all_required_fields_in_correct_shape(self):
        payload = build_alert_payload(
            short_count=5, long_count=15,
            all_signals=["sig_a", "sig_b"],
            ttps=["AML.T0048", "AML.T0051"],
            critical_combo=False,
            avg_drift=0.42,
            posture_trend={"trend": "stable", "avg": 0.3, "max": 0.5},
            posture_score=0.45,
            alert_level="high",
        )
        assert payload == {
            "short_window_count": 5,
            "long_window_count": 15,
            "session_signals": ["sig_a", "sig_b"],
            "ttps": ["AML.T0048", "AML.T0051"],
            "critical_combo": False,
            "avg_intent_drift": 0.42,
            "posture_trend": {"trend": "stable", "avg": 0.3, "max": 0.5},
            "posture_score": 0.45,
            "alert_level": "high",
        }

    def test_avg_drift_rounded_to_4_dp(self):
        payload = build_alert_payload(
            short_count=0, long_count=0, all_signals=[], ttps=[],
            critical_combo=False, avg_drift=0.123456789,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            posture_score=0.0, alert_level="ok",
        )
        assert payload["avg_intent_drift"] == 0.1235

    def test_session_signals_is_a_new_list_not_alias(self):
        sigs = ["a", "b"]
        payload = build_alert_payload(
            short_count=0, long_count=0, all_signals=sigs, ttps=[],
            critical_combo=False, avg_drift=0.0,
            posture_trend={"trend": "stable", "avg": 0.0, "max": 0.0},
            posture_score=0.0, alert_level="ok",
        )
        sigs.append("c")
        assert payload["session_signals"] == ["a", "b"]
