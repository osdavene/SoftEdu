"""
Controlador HTTP Asíncrono (`app/api/v1/routers/syllabus_router.py`).

Expone los endpoints de gestión del Sílabo Vectorizado (`pgvector`),
el Asistente Curricular Generativo para Docentes y el Tutor RAG para Estudiantes.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_service import AcademicAIService
from app.core.database import get_db_session
from app.core.security import require_roles
from app.models.academic import User, UserRole
from app.schemas.syllabus import (
    CurricularMaterialGenerationRequest,
    CurricularMaterialGenerationResponse,
    RAGTutorQueryRequest,
    RAGTutorQueryResponse,
    SubjectSyllabusTreeResponse,
    SyllabusTopicCreate,
    SyllabusTopicResponse,
    SyllabusUnitCreate,
    SyllabusUnitWithTopicsResponse,
)
from app.services.syllabus_service import SyllabusService

router = APIRouter(
    prefix="/syllabus",
    tags=["Sílabo Vectorizado (pgvector), Asistente Curricular & Tutor RAG"],
)


# =====================================================================
# PROVEEDORES DE INYECCIÓN DE DEPENDENCIAS (DI)
# =====================================================================
def get_syllabus_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SyllabusService:
    """Inyecta el servicio de dominio del sílabo con su sesión asíncrona."""
    return SyllabusService(session=session)


def get_academic_ai_service() -> AcademicAIService:
    """Inyecta el motor de IA para vectorización, diseño curricular y RAG."""
    return AcademicAIService()


# =====================================================================
# 1. ENDPOINTS DE ESTRUCTURA JERÁRQUICA Y VECTORIZACIÓN AUTOMÁTICA
# =====================================================================
@router.post(
    "/units",
    response_model=SyllabusUnitWithTopicsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear unidad temática en el sílabo de una asignatura",
)
async def create_syllabus_unit(
    payload: SyllabusUnitCreate,
    syllabus_service: Annotated[SyllabusService, Depends(get_syllabus_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER))
    ],
) -> SyllabusUnitWithTopicsResponse:
    """Registra una nueva unidad (`SyllabusUnit`) validando orden y pertenencia."""
    return await syllabus_service.create_syllabus_unit(payload=payload)


@router.post(
    "/topics",
    response_model=SyllabusTopicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tema del sílabo y disparar vectorización semántica en pgvector",
    description=(
        "Registra un `SyllabusTopic` dentro de una unidad y agenda inmediatamente "
        "en `BackgroundTasks` la generación de su vector de embeddings en `pgvector`."
    ),
)
async def create_syllabus_topic(
    payload: SyllabusTopicCreate,
    background_tasks: BackgroundTasks,
    syllabus_service: Annotated[SyllabusService, Depends(get_syllabus_service)],
    ai_service: Annotated[AcademicAIService, Depends(get_academic_ai_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER))
    ],
) -> SyllabusTopicResponse:
    """
    Crea el tema del sílabo y encola la indexación vectorial en segundo plano
    para habilitar búsquedas semánticas del Tutor RAG sin bloquear el request HTTP.
    """
    topic_dto = await syllabus_service.create_syllabus_topic(payload=payload)
    background_tasks.add_task(
        ai_service.vectorize_syllabus_topic_background,
        topic_id=topic_dto.id,
    )
    return topic_dto


@router.get(
    "/subjects/{subject_id}",
    response_model=SubjectSyllabusTreeResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar árbol jerárquico completo del sílabo (Materia -> Unidad -> Tema)",
)
async def get_subject_syllabus_tree(
    subject_id: Annotated[
        uuid.UUID, Path(..., description="UUID de la asignatura a consultar.")
    ],
    syllabus_service: Annotated[SyllabusService, Depends(get_syllabus_service)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT)),
    ],
) -> SubjectSyllabusTreeResponse:
    """Retorna todas las unidades y temas del sílabo junto con el estado de vectorización."""
    return await syllabus_service.get_subject_syllabus_tree(subject_id=subject_id)


# =====================================================================
# 2. ENDPOINT COPILOTO IA #2: ASISTENTE CURRICULAR PARA EL DOCENTE
# =====================================================================
@router.post(
    "/topics/{topic_id}/curricular-assistant",
    response_model=CurricularMaterialGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar planeación de clase, rúbrica y banco de preguntas test con IA",
    description=(
        "Recibe el UUID de un `SyllabusTopic` y parámetros pedagógicos, invocando al "
        "LLM con Structured Outputs (`AICurriculumAssistantSchema`) para generar una "
        "planeación de sesión en 3 fases, rúbrica analítica (escala 0.0-5.0) y banco "
        "de preguntas tipo test alineadas a la taxonomía de Bloom."
    ),
)
async def generate_teacher_curricular_material(
    topic_id: Annotated[
        uuid.UUID,
        Path(..., description="UUID del tema oficial del sílabo (`SyllabusTopic`)."),
    ],
    params: CurricularMaterialGenerationRequest,
    syllabus_service: Annotated[SyllabusService, Depends(get_syllabus_service)],
    ai_service: Annotated[AcademicAIService, Depends(get_academic_ai_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER))
    ],
) -> CurricularMaterialGenerationResponse:
    """Caso de Uso Copiloto IA #2: Asistente Curricular Generativo para el Docente."""
    return await syllabus_service.generate_curricular_material_for_teacher(
        topic_id=topic_id,
        params=params,
        ai_service=ai_service,
    )


# =====================================================================
# 3. ENDPOINT COPILOTO IA #3: TUTOR RAG BASADO EN EL SÍLABO (PGVECTOR)
# =====================================================================
@router.post(
    "/rag-tutor/ask",
    response_model=RAGTutorQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar al Tutor RAG basado estrictamente en el sílabo vectorizado",
    description=(
        "Convierte la pregunta del estudiante en un vector de embeddings, ejecuta "
        "búsqueda de similitud coseno (`<=>`) sobre `pgvector` en los temas de la "
        "asignatura y genera una respuesta fundamentada exclusivamente en las "
        "unidades y temas oficiales registrados."
    ),
)
async def ask_syllabus_rag_tutor(
    payload: RAGTutorQueryRequest,
    syllabus_service: Annotated[SyllabusService, Depends(get_syllabus_service)],
    ai_service: Annotated[AcademicAIService, Depends(get_academic_ai_service)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT)),
    ],
) -> RAGTutorQueryResponse:
    """Caso de Uso Copiloto IA #3: Tutor RAG Basado en el Sílabo con trazabilidad de fuentes."""
    return await syllabus_service.ask_syllabus_rag_tutor(
        payload=payload,
        ai_service=ai_service,
    )
