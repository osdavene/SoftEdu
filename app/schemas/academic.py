"""Esquemas Pydantic v2 (DTOs) para Matrículas, Calificaciones Ponderadas y Boletines."""

from datetime import datetime
from decimal import Decimal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.models.academic import EnrollmentStatus
from app.schemas.ai_schemas import StudentAIInsightResponse


# =====================================================================
# DTOS DE MATRÍCULA (ENROLLMENT)
# =====================================================================
class EnrollmentCreate(BaseModel):
    """DTO de entrada para matricular a un estudiante en una oferta de curso."""

    model_config = ConfigDict(extra="forbid")

    student_id: uuid.UUID = Field(..., description="UUID de la ficha del estudiante.")
    course_offering_id: uuid.UUID = Field(
        ..., description="UUID del grupo/oferta de curso en el período activo."
    )


class EnrollmentResponse(BaseModel):
    """DTO de salida para información de matrícula."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    course_offering_id: uuid.UUID
    status: EnrollmentStatus
    enrolled_at: datetime
    is_active: bool


# =====================================================================
# DTOS DE CALIFICACIONES PONDERADAS (GRADES)
# =====================================================================
class GradeCreate(BaseModel):
    """
    DTO de entrada para registrar una calificación parcial o final.
    Aplica validaciones estrictas de escala (0.0 a 5.0) y peso porcentual (0.01 a 100.0).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    enrollment_id: uuid.UUID = Field(
        ..., description="UUID de la matrícula activa del estudiante."
    )
    syllabus_topic_id: uuid.UUID | None = Field(
        default=None,
        description="UUID opcional del tema del sílabo evaluado para trazabilidad RAG/IA.",
    )
    evaluation_cut: int = Field(
        ...,
        ge=1,
        le=10,
        description="Número del corte académico (ej. 1, 2, 3).",
    )
    evaluation_name: str = Field(
        ...,
        min_length=3,
        max_length=150,
        description="Nombre descriptivo de la evaluación (ej. 'Parcial 1 - Estructuras Lineales').",
    )
    weight_percentage: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        le=Decimal("100.00"),
        decimal_places=2,
        description="Peso porcentual de la actividad en la nota definitiva (ej. 30.00).",
    )
    score: Decimal = Field(
        ...,
        ge=Decimal(str(settings.MIN_GRADE_SCALE)),
        le=Decimal(str(settings.MAX_GRADE_SCALE)),
        decimal_places=2,
        description="Calificación obtenida en escala de 0.00 a 5.00 (aprobatoria >= 3.00).",
    )
    teacher_observations: str | None = Field(
        default=None,
        max_length=1000,
        description="Observaciones cualitativas del docente sobre el desempeño del alumno.",
    )

    @field_validator("evaluation_name")
    @classmethod
    def validate_evaluation_name(cls, value: str) -> str:
        if not value or len(value.strip()) < 3:
            raise ValueError("El nombre de la evaluación debe tener al menos 3 caracteres.")
        return value.strip()


class GradeResponse(BaseModel):
    """DTO de salida de una calificación individual con su aporte ponderado."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    enrollment_id: uuid.UUID
    syllabus_topic_id: uuid.UUID | None
    syllabus_topic_title: str | None = None
    evaluation_cut: int
    evaluation_name: str
    weight_percentage: Decimal
    score: Decimal
    weighted_contribution: Decimal = Field(
        ...,
        description="Puntos netos aportados a la definitiva: (score * weight_percentage) / 100",
    )
    is_passing_score: bool = Field(
        ..., description="True si la nota individual es >= 3.00"
    )
    teacher_observations: str | None
    created_at: datetime


class GradeRegistrationResultResponse(BaseModel):
    """Respuesta enriquecida al registrar una nota y encolar el análisis de IA."""

    grade: GradeResponse
    accumulated_weighted_average: Decimal
    evaluated_weight_percentage: Decimal
    remaining_weight_percentage: Decimal
    ai_evaluation_status: str = Field(
        default="QUEUED_IN_BACKGROUND",
        description="Estado del diagnóstico de IA disparado mediante BackgroundTasks.",
    )


# =====================================================================
# DTOS DE RESUMEN DE ASISTENCIA Y BOLETÍN INTEGRAL (REPORT CARD)
# =====================================================================
class AttendanceSummarySchema(BaseModel):
    """Resumen cuantitativo de asistencia e inasistencias de la matrícula."""

    total_planned_sessions: int
    total_recorded_sessions: int
    present_count: int
    late_count: int
    excused_count: int
    unexcused_absent_count: int
    attendance_percentage: Decimal = Field(
        ..., description="Porcentaje efectivo de asistencia (0.00 a 100.00)."
    )
    absence_percentage: Decimal = Field(
        ..., description="Porcentaje de inasistencias sobre las sesiones impartidas/planeadas."
    )
    is_at_attendance_risk: bool = Field(
        ..., description="True si el porcentaje de fallas se acerca o supera el límite permitido."
    )


class StudentReportCardResponse(BaseModel):
    """
    Boletín académico integral del alumno para una asignatura matriculada,
    combinando notas ponderadas, métricas de asistencia y el último diagnóstico del Copiloto IA.
    """

    enrollment_id: uuid.UUID
    enrollment_status: EnrollmentStatus
    student_id: uuid.UUID
    student_code: str
    student_full_name: str
    subject_code: str
    subject_name: str
    academic_period_code: str
    group_code: str

    # Métricas de Calificaciones Ponderadas (Escala 0.00 - 5.00, mínima aprobatoria 3.00)
    evaluated_weight_percentage: Decimal = Field(
        ..., description="Porcentaje total del curso ya calificado (0.00 a 100.00)."
    )
    remaining_weight_percentage: Decimal = Field(
        ..., description="Porcentaje pendiente por evaluar."
    )
    current_weighted_average: Decimal = Field(
        ...,
        description="Promedio ponderado relativo sobre el porcentaje evaluado hasta la fecha.",
    )
    accumulated_absolute_grade: Decimal = Field(
        ...,
        description="Nota acumulada neta sobre el 100% total de la asignatura.",
    )
    minimum_score_needed_in_remaining: Decimal = Field(
        ...,
        description="Nota promedio mínima requerida en el % restante para lograr 3.00 definitivo.",
    )
    is_currently_passing: bool = Field(
        ..., description="True si el promedio ponderado actual es >= 3.00."
    )

    # Desglose de evaluaciones y asistencia
    grades: list[GradeResponse]
    attendance_summary: AttendanceSummarySchema

    # Diagnóstico vigente del Copiloto de IA (Alerta Temprana)
    current_ai_insight: StudentAIInsightResponse | None = Field(
        default=None,
        description="Última recomendación estructurada generada por el motor de IA.",
    )
