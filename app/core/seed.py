"""
Inicialización automática de tablas (`Base.metadata.create_all`) y semilla
de datos institucionales por defecto (`seed_initial_data`) para entorno local y AWS.
"""

from datetime import date
from decimal import Decimal
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_service import AcademicAIService
from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, async_engine, init_pgvector_extension
from app.core.security import hash_password
from app.models.academic import (
    AcademicPeriod,
    CourseOffering,
    Enrollment,
    EnrollmentStatus,
    Student,
    Subject,
    SyllabusTopic,
    SyllabusUnit,
    Teacher,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)


async def initialize_database_and_seed() -> None:
    """
    1. Activa la extensión `vector` (`pgvector`) en PostgreSQL.
    2. Crea todas las tablas del modelo SQLAlchemy 2.0 si no existen.
    3. Inserta usuarios RBAC y datos académicos semilla de forma idempotente.
    """
    await init_pgvector_extension()

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Esquema de tablas SQLAlchemy 2.0 verificado en PostgreSQL.")

    async with AsyncSessionLocal() as session:
        await _seed_default_records(session)


async def _seed_default_records(session: AsyncSession) -> None:
    """Siembra usuarios por defecto y catálogo académico inicial si no existen."""
    existing_admin = await session.execute(
        select(User).where(User.email == "admin@softedu.edu.co")
    )
    if existing_admin.scalars().first() is not None:
        logger.info("Datos semilla institucionales ya existen. Omitiendo seed.")
        return

    logger.info("Sembrando usuarios RBAC y catálogo académico inicial en SoftEdu...")

    # 1. Usuarios Base (Admin, Docente, Estudiante)
    admin_user = User(
        email="admin@softedu.edu.co",
        hashed_password=hash_password("admin12345"),
        first_name="Coordinador",
        last_name="Académico General",
        document_number="1000000001",
        role=UserRole.ADMIN,
    )
    teacher_user = User(
        email="docente@softedu.edu.co",
        hashed_password=hash_password("docente123"),
        first_name="Carlos Andrés",
        last_name="Martínez Gómez",
        document_number="1000000002",
        role=UserRole.TEACHER,
    )
    student_user = User(
        email="estudiante@softedu.edu.co",
        hashed_password=hash_password("estudiante123"),
        first_name="Laura Sofía",
        last_name="Rodríguez Pérez",
        document_number="1000000003",
        role=UserRole.STUDENT,
    )
    session.add_all([admin_user, teacher_user, student_user])
    await session.flush()

    # 2. Perfiles Docente y Estudiante
    teacher = Teacher(
        user_id=teacher_user.id,
        employee_code="DOC-2026-001",
        department="Ingeniería de Sistemas y Computación",
        specialization="Arquitectura de Software e Inteligencia Artificial",
        academic_degree="Magíster en Ciencias de la Computación",
        max_weekly_hours=40,
    )
    student = Student(
        user_id=student_user.id,
        student_code="EST-2026-101",
        program_name="Ingeniería de Software",
        current_semester=6,
        enrollment_cohort="2024-1",
        birth_date=date(2004, 5, 14),
    )
    session.add_all([teacher, student])
    await session.flush()

    # 3. Período Lectivo y Asignatura
    period = AcademicPeriod(
        code="2026-2",
        name="Segundo Período Académico 2026",
        start_date=date(2026, 7, 15),
        end_date=date(2026, 12, 10),
        is_current=True,
    )
    subject = Subject(
        code="ISW-402",
        name="Arquitectura Empresarial e IA Aplicada",
        description=(
            "Diseño de backends asíncronos de alta disponibilidad con Python, "
            "FastAPI, SQLAlchemy 2.0, bases vectoriales pgvector y motores LLM/RAG."
        ),
        credits=4,
        weekly_hours=4,
        minimum_passing_grade=Decimal("3.00"),
    )
    session.add_all([period, subject])
    await session.flush()

    # 4. Sílabo Vectorizado (Unidad + Temas con Embeddings)
    unit1 = SyllabusUnit(
        subject_id=subject.id,
        unit_number=1,
        title="Arquitectura en Capas, Asincronismo y Persistencia Vectorial",
        learning_objective=(
            "Diseñar arquitecturas desacopladas con el patrón Repositorio, "
            "SQLAlchemy 2.0 AsyncSession y búsquedas de similitud en pgvector."
        ),
        estimated_weeks=4,
    )
    session.add(unit1)
    await session.flush()

    topic1_desc = (
        "Uso de AsyncEngine, AsyncSession con asyncpg, bloqueo optimista, "
        "carga ansiosa (selectinload/joinedload) y manejo de transacciones "
        "aisladas en BackgroundTasks para evitar cierres prematuros de sesión."
    )
    topic1 = SyllabusTopic(
        unit_id=unit1.id,
        topic_number=1,
        title="Persistencia Asíncrona con SQLAlchemy 2.0 y Patrón Repositorio",
        content_description=topic1_desc,
        key_concepts=[
            "AsyncSession",
            "asyncpg",
            "Patrón Repositorio",
            "Inyección de Dependencias",
            "BackgroundTasks",
        ],
        bibliography_references="SQLAlchemy 2.0 Official Documentation; Clean Architecture in Python.",
        embedding=AcademicAIService._build_deterministic_unit_vector(
            topic1_desc, settings.AI_EMBEDDING_DIMENSION
        ),
    )

    topic2_desc = (
        "Indexación semántica mediante embeddings de alta dimensionalidad en PostgreSQL "
        "con pgvector, índices HNSW, operadores de distancia coseno (<=>) y generación "
        "aumentada por recuperación (RAG) con Structured Outputs en Pydantic v2."
    )
    topic2 = SyllabusTopic(
        unit_id=unit1.id,
        topic_number=2,
        title="Búsqueda Semántica con pgvector, Índices HNSW y Motores RAG",
        content_description=topic2_desc,
        key_concepts=[
            "pgvector",
            "HNSW Index",
            "Distancia Coseno",
            "Embeddings",
            "RAG",
            "Structured Outputs",
        ],
        bibliography_references="PostgreSQL pgvector Reference; Google Gemini & OpenAI Structured Outputs Guide.",
        embedding=AcademicAIService._build_deterministic_unit_vector(
            topic2_desc, settings.AI_EMBEDDING_DIMENSION
        ),
    )
    session.add_all([topic1, topic2])
    await session.flush()

    # 5. Oferta de Curso con Bloques Horarios y Matrícula Activa
    offering = CourseOffering(
        subject_id=subject.id,
        teacher_id=teacher.id,
        academic_period_id=period.id,
        group_code="G01",
        max_capacity=35,
        total_planned_sessions=32,
        schedule_blocks=[
            {
                "day": "MONDAY",
                "start_time": "08:00",
                "end_time": "10:00",
                "classroom": "LAB-IA-301",
            },
            {
                "day": "WEDNESDAY",
                "start_time": "08:00",
                "end_time": "10:00",
                "classroom": "LAB-IA-301",
            },
        ],
    )
    session.add(offering)
    await session.flush()

    enrollment = Enrollment(
        student_id=student.id,
        course_offering_id=offering.id,
        status=EnrollmentStatus.ACTIVE,
    )
    session.add(enrollment)
    await session.commit()

    logger.info(
        "Seed completado exitosamente. Enrollment ID demo: %s | Topic 1 ID: %s",
        enrollment.id,
        topic1.id,
    )
