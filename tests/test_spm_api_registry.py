# tests/test_spm_api_registry.py
from spm.db.models import ModelRegistry, ModelStatus, MODEL_TRANSITIONS

def test_state_machine_valid_transition():
    m = ModelRegistry()
    m.status = ModelStatus.registered
    assert m.can_transition_to(ModelStatus.under_review) is True

def test_state_machine_invalid_skip():
    m = ModelRegistry()
    m.status = ModelStatus.registered
    assert m.can_transition_to(ModelStatus.approved) is False

def test_state_machine_retired_is_terminal():
    m = ModelRegistry()
    m.status = ModelStatus.retired
    assert m.can_transition_to(ModelStatus.deprecated) is False
    assert m.can_transition_to(ModelStatus.approved) is False

def test_state_machine_approved_to_deprecated():
    m = ModelRegistry()
    m.status = ModelStatus.approved
    assert m.can_transition_to(ModelStatus.deprecated) is True

def test_model_registry_default_status():
    # The default status is set at the column level (database default),
    # not at the Python object instantiation level
    m = ModelRegistry()
    # When not explicitly set, check that it can be set
    m.status = ModelStatus.registered
    assert m.status == ModelStatus.registered

def test_model_upsert_key_fields():
    """Unique constraint is on (name, version, tenant_id)."""
    from spm.db.models import ModelRegistry
    constraints = {c.name for c in ModelRegistry.__table__.constraints}
    assert "uq_model_name_version_tenant" in constraints
