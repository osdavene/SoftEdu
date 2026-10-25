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
# ENUMS DE DOMINIO (100% COMPATIBLES CON ROLES INSTITUCIONALES)
# =====================================================================
class UserRole(str, enum.Enum):
    """Roles institucionales del sistema para control de acceso (RBAC)."""

    SUPERADMIN = "SUPERADMIN"
    ADMIN = "ADMIN"
    RECTOR = "RECTOR"
    COORDINADOR = "COORDINADOR"
    SECRETARIA = "SECRETARIA"
    ORIENTADOR = "ORIENTADOR"
    DOCENTE = "DOCENTE"
    ESTUDIANTE = "ESTUDIANTE"
    # Alias técnicos retrocompatibles
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"


class SchoolCalendarType(str, enum.Enum):
    """Calendario escolar reglamentario MEN (Colombia)."""

    CALENDARIO_A = "CALENDARIO_A"
    CALENDARIO_B = "CALENDARIO_B"


# Catálogo oficial de Grados Escolares (Desde Maternal hasta Grado 11° — Sistema Colombiano MEN)
SCHOOL_GRADES_CATALOG: list[dict[str, Any]] = [
    {"code": "MATERNAL", "name": "Maternal (Educación Inicial)", "short_name": "Maternal", "stage": "Educación Inicial y Preescolar", "order": 0},
    {"code": "PREJARDIN", "name": "Pre-Jardín (3-4 años)", "short_name": "Pre-Jardín", "stage": "Educación Inicial y Preescolar", "order": 0},
    {"code": "JARDIN", "name": "Jardín (4-5 años)", "short_name": "Jardín", "stage": "Educación Inicial y Preescolar", "order": 0},
    {"code": "TRANSICION", "name": "Transición / Grado 0° (5-6 años)", "short_name": "Transición (0°)", "stage": "Educación Inicial y Preescolar", "order": 0},
    {"code": "GRADO_1", "name": "Grado Primero (1° Primaria)", "short_name": "Grado 1°", "stage": "Educación Básica Primaria", "order": 1},
    {"code": "GRADO_2", "name": "Grado Segundo (2° Primaria)", "short_name": "Grado 2°", "stage": "Educación Básica Primaria", "order": 2},
    {"code": "GRADO_3", "name": "Grado Tercero (3° Primaria)", "short_name": "Grado 3°", "stage": "Educación Básica Primaria", "order": 3},
    {"code": "GRADO_4", "name": "Grado Cuarto (4° Primaria)", "short_name": "Grado 4°", "stage": "Educación Básica Primaria", "order": 4},
    {"code": "GRADO_5", "name": "Grado Quinto (5° Primaria)", "short_name": "Grado 5°", "stage": "Educación Básica Primaria", "order": 5},
    {"code": "GRADO_6", "name": "Grado Sexto (6° Bachillerato)", "short_name": "Grado 6°", "stage": "Educación Básica Secundaria", "order": 6},
    {"code": "GRADO_7", "name": "Grado Séptimo (7° Bachillerato)", "short_name": "Grado 7°", "stage": "Educación Básica Secundaria", "order": 7},
    {"code": "GRADO_8", "name": "Grado Octavo (8° Bachillerato)", "short_name": "Grado 8°", "stage": "Educación Básica Secundaria", "order": 8},
    {"code": "GRADO_9", "name": "Grado Noveno (9° Bachillerato)", "short_name": "Grado 9°", "stage": "Educación Básica Secundaria", "order": 9},
    {"code": "GRADO_10", "name": "Grado Décimo (10° Media Vocacional)", "short_name": "Grado 10°", "stage": "Educación Media Vocacional", "order": 10},
    {"code": "GRADO_11", "name": "Grado Undécimo (11° Promoción Saber 11)", "short_name": "Grado 11°", "stage": "Educación Media Vocacional", "order": 11},
]



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
# 0. ENTIDAD MULTI-COLEGIO (INSTITUCIÓN EDUCATIVA K-12: MATERNAL A 11°)
# =====================================================================
class SchoolInstitution(Base, AuditMixin):
    """
    Institución Educativa (Colegio de Maternal a Grado 11°) administrada desde el SuperPanel.
    Controla el Calendario Escolar (A o B), Jornada, Código DANE, Grados Habilitados y Rector.
    """

    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    dane_code: Mapped[str] = mapped_column(String(35), nullable=False)
    nit: Mapped[str] = mapped_column(String(35), nullable=False)
    calendar_type: Mapped[str] = mapped_column(
        String(25),
        default="CALENDARIO_A",
        server_default="CALENDARIO_A",
        nullable=False,
        comment="CALENDARIO_A (Feb-Nov) o CALENDARIO_B (Sep-Jun)",
    )
    shift_type: Mapped[str] = mapped_column(
        String(40),
        default="JORNADA_UNICA",
        server_default="JORNADA_UNICA",
        nullable=False,
        comment="JORNADA_UNICA, MANANA, TARDE, COMPLETA",
    )
    city: Mapped[str] = mapped_column(
        String(100), default="Bogotá D.C.", nullable=False
    )
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email_contact: Mapped[str | None] = mapped_column(String(150), nullable=True)
    resolution_men: Mapped[str | None] = mapped_column(String(180), nullable=True)
    rector_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    enabled_grades: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
        comment="Lista de códigos de grado habilitados por el SuperAdmin (MATERNAL .. GRADO_11)",
    )


# =====================================================================
# 1. IDENTIDAD Y PERFILES (USER, TEACHER, STUDENT)
# =====================================================================
class User(Base, AuditMixin):
    """Entidad central de identidad, credenciales y rol institucional RBAC."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
        SQLEnum(UserRole, name="user_role_enum", native_enum=False, length=40),
        nullable=False,
        index=True,
    )
    job_title: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Cargo institucional descriptivo (ej. Rector General, Coordinadora Académica)",
    )
    department_area: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Dependencia o área institucional",
    )
    phone_number: Mapped[str | None] = mapped_column(String(40), nullable=True)

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
    guardian_name: Mapped[str | None] = mapped_column(
        String(150), nullable=True, comment="Nombre del acudiente o contacto de emergencia"
    )
    guardian_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    grade_level_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        default="GRADO_11",
        comment="Código del grado escolar K-12 (MATERNAL .. GRADO_11)",
    )
    classroom_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classroom_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    group_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default="11-1",
        comment="Código o sección del grupo escolar (ej: 6-1, 6-2, 6-3, 11-1)",
    )

    # Campos Oficiales SIMAT / MEN y Ficha Médica (Maternal a 11°)
    document_type: Mapped[str] = mapped_column(
        String(15), default="TI", nullable=False, comment="Tipo de documento (RC, TI, CC, PEP, PPT, CE)"
    )
    blood_type: Mapped[str] = mapped_column(
        String(10), default="O+", nullable=False, comment="Grupo sanguíneo y factor RH"
    )
    health_provider_eps: Mapped[str] = mapped_column(
        String(120), default="Sura EPS", nullable=False, comment="Entidad prestadora de salud (EPS)"
    )
    socioeconomic_stratum: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False, comment="Estrato socioeconómico según DANE (1 a 6)"
    )
    ethnicity: Mapped[str] = mapped_column(
        String(80), default="Ninguna", nullable=False, comment="Pertenencia étnica o afrocolombiana"
    )
    disability_condition: Mapped[str] = mapped_column(
        String(100), default="Ninguna", nullable=False, comment="Condición de discapacidad o capacidad excepcional"
    )
    medical_notes_allergies: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Ficha médica, alergias y cuidados especiales (vital en Primera Infancia)"
    )
    is_financial_paz_salvo: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Estado de Paz y Salvo financiero/administrativo"
    )

    # Relaciones
    user: Mapped["User"] = relationship("User", back_populates="student_profile")
    classroom_group: Mapped["ClassroomGroup | None"] = relationship("ClassroomGroup", back_populates="students")
    enrollments: Mapped[list["Enrollment"]] = relationship(
        "Enrollment", back_populates="student"
    )
    guardians: Mapped[list["Guardian"]] = relationship(
        "Guardian", back_populates="student", cascade="all, delete-orphan"
    )
    documents: Mapped[list["StudentDocument"]] = relationship(
        "StudentDocument", back_populates="student", cascade="all, delete-orphan"
    )
    graduation_requirement: Mapped["GraduationRequirement | None"] = relationship(
        "GraduationRequirement", back_populates="student", uselist=False, cascade="all, delete-orphan"
    )
    certificates: Mapped[list["OfficialCertificate"]] = relationship(
        "OfficialCertificate", back_populates="student", cascade="all, delete-orphan"
    )


# =====================================================================
# 1.1 SECRETARÍA ACADÉMICA: ACUDIENTES, DOCUMENTOS Y REQUISITOS DE LEY
# =====================================================================
class Guardian(Base, AuditMixin):
    """
    Acudientes, Padres y Responsables Legales/Financieros del Estudiante.
    Permite separar al acudiente de la ficha del alumno (un padre puede tener varios hijos).
    """

    __tablename__ = "guardians"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    document_type: Mapped[str] = mapped_column(String(15), default="CC", nullable=False)
    document_number: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    relationship_type: Mapped[str] = mapped_column(
        String(40), default="MADRE", nullable=False, comment="MADRE, PADRE, ACUDIENTE_LEGAL, OTRO"
    )
    is_financial_responsible: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Firma contrato/pagaré de matrícula"
    )
    is_authorized_pickup: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Autorizado para retirar al menor (Maternal/Preescolar)"
    )

    # Relaciones
    student: Mapped["Student"] = relationship("Student", back_populates="guardians")


class StudentDocument(Base, AuditMixin):
    """
    Checklist Documental Oficial de Matrícula según Nivel Educativo (Maternal a 11°).
    Controla el estado de entrega y verificación legal de cada requisito.
    """

    __tablename__ = "student_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        comment="Ej: Carnet de Vacunas, Registro Civil, Certificados de 5° a 10°, Paz y Salvo",
    )
    document_stage: Mapped[str] = mapped_column(
        String(30),
        default="GENERAL",
        nullable=False,
        comment="PREESCOLAR, PRIMARIA, BACHILLERATO, MEDIA, GENERAL",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="PENDIENTE",
        nullable=False,
        comment="PENDIENTE, CARGADO, APROBADO, RECHAZADO",
    )
    file_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_user: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # Relaciones
    student: Mapped["Student"] = relationship("Student", back_populates="documents")


class GraduationRequirement(Base, AuditMixin):
    """
    Control Legal de Requisitos para Graduación de Bachilleres (Grados 10° y 11°).
    Obligatorio para la expedición de Acta de Grado y Diploma según normatividad MEN.
    """

    __tablename__ = "graduation_requirements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    social_service_hours: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="Horas cumplidas de Servicio Social Estudiantil (mín 80)"
    )
    social_service_approved: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="Verificación y aprobación formal de Secretaría"
    )
    icfes_registration_code: Mapped[str | None] = mapped_column(
        String(60), nullable=True, comment="Número de Registro oficial Prueba ICFES Saber 11"
    )
    icfes_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Puntaje global obtenido en Saber 11 (sobre 500)"
    )
    prior_certificates_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="Certificados oficiales de 5° a 10° completos en legajo"
    )
    administrative_paz_salvo: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Paz y salvo institucional (Biblioteca, Pensión, Almacén)"
    )
    diploma_folio_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Número de Folio en Libro de Actas de Grado"
    )
    diploma_book_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Número de Libro de Registro de Diplomas"
    )
    graduation_status: Mapped[str] = mapped_column(
        String(40), default="EN_PROCESO", nullable=False, comment="EN_PROCESO, APTO_PARA_GRADO, GRADUADO"
    )

    # Relaciones
    student: Mapped["Student"] = relationship("Student", back_populates="graduation_requirement")


class GradingWindow(Base, AuditMixin):
    """
    Control de Ventanilla de Calificaciones por Período Académico.
    Determina si los docentes tienen habilitada la carga o si requiere extemporaneidad de Secretaría.
    """

    __tablename__ = "grading_windows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_label: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Ej: 'Primer Período Lectivo 2026'"
    )
    is_open: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="Indica si la ventanilla está abierta para carga de notas"
    )
    closing_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Fecha y hora de cierre oficial"
    )
    extemporaneous_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="Indica si hay extemporaneidad habilitada por Secretaría"
    )

    # Relaciones
    school: Mapped["SchoolInstitution"] = relationship("SchoolInstitution")
    academic_period: Mapped["AcademicPeriod"] = relationship("AcademicPeriod")


class OfficialCertificate(Base, AuditMixin):
    """
    Registro y Trazabilidad de Constancias y Certificados Oficiales Emitidos.
    Incluye código único de verificación y validador de autenticidad institucional.
    """

    __tablename__ = "official_certificates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    certificate_type: Mapped[str] = mapped_column(
        String(40), nullable=False, comment="CONSTANCIA_ESTUDIO, CERTIFICADO_NOTAS, ACTA_GRADO"
    )
    verification_code: Mapped[str] = mapped_column(
        String(60), unique=True, index=True, nullable=False, comment="Código único de validación (ej: CERT-2026-X89J2)"
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    recipient_entity: Mapped[str] = mapped_column(
        String(180), default="A QUIEN PUEDA INTERESAR", nullable=False
    )
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relaciones
    student: Mapped["Student"] = relationship("Student", back_populates="certificates")


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


class ClassroomGroup(Base, AuditMixin):
    """
    Grupo, salón o sección escolar por Grado (ej: 6-1, 6-2, 6-3, 11-1, T-1).
    Estándar SIMAT / MEN para la organización y apertura de cursos por secretaría.
    """

    __tablename__ = "classroom_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    grade_level_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
        comment="Código del grado oficial K-12 (MATERNAL .. GRADO_11)",
    )
    group_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="Nomenclatura oficial del grupo escolar (ej: '6-1', '6-2', '6-3', '11-1')",
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Nombre descriptivo del curso (ej: 'Sexto Uno', 'Grupo 6-1')",
    )
    shift: Mapped[str] = mapped_column(
        String(30),
        default="MAÑANA",
        nullable=False,
        comment="Jornada escolar: MAÑANA, TARDE, UNICA, COMPLETA",
    )
    classroom_location: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        comment="Aula física o salón asignado (ej: 'Salón 201', 'Bloque B')",
    )
    director_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
    )
    academic_period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="SET NULL"),
        nullable=True,
    )
    max_capacity: Mapped[int] = mapped_column(
        Integer,
        default=35,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "grade_level_code",
            "group_code",
            name="uq_classroom_group_school_grade_code",
        ),
        CheckConstraint("max_capacity > 0", name="group_max_capacity_positive"),
    )

    # Relaciones
    school: Mapped["SchoolInstitution | None"] = relationship("SchoolInstitution")
    director_teacher: Mapped["Teacher | None"] = relationship("Teacher")
    academic_period: Mapped["AcademicPeriod | None"] = relationship("AcademicPeriod")
    students: Mapped[list["Student"]] = relationship("Student", back_populates="classroom_group")
    course_offerings: Mapped[list["CourseOffering"]] = relationship(
        "CourseOffering", back_populates="classroom_group"
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
    classroom_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classroom_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    group_code: Mapped[str] = mapped_column(String(20), nullable=False)
    grade_level_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        default="GRADO_11",
        comment="Grado escolar K-12 del salón/grupo (MATERNAL .. GRADO_11)",
    )
    max_capacity: Mapped[int] = mapped_column(Integer, default=35, nullable=False)
    total_planned_sessions: Mapped[int] = mapped_column(
        Integer, default=32, nullable=False
    )
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
    classroom_group: Mapped["ClassroomGroup | None"] = relationship(
        "ClassroomGroup", back_populates="course_offerings"
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
        SQLEnum(EnrollmentStatus, name="enrollment_status_enum", native_enum=False, length=30),
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
        SQLEnum(AttendanceStatus, name="attendance_status_enum", native_enum=False, length=30),
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
        SQLEnum(RiskLevel, name="risk_level_enum", native_enum=False, length=30),
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
