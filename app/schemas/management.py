"""
Esquemas Pydantic v2 para Autenticación JWT, SuperPanel Multi-Colegio (Maternal a Grado 11°),
Calendario Escolar A y B, Gobierno Escolar (SuperAdmin, Rector, Coordinador, Secretaría,
Orientador, Docente, Estudiante), Horarios Semanales, Matrículas y Planillas (100% Español).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.academic import AttendanceStatus, RiskLevel, UserRole


# =====================================================================
# 0. DTOS DE COLEGIOS (MATERNAL A GRADO 11°, CALENDARIO A/B, SUPERPANEL)
# =====================================================================
class SchoolGradeCatalogItem(BaseModel):
    """Definición oficial de un Grado Escolar (desde Maternal hasta Grado 11°)."""

    code: str
    name: str
    short_name: str
    stage: str
    order: int


class SchoolInstitutionResponse(BaseModel):
    """Información completa de un Colegio registrado en el SuperPanel."""

    id: uuid.UUID
    code: str
    name: str
    dane_code: str
    nit: str
    calendar_type: str
    calendar_label_es: str
    shift_type: str
    shift_label_es: str
    city: str
    address: str | None = None
    phone: str | None = None
    email_contact: str | None = None
    resolution_men: str | None = None
    rector_user_id: uuid.UUID | None = None
    rector_full_name: str | None = None
    rector_email: str | None = None
    enabled_grades: list[str]
    enabled_grades_details: list[SchoolGradeCatalogItem] = Field(default_factory=list)
    is_active: bool


class SchoolCreateWithRectorRequest(BaseModel):
    """
    DTO exclusivo de SUPERADMIN para dar de alta un Colegio (Calendario A o B),
    activar los grados que maneja (desde Maternal hasta Grado 11°) y crear/asignar a su Rector(a).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(..., min_length=3, max_length=30, description="Ej. 'COL-SFA-002'")
    name: str = Field(..., min_length=4, max_length=200)
    dane_code: str = Field(..., min_length=5, max_length=35)
    nit: str = Field(..., min_length=5, max_length=35)
    calendar_type: Literal["CALENDARIO_A", "CALENDARIO_B"] = Field(
        default="CALENDARIO_A",
        description="Calendario A (Febrero a Noviembre) o Calendario B (Septiembre a Junio)",
    )
    shift_type: Literal["JORNADA_UNICA", "MANANA", "TARDE", "COMPLETA"] = Field(
        default="JORNADA_UNICA"
    )
    city: str = Field(default="Bogotá D.C.", min_length=2, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    email_contact: str | None = Field(default=None, max_length=150)
    resolution_men: str | None = Field(default=None, max_length=180)
    enabled_grades: list[str] = Field(
        ...,
        min_length=1,
        description="Lista de códigos de grado activos en el colegio (MATERNAL .. GRADO_11)",
    )

    # Datos opcionales para crear y asignar al Rector inmediatamente desde el SuperPanel
    rector_first_name: str | None = Field(default=None, max_length=100)
    rector_last_name: str | None = Field(default=None, max_length=100)
    rector_document_number: str | None = Field(default=None, max_length=40)
    rector_email: EmailStr | None = None
    rector_password: str | None = Field(default="SoftEdu2026*", min_length=6)
    rector_phone: str | None = Field(default=None, max_length=40)


class SchoolUpdateGradesRequest(BaseModel):
    """DTO para activar o desactivar grados escolares (Maternal a 11°) en un colegio."""

    model_config = ConfigDict(extra="forbid")

    enabled_grades: list[str] = Field(
        ...,
        min_length=1,
        description="Códigos de grados que el colegio tiene habilitados.",
    )
    calendar_type: Literal["CALENDARIO_A", "CALENDARIO_B"] | None = None
    shift_type: Literal["JORNADA_UNICA", "MANANA", "TARDE", "COMPLETA"] | None = None


class SchoolAssignRectorRequest(BaseModel):
    """DTO para crear y nombrar al Rector(a) de un colegio desde el SuperPanel."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_name: str = Field(..., min_length=2, max_length=100)
    last_name: str = Field(..., min_length=2, max_length=100)
    document_number: str = Field(..., min_length=5, max_length=40)
    email: EmailStr
    password: str = Field(default="SoftEdu2026*", min_length=6)
    phone_number: str | None = Field(default=None, max_length=40)


class SchoolStaffCreateRequest(BaseModel):
    """
    DTO para que el Rector(a) (o SuperAdmin) agregue a su equipo directivo y administrativo:
    Secretaria Académica, Coordinador(a) Académico / Convivencia o Psicoorientador(a) Escolar.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["SECRETARIA", "COORDINADOR", "ORIENTADOR", "RECTOR"] = Field(
        ..., description="Rol directivo/administrativo dentro del colegio."
    )
    first_name: str = Field(..., min_length=2, max_length=100)
    last_name: str = Field(..., min_length=2, max_length=100)
    document_number: str = Field(..., min_length=5, max_length=40)
    email: EmailStr
    password: str = Field(default="SoftEdu2026*", min_length=6)
    job_title: str = Field(..., min_length=3, max_length=120)
    department_area: str = Field(..., min_length=3, max_length=120)
    phone_number: str | None = Field(default=None, max_length=40)
    school_id: uuid.UUID | None = None


# =====================================================================
# 1. DTOS DE AUTENTICACIÓN JWT E IDENTIDAD INSTITUCIONAL (RBAC)
# =====================================================================
class LoginRequest(BaseModel):
    """Credenciales de acceso para obtener un token Bearer JWT."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr = Field(..., description="Correo institucional del usuario.")
    password: str = Field(..., min_length=4, max_length=128)


class UserProfileResponse(BaseModel):
    """Información completa del usuario autenticado, su colegio, su cargo y permisos en español."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    school_id: uuid.UUID | None = None
    school_name: str | None = None
    school_calendar_type: str | None = None
    email: str
    first_name: str
    last_name: str
    full_name: str
    document_number: str
    role: UserRole
    role_label_es: str
    job_title: str
    department_area: str
    phone_number: str | None = None
    permissions_es: list[str] = Field(default_factory=list)
    teacher_id: uuid.UUID | None = None
    employee_code: str | None = None
    student_id: uuid.UUID | None = None
    student_code: str | None = None
    program_name: str | None = None
    grade_level_code: str | None = None
    current_semester: int | None = None
    enrollment_id: uuid.UUID | None = None
    is_active: bool


class TokenResponse(BaseModel):
    """Respuesta estándar OAuth2/JWT con token de acceso y perfil institucional."""

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
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "LUNES",
        "MARTES",
        "MIERCOLES",
        "JUEVES",
        "VIERNES",
        "SABADO",
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
        ..., min_length=2, max_length=60, description="Aula o salón asignado (ej. 'Salón 11°A - B201')."
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
    password: str = Field(default="SoftEdu2026*", min_length=6)
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
    minimum_passing_grade: Decimal = Field(
        default=Decimal("3.00"), ge=Decimal("0.00"), le=Decimal("5.00")
    )


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

    code: str = Field(..., min_length=4, max_length=20, description="Ej. '2026-CAL-A'")
    name: str = Field(..., min_length=5, max_length=120)
    start_date: date
    end_date: date
    is_current: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> "AcademicPeriodCreateRequest":
        if self.end_date <= self.start_date:
            raise ValueError(
                "La fecha de fin del período debe ser posterior a la fecha de inicio."
            )
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
    DTO para asignar un Docente a una Asignatura y Grado Escolar en un Período Lectivo
    definiendo sus bloques horarios (`schedule_blocks`).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_id: uuid.UUID
    teacher_id: uuid.UUID
    academic_period_id: uuid.UUID
    group_code: str = Field(..., min_length=1, max_length=20, description="Ej. '11°A'")
    grade_level_code: str = Field(
        default="GRADO_11",
        min_length=3,
        max_length=30,
        description="Grado escolar K-12 al que pertenece el grupo (MATERNAL .. GRADO_11)",
    )
    max_capacity: int = Field(default=35, ge=1, le=200)
    total_planned_sessions: int = Field(default=32, ge=1, le=120)
    schedule_blocks: list[ScheduleBlockSchema] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Bloques horarios semanales asignados al curso.",
    )


class CourseOfferingResponse(BaseModel):
    """DTO de salida de una oferta de curso con su grado, docente y bloques horarios."""

    id: uuid.UUID
    subject_id: uuid.UUID
    subject_code: str
    subject_name: str
    teacher_id: uuid.UUID
    teacher_full_name: str
    academic_period_id: uuid.UUID
    academic_period_code: str
    group_code: str
    grade_level_code: str | None = "GRADO_11"
    grade_level_label: str = "Grado 11°"
    max_capacity: int
    enrolled_count: int
    total_planned_sessions: int
    schedule_blocks: list[ScheduleBlockSchema]


# =====================================================================
# 3. DTOS DE ALUMNOS, PLANILLA DE ASISTENCIA Y TABLERO INSTITUCIONAL
# =====================================================================
class StudentCreateRequest(BaseModel):
    """DTO para matricular un Estudiante en un Grado activo del colegio (Maternal a 11°)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(default="SoftEdu2026*", min_length=6)
    first_name: str = Field(..., min_length=2, max_length=100)
    last_name: str = Field(..., min_length=2, max_length=100)
    document_number: str = Field(..., min_length=5, max_length=40)
    student_code: str = Field(..., min_length=3, max_length=30)
    grade_level_code: str = Field(
        default="GRADO_11",
        min_length=3,
        max_length=30,
        description="Código del grado escolar activo (ej. MATERNAL, TRANSICION, GRADO_5, GRADO_11)",
    )
    program_name: str | None = Field(default=None, max_length=150)
    current_semester: int = Field(default=11, ge=0, le=15)
    enrollment_cohort: str = Field(
        default="2026-A", min_length=4, max_length=20, description="Ej. '2026-A'"
    )
    birth_date: date | None = None
    guardian_name: str | None = Field(default=None, max_length=150)
    guardian_phone: str | None = Field(default=None, max_length=40)


class StudentResponse(BaseModel):
    """DTO de salida de la ficha estudiantil."""

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    document_number: str
    student_code: str
    grade_level_code: str | None = "GRADO_11"
    program_name: str
    current_semester: int
    enrollment_cohort: str
    birth_date: date | None
    guardian_name: str | None = None
    guardian_phone: str | None = None
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


class BulkAttendanceItemSchema(BaseModel):
    """Registro individual dentro de una toma de asistencia masiva de grupo."""

    enrollment_id: uuid.UUID
    status: AttendanceStatus
    observations: str | None = None


class BulkAttendanceCreateRequest(BaseModel):
    """Planilla de llamado a lista masivo para todos los alumnos de un grupo en una fecha."""

    model_config = ConfigDict(extra="forbid")

    session_date: date
    syllabus_topic_id: uuid.UUID | None = None
    records: list[BulkAttendanceItemSchema] = Field(..., min_length=1)


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
    ai_risk_evaluation_triggered: bool
    created_at: datetime


class AttendanceLogItemResponse(BaseModel):
    """Fila de historial de asistencia para reportes de coordinación y docentes."""

    id: uuid.UUID
    enrollment_id: uuid.UUID
    student_code: str
    student_full_name: str
    session_date: date
    status: AttendanceStatus
    status_label_es: str
    observations: str | None
    created_at: datetime


class EnrolledStudentSummaryItem(BaseModel):
    """Resumen consolidado de cada estudiante matriculado para planillas y tableros."""

    enrollment_id: uuid.UUID
    student_id: uuid.UUID
    student_code: str
    student_full_name: str
    student_email: str
    document_number: str
    grade_level_code: str | None = "GRADO_11"
    program_name: str
    current_semester: int
    guardian_name: str | None
    guardian_phone: str | None
    course_offering_id: uuid.UUID
    subject_id: uuid.UUID
    subject_code: str
    subject_name: str
    group_code: str
    academic_period_code: str
    evaluated_weight_percentage: Decimal
    remaining_weight_percentage: Decimal
    current_weighted_average: Decimal
    minimum_score_needed_in_remaining: Decimal
    is_currently_passing: bool
    grades_count: int
    present_count: int
    late_count: int
    excused_count: int
    unexcused_absent_count: int
    attendance_percentage: Decimal
    absence_percentage: Decimal
    risk_level: RiskLevel | None = None
    ai_executive_summary: str | None = None
    ai_detected_factors: list[str] = Field(default_factory=list)
    ai_action_plan: dict[str, Any] | None = None


class InstitutionalOverviewResponse(BaseModel):
    """Tablero Ejecutivo Institucional completo para SuperAdmin, Rectoría, Coordinación y Docentes."""

    active_school: SchoolInstitutionResponse | None = None
    schools: list[SchoolInstitutionResponse] = Field(default_factory=list)
    grades_catalog: list[SchoolGradeCatalogItem] = Field(default_factory=list)
    active_period_code: str
    active_period_name: str
    total_students: int
    total_teachers: int
    total_subjects: int
    total_course_offerings: int
    total_active_enrollments: int
    institutional_average_grade: Decimal
    passing_students_count: int
    failing_students_count: int
    approval_rate_percentage: Decimal
    global_attendance_percentage: Decimal
    risk_distribution: dict[str, int]
    enrolled_students: list[EnrolledStudentSummaryItem]
    recent_attendances: list[AttendanceLogItemResponse]
    institutional_directory: list[UserProfileResponse]
