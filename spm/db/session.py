"""
AI SPM — SQLAlchemy async engine and session factory.
"""
from __future__ import annotations
import os
from functools import lru_cache
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Prefer the explicit async URL injected by Helm; fall back to the sync URL
# (stripping the scheme) or finally the hardcoded default.
SPM_DB_URL = (
    os.getenv("SPM_DB_URL_ASYNC")
    or os.getenv("SPM_DB_URL", "").replace("postgresql://", "postgresql+asyncpg://", 1)
    or "postgresql+asyncpg://spm_rw:spmpass@spm-db:5432/spm"
)


@lru_cache(maxsize=1)
def get_engine():
    return create_async_engine(
        SPM_DB_URL,
        pool_size=10,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        echo=False,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
