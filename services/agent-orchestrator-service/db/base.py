"""
db/base.py
──────────
SQLAlchemy async engine factory and declarative base.

All ORM models import Base from here so Alembic autogenerate
can discover every table in a single import.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — every ORM model inherits from this."""
    pass


def make_engine(db_url: str) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine.
    db_url must use the sqlite+aiosqlite:// scheme for SQLite,
    or postgresql+asyncpg:// for PostgreSQL.

    SQLite-specific tuning
    ──────────────────────
    - check_same_thread=False  : required for async/threaded use with aiosqlite
    - timeout=30               : wait up to 30 s for a write lock before raising
                                 OperationalError (default is 5 s)
    These kwargs are silently ignored by non-SQLite dialects.
    """
    connect_args: dict = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}

    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args,
    )
    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to *engine*. expire_on_commit=False
    prevents lazy-load errors after commit in async context."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
