"""
dependencies/db.py
──────────────────
Provides the SessionRepository as a FastAPI dependency.

SessionRepository is constructed per-request with an AsyncSession from the
application's session factory (initialized at startup).
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.session import SessionRepository


async def get_session_repo(request: Request) -> SessionRepository:
    """
    FastAPI dependency: creates a SessionRepository for this request.
    Usage:
        repo: SessionRepository = Depends(get_session_repo)
    """
    session_factory = request.app.state.db_session_factory
    session: AsyncSession = session_factory()
    return SessionRepository(session)
