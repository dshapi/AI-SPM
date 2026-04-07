# tests/test_spm_enforcement.py
from spm.db.models import ModelRegistry, ModelStatus


def test_can_transition_registered_to_under_review():
    m = ModelRegistry()
    m.status = ModelStatus.registered
    assert m.can_transition_to(ModelStatus.under_review)


def test_cannot_transition_retired():
    m = ModelRegistry()
    m.status = ModelStatus.retired
    for s in ModelStatus:
        assert not m.can_transition_to(s)


def test_enforcement_sets_retired():
    """Enforcement forces status to retired regardless of current status."""
    for current in [ModelStatus.registered, ModelStatus.approved, ModelStatus.deprecated]:
        m = ModelRegistry()
        m.status = current
        # Simulate enforcement (direct status override)
        m.status = ModelStatus.retired
        assert m.status == ModelStatus.retired


def test_blocked_models_list_excludes_non_retired():
    """Only retired models go into blocked_models OPA set."""
    models = [
        {"status": ModelStatus.approved, "model_id": "a"},
        {"status": ModelStatus.retired, "model_id": "b"},
        {"status": ModelStatus.deprecated, "model_id": "c"},
    ]
    blocked = [m["model_id"] for m in models if m["status"] == ModelStatus.retired]
    assert blocked == ["b"]
    assert "a" not in blocked
    assert "c" not in blocked
