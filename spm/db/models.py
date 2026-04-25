"""
AI SPM — SQLAlchemy ORM models matching 001_initial.sql
"""
from __future__ import annotations
import enum
import uuid
from typing import Dict

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, Index, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ModelProvider(str, enum.Enum):
    # Legacy / conceptual values (kept for back-compat with existing rows + callers)
    local = "local"
    openai = "openai"
    anthropic = "anthropic"
    other = "other"
    # Cloud-provider values surfaced by the admin UI (Inventory → Models)
    aws = "aws"
    azure = "azure"
    gcp = "gcp"
    internal = "internal"


class ModelRiskTier(str, enum.Enum):
    # Legacy EU-AI-Act-style values (kept for back-compat)
    minimal = "minimal"
    limited = "limited"
    high = "high"
    unacceptable = "unacceptable"
    # UI-taxonomy values surfaced in the admin Inventory table
    low = "low"
    medium = "medium"
    critical = "critical"


class ModelStatus(str, enum.Enum):
    registered = "registered"
    under_review = "under_review"
    approved = "approved"
    deprecated = "deprecated"
    retired = "retired"


class ModelType(str, enum.Enum):
    """Coarse functional classification of the model, surfaced as the 'Type' column in the UI."""
    llm = "llm"
    open_source_llm = "open_source_llm"
    embedding_model = "embedding_model"
    audio_model = "audio_model"
    vision_model = "vision_model"
    multimodal = "multimodal"
    other = "other"


class PolicyCoverage(str, enum.Enum):
    """Policy coverage level surfaced as the 'Policy' column in the Inventory table."""
    full = "full"         # → "Covered"
    partial = "partial"   # → "Partial"
    none = "none"         # → "None"


class ComplianceStatus(str, enum.Enum):
    satisfied = "satisfied"
    partial = "partial"
    not_satisfied = "not_satisfied"


# Valid lifecycle transitions
MODEL_TRANSITIONS: Dict[ModelStatus, set] = {
    ModelStatus.registered:   {ModelStatus.under_review},
    ModelStatus.under_review: {ModelStatus.approved, ModelStatus.registered},
    ModelStatus.approved:     {ModelStatus.deprecated},
    ModelStatus.deprecated:   {ModelStatus.retired},
    ModelStatus.retired:      set(),  # terminal
}


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    model_id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name          = Column(Text, nullable=False)
    version       = Column(Text, nullable=False)
    provider      = Column(Enum(ModelProvider, name="model_provider"), nullable=False, default=ModelProvider.local)
    purpose       = Column(Text)
    risk_tier     = Column(Enum(ModelRiskTier, name="model_risk_tier"), nullable=False, default=ModelRiskTier.limited)
    model_type    = Column(Enum(ModelType, name="model_type"), nullable=True)
    # Inventory-table fields (surfaced as Owner / Policy / Alerts columns)
    owner         = Column(Text, nullable=True)
    policy_status = Column(Enum(PolicyCoverage, name="policy_coverage"), nullable=True)
    alerts_count  = Column(Integer, nullable=False, default=0, server_default="0")
    last_seen_at  = Column(DateTime(timezone=True), nullable=True)
    tenant_id     = Column(Text, nullable=False, default="global")
    status        = Column(Enum(ModelStatus, name="model_status"), nullable=False, default=ModelStatus.registered)
    approved_by   = Column(Text)
    approved_at   = Column(DateTime(timezone=True))
    notes         = Column(Text, nullable=True)
    ai_sbom       = Column(JSONB, default=dict)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("name", "version", "tenant_id", name="uq_model_name_version_tenant"),
    )

    def can_transition_to(self, new_status: ModelStatus) -> bool:
        return new_status in MODEL_TRANSITIONS.get(self.status, set())


class PostureSnapshot(Base):
    __tablename__ = "posture_snapshots"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    model_id         = Column(UUID(as_uuid=True), nullable=True)
    tenant_id        = Column(Text, nullable=False)
    snapshot_at      = Column(DateTime(timezone=True), nullable=False)
    request_count    = Column(Integer, default=0)
    block_count      = Column(Integer, default=0)
    escalation_count = Column(Integer, default=0)
    avg_risk_score   = Column(Float, default=0.0)
    max_risk_score   = Column(Float, default=0.0)
    intent_drift_avg = Column(Float, default=0.0)
    ttp_hit_count    = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_snapshots_model_tenant_time", "model_id", "tenant_id", "snapshot_at"),
    )


class ComplianceEvidence(Base):
    __tablename__ = "compliance_evidence"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    framework         = Column(Text, nullable=False, default="NIST_AI_RMF")
    function          = Column(Text, nullable=False)
    category          = Column(Text, nullable=False)
    subcategory       = Column(Text)
    cpm_control       = Column(Text, nullable=False)
    status            = Column(Enum(ComplianceStatus, name="compliance_status"), nullable=False, default=ComplianceStatus.not_satisfied)
    evidence_ref      = Column(JSONB, default=dict)
    last_evaluated_at = Column(DateTime(timezone=True))


class AuditExport(Base):
    __tablename__ = "audit_export"

    event_id   = Column(Text, primary_key=True)
    tenant_id  = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    actor      = Column(Text)
    timestamp  = Column(DateTime(timezone=True), nullable=False)
    payload    = Column(JSONB, nullable=False)
    session_id = Column(String(64), nullable=True)

    __table_args__ = (
        Index("idx_audit_export_session_id", "session_id"),
    )


# ─── Integrations module ────────────────────────────────────────────────────────
# Single source of truth for the Admin → Integrations page.  Mirrors the
# shape used by the UI (MOCK_INTEGRATIONS) so the seed script can migrate
# existing mock entries row-for-row.


class IntegrationStatus(str, enum.Enum):
    Healthy = "Healthy"
    Warning = "Warning"
    Error = "Error"
    NotConfigured = "Not Configured"
    Disabled = "Disabled"
    Partial = "Partial"


class IntegrationAuthMethod(str, enum.Enum):
    api_key = "API Key"
    oauth = "OAuth"
    iam_role = "IAM Role"
    service_account = "Service Account"


class IntegrationActivityResult(str, enum.Enum):
    Success = "Success"
    Warning = "Warning"
    Error = "Error"
    Info = "Info"


class Integration(Base):
    __tablename__ = "integrations"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id   = Column(Text, unique=True, nullable=True)
    # connector_type is the stable registry key ("postgres", "redis", …)
    # that drives schema-based form rendering and probe dispatch.  Nullable
    # for back-compat with rows written before migration 004; name-based
    # dispatch is the fallback when this is null.
    connector_type = Column(Text, nullable=True)
    name          = Column(Text, nullable=False)
    abbrev        = Column(Text, nullable=True)
    category      = Column(Text, nullable=False)
    status        = Column(Enum(IntegrationStatus, name="integration_status",
                                values_callable=lambda e: [m.value for m in e]),
                           nullable=False, default=IntegrationStatus.NotConfigured)
    auth_method   = Column(Enum(IntegrationAuthMethod, name="integration_auth_method",
                                values_callable=lambda e: [m.value for m in e]),
                           nullable=False, default=IntegrationAuthMethod.api_key)
    owner         = Column(Text, nullable=True)
    owner_display = Column(Text, nullable=True)
    environment   = Column(Text, nullable=False, default="Production")
    enabled       = Column(Boolean, nullable=False, default=True, server_default="true")
    description   = Column(Text, nullable=True)
    vendor        = Column(Text, nullable=True)
    tags          = Column(JSONB, nullable=False, default=list, server_default="[]")
    config        = Column(JSONB, nullable=False, default=dict, server_default="{}")
    tenant_id     = Column(Text, nullable=False, default="global", server_default="'global'")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    credentials = relationship("IntegrationCredential", back_populates="integration",
                               cascade="all, delete-orphan", lazy="selectin")
    connection  = relationship("IntegrationConnection", back_populates="integration",
                               uselist=False, cascade="all, delete-orphan", lazy="selectin")
    auth        = relationship("IntegrationAuth", back_populates="integration",
                               uselist=False, cascade="all, delete-orphan", lazy="selectin")
    coverage    = relationship("IntegrationCoverage", back_populates="integration",
                               cascade="all, delete-orphan", lazy="selectin",
                               order_by="IntegrationCoverage.position")
    activity    = relationship("IntegrationActivity", back_populates="integration",
                               cascade="all, delete-orphan", lazy="selectin",
                               order_by="IntegrationActivity.event_at.desc()")
    workflows   = relationship("IntegrationWorkflow", back_populates="integration",
                               uselist=False, cascade="all, delete-orphan", lazy="selectin")
    logs        = relationship("IntegrationLog", back_populates="integration",
                               cascade="all, delete-orphan", lazy="selectin",
                               order_by="IntegrationLog.event_at.desc()")


class IntegrationCredential(Base):
    __tablename__ = "integration_credentials"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id  = Column(UUID(as_uuid=True),
                             ForeignKey("integrations.id", ondelete="CASCADE"),
                             nullable=False)
    credential_type = Column(Text, nullable=False)
    name            = Column(Text, nullable=False)
    value_enc       = Column(Text, nullable=True)
    value_hint      = Column(Text, nullable=True)
    is_configured   = Column(Boolean, nullable=False, default=False, server_default="false")
    rotated_at      = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    integration = relationship("Integration", back_populates="credentials")


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id    = Column(UUID(as_uuid=True),
                               ForeignKey("integrations.id", ondelete="CASCADE"),
                               nullable=False, unique=True)
    last_sync         = Column(Text, nullable=True)
    last_sync_full    = Column(Text, nullable=True)
    last_failed_sync  = Column(Text, nullable=True)
    avg_latency       = Column(Text, nullable=True)
    uptime            = Column(Text, nullable=True)
    health_history    = Column(JSONB, nullable=False, default=list, server_default="[]")
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    integration = relationship("Integration", back_populates="connection")


class IntegrationAuth(Base):
    __tablename__ = "integration_auth"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id  = Column(UUID(as_uuid=True),
                             ForeignKey("integrations.id", ondelete="CASCADE"),
                             nullable=False, unique=True)
    token_expiry    = Column(Text, nullable=True)
    scopes          = Column(JSONB, nullable=False, default=list, server_default="[]")
    missing_scopes  = Column(JSONB, nullable=False, default=list, server_default="[]")
    setup_progress  = Column(JSONB, nullable=True)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    integration = relationship("Integration", back_populates="auth")


class IntegrationCoverage(Base):
    __tablename__ = "integration_coverage"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id  = Column(UUID(as_uuid=True),
                             ForeignKey("integrations.id", ondelete="CASCADE"),
                             nullable=False)
    position        = Column(Integer, nullable=False, default=0, server_default="0")
    label           = Column(Text, nullable=False)
    enabled         = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    integration = relationship("Integration", back_populates="coverage")


class IntegrationActivity(Base):
    __tablename__ = "integration_activity"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id  = Column(UUID(as_uuid=True),
                             ForeignKey("integrations.id", ondelete="CASCADE"),
                             nullable=False)
    ts_display      = Column(Text, nullable=False)
    event_at        = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    event           = Column(Text, nullable=False)
    result          = Column(Enum(IntegrationActivityResult, name="integration_activity_result",
                                  values_callable=lambda e: [m.value for m in e]),
                             nullable=False, default=IntegrationActivityResult.Info)
    actor           = Column(Text, nullable=True)

    integration = relationship("Integration", back_populates="activity")


class IntegrationWorkflow(Base):
    __tablename__ = "integration_workflows"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id  = Column(UUID(as_uuid=True),
                             ForeignKey("integrations.id", ondelete="CASCADE"),
                             nullable=False, unique=True)
    playbooks       = Column(JSONB, nullable=False, default=list, server_default="[]")
    alerts          = Column(JSONB, nullable=False, default=list, server_default="[]")
    policies        = Column(JSONB, nullable=False, default=list, server_default="[]")
    cases           = Column(JSONB, nullable=False, default=list, server_default="[]")
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    integration = relationship("Integration", back_populates="workflows")


class IntegrationLog(Base):
    __tablename__ = "integration_logs"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id  = Column(UUID(as_uuid=True),
                             ForeignKey("integrations.id", ondelete="CASCADE"),
                             nullable=False)
    event_at        = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    action          = Column(Text, nullable=False)
    actor           = Column(Text, nullable=True)
    result          = Column(Enum(IntegrationActivityResult, name="integration_activity_result",
                                  values_callable=lambda e: [m.value for m in e],
                                  create_type=False),
                             nullable=False, default=IntegrationActivityResult.Info)
    message         = Column(Text, nullable=True)
    detail          = Column(JSONB, nullable=False, default=dict, server_default="{}")

    integration = relationship("Integration", back_populates="logs")


# ─── Agent Runtime Control Plane models ───────────────────────────────────────────────────────
# Support for customer-uploaded AI agents running in sandboxed containers.


class AgentType(str, enum.Enum):
    """Classification of agent framework/architecture."""
    langchain = "langchain"
    llamaindex = "llamaindex"
    autogpt = "autogpt"
    openai_assistant = "openai_assistant"
    custom = "custom"


class RuntimeState(str, enum.Enum):
    """Agent container lifecycle state."""
    stopped = "stopped"
    starting = "starting"
    running = "running"
    crashed = "crashed"


class ChatRole(str, enum.Enum):
    """Role of messages in a chat session."""
    user = "user"
    agent = "agent"


class Agent(Base):
    """
    A customer-uploaded AI agent deployed on the platform.

    Agents run in sandboxed containers with access to MCP tools (web_fetch),
    an OpenAI-compatible LLM proxy, and Kafka-based chat I/O. Chat sessions
    are tracked in agent_chat_sessions; messages in agent_chat_messages.
    """
    __tablename__ = "agents"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name         = Column(Text, nullable=False)
    version      = Column(Text, nullable=False)
    agent_type   = Column(Enum(AgentType, name="agent_type"), nullable=False)
    provider     = Column(Enum(ModelProvider, name="model_provider"), nullable=False, default=ModelProvider.internal)
    owner        = Column(Text)
    description  = Column(Text, default="")
    risk         = Column(Enum(ModelRiskTier, name="model_risk_tier"), default=ModelRiskTier.low)
    policy_status= Column(Enum(PolicyCoverage, name="policy_coverage"), default=PolicyCoverage.none)
    runtime_state= Column(Enum(RuntimeState, name="runtime_state"), nullable=False, default=RuntimeState.stopped)
    code_path    = Column(Text, nullable=False)
    code_sha256  = Column(Text, nullable=False)
    mcp_token    = Column(Text, nullable=False)        # encrypted at rest (V2)
    llm_api_key  = Column(Text, nullable=False)        # encrypted at rest (V2)
    last_seen_at = Column(DateTime(timezone=True))
    tenant_id    = Column(Text, nullable=False, default="t1", index=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("name", "version", "tenant_id", name="uq_agents_name_ver_tenant"),
        Index("ix_agents_tenant_state", "tenant_id", "runtime_state"),
    )

    sessions = relationship("AgentChatSession", back_populates="agent",
                           cascade="all, delete-orphan")


class AgentChatSession(Base):
    """
    A conversation session between a user and an agent.

    One session per user per agent per conversation. Messages are stored
    in agent_chat_messages, linked by session_id.
    """
    __tablename__ = "agent_chat_sessions"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id        = Column(UUID(as_uuid=True),
                             ForeignKey("agents.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    user_id         = Column(Text, nullable=False, index=True)
    started_at      = Column(DateTime(timezone=True), server_default=func.now())
    last_message_at = Column(DateTime(timezone=True))
    message_count   = Column(Integer, nullable=False, default=0)

    agent    = relationship("Agent", back_populates="sessions")
    messages = relationship("AgentChatMessage", back_populates="session",
                           cascade="all, delete-orphan",
                           order_by="AgentChatMessage.ts")


class AgentChatMessage(Base):
    """
    A single message in an agent chat session.

    Messages are immutable once created. trace_id links to lineage events
    (prompt-guard, policy-decider, tool calls, LLM calls, output-guard).
    """
    __tablename__ = "agent_chat_messages"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True),
                       ForeignKey("agent_chat_sessions.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    role       = Column(Enum(ChatRole, name="chat_role"), nullable=False)
    text       = Column(Text, nullable=False)
    ts         = Column(DateTime(timezone=True), server_default=func.now())
    trace_id   = Column(Text, index=True)

    session    = relationship("AgentChatSession", back_populates="messages")
