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
    """
    return create_async_engine(db_url, echo=False, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to *engine*. expire_on_commit=False
    prevents lazy-load errors after commit in async context."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
