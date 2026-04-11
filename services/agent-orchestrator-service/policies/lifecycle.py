"""
policies/lifecycle.py
──────────────────────
Pure lifecycle logic — no database, no I/O.

PolicyState is the canonical state enum for the policy lifecycle engine.
All state transition validation lives here so it can be tested in isolation
and reused from both the repository layer and HTTP handlers.

Allowed transitions
────────────────────
    DRAFT      → MONITOR, ENFORCED*, DEPRECATED
    MONITOR    → ENFORCED, DEPRECATED, MONITOR (no-op demote: ENFORCED → MONITOR)
    ENFORCED   → MONITOR, DEPRECATED
    DEPRECATED → (none — terminal state; use restore to create a new version)

*DRAFT → ENFORCED is allowed (operator shortcut); callers should record a
 reason string to mark it as an override.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


# ── State enum ────────────────────────────────────────────────────────────────

class PolicyState(str, Enum):
    DRAFT      = "draft"
    MONITOR    = "monitor"
    ENFORCED   = "enforced"
    DEPRECATED = "deprecated"


# ── Transition table ─────────────────────────────────────────────────────────

_ALLOWED: dict[PolicyState, set[PolicyState]] = {
    PolicyState.DRAFT:      {PolicyState.MONITOR, PolicyState.ENFORCED, PolicyState.DEPRECATED},
    PolicyState.MONITOR:    {PolicyState.ENFORCED, PolicyState.DEPRECATED, PolicyState.MONITOR},
    PolicyState.ENFORCED:   {PolicyState.MONITOR,  PolicyState.DEPRECATED},
    PolicyState.DEPRECATED: set(),   # terminal — restore creates a new version
}


# ── Exceptions ────────────────────────────────────────────────────────────────

class TransitionError(ValueError):
    """Raised when a requested lifecycle transition is not permitted."""


# ── Public helpers ────────────────────────────────────────────────────────────

def validate_transition(
    from_state: PolicyState,
    to_state: PolicyState,
) -> None:
    """
    Raise TransitionError if from_state → to_state is not a legal move.
    Call this before writing any state change to the database.
    """
    if to_state not in _ALLOWED.get(from_state, set()):
        from_val = from_state.value
        to_val = to_state.value
        allowed_vals = [s.value for s in _ALLOWED[from_state]] or ["none (terminal state)"]
        msg = (
            "Illegal lifecycle transition: " + repr(from_val) + " → " + repr(to_val) + ". "
            "Allowed from " + repr(from_val) + ": " + str(allowed_vals)
        )
        raise TransitionError(msg)


def can_be_runtime_active(state: PolicyState) -> bool:
    """
    Return True if a version in this state is eligible to be runtime-active.
    Only ENFORCED and MONITOR versions affect runtime behaviour.
    """
    return state in (PolicyState.ENFORCED, PolicyState.MONITOR)


def map_mode_to_state(mode: str) -> PolicyState:
    """
    Convert a legacy PolicyORM.mode string to the canonical PolicyState.
    Used during backfill / migration of existing policy rows.

    Mapping rationale
    ─────────────────
    "Enforce" / "Active"  → ENFORCED  (was the primary enforcement state)
    "Monitor"             → MONITOR   (shadow mode — semantics preserved)
    "Draft"               → DRAFT     (not yet promoted)
    "Disabled"            → DEPRECATED (soft-disabled, won't be restored without action)
    unknown               → DRAFT     (safe default — never accidentally enforced)
    """
    _MAP: dict[str, PolicyState] = {
        "enforce":  PolicyState.ENFORCED,
        "active":   PolicyState.ENFORCED,
        "monitor":  PolicyState.MONITOR,
        "draft":    PolicyState.DRAFT,
        "disabled": PolicyState.DEPRECATED,
    }
    return _MAP.get(mode.lower(), PolicyState.DRAFT)


def derive_is_runtime_active(state: PolicyState, legacy_status: Optional[str] = None) -> bool:
    """
    Derive the initial is_runtime_active value during backfill.

    A policy is runtime-active if it's enforced or monitor AND
    its legacy status was "Active" (not "Disabled" / "Archived").
    """
    if not can_be_runtime_active(state):
        return False
    if legacy_status and legacy_status.lower() in ("disabled", "archived"):
        return False
    return True
