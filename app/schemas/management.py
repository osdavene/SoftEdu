"""
Esquemas Pydantic v2 para Autenticación JWT, Docentes, Horarios, Alumnos,
Matrículas y Control de Asistencia (Fase 3).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.academic import AttendanceStatus, UserRole


# =====================================================================
# 1. DTOS DE AUTENTICACIÓN JWT E IDENTIDAD (RBAC)
# =====================================================================
class LoginRequest(BaseModel):
    """Credenciales de acceso para obtener un token Bearer JWT."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr = Field(..., description="Correo institucional del usuario.")
    password: str = Field(..., min_length=4, max_length=128)


class UserProfileResponse(BaseModel):
    """Información pública del usuario autenticado y sus identificadores de perfil."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    document_number: str
    role: UserRole
    teacher_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    is_active: bool


class TokenResponse(BaseModel):
    """Respuesta estándar OAuth2/JWT con token de acceso y perfil del usuario."""

    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserProfileResponse


# =====================================================================
# 2. DTOS DE DOCENTES, MATERIAS, PERÍODOS Y HORARIOS (COURSE OFFERING)
# =====================================================================
class ScheduleBlockSchema(BaseModel):
    """Bloque horario estructurado con validación de rango de horas (`HH:MM`)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    day: Literal[
        "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"
    ] = Field(..., description="Día de la semana del bloque de clase.")
    start_time: str = Field(
        ...,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="Hora de inicio en formato 24h (ej. '08:00').",
    )
    end_time: str = Field(
        ...,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="Hora de finalización en formato 24h (ej. '10:00').",
    )
    classroom: str = Field(
        ..., min_length=2, max_length=60, description="Aula o laboratorio asignado (ej. 'B-204')."
    )

    @model_validator(mode="after")
    def validate_time_interval(self) -> "ScheduleBlockSchema":
        if self.end_time <= self.start_time:
            raise ValueError(
                f"La hora de fin ({self.end_time}) debe ser posterior a la hora de inicio ({self.start_time})."
            )
        return self


class TeacherCreateRequest(BaseModel):
    """DTO para dar de alta un Docente junto con su cuenta de usuario RBAC."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(default="Docente2026*", min_length=6)
    first_name: str = Field(..., min_length=2, max_length=100)
    last_name: str = Field(..., min_length=2, max_length=100)
    document_number: str = Field(..., min_length=5, max_length=40)
    employee_code: str = Field(..., min_length=3, max_length=30)
    department: str = Field(..., min_length=3, max_length=120)
    specialization: str = Field(..., min_length=3, max_length=150)
    academic_degree: str = Field(..., min_length=3, max_length=100)
    max_weekly_hours: int = Field(default=40, ge=4, le=48)


class TeacherResponse(BaseModel):
    """DTO de salida con la ficha completa del docente."""

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    document_number: str
    employee_code: str
    department: str
    specialization: str
    academic_degree: str
    max_weekly_hours: int
    is_active: bool


class SubjectCreateRequest(BaseModel):
    """DTO para registrar una nueva asignatura en el catálogo curricular."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(..., min_length=3, max_length=25)
    name: str = Field(..., min_length=3, max_length=180)
    description: str | None = Field(default=None, max_length=1500)
    credits: int = Field(..., ge=1, le=20)
    weekly_hours: int = Field(..., ge=1, le=30)
    minimum_passing_grade: Decimal = Field(default=Decimal("3.00"), ge=Decimal("0.00"), le=Decimal("5.00"))


class SubjectResponse(BaseModel):
    """DTO de salida de una asignatura."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    credits: int
    weekly_hours: int
    minimum_passing_grade: Decimal
    is_active: bool


class AcademicPeriodCreateRequest(BaseModel):
    """DTO para crear un período lectivo académico."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(..., min_length=4, max_length=20, description="Ej. '2026-2'")
    name: str = Field(..., min_length=5, max_length=120)
    start_date: date
    end_date: date
    is_current: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> "AcademicPeriodCreateRequest":
        if self.end_date <= self.start_date:
            raise ValueError("La fecha de fin del período debe ser posterior a la fecha de inicio.")
        return self


class AcademicPeriodResponse(BaseModel):
    """DTO de salida de un período lectivo."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    start_date: date
    end_date: date
    is_current: bool
    is_active: bool


class CourseOfferingCreateRequest(BaseModel):
    """
    DTO para asignar un Docente a una Materia en un Período Lectivo
    definiendo sus bloques horarios (`schedule_blocks`).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_id: uuid.UUID
    teacher_id: uuid.UUID
    academic_period_id: uuid.UUID
    group_code: str = Field(..., min_length=1, max_length=20, description="Ej. 'G01'")
    max_capacity: int = Field(default=35, ge=1, le=200)
    total_planned_sessions: int = Field(default=32, ge=1, le=120)
    schedule_blocks: list[ScheduleBlockSchema] = Field(
        ...,
        min_length=1,
        max_length=7,
        description="Bloques horarios semanales asignados al curso.",
    )


class CourseOfferingResponse(BaseModel):
    """DTO de salida de una oferta de curso con su docente y bloques horarios."""

    id: uuid.UUID
    subject_id: uuid.UUID
    subject_code: str
    subject_name: str
    teacher_id: uuid.UUID
    teacher_full_name: str
    academic_period_id: uuid.UUID
    academic_period_code: str
    group_code: str
    max_capacity: int
    enrolled_count: int
    total_planned_sessions: int
    schedule_blocks: list[ScheduleBlockSchema]


# =====================================================================
# 3. DTOS DE ALUMNOS Y CONTROL DE ASISTENCIA
# =====================================================================
class StudentCreateRequest(BaseModel):
    """DTO para registrar la ficha de un Estudiante junto con su usuario RBAC."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(default="Estudiante2026*", min_length=6)
    first_name: str = Field(..., min_length=2, max_length=100)
    last_name: str = Field(..., min_length=2, max_length=100)
    document_number: str = Field(..., min_length=5, max_length=40)
    student_code: str = Field(..., min_length=3, max_length=30)
    program_name: str = Field(..., min_length=3, max_length=150)
    current_semester: int = Field(default=1, ge=1, le=15)
    enrollment_cohort: str = Field(..., min_length=4, max_length=20, description="Ej. '2026-1'")
    birth_date: date | None = None


class StudentResponse(BaseModel):
    """DTO de salida de la ficha estudiantil."""

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    document_number: str
    student_code: str
    program_name: str
    current_semester: int
    enrollment_cohort: str
    birth_date: date | None
    is_active: bool


class AttendanceCreateRequest(BaseModel):
    """
    DTO para registrar la asistencia o inasistencia de un estudiante en una sesión.
    Si se registra una inasistencia (`ABSENT`), dispara el análisis de riesgo con IA.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enrollment_id: uuid.UUID
    syllabus_topic_id: uuid.UUID | None = None
    session_date: date
    status: AttendanceStatus
    observations: str | None = Field(default=None, max_length=500)


class AttendanceRegistrationResponse(BaseModel):
    """Respuesta al registrar asistencia con métricas acumuladas y alerta de IA."""

    id: uuid.UUID
    enrollment_id: uuid.UUID
    session_date: date
    status: AttendanceStatus
    observations: str | None
    unexcused_absent_count: int
    absence_percentage: Decimal
    max_absence_allowed_percentage: Decimal
    ai_risk_evaluation_triggered: bool = Field(
        ...,
        description="True si se encoló evaluación de IA por inasistencia o umbral de riesgo.",
    )
    created_at: datetime
