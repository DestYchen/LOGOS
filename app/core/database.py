from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings


_settings = get_settings()

engine: AsyncEngine = create_async_engine(str(_settings.database_url), echo=_settings.debug, future=True, pool_size=20, max_overflow=30)

AsyncSessionMaker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncSession:
    """Provide an async session scope for FastAPI dependencies and Celery tasks."""

    session = AsyncSessionMaker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
