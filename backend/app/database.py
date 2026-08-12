"""PostgreSQL connector and application-owned session lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import DatabaseUrl


class ApplicationBase(DeclarativeBase):
    """Single declarative metadata registry for application-owned tables."""


def normalize_async_database_url(database_url: DatabaseUrl) -> str:
    """Normalize accepted PostgreSQL URLs to SQLAlchemy's asyncpg driver."""
    url = str(database_url)
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@dataclass(frozen=True, slots=True)
class DatabaseConnector:
    """Owned async engine and explicit session factory for one application."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def create(cls, database_url: DatabaseUrl) -> "DatabaseConnector":
        """Build a connector without opening a network connection."""
        engine = create_async_engine(
            normalize_async_database_url(database_url),
            pool_pre_ping=True,
        )
        return cls(
            engine=engine,
            session_factory=async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            ),
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield one read session and close it deterministically."""
        async with self.session_factory() as session:
            yield session

    async def close(self) -> None:
        """Dispose pooled connections during application shutdown."""
        await self.engine.dispose()
