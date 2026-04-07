"""
AI SPM — SQLAlchemy ORM models matching 001_initial.sql
"""
from __future__ import annotations
import enum
import uuid
from typing import Dict

from sqlalchemy import (
    BigInteger, Column, DateTime, Enum, Float,
    Integer, Index, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ModelProvider(str, enum.Enum):
    local = "local"
    openai = "openai"
    anthropic = "anthropic"
    other = "other"


class ModelRiskTier(str, enum.Enum):
    minimal = "minimal"
    limited = "limited"
    high = "high"
    unacceptable = "unacceptable"


class ModelStatus(str, enum.Enum):
    registered = "registered"
    under_review = "under_review"
    approved = "approved"
    deprecated = "deprecated"
    retired = "retired"


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

    model_id    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(Text, nullable=False)
    version     = Column(Text, nullable=False)
    provider    = Column(Enum(ModelProvider), nullable=False, default=ModelProvider.local)
    purpose     = Column(Text)
    risk_tier   = Column(Enum(ModelRiskTier), nullable=False, default=ModelRiskTier.limited)
    tenant_id   = Column(Text, nullable=False, default="global")
    status      = Column(Enum(ModelStatus), nullable=False, default=ModelStatus.registered)
    approved_by = Column(Text)
    approved_at = Column(DateTime(timezone=True))
    ai_sbom     = Column(JSONB, default=dict)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

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
    status            = Column(Enum(ComplianceStatus), nullable=False, default=ComplianceStatus.not_satisfied)
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
