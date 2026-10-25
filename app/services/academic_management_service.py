"""
Servicio de Dominio para Autenticación Institucional, SuperPanel Multi-Colegio (Maternal a Grado 11°),
Gobierno Escolar (SuperAdmin, Rector, Coordinación, Secretaría, Psicoorientación, Docentes y Estudiantes),
Horarios Semanales, Matrículas y Planilla de Asistencia (100% Español).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import settings
from app.core.exceptions import (
    BusinessRuleViolationError,
    EntityNotFoundError,
    UnauthorizedAccessError,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.models.academic import (
    AcademicPeriod,
    Attendance,
    AttendanceStatus,
    CourseOffering,
    Enrollment,
    EnrollmentStatus,
    Grade,
    SCHOOL_GRADES_CATALOG,
    SchoolInstitution,
    Student,
    Subject,
    Teacher,
    User,
    UserRole,
)
from app.repositories.grades_repository import GradesRepository
from app.schemas.academic import EnrollmentCreate, EnrollmentResponse
from app.schemas.ai_schemas import StudentAcademicContextDTO
from app.schemas.management import (
    AcademicPeriodCreateRequest,
    AcademicPeriodResponse,
    AttendanceCreateRequest,
    AttendanceLogItemResponse,
    AttendanceRegistrationResponse,
    BulkAttendanceCreateRequest,
    CourseOfferingCreateRequest,
    CourseOfferingResponse,
    EnrolledStudentSummaryItem,
    InstitutionalOverviewResponse,
    LoginRequest,
    ScheduleBlockSchema,
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
    TokenResponse,
    UserProfileResponse,
)
from app.services.grades_service import GradesService

TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal("100.00")
MIN_PASSING = Decimal(str(settings.MIN_PASSING_GRADE)).quantize(TWO_PLACES)

GRADES_MAP_BY_CODE: dict[str, dict[str, Any]] = {
    item["code"]: item for item in SCHOOL_GRADES_CATALOG
}

CALENDAR_LABELS_ES: dict[str, str] = {
    "CALENDARIO_A": "Calendario A (Febrero a Noviembre)",
    "CALENDARIO_B": "Calendario B (Septiembre a Junio)",
}

SHIFT_LABELS_ES: dict[str, str] = {
    "JORNADA_UNICA": "Jornada Única / Completa (07:00 - 15:00)",
    "COMPLETA": "Jornada Completa Bilingüe (07:00 - 15:30)",
    "MANANA": "Jornada Mañana (06:30 - 12:30)",
    "TARDE": "Jornada Tarde (12:45 - 18:30)",
}

ROLE_METADATA_ES: dict[UserRole, dict[str, Any]] = {
    UserRole.SUPERADMIN: {
        "label": "SuperAdmin Global (Gobierno de Colegios)",
        "default_title": "Director(a) de Plataforma SaaS Multi-Colegio",
        "default_area": "Gobierno Corporativo SoftEdu Cloud K-12",
        "permissions": [
            "Creación y Alta de Colegios en Calendario A y Calendario B",
            "Habilitación y Activación de Grados Escolares (Maternal a Grado 11°)",
            "Designación y Nombramiento de Rectores por Institución Educativa",
            "Auditoría Global de Colegios, Matrículas, Horarios y Copiloto IA",
        ],
    },
    UserRole.RECTOR: {
        "label": "Rectoría Institucional del Colegio",
        "default_title": "Rector(a) General del Colegio",
        "default_area": "Rectoría y Consejo Directivo Escolar",
        "permissions": [
            "Dirección General del Colegio (Calendario Escolar, PEI y Decreto 1290)",
            "Vinculación de Secretaría Académica, Coordinadores y Psicoorientadores",
            "Supervisión de Grados (Maternal a 11°), Planta Docente y Horarios",
            "Tablero Ejecutivo de Promoción Escolar y Alertas Tempranas IA",
        ],
    },
    UserRole.COORDINADOR: {
        "label": "Coordinación Académica y Convivencia",
        "default_title": "Coordinador(a) Académico(a) de Preescolar, Primaria y Bachillerato",
        "default_area": "Coordinación Académica y Curricular",
        "permissions": [
            "Diseño de Horarios Semanales por Grado (Maternal a 11°) sin Cruces",
            "Gestión de Áreas, Asignaturas MEN y Planes de Estudio Vectorizados",
            "Monitoreo de Alertas Tempranas de Riesgo Escolar e Inasistencia",
            "Supervisión de Planillas Docentes y Asistente Curricular IA",
        ],
    },
    UserRole.SECRETARIA: {
        "label": "Secretaría Académica y Matrículas",
        "default_title": "Secretario(a) Académico(a) y de Admisiones",
        "default_area": "Secretaría General, SIMAT y Registro Escolar",
        "permissions": [
            "Matrícula de Estudiantes en Grados Activos del Colegio (Maternal a 11°)",
            "Registro de Padres de Familia / Acudientes y Documentos de Identidad",
            "Vinculación Administrativa de Docentes Titulares y Directores de Grupo",
            "Expedición de Boletines Escolares Oficiales y Constancias de Estudio",
        ],
    },
    UserRole.ORIENTADOR: {
        "label": "Psicoorientación Escolar",
        "default_title": "Psicoorientador(a) y Bienestar Estudiantil",
        "default_area": "Departamento de Orientación y Familia",
        "permissions": [
            "Seguimiento de Estudiantes en Riesgo Alto y Crítico (Copiloto IA)",
            "Control de Inasistencias Reiteradas y Citación a Acudientes",
            "Planes de Acompañamiento Psicopedagógico por Grado",
            "Consulta de Boletines Escolares y Observador del Alumno",
        ],
    },
    UserRole.DOCENTE: {
        "label": "Docente Titular / Director de Grupo",
        "default_title": "Docente Titular de Área Escolar",
        "default_area": "Cuerpo Docente K-12 (Preescolar, Primaria y Bachillerato)",
        "permissions": [
            "Planilla de Llamado a Lista / Toma de Asistencia por Grado y Hora",
            "Registro de Calificaciones Decreto 1290 (Escala 0.0 a 5.0 por Periodo)",
            "Planeador de Clases IA, Rúbricas MEN y Evaluaciones Tipo Saber",
            "Consulta de Horario Semanal y Diagnósticos IA de sus Alumnos",
        ],
    },
    UserRole.TEACHER: {
        "label": "Docente Titular / Director de Grupo",
        "default_title": "Docente Titular de Área Escolar",
        "default_area": "Cuerpo Docente K-12",
        "permissions": [
            "Planilla de Llamado a Lista y Toma de Asistencia por Grado",
            "Registro de Calificaciones Decreto 1290 y Planeador IA",
        ],
    },
    UserRole.ESTUDIANTE: {
        "label": "Estudiante Matriculado",
        "default_title": "Estudiante Escolar Activo",
        "default_area": "Comunidad Estudiantil y Familias",
        "permissions": [
            "Consulta de Boletín Escolar Oficial por Periodo y Desempeño MEN",
            "Visualización de Horario Semanal de Clases y Récord de Asistencia",
            "Plan de Refuerzo Escolar Personalizado por el Copiloto IA",
            "Tutor Escolar Inteligente 24/7 basado en los Temas de Clase (RAG)",
        ],
    },
    UserRole.STUDENT: {
        "label": "Estudiante Matriculado",
        "default_title": "Estudiante Escolar Activo",
        "default_area": "Comunidad Estudiantil y Familias",
        "permissions": [
            "Consulta de Boletín Escolar Oficial, Horario y Tutor IA RAG",
        ],
    },
    UserRole.ADMIN: {
        "label": "Administrador Institucional",
        "default_title": "Administrador de Plataforma Educativa",
        "default_area": "Dirección de Sistemas y Gestión Escolar",
        "permissions": [
            "Control de Usuarios, Roles RBAC y Configuración Escolar",
            "Gestión Académica, Curricular, Matrículas, Notas y Motores IA",
        ],
    },
}

ATTENDANCE_LABELS_ES: dict[AttendanceStatus, str] = {
    AttendanceStatus.PRESENT: "Presente (Asistió a clase)",
    AttendanceStatus.ABSENT: "Inasistencia (Falla injustificada)",
    AttendanceStatus.LATE: "Llegada Tarde (Retardo al salón)",
    AttendanceStatus.EXCUSED: "Excusa Médica / Familiar Justificada",
}


class AcademicManagementService:
    """
    Orquesta la lógica de negocio del SuperPanel Multi-Colegio (Maternal a Grado 11°),
    Gobierno Escolar (Rector, Secretaría, Coordinación, Docentes y Alumnos),
    Horarios Semanales, Planilla de Asistencia y Calificaciones.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._grades_repo = GradesRepository(session)

    # =================================================================
    # 0. GESTIÓN DE COLEGIOS (SUPERADMIN) Y GOBIERNO ESCOLAR (RECTOR)
    # =================================================================
    @staticmethod
    def get_grades_catalog() -> list[SchoolGradeCatalogItem]:
        """Devuelve el catálogo oficial de los 16 grados escolares (Maternal a Grado 11°)."""
        return [SchoolGradeCatalogItem(**item) for item in SCHOOL_GRADES_CATALOG]

    @staticmethod
    def _normalize_enabled_grades(codes: list[str]) -> list[str]:
        valid_ordered: list[str] = []
        requested_set = {c.strip().upper() for c in codes if c.strip()}
        for item in SCHOOL_GRADES_CATALOG:
            if item["code"] in requested_set:
                valid_ordered.append(item["code"])
        if not valid_ordered:
            raise BusinessRuleViolationError(
                message="Debe seleccionar y activar al menos un grado válido (desde Maternal hasta Grado 11°).",
                rule_code="INVALID_SCHOOL_GRADES_SELECTION",
            )
        return valid_ordered

    def _map_school_to_dto(
        self,
        school: SchoolInstitution,
        rector_user: User | None = None,
        students_count: int = 0,
        teachers_count: int = 0,
        courses_count: int = 0,
    ) -> SchoolInstitutionResponse:
        enabled_details = [
            SchoolGradeCatalogItem(**GRADES_MAP_BY_CODE[c])
            for c in (school.enabled_grades or [])
            if c in GRADES_MAP_BY_CODE
        ]
        return SchoolInstitutionResponse(
            id=school.id,
            code=school.code,
            name=school.name,
            dane_code=school.dane_code,
            nit=school.nit,
            calendar_type=school.calendar_type,
            calendar_label_es=CALENDAR_LABELS_ES.get(
                school.calendar_type, school.calendar_type
            ),
            shift_type=school.shift_type,
            shift_label_es=SHIFT_LABELS_ES.get(school.shift_type, school.shift_type),
            city=school.city,
            address=school.address,
            phone=school.phone,
            email_contact=school.email_contact,
            resolution_men=school.resolution_men,
            rector_user_id=school.rector_user_id,
            rector_full_name=rector_user.full_name if rector_user else None,
            rector_email=rector_user.email if rector_user else None,
            enabled_grades=list(school.enabled_grades or []),
            enabled_grades_details=enabled_details,
            total_students_count=students_count,
            total_teachers_count=teachers_count,
            total_courses_count=courses_count,
            is_active=school.is_active,
        )

    async def list_schools(self) -> list[SchoolInstitutionResponse]:
        """Lista todos los colegios registrados en la plataforma junto con su Rector, grados activos y estadísticas agregadas."""
        stmt = (
            select(SchoolInstitution)
            .where(SchoolInstitution.is_active.is_(True))
            .order_by(SchoolInstitution.created_at.asc())
        )
        schools = list((await self._session.execute(stmt)).scalars().all())

        rector_ids = [s.rector_user_id for s in schools if s.rector_user_id is not None]
        rectors_by_id: dict[uuid.UUID, User] = {}
        if rector_ids:
            r_stmt = select(User).where(User.id.in_(rector_ids))
            for u in (await self._session.execute(r_stmt)).scalars().all():
                rectors_by_id[u.id] = u

        # Conteo estadístico agregado por colegio (sin exponer datos individuales al SuperAdmin)
        stu_counts_stmt = (
            select(User.school_id, func.count(Student.id))
            .join(User, Student.user_id == User.id)
            .where(Student.is_active.is_(True))
            .group_by(User.school_id)
        )
        stu_counts = dict((await self._session.execute(stu_counts_stmt)).all())

        teach_counts_stmt = (
            select(User.school_id, func.count(Teacher.id))
            .join(User, Teacher.user_id == User.id)
            .where(Teacher.is_active.is_(True))
            .group_by(User.school_id)
        )
        teach_counts = dict((await self._session.execute(teach_counts_stmt)).all())

        first_school_id = schools[0].id if schools else None
        total_courses_stmt = select(func.count(CourseOffering.id)).where(CourseOffering.is_active.is_(True))
        total_courses_val = (await self._session.scalar(total_courses_stmt)) or 0

        return [
            self._map_school_to_dto(
                s,
                rector_user=rectors_by_id.get(s.rector_user_id),
                students_count=stu_counts.get(s.id, 0),
                teachers_count=teach_counts.get(s.id, 0),
                courses_count=total_courses_val if s.id == first_school_id else 0,
            )
            for s in schools
        ]

    async def create_school_with_rector(
        self, payload: SchoolCreateWithRectorRequest
    ) -> SchoolInstitutionResponse:
        """
        Caso de Uso SuperPanel (SUPERADMIN):
        Crea un nuevo Colegio (Calendario A o B), activa los grados seleccionados (Maternal a 11°)
        y crea/asigna la cuenta del Rector(a) para que pueda administrar su institución.
        """
        existing_school = await self._session.execute(
            select(SchoolInstitution.id).where(
                func.upper(SchoolInstitution.code) == payload.code.upper()
            )
        )
        if existing_school.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message=f"Ya existe un colegio registrado con el código '{payload.code}'.",
                rule_code="DUPLICATE_SCHOOL_CODE",
            )

        normalized_grades = self._normalize_enabled_grades(payload.enabled_grades)

        school = SchoolInstitution(
            code=payload.code.upper(),
            name=payload.name,
            dane_code=payload.dane_code,
            nit=payload.nit,
            calendar_type=payload.calendar_type,
            shift_type=payload.shift_type,
            city=payload.city,
            address=payload.address,
            phone=payload.phone,
            email_contact=payload.email_contact,
            resolution_men=payload.resolution_men
            or "Resolución MEN / SED Educación Preescolar, Básica y Media",
            enabled_grades=normalized_grades,
        )
        self._session.add(school)
        await self._session.flush()

        rector_user: User | None = None
        if payload.rector_email and payload.rector_first_name and payload.rector_last_name:
            dup_user = await self._session.execute(
                select(User.id).where(
                    (func.lower(User.email) == payload.rector_email.lower())
                    | (
                        User.document_number
                        == (payload.rector_document_number or f"REC-{school.code}")
                    )
                )
            )
            if dup_user.scalars().first() is not None:
                raise BusinessRuleViolationError(
                    message=(
                        f"El correo '{payload.rector_email}' o documento del Rector "
                        f"ya se encuentra registrado en otra cuenta."
                    ),
                    rule_code="DUPLICATE_RECTOR_USER",
                )

            rector_user = User(
                school_id=school.id,
                email=payload.rector_email.lower(),
                hashed_password=hash_password(payload.rector_password or "SoftEdu2026*"),
                first_name=payload.rector_first_name,
                last_name=payload.rector_last_name,
                document_number=payload.rector_document_number or f"REC-{school.code}",
                role=UserRole.RECTOR,
                job_title=f"Rector(a) General — {school.name}",
                department_area="Rectoría y Consejo Directivo",
                phone_number=payload.rector_phone or payload.phone,
            )
            self._session.add(rector_user)
            await self._session.flush()
            school.rector_user_id = rector_user.id

        await self._session.commit()
        await self._session.refresh(school)
        return self._map_school_to_dto(school, rector_user)

    async def update_school_grades(
        self, school_id: uuid.UUID, payload: SchoolUpdateGradesRequest
    ) -> SchoolInstitutionResponse:
        """
        Activa o desactiva los grados escolares (Maternal a Grado 11°) y el Calendario (A o B)
        de un colegio específico desde el SuperPanel o la Rectoría.
        """
        school = await self._session.get(SchoolInstitution, school_id)
        if school is None or not school.is_active:
            raise EntityNotFoundError("SchoolInstitution", school_id)

        school.enabled_grades = self._normalize_enabled_grades(payload.enabled_grades)
        if payload.calendar_type is not None:
            school.calendar_type = payload.calendar_type
        if payload.shift_type is not None:
            school.shift_type = payload.shift_type

        await self._session.commit()
        await self._session.refresh(school)

        rector_user = (
            await self._session.get(User, school.rector_user_id)
            if school.rector_user_id
            else None
        )
        return self._map_school_to_dto(school, rector_user)

    async def assign_school_rector(
        self, school_id: uuid.UUID, payload: SchoolAssignRectorRequest
    ) -> SchoolInstitutionResponse:
        """Crea y designa un nuevo Rector(a) para un colegio desde el SuperPanel."""
        school = await self._session.get(SchoolInstitution, school_id)
        if school is None or not school.is_active:
            raise EntityNotFoundError("SchoolInstitution", school_id)

        existing = await self._session.execute(
            select(User.id).where(
                (func.lower(User.email) == payload.email.lower())
                | (User.document_number == payload.document_number)
            )
        )
        if existing.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message="Ya existe un usuario con el correo o documento especificado para el Rector.",
                rule_code="DUPLICATE_RECTOR_EMAIL_OR_DOC",
            )

        rector_user = User(
            school_id=school.id,
            email=payload.email.lower(),
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            document_number=payload.document_number,
            role=UserRole.RECTOR,
            job_title=f"Rector(a) General — {school.name}",
            department_area="Rectoría y Consejo Directivo",
            phone_number=payload.phone_number,
        )
        self._session.add(rector_user)
        await self._session.flush()

        school.rector_user_id = rector_user.id
        await self._session.commit()
        await self._session.refresh(school)
        return self._map_school_to_dto(school, rector_user)

    async def create_school_staff(
        self, payload: SchoolStaffCreateRequest, current_user: User
    ) -> UserProfileResponse:
        """
        Permite al Rector(a) (o al SuperAdmin) vincular a su Secretaria Académica,
        Coordinador(a) Académico / de Convivencia o Psicoorientador(a) Escolar.
        """
        existing = await self._session.execute(
            select(User.id).where(
                (func.lower(User.email) == payload.email.lower())
                | (User.document_number == payload.document_number)
            )
        )
        if existing.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message="Ya existe un funcionario registrado con ese correo o documento de identidad.",
                rule_code="DUPLICATE_STAFF_USER",
            )

        target_school_id = payload.school_id or current_user.school_id
        if target_school_id is None:
            first_school = (
                await self._session.execute(
                    select(SchoolInstitution)
                    .where(SchoolInstitution.is_active.is_(True))
                    .order_by(SchoolInstitution.created_at.asc())
                    .limit(1)
                )
            ).scalars().first()
            if first_school:
                target_school_id = first_school.id

        role_enum = UserRole(payload.role)
        staff_user = User(
            school_id=target_school_id,
            email=payload.email.lower(),
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            document_number=payload.document_number,
            role=role_enum,
            job_title=payload.job_title,
            department_area=payload.department_area,
            phone_number=payload.phone_number,
        )
        self._session.add(staff_user)
        await self._session.commit()
        await self._session.refresh(staff_user)

        school = (
            await self._session.get(SchoolInstitution, target_school_id)
            if target_school_id
            else None
        )
        return self.map_user_to_profile_dto(staff_user, school=school)

    # =================================================================
    # 1. AUTENTICACIÓN JWT E IDENTIDAD INSTITUCIONAL
    # =================================================================
    async def authenticate_user(self, payload: LoginRequest) -> TokenResponse:
        """Verifica credenciales de correo y contraseña y emite un JWT firmado."""
        stmt = (
            select(User)
            .options(
                joinedload(User.teacher_profile),
                joinedload(User.student_profile).selectinload(Student.enrollments),
            )
            .where(
                func.lower(User.email) == payload.email.lower(),
                User.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        user = result.scalars().unique().first()

        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedAccessError(
                message="Correo institucional o contraseña incorrectos. Verifique sus credenciales."
            )

        school = await self._resolve_user_school(user)
        access_token = create_access_token(user_id=user.id, role=user.role)
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
            user=self.map_user_to_profile_dto(user, school=school),
        )

    async def _resolve_user_school(self, user: User) -> SchoolInstitution | None:
        if user.school_id is not None:
            school = await self._session.get(SchoolInstitution, user.school_id)
            if school is not None:
                return school
        stmt = (
            select(SchoolInstitution)
            .where(SchoolInstitution.is_active.is_(True))
            .order_by(SchoolInstitution.created_at.asc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalars().first()

    @staticmethod
    def map_user_to_profile_dto(
        user: User, school: SchoolInstitution | None = None
    ) -> UserProfileResponse:
        meta = ROLE_METADATA_ES.get(
            user.role, ROLE_METADATA_ES[UserRole.ESTUDIANTE]
        )
        enrollment_id: uuid.UUID | None = None
        if user.student_profile and user.student_profile.enrollments:
            active_enr = [
                e
                for e in user.student_profile.enrollments
                if e.is_active and e.status == EnrollmentStatus.ACTIVE
            ]
            if active_enr:
                enrollment_id = active_enr[0].id

        return UserProfileResponse(
            id=user.id,
            school_id=school.id if school else user.school_id,
            school_name=school.name if school else "Consola Global Multi-Colegio SoftEdu",
            school_calendar_type=school.calendar_type if school else "CALENDARIO_A",
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            full_name=user.full_name,
            document_number=user.document_number,
            role=user.role,
            role_label_es=meta["label"],
            job_title=user.job_title or meta["default_title"],
            department_area=user.department_area or meta["default_area"],
            phone_number=user.phone_number,
            permissions_es=meta["permissions"],
            teacher_id=user.teacher_profile.id if user.teacher_profile else None,
            employee_code=(
                user.teacher_profile.employee_code if user.teacher_profile else None
            ),
            student_id=user.student_profile.id if user.student_profile else None,
            student_code=(
                user.student_profile.student_code if user.student_profile else None
            ),
            program_name=(
                user.student_profile.program_name if user.student_profile else None
            ),
            grade_level_code=(
                user.student_profile.grade_level_code if user.student_profile else None
            ),
            current_semester=(
                user.student_profile.current_semester if user.student_profile else None
            ),
            enrollment_id=enrollment_id,
            is_active=user.is_active,
        )

    # =================================================================
    # 2. TABLERO EJECUTIVO INSTITUCIONAL (SUPERPANEL / RECTORÍA / COORDINACIÓN)
    # =================================================================
    async def get_institutional_overview(
        self,
        school_id: uuid.UUID | None = None,
        requesting_user: User | None = None,
    ) -> InstitutionalOverviewResponse:
        """
        Consolida los colegios registrados, el catálogo de grados (Maternal a 11°),
        las métricas académicas, la asistencia, las alertas IA y el directorio escolar.
        Aplica el Principio de Privacidad por Diseño (Ley 1581 de 2012 / Habeas Data):
        Si el usuario es SUPERADMIN (administrador SaaS de infraestructura), no tiene acceso
        a las identidades ni calificaciones individuales de menores de edad.
        """
        all_schools = await self.list_schools()
        active_school: SchoolInstitutionResponse | None = None
        if school_id is not None:
            active_school = next(
                (s for s in all_schools if s.id == school_id), None
            )
        if active_school is None and all_schools:
            active_school = all_schools[0]

        period_stmt = select(AcademicPeriod).where(
            AcademicPeriod.is_active.is_(True),
            AcademicPeriod.is_current.is_(True),
        )
        current_period = (await self._session.execute(period_stmt)).scalars().first()
        period_code = current_period.code if current_period else "2026-CAL-A"
        period_name = (
            current_period.name
            if current_period
            else "Año Lectivo Escolar 2026 — Calendario A"
        )

        total_students = (
            await self._session.scalar(
                select(func.count(Student.id)).where(Student.is_active.is_(True))
            )
            or 0
        )
        total_teachers = (
            await self._session.scalar(
                select(func.count(Teacher.id)).where(Teacher.is_active.is_(True))
            )
            or 0
        )
        total_subjects = (
            await self._session.scalar(
                select(func.count(Subject.id)).where(Subject.is_active.is_(True))
            )
            or 0
        )
        total_offerings = (
            await self._session.scalar(
                select(func.count(CourseOffering.id)).where(
                    CourseOffering.is_active.is_(True)
                )
            )
            or 0
        )

        # Si es SUPERADMIN, entregar exclusivamente métricas SaaS globales y agregadas
        if requesting_user is not None and requesting_user.role == UserRole.SUPERADMIN:
            return InstitutionalOverviewResponse(
                active_school=active_school,
                schools=all_schools,
                grades_catalog=self.get_grades_catalog(),
                active_period_code=period_code,
                active_period_name=period_name,
                total_students=total_students,
                total_teachers=total_teachers,
                total_subjects=total_subjects,
                total_course_offerings=total_offerings,
                total_active_enrollments=total_students,
                institutional_average_grade=Decimal("0.00"),
                passing_students_count=0,
                failing_students_count=0,
                approval_rate_percentage=Decimal("100.00"),
                global_attendance_percentage=Decimal("100.00"),
                risk_distribution={},
                enrolled_students=[],
                recent_attendances=[],
                institutional_directory=[],
            )

        enrollments_stmt = (
            select(Enrollment)
            .options(
                joinedload(Enrollment.student).joinedload(Student.user),
                joinedload(Enrollment.course_offering).joinedload(CourseOffering.subject),
                joinedload(Enrollment.course_offering).joinedload(
                    CourseOffering.academic_period
                ),
                selectinload(Enrollment.grades).joinedload(Grade.syllabus_topic),
                selectinload(Enrollment.attendances),
                selectinload(Enrollment.ai_insights),
            )
            .where(
                Enrollment.is_active.is_(True),
                Enrollment.status == EnrollmentStatus.ACTIVE,
            )
        )
        enrollments = list(
            (await self._session.execute(enrollments_stmt)).scalars().unique().all()
        )
        enrollments.sort(key=lambda e: e.student.student_code)

        roster: list[EnrolledStudentSummaryItem] = []
        risk_counts: dict[str, int] = {
            "BAJO": 0,
            "MEDIO": 0,
            "ALTO": 0,
            "CRITICO": 0,
            "SIN_DIAGNOSTICO": 0,
        }
        sum_averages = Decimal("0.00")
        sum_attendance_pct = Decimal("0.00")
        passing_count = 0
        failing_count = 0
        all_attendance_logs: list[AttendanceLogItemResponse] = []

        for enr in enrollments:
            active_grades = [g for g in enr.grades if g.is_active]
            active_att = [a for a in enr.attendances if a.is_active]
            grade_metrics = GradesService._calculate_weighted_metrics(active_grades)
            att_summary = GradesService._calculate_attendance_summary(
                attendances=active_att,
                total_planned_sessions=enr.course_offering.total_planned_sessions,
            )
            current_insight = GradesService._extract_current_ai_insight(enr)

            avg_val = grade_metrics["current_weighted_average"]
            sum_averages += avg_val
            sum_attendance_pct += att_summary.attendance_percentage

            is_passing = avg_val >= MIN_PASSING or not active_grades
            if is_passing:
                passing_count += 1
            else:
                failing_count += 1

            if current_insight is not None:
                risk_counts[current_insight.risk_level.value] = (
                    risk_counts.get(current_insight.risk_level.value, 0) + 1
                )
            else:
                risk_counts["SIN_DIAGNOSTICO"] += 1

            for att_item in active_att:
                all_attendance_logs.append(
                    AttendanceLogItemResponse(
                        id=att_item.id,
                        enrollment_id=enr.id,
                        student_code=enr.student.student_code,
                        student_full_name=enr.student.user.full_name,
                        session_date=att_item.session_date,
                        status=att_item.status,
                        status_label_es=ATTENDANCE_LABELS_ES.get(
                            att_item.status, att_item.status.value
                        ),
                        observations=att_item.observations,
                        created_at=att_item.created_at,
                    )
                )

            roster.append(
                EnrolledStudentSummaryItem(
                    enrollment_id=enr.id,
                    student_id=enr.student.id,
                    student_code=enr.student.student_code,
                    student_full_name=enr.student.user.full_name,
                    student_email=enr.student.user.email,
                    document_number=enr.student.user.document_number,
                    grade_level_code=enr.student.grade_level_code or "GRADO_11",
                    program_name=enr.student.program_name,
                    current_semester=enr.student.current_semester,
                    guardian_name=enr.student.guardian_name,
                    guardian_phone=enr.student.guardian_phone,
                    course_offering_id=enr.course_offering.id,
                    subject_id=enr.course_offering.subject.id,
                    subject_code=enr.course_offering.subject.code,
                    subject_name=enr.course_offering.subject.name,
                    group_code=enr.course_offering.group_code,
                    academic_period_code=enr.course_offering.academic_period.code,
                    evaluated_weight_percentage=grade_metrics[
                        "evaluated_weight_percentage"
                    ],
                    remaining_weight_percentage=grade_metrics[
                        "remaining_weight_percentage"
                    ],
                    current_weighted_average=avg_val,
                    minimum_score_needed_in_remaining=grade_metrics[
                        "minimum_score_needed_in_remaining"
                    ],
                    is_currently_passing=is_passing,
                    grades_count=len(active_grades),
                    present_count=att_summary.present_count,
                    late_count=att_summary.late_count,
                    excused_count=att_summary.excused_count,
                    unexcused_absent_count=att_summary.unexcused_absent_count,
                    attendance_percentage=att_summary.attendance_percentage,
                    absence_percentage=att_summary.absence_percentage,
                    risk_level=(
                        current_insight.risk_level if current_insight else None
                    ),
                    ai_executive_summary=(
                        current_insight.executive_summary if current_insight else None
                    ),
                    ai_detected_factors=(
                        current_insight.detected_factors if current_insight else []
                    ),
                    ai_action_plan=(
                        current_insight.suggested_action_plan.model_dump(mode="json")
                        if current_insight
                        else None
                    ),
                )
            )

        enr_count = len(enrollments)
        if enr_count > 0:
            inst_avg = (sum_averages / Decimal(enr_count)).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            global_att = (sum_attendance_pct / Decimal(enr_count)).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            approval_rate = (
                (Decimal(passing_count) * HUNDRED) / Decimal(enr_count)
            ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            inst_avg = Decimal("0.00")
            global_att = HUNDRED
            approval_rate = HUNDRED

        all_attendance_logs.sort(
            key=lambda x: (x.session_date, x.created_at), reverse=True
        )

        # Directorio institucional completo con colegio asociado
        schools_by_id: dict[uuid.UUID, SchoolInstitution] = {}
        raw_schools_stmt = select(SchoolInstitution).where(
            SchoolInstitution.is_active.is_(True)
        )
        for s_obj in (await self._session.execute(raw_schools_stmt)).scalars().all():
            schools_by_id[s_obj.id] = s_obj
        default_school_obj = next(iter(schools_by_id.values()), None)

        users_stmt = (
            select(User)
            .options(
                joinedload(User.teacher_profile),
                joinedload(User.student_profile).selectinload(Student.enrollments),
            )
            .where(User.is_active.is_(True))
            .order_by(User.created_at.asc())
        )
        all_users = list(
            (await self._session.execute(users_stmt)).scalars().unique().all()
        )
        directory = [
            self.map_user_to_profile_dto(
                u,
                school=schools_by_id.get(u.school_id, default_school_obj)
                if u.role != UserRole.SUPERADMIN
                else None,
            )
            for u in all_users
        ]

        return InstitutionalOverviewResponse(
            active_school=active_school,
            schools=all_schools,
            grades_catalog=self.get_grades_catalog(),
            active_period_code=period_code,
            active_period_name=period_name,
            total_students=total_students,
            total_teachers=total_teachers,
            total_subjects=total_subjects,
            total_course_offerings=total_offerings,
            total_active_enrollments=enr_count,
            institutional_average_grade=inst_avg,
            passing_students_count=passing_count,
            failing_students_count=failing_count,
            approval_rate_percentage=approval_rate,
            global_attendance_percentage=global_att,
            risk_distribution=risk_counts,
            enrolled_students=roster,
            recent_attendances=all_attendance_logs[:40],
            institutional_directory=directory,
        )

    # =================================================================
    # 3. DOCENTES, MATERIAS, PERÍODOS Y OFERTAS CON HORARIOS ESCOLARES
    # =================================================================
    async def create_teacher(self, payload: TeacherCreateRequest) -> TeacherResponse:
        existing = await self._session.execute(
            select(User.id).where(
                (func.lower(User.email) == payload.email.lower())
                | (User.document_number == payload.document_number)
            )
        )
        if existing.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message="Ya existe un usuario con el correo o documento especificado.",
                rule_code="DUPLICATE_USER_EMAIL_OR_DOCUMENT",
            )

        existing_code = await self._session.execute(
            select(Teacher.id).where(Teacher.employee_code == payload.employee_code)
        )
        if existing_code.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message=f"El código docente '{payload.employee_code}' ya se encuentra registrado.",
                rule_code="DUPLICATE_TEACHER_CODE",
            )

        first_school = (
            await self._session.execute(
                select(SchoolInstitution)
                .where(SchoolInstitution.is_active.is_(True))
                .order_by(SchoolInstitution.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

        user = User(
            school_id=first_school.id if first_school else None,
            email=payload.email.lower(),
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            document_number=payload.document_number,
            role=UserRole.DOCENTE,
            job_title=f"Docente Titular — {payload.specialization}",
            department_area=payload.department,
        )
        self._session.add(user)
        await self._session.flush()

        teacher = Teacher(
            user_id=user.id,
            employee_code=payload.employee_code,
            department=payload.department,
            specialization=payload.specialization,
            academic_degree=payload.academic_degree,
            max_weekly_hours=payload.max_weekly_hours,
        )
        self._session.add(teacher)
        await self._session.commit()
        await self._session.refresh(teacher)

        return TeacherResponse(
            id=teacher.id,
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            document_number=user.document_number,
            employee_code=teacher.employee_code,
            department=teacher.department,
            specialization=teacher.specialization,
            academic_degree=teacher.academic_degree,
            max_weekly_hours=teacher.max_weekly_hours,
            is_active=teacher.is_active,
        )

    async def list_teachers(self) -> list[TeacherResponse]:
        stmt = (
            select(Teacher)
            .options(joinedload(Teacher.user))
            .where(Teacher.is_active.is_(True))
            .order_by(Teacher.employee_code.asc())
        )
        result = await self._session.execute(stmt)
        teachers = result.scalars().all()
        return [
            TeacherResponse(
                id=t.id,
                user_id=t.user_id,
                full_name=t.user.full_name,
                email=t.user.email,
                document_number=t.user.document_number,
                employee_code=t.employee_code,
                department=t.department,
                specialization=t.specialization,
                academic_degree=t.academic_degree,
                max_weekly_hours=t.max_weekly_hours,
                is_active=t.is_active,
            )
            for t in teachers
        ]

    async def create_subject(self, payload: SubjectCreateRequest) -> SubjectResponse:
        existing = await self._session.execute(
            select(Subject.id).where(func.upper(Subject.code) == payload.code.upper())
        )
        if existing.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message=f"Ya existe una asignatura con el código '{payload.code}'.",
                rule_code="DUPLICATE_SUBJECT_CODE",
            )

        subject = Subject(
            code=payload.code.upper(),
            name=payload.name,
            description=payload.description,
            credits=payload.credits,
            weekly_hours=payload.weekly_hours,
            minimum_passing_grade=payload.minimum_passing_grade,
        )
        self._session.add(subject)
        await self._session.commit()
        await self._session.refresh(subject)
        return SubjectResponse.model_validate(subject)

    async def list_subjects(self) -> list[SubjectResponse]:
        stmt = (
            select(Subject)
            .where(Subject.is_active.is_(True))
            .order_by(Subject.code.asc())
        )
        result = await self._session.execute(stmt)
        return [SubjectResponse.model_validate(s) for s in result.scalars().all()]

    async def create_academic_period(
        self, payload: AcademicPeriodCreateRequest
    ) -> AcademicPeriodResponse:
        existing = await self._session.execute(
            select(AcademicPeriod.id).where(
                func.upper(AcademicPeriod.code) == payload.code.upper()
            )
        )
        if existing.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message=f"El período lectivo '{payload.code}' ya existe.",
                rule_code="DUPLICATE_ACADEMIC_PERIOD",
            )

        if payload.is_current:
            await self._session.execute(
                update(AcademicPeriod)
                .where(AcademicPeriod.is_current.is_(True))
                .values(is_current=False)
            )

        period = AcademicPeriod(
            code=payload.code.upper(),
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_current=payload.is_current,
        )
        self._session.add(period)
        await self._session.commit()
        await self._session.refresh(period)
        return AcademicPeriodResponse.model_validate(period)

    async def create_course_offering(
        self, payload: CourseOfferingCreateRequest
    ) -> CourseOfferingResponse:
        subject = await self._session.get(Subject, payload.subject_id)
        if subject is None or not subject.is_active:
            raise EntityNotFoundError("Subject", payload.subject_id)

        teacher_stmt = (
            select(Teacher)
            .options(joinedload(Teacher.user))
            .where(Teacher.id == payload.teacher_id, Teacher.is_active.is_(True))
        )
        teacher = (await self._session.execute(teacher_stmt)).scalars().first()
        if teacher is None:
            raise EntityNotFoundError("Teacher", payload.teacher_id)

        period = await self._session.get(AcademicPeriod, payload.academic_period_id)
        if period is None or not period.is_active:
            raise EntityNotFoundError("AcademicPeriod", payload.academic_period_id)

        grade_code = (payload.grade_level_code or "GRADO_11").upper()
        grade_meta = GRADES_MAP_BY_CODE.get(
            grade_code, GRADES_MAP_BY_CODE["GRADO_11"]
        )

        teacher_offerings_stmt = (
            select(CourseOffering)
            .options(joinedload(CourseOffering.subject))
            .where(
                CourseOffering.teacher_id == teacher.id,
                CourseOffering.academic_period_id == period.id,
                CourseOffering.is_active.is_(True),
            )
        )
        existing_offerings = (
            (await self._session.execute(teacher_offerings_stmt)).scalars().all()
        )
        new_blocks_raw = [b.model_dump(mode="json") for b in payload.schedule_blocks]

        for existing_off in existing_offerings:
            if (
                existing_off.subject_id == subject.id
                and existing_off.group_code.upper() == payload.group_code.upper()
            ):
                raise BusinessRuleViolationError(
                    message=(
                        f"Ya existe el curso/salón '{payload.group_code}' para la asignatura "
                        f"'{subject.name}' en el período '{period.code}'."
                    ),
                    rule_code="DUPLICATE_COURSE_OFFERING_GROUP",
                )

            conflict = self._detect_schedule_conflict(
                new_blocks_raw, existing_off.schedule_blocks
            )
            if conflict is not None:
                raise BusinessRuleViolationError(
                    message=(
                        f"Choque de horario escolar para el docente {teacher.user.full_name} con la "
                        f"asignatura '{existing_off.subject.name}' ({existing_off.group_code}) "
                        f"el día {conflict['day']} ({conflict['start_time']} - {conflict['end_time']})."
                    ),
                    rule_code="TEACHER_SCHEDULE_CONFLICT",
                    details=conflict,
                )

        offering = CourseOffering(
            subject_id=subject.id,
            teacher_id=teacher.id,
            academic_period_id=period.id,
            group_code=payload.group_code.upper(),
            grade_level_code=grade_code,
            max_capacity=payload.max_capacity,
            total_planned_sessions=payload.total_planned_sessions,
            schedule_blocks=new_blocks_raw,
        )
        self._session.add(offering)
        await self._session.commit()
        await self._session.refresh(offering)

        return CourseOfferingResponse(
            id=offering.id,
            subject_id=subject.id,
            subject_code=subject.code,
            subject_name=subject.name,
            teacher_id=teacher.id,
            teacher_full_name=teacher.user.full_name,
            academic_period_id=period.id,
            academic_period_code=period.code,
            group_code=offering.group_code,
            grade_level_code=grade_code,
            grade_level_label=grade_meta["short_name"],
            max_capacity=offering.max_capacity,
            enrolled_count=0,
            total_planned_sessions=offering.total_planned_sessions,
            schedule_blocks=payload.schedule_blocks,
        )

    async def list_course_offerings(self) -> list[CourseOfferingResponse]:
        stmt = (
            select(CourseOffering)
            .options(
                joinedload(CourseOffering.subject),
                joinedload(CourseOffering.teacher).joinedload(Teacher.user),
                joinedload(CourseOffering.academic_period),
                selectinload(CourseOffering.enrollments),
            )
            .where(CourseOffering.is_active.is_(True))
        )
        result = await self._session.execute(stmt)
        offerings = result.scalars().unique().all()
        items: list[CourseOfferingResponse] = []
        for off in offerings:
            g_code = off.grade_level_code or "GRADO_11"
            g_meta = GRADES_MAP_BY_CODE.get(g_code, GRADES_MAP_BY_CODE["GRADO_11"])
            items.append(
                CourseOfferingResponse(
                    id=off.id,
                    subject_id=off.subject.id,
                    subject_code=off.subject.code,
                    subject_name=off.subject.name,
                    teacher_id=off.teacher.id,
                    teacher_full_name=off.teacher.user.full_name,
                    academic_period_id=off.academic_period.id,
                    academic_period_code=off.academic_period.code,
                    group_code=off.group_code,
                    grade_level_code=g_code,
                    grade_level_label=g_meta["short_name"],
                    max_capacity=off.max_capacity,
                    enrolled_count=sum(
                        1
                        for e in off.enrollments
                        if e.is_active and e.status == EnrollmentStatus.ACTIVE
                    ),
                    total_planned_sessions=off.total_planned_sessions,
                    schedule_blocks=[
                        ScheduleBlockSchema.model_validate(b)
                        for b in off.schedule_blocks
                    ],
                )
            )
        return items

    # =================================================================
    # 4. ALUMNOS POR GRADO (MATERNAL A 11°), MATRÍCULAS Y ASISTENCIA
    # =================================================================
    async def create_student(self, payload: StudentCreateRequest) -> StudentResponse:
        existing = await self._session.execute(
            select(User.id).where(
                (func.lower(User.email) == payload.email.lower())
                | (User.document_number == payload.document_number)
            )
        )
        if existing.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message="Ya existe un estudiante o usuario con el correo o documento especificado.",
                rule_code="DUPLICATE_USER_EMAIL_OR_DOCUMENT",
            )

        existing_code = await self._session.execute(
            select(Student.id).where(Student.student_code == payload.student_code)
        )
        if existing_code.scalars().first() is not None:
            raise BusinessRuleViolationError(
                message=f"El código estudiantil '{payload.student_code}' ya existe.",
                rule_code="DUPLICATE_STUDENT_CODE",
            )

        first_school = (
            await self._session.execute(
                select(SchoolInstitution)
                .where(SchoolInstitution.is_active.is_(True))
                .order_by(SchoolInstitution.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

        grade_code = (payload.grade_level_code or "GRADO_11").upper()
        if grade_code not in GRADES_MAP_BY_CODE:
            raise BusinessRuleViolationError(
                message=f"El grado '{grade_code}' no pertenece al catálogo oficial (Maternal a Grado 11°).",
                rule_code="INVALID_GRADE_LEVEL_CODE",
            )

        if first_school and first_school.enabled_grades:
            if grade_code not in first_school.enabled_grades:
                raise BusinessRuleViolationError(
                    message=(
                        f"El grado '{GRADES_MAP_BY_CODE[grade_code]['name']}' no está habilitado "
                        f"actualmente en '{first_school.name}'. Solicite al SuperAdmin activarlo."
                    ),
                    rule_code="GRADE_NOT_ENABLED_IN_SCHOOL",
                )

        grade_info = GRADES_MAP_BY_CODE[grade_code]
        resolved_program_name = payload.program_name or grade_info["name"]
        resolved_order = max(1, int(grade_info["order"]))

        user = User(
            school_id=first_school.id if first_school else None,
            email=payload.email.lower(),
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            document_number=payload.document_number,
            role=UserRole.ESTUDIANTE,
            job_title=f"Estudiante — {grade_info['short_name']}",
            department_area=grade_info["stage"],
        )
        self._session.add(user)
        await self._session.flush()

        student = Student(
            user_id=user.id,
            student_code=payload.student_code,
            grade_level_code=grade_code,
            program_name=resolved_program_name,
            current_semester=resolved_order,
            enrollment_cohort=payload.enrollment_cohort,
            birth_date=payload.birth_date,
            guardian_name=payload.guardian_name,
            guardian_phone=payload.guardian_phone,
        )
        self._session.add(student)
        await self._session.flush()

        # Matricular automáticamente en el curso principal activo
        default_off = (
            await self._session.execute(
                select(CourseOffering)
                .where(CourseOffering.is_active.is_(True))
                .order_by(CourseOffering.created_at.asc())
                .limit(1)
            )
        ).scalars().first()
        if default_off is not None:
            enr = Enrollment(
                student_id=student.id,
                course_offering_id=default_off.id,
                status=EnrollmentStatus.ACTIVE,
            )
            self._session.add(enr)

        await self._session.commit()
        await self._session.refresh(student)

        return StudentResponse(
            id=student.id,
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            document_number=user.document_number,
            student_code=student.student_code,
            grade_level_code=student.grade_level_code,
            program_name=student.program_name,
            current_semester=student.current_semester,
            enrollment_cohort=student.enrollment_cohort,
            birth_date=student.birth_date,
            guardian_name=student.guardian_name,
            guardian_phone=student.guardian_phone,
            is_active=student.is_active,
        )

    async def list_students(self) -> list[StudentResponse]:
        stmt = (
            select(Student)
            .options(joinedload(Student.user))
            .where(Student.is_active.is_(True))
            .order_by(Student.student_code.asc())
        )
        result = await self._session.execute(stmt)
        students = result.scalars().all()
        return [
            StudentResponse(
                id=s.id,
                user_id=s.user_id,
                full_name=s.user.full_name,
                email=s.user.email,
                document_number=s.user.document_number,
                student_code=s.student_code,
                grade_level_code=s.grade_level_code or "GRADO_11",
                program_name=s.program_name,
                current_semester=s.current_semester,
                enrollment_cohort=s.enrollment_cohort,
                birth_date=s.birth_date,
                guardian_name=s.guardian_name,
                guardian_phone=s.guardian_phone,
                is_active=s.is_active,
            )
            for s in students
        ]

    async def enroll_student_in_course(
        self, payload: EnrollmentCreate
    ) -> EnrollmentResponse:
        student = await self._session.get(Student, payload.student_id)
        if student is None or not student.is_active:
            raise EntityNotFoundError("Student", payload.student_id)

        off_stmt = (
            select(CourseOffering)
            .options(
                joinedload(CourseOffering.subject),
                joinedload(CourseOffering.academic_period),
                selectinload(CourseOffering.enrollments),
            )
            .where(
                CourseOffering.id == payload.course_offering_id,
                CourseOffering.is_active.is_(True),
            )
        )
        offering = (await self._session.execute(off_stmt)).scalars().unique().first()
        if offering is None:
            raise EntityNotFoundError("CourseOffering", payload.course_offering_id)

        active_enrolled_count = sum(
            1
            for e in offering.enrollments
            if e.is_active and e.status == EnrollmentStatus.ACTIVE
        )
        if active_enrolled_count >= offering.max_capacity:
            raise BusinessRuleViolationError(
                message=(
                    f"El salón '{offering.subject.name}' ({offering.group_code}) "
                    f"ha alcanzado su capacidad máxima ({offering.max_capacity} cupos)."
                ),
                rule_code="COURSE_OFFERING_FULL",
            )

        stu_enrollments_stmt = (
            select(Enrollment)
            .join(CourseOffering, Enrollment.course_offering_id == CourseOffering.id)
            .options(
                joinedload(Enrollment.course_offering).joinedload(CourseOffering.subject)
            )
            .where(
                Enrollment.student_id == student.id,
                Enrollment.is_active.is_(True),
                Enrollment.status == EnrollmentStatus.ACTIVE,
                CourseOffering.academic_period_id == offering.academic_period_id,
            )
        )
        student_active_enrollments = (
            (await self._session.execute(stu_enrollments_stmt)).scalars().all()
        )
        for existing_enr in student_active_enrollments:
            if existing_enr.course_offering_id == offering.id:
                raise BusinessRuleViolationError(
                    message="El estudiante ya se encuentra matriculado en este curso/salón.",
                    rule_code="DUPLICATE_ENROLLMENT",
                )
            if existing_enr.course_offering.subject_id == offering.subject_id:
                raise BusinessRuleViolationError(
                    message=(
                        f"El estudiante ya tiene matriculada la asignatura "
                        f"'{offering.subject.name}' en otro grupo del año lectivo actual."
                    ),
                    rule_code="SUBJECT_ALREADY_ENROLLED_IN_PERIOD",
                )
            conflict = self._detect_schedule_conflict(
                offering.schedule_blocks,
                existing_enr.course_offering.schedule_blocks,
            )
            if conflict is not None:
                raise BusinessRuleViolationError(
                    message=(
                        f"Cruce de horario estudiantil con '{existing_enr.course_offering.subject.name}' "
                        f"el día {conflict['day']} ({conflict['start_time']} - {conflict['end_time']})."
                    ),
                    rule_code="STUDENT_SCHEDULE_CONFLICT",
                    details=conflict,
                )

        enrollment = Enrollment(
            student_id=student.id,
            course_offering_id=offering.id,
            status=EnrollmentStatus.ACTIVE,
        )
        self._session.add(enrollment)
        await self._session.commit()
        await self._session.refresh(enrollment)
        return EnrollmentResponse.model_validate(enrollment)

    async def register_attendance_and_build_ai_context(
        self,
        payload: AttendanceCreateRequest,
    ) -> tuple[AttendanceRegistrationResponse, StudentAcademicContextDTO | None]:
        """
        Registra o actualiza la asistencia de un alumno en una fecha de sesión.
        Si se registra inasistencia (`ABSENT`) o retardo (`LATE`), construye el
        `StudentAcademicContextDTO` para que `BackgroundTasks` actualice el diagnóstico IA.
        """
        enrollment = await self._grades_repo.get_enrollment_with_full_academic_context(
            payload.enrollment_id
        )
        if enrollment is None:
            raise EntityNotFoundError("Enrollment", payload.enrollment_id)

        if enrollment.status != EnrollmentStatus.ACTIVE:
            raise BusinessRuleViolationError(
                message="Solo se puede registrar asistencia en matrículas ACTIVAS.",
                rule_code="ENROLLMENT_NOT_ACTIVE",
            )

        existing_att = next(
            (
                a
                for a in enrollment.attendances
                if a.is_active and a.session_date == payload.session_date
            ),
            None,
        )
        if existing_att is not None:
            existing_att.status = payload.status
            existing_att.syllabus_topic_id = payload.syllabus_topic_id
            existing_att.observations = payload.observations
            attendance = existing_att
        else:
            attendance = Attendance(
                enrollment_id=enrollment.id,
                syllabus_topic_id=payload.syllabus_topic_id,
                session_date=payload.session_date,
                status=payload.status,
                observations=payload.observations,
            )
            self._session.add(attendance)

        await self._session.commit()
        await self._session.refresh(attendance)

        active_attendances = [a for a in enrollment.attendances if a.is_active]
        if all(a.id != attendance.id for a in active_attendances):
            active_attendances.append(attendance)

        att_summary = GradesService._calculate_attendance_summary(
            attendances=active_attendances,
            total_planned_sessions=enrollment.course_offering.total_planned_sessions,
        )

        should_trigger_ai = payload.status in (
            AttendanceStatus.ABSENT,
            AttendanceStatus.LATE,
        ) or att_summary.is_at_attendance_risk

        ai_context: StudentAcademicContextDTO | None = None
        if should_trigger_ai:
            active_grades = [g for g in enrollment.grades if g.is_active]
            grade_metrics = GradesService._calculate_weighted_metrics(active_grades)
            weak_topics: list[str] = []
            grades_breakdown: list[dict[str, str | float | int]] = []
            for g in active_grades:
                topic_title = g.syllabus_topic.title if g.syllabus_topic else "General"
                grades_breakdown.append(
                    {
                        "corte": g.evaluation_cut,
                        "evaluacion": g.evaluation_name,
                        "peso_porcentual": float(g.weight_percentage),
                        "nota": float(g.score),
                        "tema_silabo": topic_title,
                    }
                )
                if Decimal(str(g.score)) < MIN_PASSING and g.syllabus_topic is not None:
                    if g.syllabus_topic.title not in weak_topics:
                        weak_topics.append(g.syllabus_topic.title)

            last_grade_id = active_grades[-1].id if active_grades else None
            ai_context = StudentAcademicContextDTO(
                enrollment_id=enrollment.id,
                triggered_by_grade_id=last_grade_id,
                student_full_name=enrollment.student.user.full_name,
                student_code=enrollment.student.student_code,
                current_semester=enrollment.student.current_semester,
                subject_code=enrollment.course_offering.subject.code,
                subject_name=enrollment.course_offering.subject.name,
                academic_period_code=enrollment.course_offering.academic_period.code,
                accumulated_weighted_average=grade_metrics["current_weighted_average"],
                evaluated_weight_percentage=grade_metrics["evaluated_weight_percentage"],
                remaining_weight_percentage=grade_metrics["remaining_weight_percentage"],
                minimum_score_needed_to_pass=grade_metrics[
                    "minimum_score_needed_in_remaining"
                ],
                total_sessions_recorded=att_summary.total_recorded_sessions,
                absent_sessions_count=att_summary.unexcused_absent_count,
                absence_percentage=att_summary.absence_percentage,
                max_absence_allowed_percentage=Decimal(
                    str(settings.MAX_ABSENCE_PERCENTAGE_ALLOWED)
                ).quantize(TWO_PLACES),
                grades_breakdown=grades_breakdown,
                weak_syllabus_topics=weak_topics,
            )

        response_dto = AttendanceRegistrationResponse(
            id=attendance.id,
            enrollment_id=enrollment.id,
            session_date=attendance.session_date,
            status=attendance.status,
            observations=attendance.observations,
            unexcused_absent_count=att_summary.unexcused_absent_count,
            absence_percentage=att_summary.absence_percentage,
            max_absence_allowed_percentage=Decimal(
                str(settings.MAX_ABSENCE_PERCENTAGE_ALLOWED)
            ).quantize(TWO_PLACES),
            ai_risk_evaluation_triggered=should_trigger_ai,
            created_at=attendance.created_at,
        )
        return response_dto, ai_context

    async def register_bulk_attendance_session(
        self, payload: BulkAttendanceCreateRequest
    ) -> tuple[list[AttendanceRegistrationResponse], list[StudentAcademicContextDTO]]:
        """
        Registra la planilla de llamado a lista de todo un salón para una fecha de sesión
        y recopila los contextos de IA para todos los alumnos con falla o retardo.
        """
        results: list[AttendanceRegistrationResponse] = []
        ai_contexts: list[StudentAcademicContextDTO] = []

        for item in payload.records:
            res_dto, ctx_dto = await self.register_attendance_and_build_ai_context(
                AttendanceCreateRequest(
                    enrollment_id=item.enrollment_id,
                    syllabus_topic_id=payload.syllabus_topic_id,
                    session_date=payload.session_date,
                    status=item.status,
                    observations=item.observations,
                )
            )
            results.append(res_dto)
            if ctx_dto is not None:
                ai_contexts.append(ctx_dto)

        return results, ai_contexts

    @staticmethod
    def _detect_schedule_conflict(
        blocks_a: list[dict[str, Any]],
        blocks_b: list[dict[str, Any]],
    ) -> dict[str, str] | None:
        day_aliases = {
            "LUNES": "MONDAY",
            "MARTES": "TUESDAY",
            "MIERCOLES": "WEDNESDAY",
            "MIÉRCOLES": "WEDNESDAY",
            "JUEVES": "THURSDAY",
            "VIERNES": "FRIDAY",
            "SABADO": "SATURDAY",
            "SÁBADO": "SATURDAY",
        }
        for a in blocks_a:
            for b in blocks_b:
                day_a = day_aliases.get(str(a.get("day", "")).upper(), str(a.get("day", "")).upper())
                day_b = day_aliases.get(str(b.get("day", "")).upper(), str(b.get("day", "")).upper())
                if day_a == day_b:
                    start_a = str(a.get("start_time", "00:00"))
                    end_a = str(a.get("end_time", "00:00"))
                    start_b = str(b.get("start_time", "00:00"))
                    end_b = str(b.get("end_time", "00:00"))
                    if start_a < end_b and start_b < end_a:
                        return {
                            "day": str(a.get("day")),
                            "start_time": max(start_a, start_b),
                            "end_time": min(end_a, end_b),
                        }
        return None
