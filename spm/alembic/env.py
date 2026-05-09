"""
alembic/env.py — SPM PostgreSQL migration environment.

Connection priority (highest → lowest):
  1. CLI override:   alembic -x db_url=<url>
  2. Environment:    SPM_DB_URL
  3. alembic.ini:    sqlalchemy.url

The ORM layer uses asyncpg at runtime; Alembic uses the synchronous
psycopg2 driver so that migrations run without an event loop.

If SPM_DB_URL contains '+asyncpg', it is automatically converted to a
synchronous URL ('postgresql://...') for Alembic's use.
"""
from __future__ import annotations

import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import SPM ORM models so Alembic's autogenerate can detect schema drift.
# These live one directory up: spm/db/models.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from db.models import Base   # noqa: E402

# ── Alembic Config object (alembic.ini values) ────────────────────────────────
config = context.config

# Set up Python logging from alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ORM metadata — used by autogenerate
target_metadata = Base.metadata


# ── URL resolution ────────────────────────────────────────────────────────────

def _sync_url(url: str) -> str:
    """Strip '+asyncpg' driver suffix so psycopg2 is used by Alembic."""
    return re.sub(r"\+asyncpg", "", url)


def _get_url() -> str:
    # 1. CLI override: alembic -x db_url=<url>
    x_args = context.get_x_argument(as_dictionary=True)
    if "db_url" in x_args:
        return _sync_url(x_args["db_url"])
    # 2. Environment variable
    env_url = os.getenv("SPM_DB_URL", "")
    if env_url:
        return _sync_url(env_url)
    # 3. alembic.ini default
    return config.get_main_option("sqlalchemy.url")


# ── Offline migrations (generate SQL only, no live connection) ────────────────

def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without connecting to the database."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (connect and execute directly) ──────────────────────────

def run_migrations_online() -> None:
    """Connect to PostgreSQL and run pending migrations."""
    url = _get_url()
    # Override the ini URL with our resolved value
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = url

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # single connection, no pool needed for migrations
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# ── Entrypoint ────────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
