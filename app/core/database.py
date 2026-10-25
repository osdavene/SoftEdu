"""Configuración de motor asíncrono SQLAlchemy 2.0, sesiones y extensión pgvector."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging

import asyncpg
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

# Indicador en tiempo de ejecución de disponibilidad de la extensión nativa pgvector
PGVECTOR_ENABLED: bool = True

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


async def ensure_database_exists() -> None:
    """
    Verifica que la base de datos `settings.POSTGRES_DB` exista en el servidor
    PostgreSQL; si no existe, la crea automáticamente conectándose a `postgres`.
    """
    try:
        sys_conn = await asyncpg.connect(
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            database="postgres",
        )
        try:
            exists = await sys_conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                settings.POSTGRES_DB,
            )
            if not exists:
                await sys_conn.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}";')
                logger.info(
                    "Base de datos '%s' creada automáticamente en PostgreSQL.",
                    settings.POSTGRES_DB,
                )
        finally:
            await sys_conn.close()
    except Exception as exc:
        logger.warning(
            "No se pudo verificar/crear la base de datos '%s' automáticamente: %s",
            settings.POSTGRES_DB,
            str(exc),
        )


async def init_pgvector_extension() -> bool:
    """
    Garantiza que la extensión `vector` (pgvector) exista en PostgreSQL al iniciar.
    Retorna True si la extensión nativa está activa, o False si el motor local
    (ej. Windows sin binario C de pgvector) requiere modo de compatibilidad JSONB.
    """
    global PGVECTOR_ENABLED
    try:
        async with async_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            PGVECTOR_ENABLED = True
            logger.info("Extensión PostgreSQL 'pgvector' verificada y activa.")
            return True
    except Exception as exc:
        PGVECTOR_ENABLED = False
        logger.warning(
            "La extensión nativa 'vector' (pgvector) no está instalada en este host "
            "PostgreSQL (%s). Activando compatibilidad vectorial transparente (JSONB + Cosine).",
            str(exc),
        )
        return False


def is_pgvector_enabled() -> bool:
    """Indica si el servidor PostgreSQL actual cuenta con la extensión nativa `vector`."""
    return PGVECTOR_ENABLED


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
