"""Modelos de Dominio SQLAlchemy 2.0 (ORM Asíncrono + pgvector)."""

from datetime import date, datetime
from decimal import Decimal
import enum
from typing import Any
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
     Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base


# =====================================================================
# ENUMS DE DOMINIO
# =====================================================================
class UserRole(str, enum.Enum):
    """Roles del sistema para control de acceso basado en roles (RBAC)."""

    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"


class EnrollmentStatus(str, enum.Enum):
    """Estados del ciclo de vida de una matrícula académica."""

    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AttendanceStatus(str, enum.Enum):
    """Estados posibles de asistencia por sesión de clase."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    EXCUSED = "EXCUSED"


class RiskLevel(str, enum.Enum):
    """Niveles de riesgo académico diagnosticados por el motor de IA."""

    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"


# =====================================================================
# MIXIN DE AUDITORÍA TRANSVERSAL
# =====================================================================
class AuditMixin:
    """Mixin de auditoría empresarial con borrado lógico y marcas temporales."""

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# =====================================================================
# 1. IDENTIDAD Y PERFILES (USER, TEACHER, STUDENT)
# =====================================================================
class User(Base, AuditMixin):
    """Entidad central de identidad, credenciales y rol RBAC."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    document_number: Mapped[str] = mapped_column(
        String(40), unique=True, index=True, nullable=False
    )
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, name="user_role_enum"),
        nullable=False,
        index=True,
    )

    # Relaciones 1:1 hacia perfiles específicos
    teacher_profile: Mapped["Teacher | None"] = relationship(
        "Teacher",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    student_profile: Mapped["Student | None"] = relationship(
        "Student",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def full_name(self) -> str:
        """Nombre completo formateado del usuario."""
        return f"{self.first_name} {self.last_name}"


class Teacher(Base, AuditMixin):
    """Ficha profesional del Docente vinculada 1:1 con User."""

    __tablename__ = "teachers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    employee_code: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    specialization: Mapped[str] = mapped_column(String(150), nullable=False)
    academic_degree: Mapped[str] = mapped_column(String(100), nullable=False)
    max_weekly_hours: Mapped[int] = mapped_column(Integer, default=40, nullable=False)

    # Relaciones
    user: Mapped["User"] = relationship("User", back_populates="teacher_profile")
    course_offerings: Mapped[list["CourseOffering"]] = relationship(
        "CourseOffering", back_populates="teacher"
    )


class Student(Base, AuditMixin):
    """Ficha estudiantil vinculada 1:1 con User."""

    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    student_code: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    program_name: Mapped[str] = mapped_column(String(150), nullable=False)
    current_semester: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    enrollment_cohort: Mapped[str] = mapped_column(String(20), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Relaciones
    user: Mapped["User"] = relationship("User", back_populates="student_profile")
    enrollments: Mapped[list["Enrollment"]] = relationship(
        "Enrollment", back_populates="student"
    )


# =====================================================================
# 2. CATÁLOGO CURRICULAR, PERÍODOS Y SÍLABO VECTORIZADO (pgvector)
# =====================================================================
class Subject(Base, AuditMixin):
    """Asignatura o materia oficial del plan de estudios."""

    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(
        String(25), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    weekly_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_passing_grade: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("3.00"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("credits > 0", name="credits_positive"),
        CheckConstraint("weekly_hours > 0", name="weekly_hours_positive"),
    )

    # Relaciones
    syllabus_units: Mapped[list["SyllabusUnit"]] = relationship(
        "SyllabusUnit",
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="SyllabusUnit.unit_number",
    )
    course_offerings: Mapped[list["CourseOffering"]] = relationship(
        "CourseOffering", back_populates="subject"
    )


class SyllabusUnit(Base, AuditMixin):
    """Unidad temática dentro del sílabo de una materia."""

    __tablename__ = "syllabus_units"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    learning_objective: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_weeks: Mapped[int] = mapped_column(Integer, default=4, nullable=False)

    __table_args__ = (
        UniqueConstraint("subject_id", "unit_number", name="uq_syllabus_unit_per_subject"),
        CheckConstraint("unit_number >= 1", name="unit_number_positive"),
    )

    # Relaciones
    subject: Mapped["Subject"] = relationship("Subject", back_populates="syllabus_units")
    topics: Mapped[list["SyllabusTopic"]] = relationship(
        "SyllabusTopic",
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="SyllabusTopic.topic_number",
    )


class SyllabusTopic(Base, AuditMixin):
    """
    Tema específico del sílabo con vector de embeddings (`pgvector`)
    para búsqueda semántica (RAG Tutor y correlación de fallas en evaluaciones).
    """

    __tablename__ = "syllabus_topics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("syllabus_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    content_description: Mapped[str] = mapped_column(Text, nullable=False)
    key_concepts: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    bibliography_references: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Columna vectorial pgvector para similitud coseno / L2
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.AI_EMBEDDING_DIMENSION),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("unit_id", "topic_number", name="uq_topic_number_per_unit"),
        Index(
            "ix_syllabus_topics_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    # Relaciones
    unit: Mapped["SyllabusUnit"] = relationship("SyllabusUnit", back_populates="topics")
    grades: Mapped[list["Grade"]] = relationship("Grade", back_populates="syllabus_topic")


class AcademicPeriod(Base, AuditMixin):
    """Período lectivo académico (ej. 2026-1, 2026-2)."""

    __tablename__ = "academic_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, nullable=False
    )

    __table_args__ = (
        CheckConstraint("end_date > start_date", name="valid_period_date_range"),
    )

    # Relaciones
    course_offerings: Mapped[list["CourseOffering"]] = relationship(
        "CourseOffering", back_populates="academic_period"
    )


class CourseOffering(Base, AuditMixin):
    """
    Oferta de curso (Grupo/Sección): vincula Materia, Docente, Período Lectivo
    y bloques de horario (`schedule_blocks`).
    """

    __tablename__ = "course_offerings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    group_code: Mapped[str] = mapped_column(String(20), nullable=False)
    max_capacity: Mapped[int] = mapped_column(Integer, default=35, nullable=False)
    total_planned_sessions: Mapped[int] = mapped_column(
        Integer, default=32, nullable=False
    )
    # Estructura JSONB de bloques horarios: [{"day": "MONDAY", "start": "08:00", "end": "10:00", "room": "B-204"}]
    schedule_blocks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "academic_period_id",
            "group_code",
            name="uq_course_offering_subject_period_group",
        ),
        CheckConstraint("max_capacity > 0", name="max_capacity_positive"),
        CheckConstraint("total_planned_sessions > 0", name="planned_sessions_positive"),
    )

    # Relaciones
    subject: Mapped["Subject"] = relationship("Subject", back_populates="course_offerings")
    teacher: Mapped["Teacher"] = relationship("Teacher", back_populates="course_offerings")
    academic_period: Mapped["AcademicPeriod"] = relationship(
        "AcademicPeriod", back_populates="course_offerings"
    )
    enrollments: Mapped[list["Enrollment"]] = relationship(
        "Enrollment", back_populates="course_offering"
    )


# =====================================================================
# 3. MATRÍCULAS, CALIFICACIONES PONDERADAS, ASISTENCIA E INSIGHTS IA
# =====================================================================
class Enrollment(Base, AuditMixin):
    """Matrícula oficial de un Estudiante en una Oferta de Curso."""

    __tablename__ = "enrollments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    course_offering_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("course_offerings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        SQLEnum(EnrollmentStatus, name="enrollment_status_enum"),
        default=EnrollmentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "course_offering_id",
            name="uq_student_course_offering_enrollment",
        ),
    )

    # Relaciones
    student: Mapped["Student"] = relationship("Student", back_populates="enrollments")
    course_offering: Mapped["CourseOffering"] = relationship(
        "CourseOffering", back_populates="enrollments"
    )
    grades: Mapped[list["Grade"]] = relationship(
        "Grade",
        back_populates="enrollment",
        cascade="all, delete-orphan",
        order_by="Grade.evaluation_cut, Grade.created_at",
    )
    attendances: Mapped[list["Attendance"]] = relationship(
        "Attendance",
        back_populates="enrollment",
        cascade="all, delete-orphan",
        order_by="Attendance.session_date",
    )
    ai_insights: Mapped[list["StudentAIInsight"]] = relationship(
        "StudentAIInsight",
        back_populates="enrollment",
        cascade="all, delete-orphan",
        order_by="StudentAIInsight.created_at.desc()",
    )


class Grade(Base, AuditMixin):
    """
    Calificación ponderada por corte evaluativo (escala 0.00 a 5.00).
    Cada nota puede asociarse opcionalmente a un `SyllabusTopic` evaluado.
    """

    __tablename__ = "grades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    syllabus_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("syllabus_topics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evaluation_cut: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Número de corte académico (ej. 1, 2, 3)"
    )
    evaluation_name: Mapped[str] = mapped_column(
        String(150), nullable=False, comment="Nombre de la actividad (ej. Parcial 1)"
    )
    weight_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment="Peso porcentual sobre la nota definitiva (0.01 a 100.00)",
    )
    score: Mapped[Decimal] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        comment="Nota obtenida en escala de 0.00 a 5.00",
    )
    teacher_observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "enrollment_id",
            "evaluation_cut",
            "evaluation_name",
            name="uq_grade_enrollment_cut_eval_name",
        ),
        CheckConstraint("score >= 0.00 AND score <= 5.00", name="score_range_0_to_5"),
        CheckConstraint(
            "weight_percentage > 0.00 AND weight_percentage <= 100.00",
            name="weight_percentage_range_valid",
        ),
        CheckConstraint("evaluation_cut >= 1 AND evaluation_cut <= 10", name="valid_cut_number"),
    )

    # Relaciones
    enrollment: Mapped["Enrollment"] = relationship("Enrollment", back_populates="grades")
    syllabus_topic: Mapped["SyllabusTopic | None"] = relationship(
        "SyllabusTopic", back_populates="grades"
    )


class Attendance(Base, AuditMixin):
    """Registro de asistencia e inasistencias de un estudiante por fecha de sesión."""

    __tablename__ = "attendances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    syllabus_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("syllabus_topics.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        SQLEnum(AttendanceStatus, name="attendance_status_enum"),
        nullable=False,
        index=True,
    )
    observations: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "enrollment_id",
            "session_date",
            name="uq_attendance_enrollment_session_date",
        ),
    )

    # Relaciones
    enrollment: Mapped["Enrollment"] = relationship(
        "Enrollment", back_populates="attendances"
    )


class StudentAIInsight(Base, AuditMixin):
    """
    Historial y estado vigente de diagnósticos generados por el Copiloto de IA
    (Alerta Temprana de Riesgo Académico) para una matrícula específica.
    """

    __tablename__ = "student_ai_insights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_by_grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grades.id", ondelete="SET NULL"),
        nullable=True,
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        SQLEnum(RiskLevel, name="risk_level_enum"),
        nullable=False,
        index=True,
    )
    accumulated_weighted_average: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False
    )
    evaluated_weight_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    absence_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    detected_factors: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    suggested_action_plan: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Estructura JSON con acciones para docente, estudiante y temas de refuerzo",
    )
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    is_current_insight: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Indica si es el diagnóstico vigente más reciente de la matrícula",
    )

    __table_args__ = (
        Index(
            "ix_student_ai_insights_enrollment_current",
            "enrollment_id",
            "is_current_insight",
        ),
    )

    # Relaciones
    enrollment: Mapped["Enrollment"] = relationship(
        "Enrollment", back_populates="ai_insights"
    )
