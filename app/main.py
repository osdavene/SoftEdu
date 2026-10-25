"""Punto de entrada principal de la aplicación FastAPI (SoftEdu AI-Powered LMS/SIS)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routers.academic_router import router as academic_router
from app.api.v1.routers.auth_router import router as auth_router
from app.api.v1.routers.grades_router import router as grades_router
from app.api.v1.routers.syllabus_router import router as syllabus_router
from app.core.config import settings
from app.core.database import async_engine
from app.core.exceptions import SoftEduError
from app.core.seed import initialize_database_and_seed

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Ciclo de vida asíncrono para inicializar pgvector, tablas, seed y cerrar el pool."""
    logger.info("Iniciando %s v%s...", settings.PROJECT_NAME, settings.VERSION)
    try:
        await initialize_database_and_seed()
    except Exception as exc:
        logger.warning(
            "Aviso durante la inicialización automática de PostgreSQL/pgvector: %s",
            str(exc),
        )
    yield
    await async_engine.dispose()
    logger.info("Pool de conexiones PostgreSQL cerrado correctamente.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Backend Empresarial de Gestión Académica y Control Educativo Inteligente "
        "(FastAPI 100% Async + SQLAlchemy 2.0 + PostgreSQL/pgvector + Copiloto IA)."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SoftEduError)
async def softedu_domain_exception_handler(
    _request: Request, exc: SoftEduError
) -> JSONResponse:
    """Manejador global de excepciones de dominio y reglas académicas."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.get("/", tags=["Estado del Sistema"])
async def root_status() -> dict[str, str]:
    """Endpoint raíz informativo con acceso rápido a documentación OpenAPI."""
    return {
        "system": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "ai_provider": f"{settings.AI_PROVIDER}:{settings.AI_MODEL_NAME}",
        "docs_swagger": "/docs",
        "docs_redoc": "/redoc",
        "health_check": f"{settings.API_V1_STR}/health",
    }


@app.get(f"{settings.API_V1_STR}/health", tags=["Estado del Sistema"])
async def health_check() -> dict[str, str]:
    """Endpoint de monitoreo para balanceadores AWS y systemd."""
    return {
        "status": "healthy",
        "service": "softedu-api",
        "ai_engine": settings.AI_MODEL_NAME,
    }


app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(academic_router, prefix=settings.API_V1_STR)
app.include_router(syllabus_router, prefix=settings.API_V1_STR)
app.include_router(grades_router, prefix=settings.API_V1_STR)
