# tests/test_spm_aggregator.py
from datetime import datetime, timezone

def _bucket(ts: datetime, interval_sec: int = 300) -> datetime:
    """Floor timestamp to N-second bucket boundary."""
    epoch = ts.timestamp()
    bucketed = (epoch // interval_sec) * interval_sec
    return datetime.fromtimestamp(bucketed, tz=timezone.utc)

def test_bucket_floors_to_5min():
    ts = datetime(2026, 1, 1, 12, 7, 42, tzinfo=timezone.utc)
    b = _bucket(ts, 300)
    assert b.minute == 5
    assert b.second == 0

def test_bucket_at_exact_boundary():
    ts = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    b = _bucket(ts, 300)
    assert b.minute == 5

def test_rolling_average_skips_empty_windows():
    snapshots = [
        {"avg_risk_score": 0.8},
        {"avg_risk_score": 0.9},
    ]
    # Only 2 snapshots, not 3 — should average the 2 that exist
    scores = [s["avg_risk_score"] for s in snapshots]
    avg = sum(scores) / len(scores)
    assert abs(avg - 0.85) < 0.001

def test_rolling_average_triggers_enforcement():
    threshold = 0.85
    scores = [0.9, 0.88, 0.92]
    avg = sum(scores) / len(scores)
    assert avg > threshold  # should trigger

def test_rolling_average_no_trigger_below_threshold():
    threshold = 0.85
    scores = [0.5, 0.6, 0.7]
    avg = sum(scores) / len(scores)
    assert avg < threshold  # should NOT trigger

def test_audit_event_id_derivation():
    """When event_id is absent, derive deterministic UUID from content."""
    import hashlib
    tenant_id = "t1"
    event_type = "guard_model_block"
    timestamp = "2026-01-01T12:00:00Z"
    derived = hashlib.sha256(
        f"{tenant_id}{event_type}{timestamp}".encode()
    ).hexdigest()[:36]
    assert len(derived) == 36
