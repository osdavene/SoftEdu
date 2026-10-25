"""
Capa de Servicio de Dominio para Calificaciones Ponderadas, Asistencia y Boletines.

Orquesta las reglas de negocio académicas, garantiza la atomicidad transaccional
del registro de notas y construye el contexto analítico para el Copiloto de IA.
"""

from decimal import Decimal, ROUND_HALF_UP
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessRuleViolationError, EntityNotFoundError
from app.models.academic import (
    Attendance,
    AttendanceStatus,
    Enrollment,
    EnrollmentStatus,
    Grade,
    SyllabusTopic,
)
from app.repositories.grades_repository import GradesRepository
from app.schemas.academic import (
    AttendanceSummarySchema,
    GradeCreate,
    GradeRegistrationResultResponse,
    GradeResponse,
    StudentReportCardResponse,
)
from app.schemas.ai_schemas import (
    StudentAcademicContextDTO,
    StudentAIInsightResponse,
    SuggestedActionPlanSchema,
)

TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal("100.00")
MIN_PASSING = Decimal(str(settings.MIN_PASSING_GRADE)).quantize(TWO_PLACES)


class GradesService:
    """Servicio de aplicación para gestión de calificaciones y generación de boletines."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = GradesRepository(session)

    async def register_grade_and_build_ai_context(
        self,
        payload: GradeCreate,
        recorded_by_user_id: uuid.UUID | None = None,
    ) -> tuple[GradeRegistrationResultResponse, StudentAcademicContextDTO]:
        """
        Registra una calificación aplicando todas las reglas de negocio académicas:
        1. Verifica existencia y estado ACTIVO de la matrícula.
        2. Valida pertenencia del `syllabus_topic_id` (si se envía) a la materia.
        3. Verifica que no exista duplicidad de evaluación en el mismo corte.
        4. Verifica que la suma de pesos porcentuales no supere el 100.00%.
        5. Persiste y confirma (`commit`) la calificación.
        6. Construye el `StudentAcademicContextDTO` para la tarea de IA en segundo plano.
        """
        enrollment = await self._repo.get_enrollment_with_full_academic_context(
            payload.enrollment_id
        )
        if enrollment is None:
            raise EntityNotFoundError("Enrollment", payload.enrollment_id)

        if enrollment.status != EnrollmentStatus.ACTIVE:
            raise BusinessRuleViolationError(
                message=(
                    f"No es posible registrar notas: la matrícula se encuentra en estado "
                    f"'{enrollment.status.value}' (se requiere '{EnrollmentStatus.ACTIVE.value}')."
                ),
                rule_code="ENROLLMENT_NOT_ACTIVE",
                details={"current_status": enrollment.status.value},
            )

        subject = enrollment.course_offering.subject
        matched_topic: SyllabusTopic | None = None
        if payload.syllabus_topic_id is not None:
            matched_topic = await self._repo.get_syllabus_topic_for_subject(
                topic_id=payload.syllabus_topic_id,
                subject_id=subject.id,
            )
            if matched_topic is None:
                raise BusinessRuleViolationError(
                    message=(
                        "El tema del sílabo especificado no existe o no pertenece "
                        f"a la asignatura '{subject.name}' ({subject.code})."
                    ),
                    rule_code="INVALID_SYLLABUS_TOPIC_FOR_SUBJECT",
                )

        is_duplicate = await self._repo.exists_evaluation_in_cut(
            enrollment_id=enrollment.id,
            evaluation_cut=payload.evaluation_cut,
            evaluation_name=payload.evaluation_name,
        )
        if is_duplicate:
            raise BusinessRuleViolationError(
                message=(
                    f"Ya existe una calificación registrada como '{payload.evaluation_name}' "
                    f"en el corte {payload.evaluation_cut} para este estudiante."
                ),
                rule_code="DUPLICATE_EVALUATION_IN_CUT",
            )

        current_total_weight = await self._repo.get_accumulated_weight_percentage(
            enrollment.id
        )
        projected_total_weight = (current_total_weight + payload.weight_percentage).quantize(
            TWO_PLACES
        )
        if projected_total_weight > HUNDRED:
            available_weight = (HUNDRED - current_total_weight).quantize(TWO_PLACES)
            raise BusinessRuleViolationError(
                message=(
                    f"El peso porcentual ({payload.weight_percentage}%) excede el 100% permitido. "
                    f"Porcentaje acumulado actual: {current_total_weight}%, "
                    f"disponible: {available_weight}%."
                ),
                rule_code="WEIGHT_PERCENTAGE_OVERFLOW",
                details={
                    "current_evaluated_percentage": float(current_total_weight),
                    "attempted_percentage": float(payload.weight_percentage),
                    "available_percentage": float(available_weight),
                },
            )

        # Creación y persistencia transaccional de la nota
        new_grade = Grade(
            enrollment_id=enrollment.id,
            syllabus_topic_id=payload.syllabus_topic_id,
            evaluation_cut=payload.evaluation_cut,
            evaluation_name=payload.evaluation_name,
            weight_percentage=payload.weight_percentage,
            score=payload.score,
            teacher_observations=payload.teacher_observations,
            recorded_by_user_id=recorded_by_user_id,
        )
        created_grade = await self._repo.create_grade(new_grade)
        if matched_topic is not None:
            created_grade.syllabus_topic = matched_topic

        # Confirmamos la transacción principal antes de encolar el análisis de IA
        await self._session.commit()

        # Recargamos la lista completa de notas activas incluyendo la recién creada
        active_grades = [g for g in enrollment.grades if g.is_active]
        if all(g.id != created_grade.id for g in active_grades):
            active_grades.append(created_grade)

        grade_metrics = self._calculate_weighted_metrics(active_grades)
        attendance_summary = self._calculate_attendance_summary(
            attendances=[a for a in enrollment.attendances if a.is_active],
            total_planned_sessions=enrollment.course_offering.total_planned_sessions,
        )

        # Identificar temas del sílabo con nota reprobatoria (< 3.00)
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

        ai_context = StudentAcademicContextDTO(
            enrollment_id=enrollment.id,
            triggered_by_grade_id=created_grade.id,
            student_full_name=enrollment.student.user.full_name,
            student_code=enrollment.student.student_code,
            current_semester=enrollment.student.current_semester,
            subject_code=subject.code,
            subject_name=subject.name,
            academic_period_code=enrollment.course_offering.academic_period.code,
            accumulated_weighted_average=grade_metrics["current_weighted_average"],
            evaluated_weight_percentage=grade_metrics["evaluated_weight_percentage"],
            remaining_weight_percentage=grade_metrics["remaining_weight_percentage"],
            minimum_score_needed_to_pass=grade_metrics["minimum_score_needed_in_remaining"],
            total_sessions_recorded=attendance_summary.total_recorded_sessions,
            absent_sessions_count=attendance_summary.unexcused_absent_count,
            absence_percentage=attendance_summary.absence_percentage,
            max_absence_allowed_percentage=Decimal(
                str(settings.MAX_ABSENCE_PERCENTAGE_ALLOWED)
            ).quantize(TWO_PLACES),
            grades_breakdown=grades_breakdown,
            weak_syllabus_topics=weak_topics,
        )

        grade_response = self._map_grade_to_dto(created_grade)
        result_response = GradeRegistrationResultResponse(
            grade=grade_response,
            accumulated_weighted_average=grade_metrics["current_weighted_average"],
            evaluated_weight_percentage=grade_metrics["evaluated_weight_percentage"],
            remaining_weight_percentage=grade_metrics["remaining_weight_percentage"],
            ai_evaluation_status="QUEUED_IN_BACKGROUND",
        )
        return result_response, ai_context

    async def get_student_report_card(
        self, enrollment_id: uuid.UUID
    ) -> StudentReportCardResponse:
        """
        Genera el boletín académico consolidado de un estudiante junto con la
        recomendación estructurada vigente de la IA (`StudentAIInsight`).
        """
        enrollment = await self._repo.get_enrollment_with_full_academic_context(
            enrollment_id
        )
        if enrollment is None:
            raise EntityNotFoundError("Enrollment", enrollment_id)

        active_grades = [g for g in enrollment.grades if g.is_active]
        grade_metrics = self._calculate_weighted_metrics(active_grades)
        attendance_summary = self._calculate_attendance_summary(
            attendances=[a for a in enrollment.attendances if a.is_active],
            total_planned_sessions=enrollment.course_offering.total_planned_sessions,
        )

        current_insight_dto = self._extract_current_ai_insight(enrollment)

        return StudentReportCardResponse(
            enrollment_id=enrollment.id,
            enrollment_status=enrollment.status,
            student_id=enrollment.student.id,
            student_code=enrollment.student.student_code,
            student_full_name=enrollment.student.user.full_name,
            subject_code=enrollment.course_offering.subject.code,
            subject_name=enrollment.course_offering.subject.name,
            academic_period_code=enrollment.course_offering.academic_period.code,
            group_code=enrollment.course_offering.group_code,
            evaluated_weight_percentage=grade_metrics["evaluated_weight_percentage"],
            remaining_weight_percentage=grade_metrics["remaining_weight_percentage"],
            current_weighted_average=grade_metrics["current_weighted_average"],
            accumulated_absolute_grade=grade_metrics["accumulated_absolute_grade"],
            minimum_score_needed_in_remaining=grade_metrics[
                "minimum_score_needed_in_remaining"
            ],
            is_currently_passing=(
                grade_metrics["current_weighted_average"] >= MIN_PASSING
            ),
            grades=[self._map_grade_to_dto(g) for g in active_grades],
            attendance_summary=attendance_summary,
            current_ai_insight=current_insight_dto,
        )

    @staticmethod
    def _calculate_weighted_metrics(grades: list[Grade]) -> dict[str, Decimal]:
        """
        Calcula con precisión decimal financiera/académica:
        - Porcentaje total evaluado y restante.
        - Nota absoluta acumulada (aportes sobre el 100%).
        - Promedio ponderado relativo sobre lo evaluado hasta el momento.
        - Nota mínima necesaria en el porcentaje restante para llegar a 3.00.
        """
        if not grades:
            return {
                "evaluated_weight_percentage": Decimal("0.00"),
                "remaining_weight_percentage": HUNDRED,
                "accumulated_absolute_grade": Decimal("0.00"),
                "current_weighted_average": Decimal("0.00"),
                "minimum_score_needed_in_remaining": MIN_PASSING,
            }

        evaluated_weight = sum(
            (Decimal(str(g.weight_percentage)) for g in grades), Decimal("0.00")
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        remaining_weight = max(Decimal("0.00"), HUNDRED - evaluated_weight).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

        # Suma de (nota * peso / 100)
        accumulated_absolute = sum(
            (
                (Decimal(str(g.score)) * Decimal(str(g.weight_percentage))) / HUNDRED
                for g in grades
            ),
            Decimal("0.00"),
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        # Promedio ponderado relativo sobre el porcentaje ya evaluado
        if evaluated_weight > Decimal("0.00"):
            current_weighted_avg = (
                (accumulated_absolute * HUNDRED) / evaluated_weight
            ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            current_weighted_avg = Decimal("0.00")

        # Nota mínima necesaria en el porcentaje restante para obtener 3.00 definitivo
        points_needed = max(Decimal("0.00"), MIN_PASSING - accumulated_absolute)
        if remaining_weight > Decimal("0.00"):
            min_score_remaining = ((points_needed * HUNDRED) / remaining_weight).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
        else:
            min_score_remaining = Decimal("0.00")

        return {
            "evaluated_weight_percentage": evaluated_weight,
            "remaining_weight_percentage": remaining_weight,
            "accumulated_absolute_grade": accumulated_absolute,
            "current_weighted_average": current_weighted_avg,
            "minimum_score_needed_in_remaining": min_score_remaining,
        }

    @staticmethod
    def _calculate_attendance_summary(
        attendances: list[Attendance],
        total_planned_sessions: int,
    ) -> AttendanceSummarySchema:
        """Calcula las métricas de asistencia y porcentaje de inasistencias."""
        planned = max(total_planned_sessions, 1)
        recorded = len(attendances)

        present_count = sum(
            1 for a in attendances if a.status == AttendanceStatus.PRESENT
        )
        late_count = sum(1 for a in attendances if a.status == AttendanceStatus.LATE)
        excused_count = sum(
            1 for a in attendances if a.status == AttendanceStatus.EXCUSED
        )
        unexcused_absent_count = sum(
            1 for a in attendances if a.status == AttendanceStatus.ABSENT
        )

        # Porcentaje de inasistencia injustificada sobre el total de sesiones planeadas del curso
        absence_pct = (
            (Decimal(unexcused_absent_count) * HUNDRED) / Decimal(planned)
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        if recorded > 0:
            effective_attended = present_count + late_count + excused_count
            attendance_pct = (
                (Decimal(effective_attended) * HUNDRED) / Decimal(recorded)
            ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            attendance_pct = HUNDRED

        max_allowed = Decimal(str(settings.MAX_ABSENCE_PERCENTAGE_ALLOWED))
        # Alerta temprana si supera el 75% del límite máximo de inasistencias permitido
        is_at_risk = absence_pct >= (max_allowed * Decimal("0.75")).quantize(TWO_PLACES)

        return AttendanceSummarySchema(
            total_planned_sessions=planned,
            total_recorded_sessions=recorded,
            present_count=present_count,
            late_count=late_count,
            excused_count=excused_count,
            unexcused_absent_count=unexcused_absent_count,
            attendance_percentage=attendance_pct,
            absence_percentage=absence_pct,
            is_at_attendance_risk=is_at_risk,
        )

    @staticmethod
    def _map_grade_to_dto(grade: Grade) -> GradeResponse:
        """Transforma una entidad `Grade` en su DTO `GradeResponse`."""
        score_dec = Decimal(str(grade.score)).quantize(TWO_PLACES)
        weight_dec = Decimal(str(grade.weight_percentage)).quantize(TWO_PLACES)
        contribution = ((score_dec * weight_dec) / HUNDRED).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        return GradeResponse(
            id=grade.id,
            enrollment_id=grade.enrollment_id,
            syllabus_topic_id=grade.syllabus_topic_id,
            syllabus_topic_title=(
                grade.syllabus_topic.title if grade.syllabus_topic else None
            ),
            evaluation_cut=grade.evaluation_cut,
            evaluation_name=grade.evaluation_name,
            weight_percentage=weight_dec,
            score=score_dec,
            weighted_contribution=contribution,
            is_passing_score=(score_dec >= MIN_PASSING),
            teacher_observations=grade.teacher_observations,
            created_at=grade.created_at,
        )

    @staticmethod
    def _extract_current_ai_insight(
        enrollment: Enrollment,
    ) -> StudentAIInsightResponse | None:
        """Obtiene el diagnóstico de IA vigente (`is_current_insight=True`) de la matrícula."""
        active_insights = [i for i in enrollment.ai_insights if i.is_active]
        if not active_insights:
            return None

        current = next(
            (i for i in active_insights if i.is_current_insight),
            active_insights[0],
        )
        try:
            action_plan = SuggestedActionPlanSchema.model_validate(
                current.suggested_action_plan
            )
        except Exception:
            raw = current.suggested_action_plan if isinstance(current.suggested_action_plan, dict) else {}
            acciones_doc = raw.get("acciones_docente") or raw.get("plan_docente") or ["Acompañamiento pedagógico."]
            acciones_est = raw.get("acciones_estudiante") or raw.get("plan_estudiante") or ["Refuerzo académico."]
            temas = raw.get("temas_refuerzo_prioritarios") or []
            meta_nota = float(raw.get("meta_nota_restante_sugerida") or 3.0)
            action_plan = SuggestedActionPlanSchema(
                acciones_docente=acciones_doc if isinstance(acciones_doc, list) else [str(acciones_doc)],
                acciones_estudiante=acciones_est if isinstance(acciones_est, list) else [str(acciones_est)],
                temas_refuerzo_prioritarios=temas if isinstance(temas, list) else [],
                meta_nota_restante_sugerida=min(5.0, max(0.0, meta_nota)),
            )
        return StudentAIInsightResponse(
            id=current.id,
            enrollment_id=current.enrollment_id,
            triggered_by_grade_id=current.triggered_by_grade_id,
            risk_level=current.risk_level,
            accumulated_weighted_average=Decimal(
                str(current.accumulated_weighted_average)
            ).quantize(TWO_PLACES),
            evaluated_weight_percentage=Decimal(
                str(current.evaluated_weight_percentage)
            ).quantize(TWO_PLACES),
            absence_percentage=Decimal(str(current.absence_percentage)).quantize(
                TWO_PLACES
            ),
            detected_factors=current.detected_factors,
            suggested_action_plan=action_plan,
            executive_summary=current.executive_summary,
            llm_model_used=current.llm_model_used,
            is_current_insight=current.is_current_insight,
            created_at=current.created_at,
        )
