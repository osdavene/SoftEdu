"""
Controlador HTTP Asíncrono (`app/api/v1/routers/grades_router.py`).

Expone los endpoints de registro de calificaciones ponderadas con disparo
asíncrono del Copiloto de IA (`BackgroundTasks`) y consulta de boletín integral.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_service import AcademicAIService
from app.core.database import get_db_session
from app.core.exceptions import (
    BusinessRuleViolationError,
    EntityNotFoundError,
    SoftEduError,
)
from app.core.security import require_roles
from app.models.academic import User, UserRole
from app.schemas.academic import (
    GradeCreate,
    GradeRegistrationResultResponse,
    StudentReportCardResponse,
)
from app.services.grades_service import GradesService

router = APIRouter(
    prefix="/grades",
    tags=["Calificaciones Ponderadas & Copiloto IA"],
)


# =====================================================================
# PROVEEDORES DE INYECCIÓN DE DEPENDENCIAS (DI)
# =====================================================================
def get_grades_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GradesService:
    """Inyecta el servicio de dominio de calificaciones con su sesión asíncrona."""
    return GradesService(session=session)


def get_academic_ai_service() -> AcademicAIService:
    """Inyecta el motor de IA configurado mediante el patrón Strategy/Adapter."""
    return AcademicAIService()


# =====================================================================
# ENDPOINTS HTTP ASÍNCRONOS
# =====================================================================
@router.post(
    "",
    response_model=GradeRegistrationResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar calificación ponderada y disparar diagnóstico de riesgo con IA",
    description=(
        "Valida matrícula activa y reglas de ponderación (escala 0.0 a 5.0, suma <= 100%), "
        "persiste la nota de manera atómica y encola en segundo plano (`BackgroundTasks`) "
        "la evaluación predictiva de riesgo académico con el motor de IA."
    ),
)
async def register_student_grade(
    payload: GradeCreate,
    background_tasks: BackgroundTasks,
    grades_service: Annotated[GradesService, Depends(get_grades_service)],
    ai_service: Annotated[AcademicAIService, Depends(get_academic_ai_service)],
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER))
    ],
) -> GradeRegistrationResultResponse:
    """
    Registra una nota parcial/corte y agenda el análisis del Copiloto de IA sin
    bloquear la latencia de respuesta del cliente HTTP.
    """
    try:
        result_dto, ai_context_dto = (
            await grades_service.register_grade_and_build_ai_context(
                payload=payload,
                recorded_by_user_id=current_user.id,
            )
        )
    except EntityNotFoundError as not_found_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": not_found_err.message,
                "details": not_found_err.details,
            },
        ) from not_found_err
    except BusinessRuleViolationError as rule_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": rule_err.message,
                "details": rule_err.details,
            },
        ) from rule_err
    except SoftEduError as domain_err:
        raise HTTPException(
            status_code=domain_err.status_code,
            detail={
                "message": domain_err.message,
                "details": domain_err.details,
            },
        ) from domain_err

    # Disparo desacoplado en segundo plano: nunca bloquea ni tumba la transacción principal
    background_tasks.add_task(
        ai_service.evaluate_and_save_student_risk_background,
        context=ai_context_dto,
    )

    return result_dto


@router.get(
    "/enrollments/{enrollment_id}/report-card",
    response_model=StudentReportCardResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar boletín académico integral y diagnóstico vigente de IA",
    description=(
        "Retorna el boletín detallado de una matrícula: notas por corte, promedio "
        "ponderado acumulado, nota mínima necesaria en el porcentaje restante, "
        "estadísticas de asistencia y el último diagnóstico estructurado del Copiloto IA."
    ),
)
async def get_enrollment_report_card(
    enrollment_id: Annotated[
        uuid.UUID,
        Path(..., description="UUID de la matrícula académica del estudiante."),
    ],
    grades_service: Annotated[GradesService, Depends(get_grades_service)],
    current_user: Annotated[
        User,
        Depends(
            require_roles(UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT)
        ),
    ],
) -> StudentReportCardResponse:
    """
    Consulta el boletín integral del alumno junto con la recomendación vigente de IA.
    Si el usuario autenticado tiene rol `STUDENT`, valida que el boletín le pertenezca.
    """
    try:
        report_card = await grades_service.get_student_report_card(
            enrollment_id=enrollment_id
        )
    except EntityNotFoundError as not_found_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": not_found_err.message,
                "details": not_found_err.details,
            },
        ) from not_found_err

    # Control adicional de aislamiento de datos para rol STUDENT
    if (
        current_user.role in (UserRole.STUDENT, UserRole.ESTUDIANTE)
        and current_user.student_profile is not None
        and report_card.student_id != current_user.student_profile.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Un estudiante únicamente puede consultar su propio boletín académico.",
        )

    return report_card
