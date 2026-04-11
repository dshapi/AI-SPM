"""
alembic/env.py
──────────────
Alembic environment for async SQLAlchemy + SQLite.

Supports:
  • alembic upgrade head        — run migrations forward
  • alembic downgrade base      — roll back all migrations
  • alembic revision --autogenerate  — generate new migration from ORM diff

Pass a custom DB path at the command line with:
  alembic -x db_path=/path/to/test.db upgrade head
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Register ORM models so autogenerate can see all tables ────────────────────
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.base import Base
from db.models import AgentSessionORM, SessionEventORM, CaseORM, ThreatFindingORM  # noqa: F401
from policies.db_models import PolicyORM, PolicyVersionORM, PolicyLifecycleAuditORM  # noqa: F401

# ─────────────────────────────────────────────────────────────────────────────

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Allow overriding the DB path via -x db_path=... on the CLI."""
    db_path = context.get_x_argument(as_dictionary=True).get("db_path")
    if db_path:
        return f"sqlite+aiosqlite:///{db_path}"
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,          # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,          # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()
    connectable = async_engine_from_config(
        cfg, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
