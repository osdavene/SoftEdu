"""
Servicio de Dominio para Autenticación, Docentes, Horarios, Alumnos,
Matrículas y Registro de Asistencia con Alerta Temprana de IA (Fase 3).
"""

from decimal import Decimal
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
    AttendanceRegistrationResponse,
    CourseOfferingCreateRequest,
    CourseOfferingResponse,
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
MIN_PASSING = Decimal(str(settings.MIN_PASSING_GRADE)).quantize(TWO_PLACES)


class AcademicManagementService:
    """
    Orquesta la lógica de negocio de los módulos Core:
    - Autenticación JWT + Perfiles RBAC
    - Docentes, Materias, Períodos y Control de Cruces de Horario (`schedule_blocks`)
    - Alumnos, Matrículas con validación de cupo/horario y Asistencia con disparo de IA
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._grades_repo = GradesRepository(session)

    # =================================================================
    # 1. AUTENTICACIÓN JWT E IDENTIDAD
    # =================================================================
    async def authenticate_user(self, payload: LoginRequest) -> TokenResponse:
        """Verifica credenciales de correo y contraseña y emite un JWT firmado."""
        stmt = (
            select(User)
            .options(
                joinedload(User.teacher_profile),
                joinedload(User.student_profile),
            )
            .where(
                func.lower(User.email) == payload.email.lower(),
                User.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        user = result.scalars().first()

        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedAccessError(
                message="Correo electrónico o contraseña incorrectos."
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
        return UserProfileResponse(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            full_name=user.full_name,
            document_number=user.document_number,
            role=user.role,
            teacher_id=user.teacher_profile.id if user.teacher_profile else None,
            student_id=user.student_profile.id if user.student_profile else None,
            is_active=user.is_active,
        )

    # =================================================================
    # 2. DOCENTES, MATERIAS, PERÍODOS Y OFERTAS CON HORARIOS
    # =================================================================
    async def create_teacher(self, payload: TeacherCreateRequest) -> TeacherResponse:
        """Crea un usuario con rol `TEACHER` y su ficha profesional `Teacher`."""
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
            role=UserRole.TEACHER,
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
        """
        Asigna un Docente a una Materia en un Período Lectivo validando que:
        1. Materia, Docente y Período existan y estén activos.
        2. No exista cruce de horarios (`schedule_blocks`) con otros cursos del mismo docente.
        """
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

        # Validar choques de bloques horarios del docente en el mismo período lectivo
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
    # 3. ALUMNOS, MATRÍCULAS Y ASISTENCIA CON ALERTA TEMPRANA IA
    # =================================================================
    async def create_student(self, payload: StudentCreateRequest) -> StudentResponse:
        """Crea un usuario con rol `STUDENT` y su ficha estudiantil `Student`."""
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
            role=UserRole.STUDENT,
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
        )
        self._session.add(student)
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
                is_active=s.is_active,
            )
            for s in students
        ]

    async def enroll_student_in_course(
        self, payload: EnrollmentCreate
    ) -> EnrollmentResponse:
        """
        Matricula a un estudiante en una oferta de curso verificando:
        1. Existencia de estudiante y oferta de curso.
        2. Disponibilidad de cupo (`max_capacity`).
        3. Ausencia de matrícula duplicada o cruce de horario en el período.
        """
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

        # Verificar matrículas activas del estudiante en el mismo período
        stu_enrollments_stmt = (
            select(Enrollment)
            .join(CourseOffering, Enrollment.course_offering_id == CourseOffering.id)
            .options(joinedload(Enrollment.course_offering).joinedload(CourseOffering.subject))
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
        Registra la asistencia de un alumno en una fecha de sesión.
        Si se registra inasistencia (`ABSENT`) o retardo (`LATE`), construye el
        `StudentAcademicContextDTO` para que `BackgroundTasks` actualice el
        diagnóstico de riesgo académico del Copiloto de IA.
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

        for existing_att in enrollment.attendances:
            if existing_att.is_active and existing_att.session_date == payload.session_date:
                raise BusinessRuleViolationError(
                    message=(
                        f"Ya existe un registro de asistencia para la fecha "
                        f"'{payload.session_date.isoformat()}' en esta matrícula."
                    ),
                    rule_code="DUPLICATE_ATTENDANCE_SESSION_DATE",
                )

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

        # Disparar evaluación de riesgo con IA cuando ocurre una inasistencia o retardo
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

            last_grade_id = active_grades[-1].id if active_grades else enrollment.id
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

    @staticmethod
    def _detect_schedule_conflict(
        blocks_a: list[dict[str, Any]],
        blocks_b: list[dict[str, Any]],
    ) -> dict[str, str] | None:
        """
        Detecta si dos conjuntos de bloques horarios (`schedule_blocks`) tienen
        intersección temporal el mismo día (`start_a < end_b and start_b < end_a`).
        """
        for a in blocks_a:
            for b in blocks_b:
                if a.get("day") == b.get("day"):
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
