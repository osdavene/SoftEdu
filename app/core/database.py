"""Configuración de motor asíncrono SQLAlchemy 2.0, sesiones y extensión pgvector."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

# Convención de nombres determinista para índices y constraints (compatible con Alembic)
POSTGRES_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Clase base declarativa de SQLAlchemy 2.0 con metadatos estandarizados."""

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


# Motor asíncrono global respaldado por asyncpg
async_engine: AsyncEngine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=settings.DB_ECHO_SQL,
    future=True,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
)

# Fábrica de sesiones asíncronas con expire_on_commit=False (obligatorio en flujos async)
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def init_pgvector_extension() -> None:
    """Garantiza que la extensión `vector` (pgvector) exista en PostgreSQL al iniciar."""
    async with async_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        logger.info("Extensión PostgreSQL 'pgvector' verificada correctamente.")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependencia de FastAPI para proveer una `AsyncSession` por petición HTTP.
    Gestiona rollback automático ante excepciones no controladas y cierre seguro.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_isolated_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager asíncrono para tareas en segundo plano (`BackgroundTasks` / workers).
    Crea una sesión desacoplada del ciclo de vida del request HTTP original.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
