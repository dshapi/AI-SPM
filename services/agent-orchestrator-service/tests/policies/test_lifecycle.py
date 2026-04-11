"""
Tests for the pure lifecycle transition engine.
No DB — all pure Python.
"""
import pytest
from policies.lifecycle import (
    PolicyState,
    validate_transition,
    can_be_runtime_active,
    map_mode_to_state,
    TransitionError,
)


# ── PolicyState ───────────────────────────────────────────────────────────────

def test_policy_state_values():
    assert PolicyState.DRAFT.value     == "draft"
    assert PolicyState.MONITOR.value   == "monitor"
    assert PolicyState.ENFORCED.value  == "enforced"
    assert PolicyState.DEPRECATED.value == "deprecated"


# ── Allowed transitions ───────────────────────────────────────────────────────

@pytest.mark.parametrize("from_s,to_s", [
    (PolicyState.DRAFT,    PolicyState.MONITOR),
    (PolicyState.DRAFT,    PolicyState.ENFORCED),
    (PolicyState.DRAFT,    PolicyState.DEPRECATED),
    (PolicyState.MONITOR,  PolicyState.ENFORCED),
    (PolicyState.MONITOR,  PolicyState.DEPRECATED),
    (PolicyState.ENFORCED, PolicyState.DEPRECATED),
    (PolicyState.ENFORCED, PolicyState.MONITOR),
])
def test_valid_transition(from_s, to_s):
    validate_transition(from_s, to_s)   # must not raise


# ── Forbidden transitions ─────────────────────────────────────────────────────
@pytest.mark.parametrize("from_s,to_s", [
    (PolicyState.DEPRECATED, PolicyState.ENFORCED),
    (PolicyState.DEPRECATED, PolicyState.MONITOR),
    (PolicyState.DEPRECATED, PolicyState.DRAFT),
    (PolicyState.ENFORCED,   PolicyState.DRAFT),
    (PolicyState.MONITOR,    PolicyState.DRAFT),
    (PolicyState.DRAFT,      PolicyState.DRAFT),
])
def test_invalid_transition_raises(from_s, to_s):
    with pytest.raises(TransitionError):
        validate_transition(from_s, to_s)


# ── can_be_runtime_active ─────────────────────────────────────────────────────

def test_enforced_can_be_runtime_active():
    assert can_be_runtime_active(PolicyState.ENFORCED) is True

def test_monitor_can_be_runtime_active():
    assert can_be_runtime_active(PolicyState.MONITOR) is True

def test_draft_cannot_be_runtime_active():
    assert can_be_runtime_active(PolicyState.DRAFT) is False

def test_deprecated_cannot_be_runtime_active():
    assert can_be_runtime_active(PolicyState.DEPRECATED) is False


# ── map_mode_to_state (backward compat mapping) ───────────────────────────────

@pytest.mark.parametrize("mode,expected", [
    ("Monitor",  PolicyState.MONITOR),
    ("Enforce",  PolicyState.ENFORCED),
    ("Draft",    PolicyState.DRAFT),
    ("Disabled", PolicyState.DEPRECATED),
    ("Active",   PolicyState.ENFORCED),
    ("monitor",  PolicyState.MONITOR),
    ("unknown",  PolicyState.DRAFT),
])
def test_map_mode_to_state(mode, expected):
    assert map_mode_to_state(mode) == expected
