"""
Context Posture Management — Domain Models
All Pydantic v2 models used across every service.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, field_validator
import time


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

class AuthContext(BaseModel):
    sub: str
    tenant_id: str
    roles: List[str] = Field(default_factory=list)
    scopes: List[str] = Field(default_factory=list)
    claims: Dict[str, Any] = Field(default_factory=dict)
    issued_at: int = Field(default_factory=lambda: int(time.time()))
    expires_at: Optional[int] = None

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_any_scope(self, *scopes: str) -> bool:
        return any(s in self.scopes for s in scopes)

    def is_admin(self) -> bool:
        return "spm:admin" in self.roles


# ─────────────────────────────────────────────────────────────────────────────
# Retrieved context
# ─────────────────────────────────────────────────────────────────────────────

class RetrievedContextItem(BaseModel):
    source: str
    owner: str = "unknown"
    classification: Literal["public", "internal", "confidential", "restricted", "external", "unclassified"] = "unclassified"
    freshness_days: int = 365
    content: str
    trust_score: float = 0.5
    sanitization_status: Literal["unchecked", "sanitized", "rejected"] = "unchecked"
    provenance: Dict[str, Any] = Field(default_factory=dict)
    content_hash: Optional[str] = None
    ingestion_hash: Optional[str] = None
    hash_verified: bool = False
    semantic_coherence: float = 1.0
    embedding_anomaly_score: float = 0.0
    retrieval_rank: int = 0

    @field_validator("trust_score", "semantic_coherence", "embedding_anomaly_score")
    @classmethod
    def clamp_float(cls, v: float) -> float:
        return max(0.0, min(1.0, round(v, 4)))


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline events
# ─────────────────────────────────────────────────────────────────────────────

class RawEvent(BaseModel):
    event_id: str
    ts: int
    tenant_id: str
    user_id: str
    session_id: str
    prompt: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    auth_context: AuthContext
    guard_verdict: Literal["allow", "flag", "block", "unchecked"] = "unchecked"
    guard_score: float = 0.0
    guard_categories: List[str] = Field(default_factory=list)
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None


class RetrievedEvent(BaseModel):
    event_id: str
    ts: int
    tenant_id: str
    user_id: str
    session_id: str
    prompt: str
    auth_context: AuthContext
    metadata: Dict[str, Any] = Field(default_factory=dict)
    retrieved_contexts: List[RetrievedContextItem] = Field(default_factory=list)
    retrieval_latency_ms: int = 0
    guard_verdict: Literal["allow", "flag", "block", "unchecked"] = "unchecked"
    guard_score: float = 0.0
    guard_categories: List[str] = Field(default_factory=list)


class PostureEnrichedEvent(BaseModel):
    event_id: str
    ts: int
    tenant_id: str
    user_id: str
    session_id: str
    prompt: str
    auth_context: AuthContext
    metadata: Dict[str, Any] = Field(default_factory=dict)
    retrieved_contexts: List[RetrievedContextItem] = Field(default_factory=list)
    # Risk dimensions
    prompt_risk: float = 0.0
    behavioral_risk: float = 0.0
    identity_risk: float = 0.0
    memory_risk: float = 0.0
    retrieval_trust: float = 1.0
    guard_risk: float = 0.0
    intent_drift_score: float = 0.0
    posture_score: float = 0.0
    # Signals
    signals: List[str] = Field(default_factory=list)
    behavioral_signals: List[str] = Field(default_factory=list)
    cep_ttps: List[str] = Field(default_factory=list)
    # Guard passthrough
    guard_verdict: Literal["allow", "flag", "block", "unchecked"] = "unchecked"
    guard_score: float = 0.0
    guard_categories: List[str] = Field(default_factory=list)
    model_id: Optional[str] = None  # stamped by Processor from LLM_MODEL_ID env var


class DecisionEvent(BaseModel):
    event_id: str
    ts: int
    tenant_id: str
    user_id: str
    session_id: str
    prompt: str
    auth_context: AuthContext
    posture_score: float
    signals: List[str] = Field(default_factory=list)
    decision: Literal["allow", "escalate", "block"] = "block"
    reason: str
    action: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    policy_version: str = "1.0"


# ─────────────────────────────────────────────────────────────────────────────
# Memory
# ─────────────────────────────────────────────────────────────────────────────

class MemoryNamespace:
    SESSION = "session"
    LONGTERM = "longterm"
    SYSTEM = "system"
    ALL = {SESSION, LONGTERM, SYSTEM}


class MemoryRequest(BaseModel):
    event_id: str
    tenant_id: str
    user_id: str
    session_id: str
    key: str
    operation: Literal["read", "write", "delete", "list"] = "read"
    namespace: str = MemoryNamespace.SESSION
    value: Optional[str] = None
    posture_score: float = 0.0
    auth_context: AuthContext
    metadata: Dict[str, Any] = Field(default_factory=dict)
    ttl_override: Optional[int] = None

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        if v not in MemoryNamespace.ALL:
            raise ValueError(f"namespace must be one of {MemoryNamespace.ALL}")
        return v


class MemoryResult(BaseModel):
    event_id: str
    tenant_id: str
    user_id: str
    session_id: str
    operation: str
    namespace: str = MemoryNamespace.SESSION
    status: Literal["ok", "denied", "not_found", "error"] = "ok"
    value: Optional[str] = None
    reason: str = ""
    memory_risk: float = 0.0
    integrity_ok: bool = True
    keys: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────────────────────────────────────

class ToolRequest(BaseModel):
    event_id: str
    tenant_id: str
    user_id: str
    session_id: str
    agent_id: str
    tool_name: str
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    posture_score: float = 0.0
    signals: List[str] = Field(default_factory=list)
    auth_context: AuthContext
    intent: str = "general"
    requires_approval: bool = False
    approval_id: Optional[str] = None


class ToolResult(BaseModel):
    event_id: str
    tenant_id: str
    user_id: str
    session_id: str
    tool_name: str
    status: Literal["ok", "blocked", "error", "pending_approval"] = "ok"
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_ms: int = 0


class ToolObservation(BaseModel):
    event_id: str
    tenant_id: str
    user_id: str
    session_id: str
    tool_name: str
    observation: Dict[str, Any] = Field(default_factory=dict)
    sanitization_notes: List[str] = Field(default_factory=list)
    schema_violations: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────────

class FinalResponse(BaseModel):
    event_id: str
    tenant_id: str
    user_id: str
    session_id: str
    text: str
    provenance: Dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    reason: str = ""
    output_scan_notes: List[str] = Field(default_factory=list)
    pii_redacted: bool = False
    response_latency_ms: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Control plane
# ─────────────────────────────────────────────────────────────────────────────

class FreezeControlEvent(BaseModel):
    scope: Literal["tenant", "user", "session"] = "user"
    target: str
    action: Literal["freeze", "unfreeze"] = "freeze"
    reason: str
    ts: int = Field(default_factory=lambda: int(time.time() * 1000))
    issued_by: str = "system"
    expires_at: Optional[int] = None
    freeze_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    approval_id: str
    event_id: str
    tenant_id: str
    user_id: str
    tool_name: str
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    intent: str
    posture_score: float
    requested_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    status: Literal["pending", "approved", "denied", "expired"] = "pending"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[int] = None


class PolicySimulationRequest(BaseModel):
    tenant_id: str
    candidate_policy_set: str
    sample_events: List[Dict[str, Any]] = Field(default_factory=list)
    dry_run: bool = True


class PolicySimulationResult(BaseModel):
    tenant_id: str
    total_events: int
    allow_count: int
    escalate_count: int
    block_count: int
    results: List[Dict[str, Any]] = Field(default_factory=list)
    policy_version: str = "candidate"


class AuditEvent(BaseModel):
    ts: int = Field(default_factory=lambda: int(time.time() * 1000))
    tenant_id: str
    component: str
    event_type: str
    event_id: Optional[str] = None
    principal: Optional[str] = None
    session_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    severity: Literal["info", "warning", "critical"] = "info"
    ttp_codes: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Startup / inventory
# ─────────────────────────────────────────────────────────────────────────────

class ServiceInventory(BaseModel):
    service: str
    version: str
    model: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    started_at: int = Field(default_factory=lambda: int(time.time()))
    environment: str = "production"


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    service: str
    version: str
    checks: Dict[str, bool] = Field(default_factory=dict)
    uptime_seconds: int = 0
    ts: int = Field(default_factory=lambda: int(time.time()))
