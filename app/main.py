"""Punto de entrada principal de la aplicación FastAPI (SoftEdu AI-Powered LMS/SIS)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.academic_router import router as academic_router
from app.api.v1.routers.auth_router import router as auth_router
from app.api.v1.routers.grades_router import router as grades_router
from app.api.v1.routers.syllabus_router import router as syllabus_router
from app.core.config import settings
from app.core.database import async_engine, get_db_session
from app.core.exceptions import SoftEduError
from app.core.seed import initialize_database_and_seed
from app.models.academic import CourseOffering, Enrollment

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

DASHBOARD_TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html"


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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def interactive_dashboard() -> HTMLResponse:
    """Renderiza la Consola Interactiva Web del Sistema Académico y Copiloto IA."""
    if DASHBOARD_TEMPLATE_PATH.exists():
        return HTMLResponse(
            content=DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")
        )
    return HTMLResponse(
        content="<h1>SoftEdu API Activa — Visita <a href='/docs'>/docs</a></h1>"
    )


@app.get(f"{settings.API_V1_STR}/demo-context", tags=["Estado del Sistema"])
async def get_demo_context(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str | None]:
    """Retorna los UUIDs semilla activos para inicializar la consola web interactiva."""
    stmt = (
        select(Enrollment.id, CourseOffering.subject_id)
        .join(CourseOffering, Enrollment.course_offering_id == CourseOffering.id)
        .where(Enrollment.is_active.is_(True))
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return {"enrollment_id": None, "subject_id": None}
    return {
        "enrollment_id": str(row[0]),
        "subject_id": str(row[1]),
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
