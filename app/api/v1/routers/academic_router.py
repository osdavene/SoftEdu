"""
Controlador HTTP Asíncrono (`app/api/v1/routers/academic_router.py`).

Gestiona Docentes, Materias, Períodos, Ofertas y Horarios (`schedule_blocks`),
Alumnos, Matrículas y Registro de Asistencia con disparo de Alerta Temprana de IA.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_service import AcademicAIService
from app.core.database import get_db_session
from app.core.security import require_roles
from app.models.academic import User, UserRole
from app.schemas.academic import EnrollmentCreate, EnrollmentResponse
from app.schemas.management import (
    AcademicPeriodCreateRequest,
    AcademicPeriodResponse,
    AttendanceCreateRequest,
    AttendanceRegistrationResponse,
    CourseOfferingCreateRequest,
    CourseOfferingResponse,
    StudentCreateRequest,
    StudentResponse,
    SubjectCreateRequest,
    SubjectResponse,
    TeacherCreateRequest,
    TeacherResponse,
)
from app.services.academic_management_service import AcademicManagementService

router = APIRouter(
    prefix="/academic",
    tags=["Docentes, Horarios, Alumnos, Matrículas & Asistencia"],
)


def get_management_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AcademicManagementService:
    return AcademicManagementService(session=session)


def get_academic_ai_service() -> AcademicAIService:
    return AcademicAIService()


# =====================================================================
# 1. DOCENTES, MATERIAS, PERÍODOS Y HORARIOS (COURSE OFFERINGS)
# =====================================================================
@router.post(
    "/teachers",
    response_model=TeacherResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo docente y su cuenta RBAC",
)
async def create_teacher(
    payload: TeacherCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> TeacherResponse:
    return await service.create_teacher(payload=payload)


@router.get(
    "/teachers",
    response_model=list[TeacherResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar planta docente activa",
)
async def list_teachers(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER))
    ],
) -> list[TeacherResponse]:
    return await service.list_teachers()


@router.post(
    "/subjects",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva asignatura en el catálogo curricular",
)
async def create_subject(
    payload: SubjectCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> SubjectResponse:
    return await service.create_subject(payload=payload)


@router.get(
    "/subjects",
    response_model=list[SubjectResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar asignaturas activas del plan de estudios",
)
async def list_subjects(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT)),
    ],
) -> list[SubjectResponse]:
    return await service.list_subjects()


@router.post(
    "/periods",
    response_model=AcademicPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear período lectivo académico",
)
async def create_academic_period(
    payload: AcademicPeriodCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> AcademicPeriodResponse:
    return await service.create_academic_period(payload=payload)


@router.post(
    "/course-offerings",
    response_model=CourseOfferingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar materia a docente por período con validación de cruces de horario",
)
async def create_course_offering(
    payload: CourseOfferingCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> CourseOfferingResponse:
    """
    Crea una oferta de curso validando que los bloques horarios (`schedule_blocks`)
    del docente no se solapen con otras materias asignadas en el mismo período.
    """
    return await service.create_course_offering(payload=payload)


@router.get(
    "/course-offerings",
    response_model=list[CourseOfferingResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar ofertas de cursos, docentes asignados y bloques horarios",
)
async def list_course_offerings(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER, UserRole.STUDENT)),
    ],
) -> list[CourseOfferingResponse]:
    return await service.list_course_offerings()


# =====================================================================
# 2. ALUMNOS, MATRÍCULAS Y ASISTENCIA CON ALERTA TEMPRANA IA
# =====================================================================
@router.post(
    "/students",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo estudiante y su cuenta RBAC",
)
async def create_student(
    payload: StudentCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> StudentResponse:
    return await service.create_student(payload=payload)


@router.get(
    "/students",
    response_model=list[StudentResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar estudiantes activos",
)
async def list_students(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER))
    ],
) -> list[StudentResponse]:
    return await service.list_students()


@router.post(
    "/enrollments",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Matricular alumno en oferta de curso validando cupo y horario",
)
async def enroll_student(
    payload: EnrollmentCreate,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> EnrollmentResponse:
    return await service.enroll_student_in_course(payload=payload)


@router.post(
    "/attendances",
    response_model=AttendanceRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar asistencia/inasistencia y disparar alerta temprana de IA",
    description=(
        "Registra la asistencia de un alumno en una fecha de sesión. Cuando se "
        "registra una inasistencia (`ABSENT`) o retardo (`LATE`), dispara en "
        "`BackgroundTasks` el análisis de riesgo académico con el Copiloto de IA."
    ),
)
async def register_student_attendance(
    payload: AttendanceCreateRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    ai_service: Annotated[AcademicAIService, Depends(get_academic_ai_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.TEACHER))
    ],
) -> AttendanceRegistrationResponse:
    result_dto, ai_context_dto = (
        await service.register_attendance_and_build_ai_context(payload=payload)
    )
    if ai_context_dto is not None:
        background_tasks.add_task(
            ai_service.evaluate_and_save_student_risk_background,
            context=ai_context_dto,
        )
    return result_dto
