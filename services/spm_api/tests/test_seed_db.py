"""
Tests for services/spm_api/seed_db.py
======================================

Strategy
--------
spm.db.models uses PostgreSQL-specific column types (UUID, JSONB) that
cannot be compiled by the SQLite dialect.  To keep tests hermetic and
dependency-free we:

  1. Define SQLite-compatible stub models that mirror exactly the schema
     that seed_db.py relies on.
  2. Inject them into sys.modules["spm.db.models"] BEFORE importing
     seed_db so that the lazy ``from spm.db.models import …`` inside
     seed_models() and seed_posture_snapshots() resolves to our stubs.
  3. Create a fresh in-memory aiosqlite DB per test and pass the async
     session directly to the seed functions.

No real Postgres instance is required.
"""
from __future__ import annotations

import enum
import sys
import types
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


# ── 1. SQLite-compatible stub models ─────────────────────────────────────────
# These mirror the shape that seed_db.py queries/inserts against.  We use
# plain String/Text/Integer columns instead of the pg-specific UUID/JSONB.

class _Base(DeclarativeBase):
    pass


class ModelProvider(str, enum.Enum):
    anthropic = "anthropic"
    openai    = "openai"
    local     = "local"
    internal  = "internal"
    aws       = "aws"
    azure     = "azure"
    gcp       = "gcp"
    other     = "other"


class ModelRiskTier(str, enum.Enum):
    minimal     = "minimal"
    limited     = "limited"
    high        = "high"
    unacceptable = "unacceptable"
    low         = "low"
    medium      = "medium"
    critical    = "critical"


class ModelStatus(str, enum.Enum):
    registered  = "registered"
    under_review = "under_review"
    approved    = "approved"
    deprecated  = "deprecated"
    retired     = "retired"


class ModelType(str, enum.Enum):
    llm             = "llm"
    embedding_model = "embedding_model"
    audio_model     = "audio_model"
    vision_model    = "vision_model"
    multimodal      = "multimodal"
    other           = "other"


class PolicyCoverage(str, enum.Enum):
    full    = "full"
    partial = "partial"
    none    = "none"


class ModelRegistry(_Base):
    __tablename__ = "model_registry"

    # Uuid(as_uuid=True) is cross-dialect: native UUID on Postgres, String on SQLite
    model_id      = Column(Uuid(as_uuid=True), primary_key=True)
    name          = Column(Text, nullable=False)
    version       = Column(Text, nullable=False)
    provider      = Column(SAEnum(ModelProvider,  name="model_provider"),  nullable=False, default=ModelProvider.local)
    purpose       = Column(Text)
    risk_tier     = Column(SAEnum(ModelRiskTier,  name="model_risk_tier"), nullable=False, default=ModelRiskTier.limited)
    model_type    = Column(SAEnum(ModelType,       name="model_type"),      nullable=True)
    owner         = Column(Text,  nullable=True)
    policy_status = Column(SAEnum(PolicyCoverage, name="policy_coverage"), nullable=True)
    alerts_count  = Column(Integer, nullable=False, default=0)
    last_seen_at  = Column(DateTime(timezone=True), nullable=True)
    tenant_id     = Column(Text, nullable=False, default="global")
    status        = Column(SAEnum(ModelStatus,    name="model_status"),    nullable=False, default=ModelStatus.registered)
    approved_by   = Column(Text)
    approved_at   = Column(DateTime(timezone=True))
    notes         = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("name", "version", "tenant_id", name="uq_model_name_version_tenant"),
    )


class PostureSnapshot(_Base):
    __tablename__ = "posture_snapshots"

    # Use Integer (not BigInteger) — SQLite autoincrement requires INTEGER primary key
    id               = Column(Integer, primary_key=True, autoincrement=True)
    # Uuid(as_uuid=True) is cross-dialect: native UUID on Postgres, String on SQLite
    model_id         = Column(Uuid(as_uuid=True), nullable=True)
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


# ── 2. Inject stub module before importing seed_db ────────────────────────────
# seed_models() and seed_posture_snapshots() contain lazy imports:
#   from spm.db.models import ModelRegistry, …
# Injecting into sys.modules ensures those resolve to our SQLite-compatible
# stubs rather than the production PostgreSQL models.

_stub_module = types.ModuleType("spm.db.models")
_stub_module.ModelRegistry  = ModelRegistry
_stub_module.PostureSnapshot = PostureSnapshot
_stub_module.ModelProvider  = ModelProvider
_stub_module.ModelRiskTier  = ModelRiskTier
_stub_module.ModelStatus    = ModelStatus
_stub_module.ModelType      = ModelType
_stub_module.PolicyCoverage = PolicyCoverage

for _key in ("spm", "spm.db", "spm.db.models", "spm.db.session"):
    sys.modules.setdefault(_key, types.ModuleType(_key))
sys.modules["spm.db.models"] = _stub_module

# ── 3. Import the seed functions ──────────────────────────────────────────────
_SVC_ROOT = Path(__file__).parents[1]  # services/spm_api/
if str(_SVC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SVC_ROOT))

from seed_db import seed_models, seed_posture_snapshots  # noqa: E402


# ── 4. Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    """
    Isolated in-memory SQLite DB with stub tables.
    A fresh engine + session is created per test, then torn down.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── 5. ModelRegistry tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_models_inserts_12_rows(db_session):
    """First seed run creates exactly 12 ModelRegistry rows."""
    inserted = await seed_models(db_session)
    assert inserted == 12


@pytest.mark.asyncio
async def test_seed_models_db_count_equals_12(db_session):
    """DB query after seeding confirms 12 rows are present."""
    await seed_models(db_session)
    result = await db_session.execute(
        select(func.count()).select_from(ModelRegistry)
    )
    assert result.scalar() == 12


@pytest.mark.asyncio
async def test_seed_models_is_idempotent(db_session):
    """Second seed run inserts 0 rows — no duplicates created."""
    await seed_models(db_session)
    inserted_second = await seed_models(db_session)
    assert inserted_second == 0


@pytest.mark.asyncio
async def test_seed_models_idempotent_total_stays_at_12(db_session):
    """After two seed runs the total row count is still 12."""
    await seed_models(db_session)
    await seed_models(db_session)
    result = await db_session.execute(
        select(func.count()).select_from(ModelRegistry)
    )
    assert result.scalar() == 12


# ── 6. PostureSnapshot tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_posture_snapshots_inserts_30_rows(db_session):
    """First seed run creates exactly 30 PostureSnapshot rows (30 days)."""
    inserted = await seed_posture_snapshots(db_session)
    assert inserted == 30


@pytest.mark.asyncio
async def test_seed_posture_snapshots_db_count_equals_30(db_session):
    """DB query after seeding confirms 30 rows are present."""
    await seed_posture_snapshots(db_session)
    result = await db_session.execute(
        select(func.count()).select_from(PostureSnapshot)
    )
    assert result.scalar() == 30


@pytest.mark.asyncio
async def test_seed_posture_snapshots_is_idempotent(db_session):
    """Second seed run inserts 0 rows — idempotency guard (≥20 rows) fires."""
    await seed_posture_snapshots(db_session)
    inserted_second = await seed_posture_snapshots(db_session)
    assert inserted_second == 0


@pytest.mark.asyncio
async def test_seed_posture_snapshots_idempotent_total_stays_at_30(db_session):
    """After two seed runs the total snapshot count is still 30."""
    await seed_posture_snapshots(db_session)
    await seed_posture_snapshots(db_session)
    result = await db_session.execute(
        select(func.count()).select_from(PostureSnapshot)
    )
    assert result.scalar() == 30


@pytest.mark.asyncio
async def test_seed_posture_snapshots_all_have_global_tenant(db_session):
    """Every snapshot is tagged with tenant_id='global'."""
    await seed_posture_snapshots(db_session)
    result = await db_session.execute(
        select(func.count()).select_from(PostureSnapshot).where(
            PostureSnapshot.tenant_id == "global"
        )
    )
    assert result.scalar() == 30
