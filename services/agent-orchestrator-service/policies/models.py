"""
policies/models.py
──────────────────
Pydantic schemas for the Policies API.
Policy shape mirrors the frontend POLICIES mock format so the UI can drop
the hardcoded array and fetch from this endpoint with zero rendering changes.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from pydantic import ConfigDict

# ── Sub-schemas ───────────────────────────────────────────────────────────────

class ImpactStats(BaseModel):
    blocked: int = 0
    flagged: int = 0
    unchanged: int = 0
    total: int = 100


class HistoryEntry(BaseModel):
    version: str
    by: str
    when: str
    change: str


# ── Core Policy model ─────────────────────────────────────────────────────────

class Policy(BaseModel):
    """Single policy — mirrors the frontend POLICIES[i] shape."""
    # Identity
    id: str
    name: str
    version: str = "v1"
    type: str                           # prompt-safety | tool-access | data-access | …
    mode: str = "Monitor"               # Enforce | Monitor | Disabled | Draft
    status: str = "Active"             # Active | Disabled | Archived

    # Display
    scope: str = ""                     # human-readable scope string
    owner: str = ""
    created_by: str = Field("", alias="createdBy")
    created: str = ""
    updated: str = ""
    updated_full: str = Field("", alias="updatedFull")
    description: str = ""

    # Stats
    affected_assets: int = Field(0, alias="affectedAssets")
    related_alerts: int = Field(0, alias="relatedAlerts")
    linked_simulations: int = Field(0, alias="linkedSimulations")

    # Scope detail
    agents: list[str] = []
    tools: list[str] = []
    data_sources: list[str] = Field([], alias="dataSources")
    environments: list[str] = []
    exceptions: list[str] = []

    # Impact bar
    impact: ImpactStats = Field(default_factory=ImpactStats)

    # History
    history: list[HistoryEntry] = []

    # Logic — tokens for CodeBlock rendering (list of {t, v} dicts)
    logic: list[dict[str, str]] = []

    # Raw code string for edit mode (not rendered by CodeBlock)
    logic_code: str = ""
    logic_language: str = "rego"        # "rego" | "json"

    model_config = ConfigDict(populate_by_name=True)


# ── Request/response schemas ──────────────────────────────────────────────────

class PolicyCreate(BaseModel):
    name: str
    type: str
    mode: str = "Monitor"
    status: str = "Active"
    scope: str = ""
    owner: str = ""
    description: str = ""
    logic_code: str = ""
    logic_language: str = "rego"
    agents: list[str] = []
    tools: list[str] = []
    data_sources: list[str] = []
    environments: list[str] = []
    exceptions: list[str] = []


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    mode: Optional[str] = None
    status: Optional[str] = None
    scope: Optional[str] = None
    owner: Optional[str] = None
    description: Optional[str] = None
    logic_code: Optional[str] = None
    logic_language: Optional[str] = None
    agents: Optional[list[str]] = None
    tools: Optional[list[str]] = None
    data_sources: Optional[list[str]] = None
    environments: Optional[list[str]] = None
    exceptions: Optional[list[str]] = None


class SimulateRequest(BaseModel):
    """Sample input to run through a policy."""
    input: dict[str, Any] = Field(
        default_factory=lambda: {
            "prompt": "Show me all user records from the database",
            "posture_score": 0.55,
            "signals": ["exfiltration"],
            "guard_verdict": "allow",
        }
    )


class SimulateResponse(BaseModel):
    policy_id: str
    policy_name: str
    decision: str               # allow | block | flag | redact | escalate
    reason: str
    matched_rule: Optional[str] = None
    details: dict[str, Any] = {}


class ValidateResponse(BaseModel):
    policy_id: str
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    line_count: int = 0
