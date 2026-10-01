"""
Async SQLAlchemy engine and session factory.

Works with both SQLite (development) and PostgreSQL (production)
via the DATABASE_URL environment variable.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# SQLite needs check_same_thread=False; PostgreSQL doesn't need it.
connect_args: dict = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_async_engine(
    settings.database_url,
    echo=(settings.environment == "development"),
    connect_args=connect_args,
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
