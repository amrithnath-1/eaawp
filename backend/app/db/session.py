"""
Async SQLAlchemy engine and session factory.

Works with both SQLite (development) and PostgreSQL (production)
via the DATABASE_URL environment variable.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

# SQLite needs check_same_thread=False; PostgreSQL doesn't need it.
connect_args: dict = {"check_same_thread": False} if settings.is_sqlite else {}

# On Vercel a function instance can be frozen between requests, so pooled
# connections go stale; open a fresh connection per session there instead.
pool_options: dict = {"poolclass": NullPool} if os.environ.get("VERCEL") else {}

engine = create_async_engine(
    settings.database_url,
    # SQL echo logs every statement; with bound parameters that would write
    # password hashes, OAuth state tokens and personal data to the log.
    # Opt in explicitly (SQL_ECHO=true) when debugging; parameters stay hidden.
    echo=settings.sql_echo,
    hide_parameters=True,
    connect_args=connect_args,
    **pool_options,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields a scoped database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
