"""
dependencies/db.py
──────────────────
FastAPI dependency functions for database access.

get_async_db       — yields a fresh AsyncSession per request (auto-closed).
get_session_repo   — returns SessionRepository bound to the request's session.
get_event_repo     — returns EventRepository bound to the request's session.

IMPORTANT: SessionRepository and EventRepository are instantiated per-request,
not stored on app.state. The shared state is app.state.db_session_factory
(the session factory, not a session itself). This ensures each request gets
its own AsyncSession with no cross-request shared state.

Because FastAPI caches dependencies within a single request, get_async_db
is called once even when both get_session_repo and get_event_repo are
declared as dependencies in the same route — they share the same AsyncSession
and therefore the same database transaction.
"""
from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.event import EventRepository
from models.session import SessionRepository


async def get_async_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: yields one AsyncSession per HTTP request.

    The session factory is stored on app.state at startup.
    The session is automatically closed when the response is sent.
    """
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


async def get_session_repo(
    session: AsyncSession = Depends(get_async_db),
) -> SessionRepository:
    """FastAPI dependency: returns SessionRepository for the current request."""
    return SessionRepository(session)


async def get_event_repo(
    session: AsyncSession = Depends(get_async_db),
) -> EventRepository:
    """FastAPI dependency: returns EventRepository for the current request."""
    return EventRepository(session)
