"""
Controlador HTTP Asíncrono (`app/api/v1/routers/academic_router.py`).

Gestiona SuperPanel Multi-Colegio (Maternal a Grado 11°), Calendario Escolar A y B,
Gobierno Escolar (SuperAdmin, Rector, Coordinación, Secretaría, Orientación, Docentes),
Horarios Escolares, Alumnos, Matrículas y Planillas de Asistencia con Copiloto IA.
"""

from typing import Annotated
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_service import AcademicAIService
from app.core.database import get_db_session
from app.core.security import get_current_active_user, require_roles
from app.models.academic import User, UserRole
from app.schemas.academic import EnrollmentCreate, EnrollmentResponse
from app.schemas.management import (
    AcademicPeriodCreateRequest,
    AcademicPeriodResponse,
    AttendanceCreateRequest,
    AttendanceRegistrationResponse,
    BulkAttendanceCreateRequest,
    CourseOfferingCreateRequest,
    CourseOfferingResponse,
    InstitutionalOverviewResponse,
    SchoolAssignRectorRequest,
    SchoolCreateWithRectorRequest,
    SchoolGradeCatalogItem,
    SchoolInstitutionResponse,
    SchoolStaffCreateRequest,
    SchoolUpdateGradesRequest,
    StudentCreateRequest,
    StudentResponse,
    SubjectCreateRequest,
    SubjectResponse,
    TeacherCreateRequest,
    TeacherResponse,
    UserProfileResponse,
)
from app.services.academic_management_service import AcademicManagementService

router = APIRouter(
    prefix="/academic",
    tags=["Gestión Escolar K-12, SuperPanel, Docentes, Horarios, Matrículas y Asistencia"],
)


def get_management_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AcademicManagementService:
    return AcademicManagementService(session=session)


def get_academic_ai_service() -> AcademicAIService:
    return AcademicAIService()


# =====================================================================
# 0. CATÁLOGO DE GRADOS K-12 Y GESTIÓN DE COLEGIOS (SUPERPANEL SAAS)
# =====================================================================
@router.get(
    "/grades-catalog",
    response_model=list[SchoolGradeCatalogItem],
    status_code=status.HTTP_200_OK,
    summary="Catálogo oficial de los 16 grados escolares (desde Maternal hasta Grado 11°)",
)
async def get_grades_catalog(
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[SchoolGradeCatalogItem]:
    """Retorna la lista oficial de grados desde Maternal, Párvulos hasta Grado 11° con etapas MEN."""
    return AcademicManagementService.get_grades_catalog()


@router.get(
    "/schools",
    response_model=list[SchoolInstitutionResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar todos los colegios registrados en la plataforma SaaS",
)
async def list_schools(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[SchoolInstitutionResponse]:
    """Retorna colegios registrados, indicando Calendario A o B, DANE, Rector y grados activos."""
    return await service.list_schools()


@router.post(
    "/schools",
    response_model=SchoolInstitutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="SuperAdmin: Crear un nuevo Colegio, definir Calendario A/B, activar grados y crear Rector",
)
async def create_school(
    payload: SchoolCreateWithRectorRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.SUPERADMIN))],
) -> SchoolInstitutionResponse:
    """Acceso restringido a SuperAdmin para dar de alta una institución educativa."""
    return await service.create_school_with_rector(payload=payload)


@router.patch(
    "/schools/{school_id}/grades",
    response_model=SchoolInstitutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Activar o desactivar grados (Maternal a 11°) y ajustar Calendario de un colegio",
)
async def update_school_grades(
    school_id: uuid.UUID,
    payload: SchoolUpdateGradesRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.SUPERADMIN, UserRole.RECTOR))],
) -> SchoolInstitutionResponse:
    """Permite al SuperAdmin o al Rector del colegio activar/desactivar grados escolares."""
    return await service.update_school_grades(school_id=school_id, payload=payload)


@router.post(
    "/schools/{school_id}/rector",
    response_model=SchoolInstitutionResponse,
    status_code=status.HTTP_200_OK,
    summary="SuperAdmin: Nombrar o asignar un nuevo Rector a un colegio",
)
async def assign_school_rector(
    school_id: uuid.UUID,
    payload: SchoolAssignRectorRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(require_roles(UserRole.SUPERADMIN))],
) -> SchoolInstitutionResponse:
    return await service.assign_school_rector(school_id=school_id, payload=payload)


@router.post(
    "/staff",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Rectoría: Vincular Secretaría Académica, Coordinación o Psicoorientación",
)
async def create_school_staff(
    payload: SchoolStaffCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    current_user: Annotated[
        User, Depends(require_roles(UserRole.RECTOR, UserRole.ADMIN))
    ],
) -> UserProfileResponse:
    """Permite al Rector(a) conformar su equipo directivo y administrativo institucional."""
    return await service.create_school_staff(payload=payload, current_user=current_user)


# =====================================================================
# 1. TABLERO INSTITUCIONAL EJECUTIVO (SUPERPANEL / RECTORÍA / COORDINACIÓN)
# =====================================================================
@router.get(
    "/institutional-overview",
    response_model=InstitutionalOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener tablero ejecutivo escolar, colegios, catálogo de grados y directorio",
)
async def get_institutional_overview(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    school_id: uuid.UUID | None = Query(default=None, description="Filtrar métricas por ID de Colegio"),
) -> InstitutionalOverviewResponse:
    """Consolida métricas escolares, lista de colegios, grados activos, estudiantes y directorio."""
    return await service.get_institutional_overview(
        school_id=school_id, requesting_user=_current_user
    )


# =====================================================================
# 2. DOCENTES, MATERIAS, PERÍODOS Y HORARIOS ESCOLARES (COURSE OFFERINGS)
# =====================================================================
@router.post(
    "/teachers",
    response_model=TeacherResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo docente y su cuenta de acceso",
)
async def create_teacher(
    payload: TeacherCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.COORDINADOR, UserRole.SECRETARIA))
    ],
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
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[TeacherResponse]:
    return await service.list_teachers()


@router.post(
    "/subjects",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva asignatura en el plan de estudios",
)
async def create_subject(
    payload: SubjectCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.COORDINADOR))
    ],
) -> SubjectResponse:
    return await service.create_subject(payload=payload)


@router.get(
    "/subjects",
    response_model=list[SubjectResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar asignaturas activas del plan de estudios escolar",
)
async def list_subjects(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[SubjectResponse]:
    return await service.list_subjects()


@router.post(
    "/periods",
    response_model=AcademicPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear año o período lectivo escolar",
)
async def create_academic_period(
    payload: AcademicPeriodCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.COORDINADOR))
    ],
) -> AcademicPeriodResponse:
    return await service.create_academic_period(payload=payload)


@router.post(
    "/course-offerings",
    response_model=CourseOfferingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar horario y docente a un grado/salón validando cruces de horario",
)
async def create_course_offering(
    payload: CourseOfferingCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.COORDINADOR))
    ],
) -> CourseOfferingResponse:
    return await service.create_course_offering(payload=payload)


@router.get(
    "/course-offerings",
    response_model=list[CourseOfferingResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar cursos/salones, docentes asignados y bloques de horario semanal",
)
async def list_course_offerings(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[CourseOfferingResponse]:
    return await service.list_course_offerings()


# =====================================================================
# 3. ALUMNOS, MATRÍCULAS POR GRADO Y ASISTENCIA CON CO-PILOTO IA
# =====================================================================
@router.post(
    "/students",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Matricular nuevo estudiante en un grado activo del colegio (Maternal a 11°)",
)
async def create_student(
    payload: StudentCreateRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.SECRETARIA, UserRole.COORDINADOR))
    ],
) -> StudentResponse:
    return await service.create_student(payload=payload)


@router.get(
    "/students",
    response_model=list[StudentResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar estudiantes escolares activos",
)
async def list_students(
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[StudentResponse]:
    return await service.list_students()


@router.post(
    "/enrollments",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Formalizar matrícula de un alumno en un salón/grupo",
)
async def enroll_student(
    payload: EnrollmentCreate,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.SECRETARIA, UserRole.COORDINADOR))
    ],
) -> EnrollmentResponse:
    return await service.enroll_student_in_course(payload=payload)


@router.post(
    "/attendances",
    response_model=AttendanceRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar asistencia individual y evaluar riesgo de deserción con IA",
)
async def register_student_attendance(
    payload: AttendanceCreateRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    ai_service: Annotated[AcademicAIService, Depends(get_academic_ai_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.COORDINADOR, UserRole.DOCENTE, UserRole.TEACHER))
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


@router.post(
    "/attendances/bulk",
    response_model=list[AttendanceRegistrationResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Planilla de llamado a lista masivo del grupo/salón y disparar alertas IA",
)
async def register_bulk_attendance(
    payload: BulkAttendanceCreateRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
    ai_service: Annotated[AcademicAIService, Depends(get_academic_ai_service)],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.RECTOR, UserRole.COORDINADOR, UserRole.DOCENTE, UserRole.TEACHER))
    ],
) -> list[AttendanceRegistrationResponse]:
    results, ai_contexts = await service.register_bulk_attendance_session(
        payload=payload
    )
    for ctx in ai_contexts:
        background_tasks.add_task(
            ai_service.evaluate_and_save_student_risk_background,
            context=ctx,
        )
    return results
