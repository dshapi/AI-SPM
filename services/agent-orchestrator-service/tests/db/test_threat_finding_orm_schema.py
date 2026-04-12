"""Smoke-test: every new column must exist on ThreatFindingORM."""
from db.models import ThreatFindingORM

NEW_COLUMNS = {
    "confidence", "risk_score", "hypothesis", "asset", "environment",
    "correlated_events", "correlated_findings", "triggered_policies",
    "policy_signals", "recommended_actions", "should_open_case",
    "case_id", "source", "updated_at", "timestamp",
}

def test_new_columns_on_orm():
    cols = {c.key for c in ThreatFindingORM.__table__.columns}
    missing = NEW_COLUMNS - cols
    assert not missing, f"Missing ORM columns: {missing}"
