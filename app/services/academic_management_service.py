"""
Servicio de Dominio para Autenticación Institucional, Rectoría, Coordinación,
Secretaría, Docentes, Horarios, Alumnos, Matrículas y Planilla de Asistencia (100% Español).
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

ROLE_METADATA_ES: dict[UserRole, dict[str, Any]] = {
    UserRole.RECTOR: {
        "label": "Rectoría General",
        "default_title": "Rector General Institucional",
        "default_area": "Rectoría y Dirección Estratégica",
        "permissions": [
            "Tablero Ejecutivo Institucional e Indicadores Globales",
            "Supervisión de Tasas de Aprobación, Permanencia y Riesgo IA",
            "Auditoría de Planta Docente, Coordinación y Secretaría",
            "Acceso Total a Boletines, Sílabos y Copiloto IA",
        ],
    },
    UserRole.COORDINADOR: {
        "label": "Coordinación Académica",
        "default_title": "Coordinador(a) Académico(a) y Curricular",
        "default_area": "Vicerrectoría / Coordinación Académica",
        "permissions": [
            "Gestión de Períodos Lectivos, Asignaturas y Sílabos Vectorizados",
            "Asignación de Carga Académica y Control de Choques de Horario",
            "Monitoreo de Alertas Tempranas de Riesgo Académico e Inasistencia",
            "Supervisión de Planillas de Notas y Asistente Curricular IA",
        ],
    },
    UserRole.SECRETARIA: {
        "label": "Secretaría Académica y Admisiones",
        "default_title": "Secretario(a) General y de Matrículas",
        "default_area": "Registro, Control y Admisiones",
        "permissions": [
            "Inscripción y Ficha Oficial de Estudiantes y Acudientes",
            "Vinculación Administrativa de Planta Docente",
            "Formalización de Matrículas por Período y Control de Cupos",
            "Expedición de Boletines Académicos y Certificados",
        ],
    },
    UserRole.ORIENTADOR: {
        "label": "Psicoorientación y Bienestar",
        "default_title": "Psicoorientador(a) y Permanencia Estudiantil",
        "default_area": "Bienestar Institucional y Psicología",
        "permissions": [
            "Seguimiento de Casos en Riesgo Alto y Crítico (Copiloto IA)",
            "Control de Alertas por Inasistencia y Contacto a Acudientes",
            "Diseño de Planes de Intervención Psicopedagógica",
            "Consulta de Boletines e Historial de Asistencia",
        ],
    },
    UserRole.DOCENTE: {
        "label": "Docente Titular",
        "default_title": "Docente Titular de Cátedra / Planta",
        "default_area": "Facultad de Ingeniería y Ciencias Aplicadas",
        "permissions": [
            "Llamado a Lista y Toma de Asistencia Masiva / Individual por Sesión",
            "Registro de Calificaciones Ponderadas por Cortes (Escala 0.0 a 5.0)",
            "Asistente Curricular IA (Planeación de Clase, Rúbricas y Exámenes Test)",
            "Consulta de Diagnósticos IA y Planes de Acción de sus Estudiantes",
        ],
    },
    UserRole.TEACHER: {
        "label": "Docente Titular",
        "default_title": "Docente Titular de Cátedra / Planta",
        "default_area": "Facultad de Ingeniería y Ciencias Aplicadas",
        "permissions": [
            "Llamado a Lista y Toma de Asistencia por Sesión",
            "Registro de Calificaciones Ponderadas por Cortes",
            "Asistente Curricular IA y Diagnósticos de Riesgo",
        ],
    },
    UserRole.ESTUDIANTE: {
        "label": "Estudiante Activo",
        "default_title": "Estudiante de Pregrado / Formación",
        "default_area": "Comunidad Estudiantil",
        "permissions": [
            "Consulta de Boletín Académico Ponderado y Simulador de Notas",
            "Revisión de Historial Personal de Asistencia e Inasistencias",
            "Plan de Estudio Personalizado sugerido por el Copiloto IA",
            "Consultorio Académico 24/7 con el Tutor Inteligente RAG (pgvector)",
        ],
    },
    UserRole.STUDENT: {
        "label": "Estudiante Activo",
        "default_title": "Estudiante de Pregrado / Formación",
        "default_area": "Comunidad Estudiantil",
        "permissions": [
            "Consulta de Boletín Académico Personal y Asistencia",
            "Plan de Estudio IA y Tutor Inteligente RAG (pgvector)",
        ],
    },
    UserRole.ADMIN: {
        "label": "Administrador General del Sistema",
        "default_title": "Administrador de Plataforma ERP/LMS",
        "default_area": "Dirección de Tecnología y Sistemas",
        "permissions": [
            "Control Total de Usuarios, Roles RBAC y Parámetros del Sistema",
            "Gestión Académica, Curricular, Matrículas, Notas y Motores IA",
        ],
    },
}

ATTENDANCE_LABELS_ES: dict[AttendanceStatus, str] = {
    AttendanceStatus.PRESENT: "Presente (Asistió)",
    AttendanceStatus.ABSENT: "Inasistencia (Falla Injustificada)",
    AttendanceStatus.LATE: "Llegada Tarde (Retardo)",
    AttendanceStatus.EXCUSED: "Excusa Médica / Justificada",
}


class AcademicManagementService:
    """
    Orquesta la lógica de negocio de todos los roles y módulos institucionales.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._grades_repo = GradesRepository(session)

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
                message="Correo institucional o contraseña incorrectos."
            )

        access_token = create_access_token(user_id=user.id, role=user.role)
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
            user=self.map_user_to_profile_dto(user),
        )

    @staticmethod
    def map_user_to_profile_dto(user: User) -> UserProfileResponse:
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
            current_semester=(
                user.student_profile.current_semester if user.student_profile else None
            ),
            enrollment_id=enrollment_id,
            is_active=user.is_active,
        )

    # =================================================================
    # 2. TABLERO EJECUTIVO INSTITUCIONAL (RECTORÍA / COORDINACIÓN)
    # =================================================================
    async def get_institutional_overview(self) -> InstitutionalOverviewResponse:
        """
        Consolida todas las métricas académicas, de asistencia, distribución de
        riesgo IA, directorio de usuarios y planilla general de matriculados.
        """
        period_stmt = select(AcademicPeriod).where(
            AcademicPeriod.is_active.is_(True),
            AcademicPeriod.is_current.is_(True),
        )
        current_period = (await self._session.execute(period_stmt)).scalars().first()
        period_code = current_period.code if current_period else "2026-2"
        period_name = (
            current_period.name
            if current_period
            else "Segundo Período Académico 2026"
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
        # Ordenar por código de estudiante
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

        # Directorio institucional completo
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
        directory = [self.map_user_to_profile_dto(u) for u in all_users]

        return InstitutionalOverviewResponse(
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
            recent_attendances=all_attendance_logs[:35],
            institutional_directory=directory,
        )

    # =================================================================
    # 3. DOCENTES, MATERIAS, PERÍODOS Y OFERTAS CON HORARIOS
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

        user = User(
            email=payload.email.lower(),
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            document_number=payload.document_number,
            role=UserRole.DOCENTE,
            job_title=f"Docente Titular - {payload.specialization}",
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
                        f"Ya existe el grupo '{payload.group_code}' para la materia "
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
                        f"Choque de horario para el docente {teacher.user.full_name} con la "
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
        return [
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
                max_capacity=off.max_capacity,
                enrolled_count=sum(
                    1
                    for e in off.enrollments
                    if e.is_active and e.status == EnrollmentStatus.ACTIVE
                ),
                total_planned_sessions=off.total_planned_sessions,
                schedule_blocks=[
                    ScheduleBlockSchema.model_validate(b) for b in off.schedule_blocks
                ],
            )
            for off in offerings
        ]

    # =================================================================
    # 4. ALUMNOS, MATRÍCULAS Y PLANILLAS DE ASISTENCIA CON ALERTA IA
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
                message="Ya existe un usuario con el correo o documento especificado.",
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

        user = User(
            email=payload.email.lower(),
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            document_number=payload.document_number,
            role=UserRole.ESTUDIANTE,
            job_title=f"Estudiante - {payload.program_name}",
            department_area=payload.program_name,
        )
        self._session.add(user)
        await self._session.flush()

        student = Student(
            user_id=user.id,
            student_code=payload.student_code,
            program_name=payload.program_name,
            current_semester=payload.current_semester,
            enrollment_cohort=payload.enrollment_cohort,
            birth_date=payload.birth_date,
            guardian_name=payload.guardian_name,
            guardian_phone=payload.guardian_phone,
        )
        self._session.add(student)
        await self._session.flush()

        # Matricular automáticamente en el curso principal activo si existe para agilizar demostraciones
        default_off = (
            await self._session.execute(
                select(CourseOffering).where(CourseOffering.is_active.is_(True)).limit(1)
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
                    f"El curso '{offering.subject.name}' ({offering.group_code}) "
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
                    message="El estudiante ya se encuentra matriculado en este grupo.",
                    rule_code="DUPLICATE_ENROLLMENT",
                )
            if existing_enr.course_offering.subject_id == offering.subject_id:
                raise BusinessRuleViolationError(
                    message=(
                        f"El estudiante ya tiene matriculada la asignatura "
                        f"'{offering.subject.name}' en otro grupo del período actual."
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
        Registra la planilla de llamado a lista de todo un curso para una fecha de sesión
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
