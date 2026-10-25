"""
Inicialización automática de tablas (`Base.metadata.create_all`), actualización de
columnas y semilla completa de roles institucionales (Rector, Coordinador, Secretaría,
Orientador, Docentes y 5 Estudiantes con notas, asistencias y diagnósticos IA).
"""

from datetime import date
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_service import AcademicAIService
from app.core.config import settings
from app.core.database import (
    AsyncSessionLocal,
    Base,
    async_engine,
    ensure_database_exists,
    init_pgvector_extension,
)
from app.core.security import hash_password
from app.models.academic import (
    AcademicPeriod,
    Attendance,
    AttendanceStatus,
    CourseOffering,
    Enrollment,
    EnrollmentStatus,
    Grade,
    RiskLevel,
    Student,
    StudentAIInsight,
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
    1. Crea la base de datos `softedu_db` si no existe.
    2. Activa la extensión `vector` (`pgvector`) en PostgreSQL (o adapta el tipo en local).
    3. Crea o actualiza el esquema de tablas SQLAlchemy 2.0.
    4. Inserta todos los roles institucionales y datos académicos de demostración.
    """
    await ensure_database_exists()
    has_pgvector = await init_pgvector_extension()

    if not has_pgvector:
        SyllabusTopic.__table__.c.embedding.type = JSONB()
        SyllabusTopic.__table__.indexes = {
            idx
            for idx in SyllabusTopic.__table__.indexes
            if idx.name != "ix_syllabus_topics_embedding_hnsw"
        }

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Asegurar migración transparente de columnas nuevas o tipos ENUM previos
        await _ensure_schema_columns_upgraded(conn)
        logger.info("Esquema de tablas SQLAlchemy 2.0 verificado en PostgreSQL.")

    async with AsyncSessionLocal() as session:
        await _seed_institutional_records(session)


async def _ensure_schema_columns_upgraded(conn: Any) -> None:
    """Garantiza que las columnas nuevas y tipos VARCHAR de roles existan en tablas previas."""
    alter_statements = [
        "ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(40) USING role::text;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title VARCHAR(120);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department_area VARCHAR(120);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(40);",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS guardian_name VARCHAR(150);",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS guardian_phone VARCHAR(40);",
        "ALTER TABLE enrollments ALTER COLUMN status TYPE VARCHAR(30) USING status::text;",
        "ALTER TABLE attendances ALTER COLUMN status TYPE VARCHAR(30) USING status::text;",
        "ALTER TABLE student_ai_insights ALTER COLUMN risk_level TYPE VARCHAR(30) USING risk_level::text;",
    ]
    for stmt_sql in alter_statements:
        try:
            await conn.execute(text(stmt_sql))
        except Exception:
            pass


async def _seed_institutional_records(session: AsyncSession) -> None:
    """Siembra el ecosistema institucional completo si aún no está poblado."""
    existing_rector = await session.execute(
        select(User).where(User.email == "rector@softedu.edu.co")
    )
    if existing_rector.scalars().first() is not None:
        logger.info("Ecosistema institucional completo ya sembrado. Omitiendo seed.")
        return

    logger.info("Sembrando roles institucionales (Rector, Coordinador, Secretaría, Orientador, Docentes, Estudiantes)...")

    # 1. Roles Directivos y Administrativos
    rector_user = User(
        email="rector@softedu.edu.co",
        hashed_password=hash_password("rector123"),
        first_name="Dr. Hernando José",
        last_name="Villamizar Ordóñez",
        document_number="79450112",
        role=UserRole.RECTOR,
        job_title="Rector General Institucional",
        department_area="Rectoría y Dirección Estratégica",
        phone_number="310-450-9811",
    )
    coordinador_user = User(
        email="coordinador@softedu.edu.co",
        hashed_password=hash_password("coordinador123"),
        first_name="Mg. Claudia Patricia",
        last_name="Mendoza Salazar",
        document_number="52890341",
        role=UserRole.COORDINADOR,
        job_title="Coordinadora Académica y Curricular",
        department_area="Vicerrectoría Académica",
        phone_number="315-820-3344",
    )
    secretaria_user = User(
        email="secretaria@softedu.edu.co",
        hashed_password=hash_password("secretaria123"),
        first_name="Lic. Diana Carolina",
        last_name="Ospina Restrepo",
        document_number="1018432098",
        role=UserRole.SECRETARIA,
        job_title="Secretaria General de Registro y Matrículas",
        department_area="Secretaría Académica y Admisiones",
        phone_number="318-640-1122",
    )
    orientador_user = User(
        email="orientador@softedu.edu.co",
        hashed_password=hash_password("orientador123"),
        first_name="Psic. Andrés Felipe",
        last_name="Quintero Lozano",
        document_number="1032455901",
        role=UserRole.ORIENTADOR,
        job_title="Psicoorientador y Permanencia Estudiantil",
        department_area="Bienestar Institucional y Psicología",
        phone_number="300-711-8900",
    )
    session.add_all([rector_user, coordinador_user, secretaria_user, orientador_user])
    await session.flush()

    # Asegurar que el usuario admin previo (si existe) tenga metadatos actualizados
    existing_admin = (
        await session.execute(select(User).where(User.email == "admin@softedu.edu.co"))
    ).scalars().first()
    if existing_admin is None:
        existing_admin = User(
            email="admin@softedu.edu.co",
            hashed_password=hash_password("admin12345"),
            first_name="Ing. Óscar David",
            last_name="Administrador General",
            document_number="1000000001",
            role=UserRole.ADMIN,
            job_title="Director de Tecnología y Plataforma LMS/SIS",
            department_area="Dirección TIC",
            phone_number="311-500-0001",
        )
        session.add(existing_admin)
    else:
        existing_admin.job_title = "Director de Tecnología y Plataforma LMS/SIS"
        existing_admin.department_area = "Dirección TIC"

    # 2. Docentes
    teacher_user_1 = (
        await session.execute(select(User).where(User.email == "docente@softedu.edu.co"))
    ).scalars().first()
    if teacher_user_1 is None:
        teacher_user_1 = User(
            email="docente@softedu.edu.co",
            hashed_password=hash_password("docente123"),
            first_name="Carlos Andrés",
            last_name="Martínez Gómez",
            document_number="1000000002",
            role=UserRole.DOCENTE,
            job_title="Docente Titular de Arquitectura de Software e IA",
            department_area="Facultad de Ingeniería de Sistemas",
            phone_number="312-409-2210",
        )
        session.add(teacher_user_1)
        await session.flush()
    else:
        teacher_user_1.role = UserRole.DOCENTE
        teacher_user_1.job_title = "Docente Titular de Arquitectura de Software e IA"
        teacher_user_1.department_area = "Facultad de Ingeniería de Sistemas"

    teacher_1 = (
        await session.execute(
            select(Teacher).where(Teacher.user_id == teacher_user_1.id)
        )
    ).scalars().first()
    if teacher_1 is None:
        teacher_1 = Teacher(
            user_id=teacher_user_1.id,
            employee_code="DOC-2026-001",
            department="Ingeniería de Sistemas y Computación",
            specialization="Arquitectura de Software e Inteligencia Artificial",
            academic_degree="Magíster en Ciencias de la Computación",
            max_weekly_hours=40,
        )
        session.add(teacher_1)
        await session.flush()

    teacher_user_2 = User(
        email="elena.suarez@softedu.edu.co",
        hashed_password=hash_password("docente123"),
        first_name="Dra. Elena Isabel",
        last_name="Suárez Valenzuela",
        document_number="53119874",
        role=UserRole.DOCENTE,
        job_title="Docente Investigadora en Ciencia de Datos y Analítica",
        department_area="Facultad de Ingeniería de Sistemas",
        phone_number="314-298-7741",
    )
    session.add(teacher_user_2)
    await session.flush()

    teacher_2 = Teacher(
        user_id=teacher_user_2.id,
        employee_code="DOC-2026-002",
        department="Ingeniería de Sistemas y Computación",
        specialization="Machine Learning y Bases de Datos Vectoriales",
        academic_degree="Doctora en Ingeniería Informática",
        max_weekly_hours=36,
    )
    session.add(teacher_2)
    await session.flush()

    # 3. Período Lectivo y Asignaturas
    period = (
        await session.execute(
            select(AcademicPeriod).where(AcademicPeriod.code == "2026-2")
        )
    ).scalars().first()
    if period is None:
        period = AcademicPeriod(
            code="2026-2",
            name="Segundo Período Académico 2026",
            start_date=date(2026, 7, 15),
            end_date=date(2026, 12, 10),
            is_current=True,
        )
        session.add(period)
        await session.flush()

    subject_1 = (
        await session.execute(select(Subject).where(Subject.code == "ISW-402"))
    ).scalars().first()
    if subject_1 is None:
        subject_1 = Subject(
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
        session.add(subject_1)
        await session.flush()

    # Asegurar Unidades y Temas del Sílabo
    units = list(
        (
            await session.execute(
                select(SyllabusUnit).where(SyllabusUnit.subject_id == subject_1.id)
            )
        )
        .scalars()
        .all()
    )
    if not units:
        unit1 = SyllabusUnit(
            subject_id=subject_1.id,
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

        t1_desc = (
            "Uso de AsyncEngine, AsyncSession con asyncpg, bloqueo optimista, "
            "carga ansiosa (selectinload/joinedload) y manejo de transacciones "
            "aisladas en BackgroundTasks para evitar cierres prematuros de sesión."
        )
        topic1 = SyllabusTopic(
            unit_id=unit1.id,
            topic_number=1,
            title="Persistencia Asíncrona con SQLAlchemy 2.0 y Patrón Repositorio",
            content_description=t1_desc,
            key_concepts=[
                "AsyncSession",
                "asyncpg",
                "Patrón Repositorio",
                "Inyección de Dependencias",
                "BackgroundTasks",
            ],
            bibliography_references="Documentación Oficial SQLAlchemy 2.0; Arquitectura Limpia en Python.",
            embedding=AcademicAIService._build_deterministic_unit_vector(
                t1_desc, settings.AI_EMBEDDING_DIMENSION
            ),
        )
        t2_desc = (
            "Indexación semántica mediante embeddings de alta dimensionalidad en PostgreSQL "
            "con pgvector, índices HNSW, operadores de distancia coseno (<=>) y generación "
            "aumentada por recuperación (RAG) con Structured Outputs en Pydantic v2."
        )
        topic2 = SyllabusTopic(
            unit_id=unit1.id,
            topic_number=2,
            title="Búsqueda Semántica con pgvector, Índices HNSW y Motores RAG",
            content_description=t2_desc,
            key_concepts=[
                "pgvector",
                "Índice HNSW",
                "Distancia Coseno",
                "Embeddings",
                "RAG",
                "Structured Outputs",
            ],
            bibliography_references="Referencia Oficial pgvector; Guía de Structured Outputs en Gemini y OpenAI.",
            embedding=AcademicAIService._build_deterministic_unit_vector(
                t2_desc, settings.AI_EMBEDDING_DIMENSION
            ),
        )
        session.add_all([topic1, topic2])
        await session.flush()
    else:
        unit1 = units[0]

    # Agregar Unidad 2 al Sílabo si solo existe la Unidad 1
    if len(units) < 2:
        unit2 = SyllabusUnit(
            subject_id=subject_1.id,
            unit_number=2,
            title="Seguridad Empresarial JWT, RBAC y Despliegue en Nube AWS",
            learning_objective=(
                "Implementar control de acceso basado en roles institucionales, "
                "auditoría transaccional y pipelines de integración continua hacia AWS."
            ),
            estimated_weeks=4,
        )
        session.add(unit2)
        await session.flush()
        t3_desc = (
            "Autenticación stateless mediante JSON Web Tokens (JWT), hashing con Bcrypt, "
            "control de acceso granular por roles (Rector, Coordinador, Docente, Estudiante) "
            "y despliegue automatizado con GitHub Actions y systemd en AWS EC2."
        )
        topic3 = SyllabusTopic(
            unit_id=unit2.id,
            topic_number=1,
            title="Autenticación JWT, Matriz RBAC y Despliegue Continuo en AWS",
            content_description=t3_desc,
            key_concepts=["JWT", "Bcrypt", "RBAC", "AWS EC2", "GitHub Actions", "systemd"],
            bibliography_references="OWASP API Security Top 10; FastAPI Security Documentation.",
            embedding=AcademicAIService._build_deterministic_unit_vector(
                t3_desc, settings.AI_EMBEDDING_DIMENSION
            ),
        )
        session.add(topic3)
        await session.flush()

    topics_list = list(
        (
            await session.execute(
                select(SyllabusTopic)
                .join(SyllabusUnit, SyllabusTopic.unit_id == SyllabusUnit.id)
                .where(SyllabusUnit.subject_id == subject_1.id)
                .order_by(SyllabusUnit.unit_number, SyllabusTopic.topic_number)
            )
        )
        .scalars()
        .all()
    )
    first_topic_id = topics_list[0].id if topics_list else None
    second_topic_id = topics_list[1].id if len(topics_list) > 1 else first_topic_id

    # Oferta de Curso Principal
    offering = (
        await session.execute(
            select(CourseOffering).where(
                CourseOffering.subject_id == subject_1.id,
                CourseOffering.group_code == "G01",
            )
        )
    ).scalars().first()
    if offering is None:
        offering = CourseOffering(
            subject_id=subject_1.id,
            teacher_id=teacher_1.id,
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

    # 4. Poblar 5 Estudiantes con Perfiles, Matrículas, Notas, Asistencias e Insights IA
    students_seed_data = [
        {
            "email": "estudiante@softedu.edu.co",
            "first_name": "Laura Sofía",
            "last_name": "Rodríguez Pérez",
            "doc": "1000000003",
            "code": "EST-2026-101",
            "program": "Ingeniería de Software",
            "semester": 6,
            "guardian": "Martha Lucía Pérez (Madre)",
            "guardian_phone": "310-889-1201",
            "grades": [
                (1, "Parcial 1 - Persistencia Async", Decimal("30.00"), Decimal("2.40"), first_topic_id, "Presenta dificultad en sesiones aisladas de BackgroundTasks."),
                (1, "Taller Práctico 1 - pgvector", Decimal("20.00"), Decimal("2.80"), second_topic_id, "Debe reforzar índices HNSW y operadores de distancia coseno."),
            ],
            "attendances": [
                (date(2026, 8, 3), AttendanceStatus.PRESENT, "Asistencia puntual y participativa."),
                (date(2026, 8, 5), AttendanceStatus.ABSENT, "Inasistencia sin justificación reportada."),
                (date(2026, 8, 10), AttendanceStatus.ABSENT, "Segunda falla consecutiva en sesión de laboratorio."),
                (date(2026, 8, 12), AttendanceStatus.LATE, "Ingresó 25 minutos después del inicio de la práctica."),
                (date(2026, 8, 17), AttendanceStatus.ABSENT, "Tercera inasistencia acumulada en el corte."),
            ],
            "risk": RiskLevel.ALTO,
            "avg": Decimal("2.56"),
            "eval_w": Decimal("50.00"),
            "abs_pct": Decimal("9.38"),
            "summary": "Alerta Temprana IA: Laura Sofía registra un promedio ponderado reprobatorio de 2.56/5.00 (50% evaluado) combinado con 3 inasistencias injustificadas y 1 retardo. Requiere obtener mínimo 3.44 en el 50% restante del curso.",
            "factors": [
                "Promedio ponderado actual (2.56/5.00) por debajo de la nota mínima aprobatoria (3.00).",
                "3 inasistencias injustificadas acumuladas (9.38% del total de sesiones del curso).",
                "Dificultades técnicas detectadas en: Persistencia Asíncrona con SQLAlchemy 2.0 y Búsqueda Semántica con pgvector.",
            ],
            "teacher_actions": [
                "Citar a la estudiante a tutoría de refuerzo práctico sobre AsyncSession y manejo de transacciones en BackgroundTasks.",
                "Realizar seguimiento preventivo de asistencia junto con Coordinación Académica.",
            ],
            "student_actions": [
                "Alcanzar una nota promedio mínima de 3.44 en el 50% restante de la asignatura para aprobar en 3.00.",
                "Utilizar el Tutor RAG del curso para practicar ejercicios sobre pgvector e índices HNSW.",
            ],
        },
        {
            "email": "mateo.gomez@softedu.edu.co",
            "first_name": "Mateo Alejandro",
            "last_name": "Gómez Silva",
            "doc": "1001298344",
            "code": "EST-2026-102",
            "program": "Ingeniería de Software",
            "semester": 6,
            "guardian": "Jorge Enrique Gómez (Padre)",
            "guardian_phone": "315-332-4490",
            "grades": [
                (1, "Parcial 1 - Persistencia Async", Decimal("30.00"), Decimal("4.60"), first_topic_id, "Excelente dominio del patrón Repositorio e inyección de dependencias."),
                (1, "Taller Práctico 1 - pgvector", Decimal("20.00"), Decimal("4.40"), second_topic_id, "Implementación sobresaliente de consultas por similitud coseno."),
            ],
            "attendances": [
                (date(2026, 8, 3), AttendanceStatus.PRESENT, "Participación destacada."),
                (date(2026, 8, 5), AttendanceStatus.PRESENT, "Entrega completa de laboratorio."),
                (date(2026, 8, 10), AttendanceStatus.PRESENT, "Asistencia puntual."),
                (date(2026, 8, 12), AttendanceStatus.PRESENT, "Lideró el ejercicio en equipo."),
                (date(2026, 8, 17), AttendanceStatus.PRESENT, "100% de asistencia en el corte."),
            ],
            "risk": RiskLevel.BAJO,
            "avg": Decimal("4.52"),
            "eval_w": Decimal("50.00"),
            "abs_pct": Decimal("0.00"),
            "summary": "Diagnóstico IA Positivo: Mateo Alejandro mantiene un rendimiento sobresaliente de 4.52/5.00 con 100% de asistencia efectiva. Solo necesita 1.48 en el 50% restante para asegurar la aprobación.",
            "factors": [
                "Promedio ponderado sobresaliente (4.52/5.00) en el primer 50% evaluado.",
                "Asistencia perfecta (0% de inasistencias injustificadas).",
            ],
            "teacher_actions": [
                "Vincular al estudiante como monitor par o líder técnico en los talleres de arquitectura RAG.",
            ],
            "student_actions": [
                "Mantener el ritmo de estudio y profundizar en los retos avanzados de despliegue en AWS.",
            ],
        },
        {
            "email": "valentina.herrera@softedu.edu.co",
            "first_name": "Valentina",
            "last_name": "Herrera Castro",
            "doc": "1002567891",
            "code": "EST-2026-103",
            "program": "Ingeniería de Sistemas",
            "semester": 6,
            "guardian": "Gloria Inés Castro (Madre)",
            "guardian_phone": "316-778-9012",
            "grades": [
                (1, "Parcial 1 - Persistencia Async", Decimal("30.00"), Decimal("3.20"), first_topic_id, "Aprobado en el límite; revisar manejo de excepciones."),
                (1, "Taller Práctico 1 - pgvector", Decimal("20.00"), Decimal("2.90"), second_topic_id, "Confusión menor en la configuración de dimensiones del vector."),
            ],
            "attendances": [
                (date(2026, 8, 3), AttendanceStatus.PRESENT, "Asistió."),
                (date(2026, 8, 5), AttendanceStatus.PRESENT, "Asistió."),
                (date(2026, 8, 10), AttendanceStatus.ABSENT, "Inasistencia reportada."),
                (date(2026, 8, 12), AttendanceStatus.PRESENT, "Asistió."),
                (date(2026, 8, 17), AttendanceStatus.ABSENT, "Falla en sesión de taller práctico."),
            ],
            "risk": RiskLevel.MEDIO,
            "avg": Decimal("3.08"),
            "eval_w": Decimal("50.00"),
            "abs_pct": Decimal("6.25"),
            "summary": "Atención Preventiva IA: Valentina presenta un promedio cercano al umbral mínimo (3.08/5.00) y una leve caída en el taller de pgvector (2.90) junto con 2 inasistencias. Se recomienda acompañamiento preventivo.",
            "factors": [
                "Promedio ponderado en franja límite (3.08/5.00).",
                "Nota inferior a 3.00 en el Taller Práctico de Búsqueda Semántica con pgvector (2.90).",
                "2 inasistencias registradas (6.25%).",
            ],
            "teacher_actions": [
                "Retroalimentar los errores del taller de pgvector antes de la evaluación del Corte 2.",
            ],
            "student_actions": [
                "Obtener al menos 2.92 en el 50% restante y evitar nuevas inasistencias a los laboratorios.",
            ],
        },
        {
            "email": "sebastian.vargas@softedu.edu.co",
            "first_name": "Sebastián Camilo",
            "last_name": "Vargas Díaz",
            "doc": "1003998120",
            "code": "EST-2026-104",
            "program": "Ingeniería de Software",
            "semester": 6,
            "guardian": "Carlos Arturo Vargas (Padre)",
            "guardian_phone": "320-551-6734",
            "grades": [
                (1, "Parcial 1 - Persistencia Async", Decimal("30.00"), Decimal("1.80"), first_topic_id, "No entregó el módulo de repositorio asíncrono."),
                (1, "Taller Práctico 1 - pgvector", Decimal("20.00"), Decimal("2.10"), second_topic_id, "Incompleto; requiere intervención inmediata."),
            ],
            "attendances": [
                (date(2026, 8, 3), AttendanceStatus.ABSENT, "No asistió a la sesión inaugural."),
                (date(2026, 8, 5), AttendanceStatus.ABSENT, "Inasistencia injustificada."),
                (date(2026, 8, 10), AttendanceStatus.ABSENT, "No se presentó al laboratorio."),
                (date(2026, 8, 12), AttendanceStatus.ABSENT, "Cuarta falla consecutiva."),
                (date(2026, 8, 17), AttendanceStatus.ABSENT, "Quinta falla; remitir a Psicoorientación."),
                (date(2026, 8, 19), AttendanceStatus.ABSENT, "Sexta inasistencia acumulada (18.75%)."),
            ],
            "risk": RiskLevel.CRITICO,
            "avg": Decimal("1.92"),
            "eval_w": Decimal("50.00"),
            "abs_pct": Decimal("18.75"),
            "summary": "ALERTA CRÍTICA INSTITUCIONAL: Sebastián Camilo presenta alto riesgo de pérdida académica y deserción. Promedio actual de 1.92/5.00 y 18.75% de inasistencias (a 1 falla de superar el tope máximo del 20%). Requiere intervención conjunta de Docente, Coordinación y Psicoorientación.",
            "factors": [
                "Promedio crítico de 1.92/5.00 en el 50% evaluado (necesita 4.08 en el 50% restante).",
                "6 inasistencias injustificadas (18.75%), al borde del límite reglamentario del 20.0%.",
                "Reprobación consecutiva en todos los temas evaluados de la Unidad 1.",
            ],
            "teacher_actions": [
                "Remitir caso de forma prioritaria a Coordinación Académica y Psicoorientación.",
                "Establecer compromiso académico escrito y plan de nivelación intensivo.",
            ],
            "student_actions": [
                "Asistir obligatoriamente al 100% de las sesiones restantes y presentar plan de nivelación.",
                "Alcanzar un promedio mínimo de 4.08 en el 50% restante del curso.",
            ],
        },
        {
            "email": "isabella.morales@softedu.edu.co",
            "first_name": "Isabella",
            "last_name": "Morales Ríos",
            "doc": "1004771239",
            "code": "EST-2026-105",
            "program": "Ingeniería de Sistemas",
            "semester": 6,
            "guardian": "Patricia Ríos Cano (Madre)",
            "guardian_phone": "311-904-5567",
            "grades": [
                (1, "Parcial 1 - Persistencia Async", Decimal("30.00"), Decimal("4.80"), first_topic_id, "Arquitectura impecable y código limpio PEP 8."),
                (1, "Taller Práctico 1 - pgvector", Decimal("20.00"), Decimal("4.90"), second_topic_id, "Mejor calificación del grupo en implementación RAG."),
            ],
            "attendances": [
                (date(2026, 8, 3), AttendanceStatus.PRESENT, "Asistencia puntual."),
                (date(2026, 8, 5), AttendanceStatus.PRESENT, "Asistencia puntual."),
                (date(2026, 8, 10), AttendanceStatus.PRESENT, "Asistencia puntual."),
                (date(2026, 8, 12), AttendanceStatus.EXCUSED, "Permiso institucional por ponencia en congreso."),
                (date(2026, 8, 17), AttendanceStatus.PRESENT, "Asistencia puntual."),
            ],
            "risk": RiskLevel.BAJO,
            "avg": Decimal("4.84"),
            "eval_w": Decimal("50.00"),
            "abs_pct": Decimal("0.00"),
            "summary": "Diagnóstico IA Excelente: Isabella lidera el rendimiento académico del grupo con promedio ponderado de 4.84/5.00 y 0% de fallas injustificadas.",
            "factors": [
                "Primer puesto académico del curso (4.84/5.00).",
                "0% de inasistencias injustificadas.",
            ],
            "teacher_actions": [
                "Postular a la estudiante al semillero de investigación en Inteligencia Artificial Aplicada.",
            ],
            "student_actions": [
                "Continuar con el desempeño sobresaliente; solo requiere 1.16 en el 50% restante.",
            ],
        },
    ]

    for s_data in students_seed_data:
        stu_user = (
            await session.execute(select(User).where(User.email == s_data["email"]))
        ).scalars().first()
        if stu_user is None:
            stu_user = User(
                email=s_data["email"],
                hashed_password=hash_password("estudiante123"),
                first_name=s_data["first_name"],
                last_name=s_data["last_name"],
                document_number=s_data["doc"],
                role=UserRole.ESTUDIANTE,
                job_title=f"Estudiante Activo - {s_data['program']}",
                department_area=s_data["program"],
                phone_number=s_data["guardian_phone"],
            )
            session.add(stu_user)
            await session.flush()
        else:
            stu_user.role = UserRole.ESTUDIANTE
            stu_user.job_title = f"Estudiante Activo - {s_data['program']}"
            stu_user.department_area = s_data["program"]

        stu_profile = (
            await session.execute(
                select(Student).where(Student.user_id == stu_user.id)
            )
        ).scalars().first()
        if stu_profile is None:
            stu_profile = Student(
                user_id=stu_user.id,
                student_code=s_data["code"],
                program_name=s_data["program"],
                current_semester=s_data["semester"],
                enrollment_cohort="2024-1",
                birth_date=date(2004, 5, 14),
                guardian_name=s_data["guardian"],
                guardian_phone=s_data["guardian_phone"],
            )
            session.add(stu_profile)
            await session.flush()
        else:
            stu_profile.guardian_name = s_data["guardian"]
            stu_profile.guardian_phone = s_data["guardian_phone"]

        enr = (
            await session.execute(
                select(Enrollment).where(
                    Enrollment.student_id == stu_profile.id,
                    Enrollment.course_offering_id == offering.id,
                )
            )
        ).scalars().first()
        if enr is None:
            enr = Enrollment(
                student_id=stu_profile.id,
                course_offering_id=offering.id,
                status=EnrollmentStatus.ACTIVE,
            )
            session.add(enr)
            await session.flush()

        # Sembrar notas iniciales si la matrícula aún no tiene notas
        existing_grades = list(
            (
                await session.execute(
                    select(Grade).where(Grade.enrollment_id == enr.id)
                )
            )
            .scalars()
            .all()
        )
        last_grade_id = None
        if not existing_grades:
            for cut_num, eval_name, weight_val, score_val, top_id, obs_txt in s_data["grades"]:
                g_obj = Grade(
                    enrollment_id=enr.id,
                    syllabus_topic_id=top_id,
                    evaluation_cut=cut_num,
                    evaluation_name=eval_name,
                    weight_percentage=weight_val,
                    score=score_val,
                    teacher_observations=obs_txt,
                    recorded_by_user_id=teacher_user_1.id,
                )
                session.add(g_obj)
                await session.flush()
                last_grade_id = g_obj.id
        else:
            last_grade_id = existing_grades[-1].id

        # Sembrar asistencias iniciales si aún no tiene asistencias
        existing_att = list(
            (
                await session.execute(
                    select(Attendance).where(Attendance.enrollment_id == enr.id)
                )
            )
            .scalars()
            .all()
        )
        if not existing_att:
            for att_date, att_status, att_obs in s_data["attendances"]:
                session.add(
                    Attendance(
                        enrollment_id=enr.id,
                        syllabus_topic_id=first_topic_id,
                        session_date=att_date,
                        status=att_status,
                        observations=att_obs,
                    )
                )
            await session.flush()

        # Sembrar diagnóstico IA vigente si no tiene
        existing_insight = (
            await session.execute(
                select(StudentAIInsight).where(
                    StudentAIInsight.enrollment_id == enr.id
                )
            )
        ).scalars().first()
        if existing_insight is None:
            needed = max(
                0.0,
                round(
                    float(
                        (Decimal("3.00") - (s_data["avg"] * Decimal("0.50")))
                        / Decimal("0.50")
                    ),
                    2,
                ),
            )
            session.add(
                StudentAIInsight(
                    enrollment_id=enr.id,
                    triggered_by_grade_id=last_grade_id,
                    risk_level=s_data["risk"],
                    accumulated_weighted_average=s_data["avg"],
                    evaluated_weight_percentage=s_data["eval_w"],
                    absence_percentage=s_data["abs_pct"],
                    detected_factors=s_data["factors"],
                    suggested_action_plan={
                        "acciones_docente": s_data["teacher_actions"],
                        "acciones_estudiante": s_data["student_actions"],
                        "temas_refuerzo_prioritarios": [
                            "Persistencia Asíncrona con SQLAlchemy 2.0",
                            "Búsqueda Semántica con pgvector e Índices HNSW",
                        ],
                        "meta_nota_restante_sugerida": needed,
                    },
                    executive_summary=s_data["summary"],
                    llm_model_used=f"google-genai:{settings.AI_MODEL_NAME}",
                    is_current_insight=True,
                )
            )

    await session.commit()
    logger.info("Ecosistema institucional SoftEdu (Rector, Coordinador, Secretaría, Orientador, Docentes y 5 Estudiantes) sembrado exitosamente.")
