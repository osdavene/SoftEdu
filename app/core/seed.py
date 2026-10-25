"""
Inicialización automática de tablas (`Base.metadata.create_all`), actualización de
columnas y semilla completa de Colegios K-12 (Maternal a Grado 11°), Calendario A y B,
SuperAdmin Global, Rectores, Coordinación, Secretaría, Psicoorientación, Docentes y Estudiantes.
"""

from datetime import date
from decimal import Decimal
import logging
from typing import Any
import uuid

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
    SCHOOL_GRADES_CATALOG,
    SchoolInstitution,
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
    4. Inserta Colegios K-12 (Calendario A y B), SuperAdmin, Rectores y datos académicos.
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
        await _ensure_schema_columns_upgraded(conn)
        logger.info("Esquema de tablas SQLAlchemy 2.0 verificado en PostgreSQL.")

    async with AsyncSessionLocal() as session:
        await _seed_institutional_records(session)


async def _ensure_schema_columns_upgraded(conn: Any) -> None:
    """Garantiza que la tabla de colegios y las columnas nuevas existan sin error."""
    alter_statements = [
        """
        CREATE TABLE IF NOT EXISTS schools (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(30) UNIQUE NOT NULL,
            name VARCHAR(200) NOT NULL,
            dane_code VARCHAR(35) NOT NULL,
            nit VARCHAR(35) NOT NULL,
            calendar_type VARCHAR(25) DEFAULT 'CALENDARIO_A' NOT NULL,
            shift_type VARCHAR(40) DEFAULT 'JORNADA_UNICA' NOT NULL,
            city VARCHAR(100) DEFAULT 'Bogotá D.C.' NOT NULL,
            address VARCHAR(200),
            phone VARCHAR(50),
            email_contact VARCHAR(150),
            resolution_men VARCHAR(180),
            rector_user_id UUID,
            enabled_grades JSONB DEFAULT '[]'::jsonb NOT NULL,
            is_active BOOLEAN DEFAULT true NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
        );
        """,
        "ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(40) USING role::text;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS school_id UUID;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title VARCHAR(120);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department_area VARCHAR(120);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(40);",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS grade_level_code VARCHAR(30) DEFAULT 'GRADO_11';",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS guardian_name VARCHAR(150);",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS guardian_phone VARCHAR(40);",
        "ALTER TABLE course_offerings ADD COLUMN IF NOT EXISTS grade_level_code VARCHAR(30) DEFAULT 'GRADO_11';",
        "ALTER TABLE enrollments ALTER COLUMN status TYPE VARCHAR(30) USING status::text;",
        "ALTER TABLE attendances ALTER COLUMN status TYPE VARCHAR(30) USING status::text;",
        "ALTER TABLE student_ai_insights ALTER COLUMN risk_level TYPE VARCHAR(30) USING risk_level::text;",
    ]
    for stmt_sql in alter_statements:
        try:
            await conn.execute(text(stmt_sql))
        except Exception:
            pass


async def _upsert_user(
    session: AsyncSession,
    email: str,
    document_number: str,
    defaults: dict[str, Any],
) -> User:
    """Inserta o actualiza un usuario de forma resiliente ante colisiones de seed previo."""
    stmt = select(User).where(
        (func_lower := func_lower_helper(email)) | (User.document_number == document_number)
    )
    user = (await session.execute(stmt)).scalars().first()
    if user is None:
        user = User(
            email=email.lower(),
            document_number=document_number,
            **defaults,
        )
        session.add(user)
        await session.flush()
    else:
        user.email = email.lower()
        user.document_number = document_number
        for k, v in defaults.items():
            setattr(user, k, v)
        await session.flush()
    return user


def func_lower_helper(email: str):
    from sqlalchemy import func
    return func.lower(User.email) == email.lower()


async def _seed_institutional_records(session: AsyncSession) -> None:
    """Siembra el ecosistema de colegios K-12, SuperAdmin y comunidad escolar."""
    all_grades_codes = [g["code"] for g in SCHOOL_GRADES_CATALOG]

    # Colegio 1 (Gimnasio San Ángel - Calendario A)
    existing_school = (
        await session.execute(
            select(SchoolInstitution).where(SchoolInstitution.code == "COL-GSA-001")
        )
    ).scalars().first()

    if existing_school is None:
        logger.info("Sembrando Colegio 1 (Gimnasio San Ángel - Calendario A)...")
        school_1 = SchoolInstitution(
            code="COL-GSA-001",
            name="Colegio Bilingüe Gimnasio San Ángel",
            dane_code="311001098452",
            nit="900.845.120-4",
            calendar_type="CALENDARIO_A",
            shift_type="JORNADA_UNICA",
            city="Bogotá D.C.",
            address="Av. Calle 127 # 19-45, Usaquén",
            phone="+57 (601) 629-4400",
            email_contact="contacto@gimnasiosanangel.edu.co",
            resolution_men="Resolución SED N.° 11-0482 de Educación Preescolar, Básica y Media",
            enabled_grades=all_grades_codes,
        )
        session.add(school_1)
        await session.flush()
    else:
        school_1 = existing_school
        if not school_1.enabled_grades:
            school_1.enabled_grades = all_grades_codes

    # Colegio 2 (Colegio Campestre La Colina - Calendario B)
    school_2 = (
        await session.execute(
            select(SchoolInstitution).where(SchoolInstitution.code == "COL-CLC-002")
        )
    ).scalars().first()

    if school_2 is None:
        logger.info("Sembrando Colegio 2 (Colegio Campestre La Colina - Calendario B)...")
        school_2 = SchoolInstitution(
            code="COL-CLC-002",
            name="Colegio Campestre La Colina",
            dane_code="311001087123",
            nit="901.320.450-8",
            calendar_type="CALENDARIO_B",
            shift_type="COMPLETA",
            city="Chía, Cundinamarca",
            address="Km 4 Vía Chía - Cajicá",
            phone="+57 (601) 862-9010",
            email_contact="admisiones@lacolina.edu.co",
            resolution_men="Resolución Secretaría de Educación N.° 2021-089",
            enabled_grades=[
                "MATERNAL", "PARVULOS", "PREJARDIN", "JARDIN", "TRANSICION",
                "GRADO_1", "GRADO_2", "GRADO_3", "GRADO_4", "GRADO_5",
            ],
        )
        session.add(school_2)
        await session.flush()

    # 1. SuperAdmin Global (Acceso al SuperPanel)
    superadmin = await _upsert_user(
        session=session,
        email="superadmin@softedu.co",
        document_number="SUPER-001",
        defaults={
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "SuperAdmin",
            "last_name": "Global",
            "role": UserRole.SUPERADMIN,
            "job_title": "Director de Gobierno y Plataforma SaaS K-12",
            "department_area": "Gobierno Corporativo SoftEdu",
            "phone_number": "+57 300 000 0001",
        },
    )

    # 2. Rector del Colegio 1 (Gimnasio San Ángel)
    rector_1 = await _upsert_user(
        session=session,
        email="rector@gimnasiosanangel.edu.co",
        document_number="79450112",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Dr. Fernando",
            "last_name": "Molina Villamizar",
            "role": UserRole.RECTOR,
            "job_title": "Rector General Institucional",
            "department_area": "Rectoría y Consejo Directivo",
            "phone_number": "+57 (601) 629-4401",
        },
    )
    school_1.rector_user_id = rector_1.id

    # Rector del Colegio 2 (La Colina - Calendario B)
    rector_2 = await _upsert_user(
        session=session,
        email="rector@lacolina.edu.co",
        document_number="52981045",
        defaults={
            "school_id": school_2.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Dra. Beatriz Eugenia",
            "last_name": "Restrepo Gómez",
            "role": UserRole.RECTOR,
            "job_title": "Rectora General — Colegio Campestre La Colina",
            "department_area": "Rectoría y Dirección Bilingüe",
            "phone_number": "+57 (601) 862-9011",
        },
    )
    school_2.rector_user_id = rector_2.id

    # 3. Equipo Directivo y Administrativo del Colegio 1
    # Coordinadora Académica
    coordinadora = await _upsert_user(
        session=session,
        email="coordinador@gimnasiosanangel.edu.co",
        document_number="52890341",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Mg. Claudia Patricia",
            "last_name": "Gómez Salazar",
            "role": UserRole.COORDINADOR,
            "job_title": "Coordinadora Académica de Preescolar, Primaria y Bachillerato",
            "department_area": "Coordinación Académica y Convivencia",
            "phone_number": "+57 315 820 3344",
        },
    )

    # Secretaría Académica y Matrículas
    secretaria = await _upsert_user(
        session=session,
        email="secretaria@gimnasiosanangel.edu.co",
        document_number="1018432098",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Lic. Martha Lucía",
            "last_name": "Pineda Restrepo",
            "role": UserRole.SECRETARIA,
            "job_title": "Secretaria General, SIMAT y Matrículas",
            "department_area": "Secretaría Académica y Admisiones",
            "phone_number": "+57 318 640 1122",
        },
    )

    # Psicoorientador Escolar
    orientador = await _upsert_user(
        session=session,
        email="orientador@gimnasiosanangel.edu.co",
        document_number="1032455901",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Ps. Julián Andrés",
            "last_name": "Orozco Lozano",
            "role": UserRole.ORIENTADOR,
            "job_title": "Psicoorientador Escolar y Bienestar Familiar",
            "department_area": "Departamento de Orientación y Familia",
            "phone_number": "+57 300 711 8900",
        },
    )

    # Docente Titular de Matemáticas
    docente_user = await _upsert_user(
        session=session,
        email="docente@gimnasiosanangel.edu.co",
        document_number="79840120",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Dr. Carlos Eduardo",
            "last_name": "Mendoza Gómez",
            "role": UserRole.DOCENTE,
            "job_title": "Docente Titular de Matemáticas y Director de Grupo 11°A",
            "department_area": "Área de Matemáticas y Ciencias Naturales",
            "phone_number": "+57 312 409 2210",
        },
    )

    teacher_prof = (
        await session.execute(
            select(Teacher).where(Teacher.user_id == docente_user.id)
        )
    ).scalars().first()
    if teacher_prof is None:
        teacher_prof = Teacher(
            user_id=docente_user.id,
            employee_code="DOC-COL-001",
            department="Área de Matemáticas",
            specialization="Licenciatura en Matemáticas y Física (Magíster en Educación)",
            academic_degree="Magíster en Didáctica de las Ciencias",
            max_weekly_hours=35,
        )
        session.add(teacher_prof)
        await session.flush()

    # Docente Titular 2 (Lengua Castellana)
    docente_user_2 = await _upsert_user(
        session=session,
        email="diana.docente@gimnasiosanangel.edu.co",
        document_number="53119874",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Mg. Diana Marcela",
            "last_name": "Castro Valenzuela",
            "role": UserRole.DOCENTE,
            "job_title": "Docente Titular de Lengua Castellana y Literatura",
            "department_area": "Área de Humanidades y Lengua Castellana",
            "phone_number": "+57 314 298 7741",
        },
    )

    teacher_prof_2 = (
        await session.execute(
            select(Teacher).where(Teacher.user_id == docente_user_2.id)
        )
    ).scalars().first()
    if teacher_prof_2 is None:
        teacher_prof_2 = Teacher(
            user_id=docente_user_2.id,
            employee_code="DOC-COL-002",
            department="Área de Humanidades",
            specialization="Licenciatura en Lenguas y Literatura",
            academic_degree="Magíster en Lingüística Aplicada",
            max_weekly_hours=32,
        )
        session.add(teacher_prof_2)
        await session.flush()

    # 4. Período Lectivo Escolar (Calendario A)
    period = (
        await session.execute(
            select(AcademicPeriod).where(AcademicPeriod.code == "2026-CAL-A")
        )
    ).scalars().first()
    if period is None:
        period = AcademicPeriod(
            code="2026-CAL-A",
            name="Año Lectivo Escolar 2026 (Calendario A — Feb a Nov)",
            start_date=date(2026, 2, 2),
            end_date=date(2026, 11, 27),
            is_current=True,
        )
        session.add(period)
        await session.flush()

    # 5. Asignaturas Escolares (MEN)
    subject_mat = (
        await session.execute(select(Subject).where(Subject.code == "MAT-11"))
    ).scalars().first()
    if subject_mat is None:
        subject_mat = Subject(
            code="MAT-11",
            name="Matemáticas y Cálculo Diferencial — Grado 11°",
            description="Cálculo diferencial, funciones trascendentes, trigonometría analítica y preparación Prueba Saber 11 (ICFES).",
            credits=4,
            weekly_hours=5,
            minimum_passing_grade=Decimal("3.00"),
        )
        session.add(subject_mat)
        await session.flush()

    # Sílabo oficial vectorizado de la materia
    units = list(
        (await session.execute(select(SyllabusUnit).where(SyllabusUnit.subject_id == subject_mat.id)))
        .scalars()
        .all()
    )
    if not units:
        unit1 = SyllabusUnit(
            subject_id=subject_mat.id,
            unit_number=1,
            title="Funciones Reales y Límites de Funciones",
            learning_objective="Comprender el concepto de límite algebraico y gráfico con aplicaciones al cambio de razones.",
            estimated_weeks=4,
        )
        unit2 = SyllabusUnit(
            subject_id=subject_mat.id,
            unit_number=2,
            title="Derivadas, Reglas de Derivación y Optimización",
            learning_objective="Calcular derivadas aplicando reglas del producto y de la cadena para resolver problemas de optimización.",
            estimated_weeks=4,
        )
        session.add_all([unit1, unit2])
        await session.flush()

        topic1 = SyllabusTopic(
            unit_id=unit1.id,
            topic_number=1,
            title="Definición Formal de Límite y Límites Laterales",
            content_description="Propiedades fundamentales de los límites, continuidad puntual y discontinuidades evitables.",
            key_concepts=["Límite", "Continuidad", "Asíntota", "Épsilon-Delta"],
            bibliography_references="Cálculo con Geometría Analítica — Stewart 8.ª Ed.",
        )
        topic2 = SyllabusTopic(
            unit_id=unit1.id,
            topic_number=2,
            title="Formas Indeterminadas 0/0 e Infinito sobre Infinito",
            content_description="Técnicas de factorización, racionalización conjugada y regla de L'Hôpital.",
            key_concepts=["Indeterminación", "Racionalización", "Factorización", "L'Hôpital"],
            bibliography_references="Cálculo Diferencial e Integral — Purcel 9.ª Ed.",
        )
        topic3 = SyllabusTopic(
            unit_id=unit2.id,
            topic_number=3,
            title="La Derivada como Pendiente de la Recta Tangente y Razón de Cambio",
            content_description="Interpretación geométrica y física de la derivada instantánea con aplicaciones a velocidad y aceleración.",
            key_concepts=["Derivada", "Recta Tangente", "Razón de Cambio", "Velocidad"],
            bibliography_references="Matemáticas Avanzadas para Bachillerato — Santillana",
        )
        session.add_all([topic1, topic2, topic3])
        await session.flush()

        ai_svc = AcademicAIService()
        for t in [topic1, topic2, topic3]:
            try:
                emb = await ai_svc.generate_embedding_text(
                    f"{t.title}. {t.content_description}. Conceptos: {', '.join(t.key_concepts)}"
                )
                t.embedding = emb
            except Exception:
                pass

    # 6. Oferta de Curso / Horario Escolar Semanal (Grado 11°A)
    course_off = (
        await session.execute(
            select(CourseOffering).where(
                CourseOffering.subject_id == subject_mat.id,
                CourseOffering.academic_period_id == period.id,
                CourseOffering.group_code == "11°A",
            )
        )
    ).scalars().first()
    if course_off is None:
        course_off = CourseOffering(
            subject_id=subject_mat.id,
            teacher_id=teacher_prof.id,
            academic_period_id=period.id,
            group_code="11°A",
            grade_level_code="GRADO_11",
            max_capacity=30,
            total_planned_sessions=36,
            schedule_blocks=[
                {
                    "day": "LUNES",
                    "start_time": "07:00",
                    "end_time": "08:30",
                    "classroom": "Salón 11°A (Bloque B-201)",
                },
                {
                    "day": "MIERCOLES",
                    "start_time": "08:30",
                    "end_time": "10:00",
                    "classroom": "Salón 11°A (Bloque B-201)",
                },
                {
                    "day": "VIERNES",
                    "start_time": "10:30",
                    "end_time": "12:00",
                    "classroom": "Laboratorio de Ciencias y Matemáticas",
                },
            ],
        )
        session.add(course_off)
        await session.flush()

    # 7. Estudiantes de Demostración
    # Estudiante 1: Laura Sofía Rodríguez (Grado 11°A — Desempeño Superior, Riesgo BAJO)
    laura_user = await _upsert_user(
        session=session,
        email="laura.rodriguez@gimnasiosanangel.edu.co",
        document_number="1025890123",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Laura Sofía",
            "last_name": "Rodríguez Peña",
            "role": UserRole.ESTUDIANTE,
            "job_title": "Estudiante — Grado 11°A",
            "department_area": "Educación Media Vocacional",
            "phone_number": "+57 316 789 0123",
        },
    )

    laura_student = (
        await session.execute(
            select(Student).where(Student.user_id == laura_user.id)
        )
    ).scalars().first()
    if laura_student is None:
        laura_student = Student(
            user_id=laura_user.id,
            student_code="COL-2026-101",
            grade_level_code="GRADO_11",
            program_name="Grado Undécimo (11° Promoción Saber 11)",
            current_semester=11,
            enrollment_cohort="2026-CAL-A",
            birth_date=date(2009, 4, 18),
            guardian_name="Ing. Andrés Rodríguez (Padre de Familia)",
            guardian_phone="+57 310 450 7890",
        )
        session.add(laura_student)
        await session.flush()

    # Estudiante 2: Mateo Alejandro Gómez (Grado 11°A — Desempeño Bajo 2.15, Alerta IA CRÍTICA)
    mateo_user = await _upsert_user(
        session=session,
        email="mateo.gomez@gimnasiosanangel.edu.co",
        document_number="1025890124",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Mateo Alejandro",
            "last_name": "Gómez Cárdenas",
            "role": UserRole.ESTUDIANTE,
            "job_title": "Estudiante — Grado 11°A",
            "department_area": "Educación Media Vocacional",
            "phone_number": "+57 317 654 3210",
        },
    )

    mateo_student = (
        await session.execute(
            select(Student).where(Student.user_id == mateo_user.id)
        )
    ).scalars().first()
    if mateo_student is None:
        mateo_student = Student(
            user_id=mateo_user.id,
            student_code="COL-2026-102",
            grade_level_code="GRADO_11",
            program_name="Grado Undécimo (11° Promoción Saber 11)",
            current_semester=11,
            enrollment_cohort="2026-CAL-A",
            birth_date=date(2009, 6, 12),
            guardian_name="Dra. Patricia Cárdenas (Madre de Familia)",
            guardian_phone="+57 311 223 3445",
        )
        session.add(mateo_student)
        await session.flush()

    # Estudiante 3: Valentina Herrera (Grado 11°A — Desempeño Básico 3.40, Riesgo MEDIO)
    valentina_user = await _upsert_user(
        session=session,
        email="valentina.herrera@gimnasiosanangel.edu.co",
        document_number="1025890125",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Valentina",
            "last_name": "Herrera Morales",
            "role": UserRole.ESTUDIANTE,
            "job_title": "Estudiante — Grado 11°A",
            "department_area": "Educación Media Vocacional",
            "phone_number": "+57 319 888 7766",
        },
    )

    valentina_student = (
        await session.execute(
            select(Student).where(Student.user_id == valentina_user.id)
        )
    ).scalars().first()
    if valentina_student is None:
        valentina_student = Student(
            user_id=valentina_user.id,
            student_code="COL-2026-103",
            grade_level_code="GRADO_11",
            program_name="Grado Undécimo (11° Promoción Saber 11)",
            current_semester=11,
            enrollment_cohort="2026-CAL-A",
            birth_date=date(2009, 9, 25),
            guardian_name="Don Javier Herrera (Padre de Familia)",
            guardian_phone="+57 312 999 1122",
        )
        session.add(valentina_student)
        await session.flush()

    # Estudiante 4: Sebastián Vargas (Grado 5° Primaria)
    sebastian_user = await _upsert_user(
        session=session,
        email="sebastian.vargas@gimnasiosanangel.edu.co",
        document_number="1089234567",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Sebastián",
            "last_name": "Vargas Duarte",
            "role": UserRole.ESTUDIANTE,
            "job_title": "Estudiante — Grado 5°A Primaria",
            "department_area": "Educación Básica Primaria",
            "phone_number": "+57 320 555 4321",
        },
    )

    sebastian_student = (
        await session.execute(
            select(Student).where(Student.user_id == sebastian_user.id)
        )
    ).scalars().first()
    if sebastian_student is None:
        sebastian_student = Student(
            user_id=sebastian_user.id,
            student_code="COL-2026-501",
            grade_level_code="GRADO_5",
            program_name="Grado Quinto (5° Primaria)",
            current_semester=5,
            enrollment_cohort="2026-CAL-A",
            birth_date=date(2015, 8, 14),
            guardian_name="Sra. Mónica Duarte (Madre de Familia)",
            guardian_phone="+57 315 444 7788",
        )
        session.add(sebastian_student)
        await session.flush()

    # Estudiante 5: Isabella Morales (Transición / Grado 0° Preescolar)
    isabella_user = await _upsert_user(
        session=session,
        email="isabella.morales@gimnasiosanangel.edu.co",
        document_number="1198345678",
        defaults={
            "school_id": school_1.id,
            "hashed_password": hash_password("SoftEdu2026*"),
            "first_name": "Isabella",
            "last_name": "Morales Castro",
            "role": UserRole.ESTUDIANTE,
            "job_title": "Estudiante — Transición (Preescolar)",
            "department_area": "Educación Inicial y Preescolar",
            "phone_number": "+57 321 777 8899",
        },
    )

    isabella_student = (
        await session.execute(
            select(Student).where(Student.user_id == isabella_user.id)
        )
    ).scalars().first()
    if isabella_student is None:
        isabella_student = Student(
            user_id=isabella_user.id,
            student_code="COL-2026-001",
            grade_level_code="TRANSICION",
            program_name="Transición / Grado 0° (Preescolar)",
            current_semester=0,
            enrollment_cohort="2026-CAL-A",
            birth_date=date(2020, 11, 5),
            guardian_name="Dra. Camilo Morales (Padre de Familia)",
            guardian_phone="+57 318 333 2211",
        )
        session.add(isabella_student)
        await session.flush()

    # Matricular estudiantes en el grupo 11°A para interactuar con la planilla completa
    first_topics = list(
        (await session.execute(select(SyllabusTopic).order_by(SyllabusTopic.topic_number.asc()))).scalars().all()
    )
    t1 = first_topics[0] if first_topics else None
    t2 = first_topics[1] if len(first_topics) > 1 else t1

    students_to_enroll = [laura_student, mateo_student, valentina_student, sebastian_student, isabella_student]
    for s_item in students_to_enroll:
        enr = (
            await session.execute(
                select(Enrollment).where(
                    Enrollment.student_id == s_item.id,
                    Enrollment.course_offering_id == course_off.id,
                )
            )
        ).scalars().first()
        if enr is None:
            enr = Enrollment(
                student_id=s_item.id,
                course_offering_id=course_off.id,
                status=EnrollmentStatus.ACTIVE,
            )
            session.add(enr)
            await session.flush()

            # Notas de ejemplo para Laura (Sobresaliente)
            if s_item.student_code == "COL-2026-101":
                g1 = Grade(
                    enrollment_id=enr.id,
                    syllabus_topic_id=t1.id if t1 else None,
                    evaluation_cut=1,
                    evaluation_name="Taller de Límites Algebraicos",
                    weight_percentage=Decimal("15.00"),
                    score=Decimal("4.80"),
                )
                g2 = Grade(
                    enrollment_id=enr.id,
                    syllabus_topic_id=t2.id if t2 else None,
                    evaluation_cut=1,
                    evaluation_name="Evaluación Parcial Tipo Saber 11",
                    weight_percentage=Decimal("20.00"),
                    score=Decimal("4.90"),
                )
                a1 = Attendance(
                    enrollment_id=enr.id,
                    syllabus_topic_id=t1.id if t1 else None,
                    session_date=date(2026, 2, 9),
                    status=AttendanceStatus.PRESENT,
                    observations="Participación activa en el tablero.",
                )
                insight_l = StudentAIInsight(
                    enrollment_id=enr.id,
                    risk_level=RiskLevel.BAJO,
                    accumulated_weighted_average=Decimal("4.86"),
                    evaluated_weight_percentage=Decimal("35.00"),
                    absence_percentage=Decimal("0.00"),
                    detected_factors=["Excelente asimilación conceptual", "Asistencia perfecta (100%)"],
                    suggested_action_plan={
                        "plan_estudiante": [
                            "Continuar con el banco de ejercicios avanzados de optimización.",
                            "Postularse como monitora académica de apoyo a sus compañeros de grado.",
                        ],
                        "plan_docente": [
                            "Proponerle retos de nivel olimpiada matemática colombiana para profundizar.",
                        ],
                    },
                    executive_summary="Rendimiento académico superior. Demuestra dominio total de las competencias evaluadas sin registrar inasistencias.",
                    llm_model_used="google/gemini-2.0-pro (Copiloto SoftEdu)",
                    is_current_insight=True,
                )
                session.add_all([g1, g2, a1, insight_l])

            # Notas de ejemplo para Mateo (Riesgo Crítico)
            elif s_item.student_code == "COL-2026-102":
                g1_m = Grade(
                    enrollment_id=enr.id,
                    syllabus_topic_id=t1.id if t1 else None,
                    evaluation_cut=1,
                    evaluation_name="Taller de Límites Algebraicos",
                    weight_percentage=Decimal("15.00"),
                    score=Decimal("2.20"),
                )
                g2_m = Grade(
                    enrollment_id=enr.id,
                    syllabus_topic_id=t2.id if t2 else None,
                    evaluation_cut=1,
                    evaluation_name="Evaluación Parcial Tipo Saber 11",
                    weight_percentage=Decimal("20.00"),
                    score=Decimal("2.10"),
                )
                a1_m = Attendance(
                    enrollment_id=enr.id,
                    syllabus_topic_id=t1.id if t1 else None,
                    session_date=date(2026, 2, 9),
                    status=AttendanceStatus.ABSENT,
                    observations="No asistió a clase sin justificación médica.",
                )
                a2_m = Attendance(
                    enrollment_id=enr.id,
                    syllabus_topic_id=t2.id if t2 else None,
                    session_date=date(2026, 2, 11),
                    status=AttendanceStatus.LATE,
                    observations="Ingresó con 25 minutos de retardo al salón.",
                )
                insight_m = StudentAIInsight(
                    enrollment_id=enr.id,
                    risk_level=RiskLevel.CRITICO,
                    accumulated_weighted_average=Decimal("2.14"),
                    evaluated_weight_percentage=Decimal("35.00"),
                    absence_percentage=Decimal("22.50"),
                    detected_factors=[
                        "Promedio ponderado acumulado (2.14) significativamente inferior a la nota aprobatoria (3.00)",
                        "Inasistencia reiterada (22.5%) cercana al límite de reprobación por fallas",
                        "Vacíos graves en conceptos previos de factorización y formas indeterminadas",
                    ],
                    suggested_action_plan={
                        "plan_estudiante": [
                            "Asistir obligatoriamente a las tutorías de nivelación de los martes a las 14:30.",
                            "Completar la guía de refuerzo remedial de límites con apoyo del Tutor IA.",
                            "Justificar de inmediato las inasistencias con la coordinación de convivencia.",
                        ],
                        "plan_docente": [
                            "Citar urgentemente a los padres de familia / acudientes ante orientación escolar.",
                            "Aplicar evaluación remedial de recuperación según Decreto 1290 MEN.",
                        ],
                    },
                    executive_summary="Alerta de Riesgo Académico Crítico. El estudiante reprueba las evaluaciones del primer corte y acumula un alto porcentaje de inasistencias injustificadas.",
                    llm_model_used="google/gemini-2.0-pro (Copiloto SoftEdu)",
                    is_current_insight=True,
                )
                session.add_all([g1_m, g2_m, a1_m, a2_m, insight_m])

    await session.commit()
    logger.info("Ecosistema institucional SoftEdu K-12 (Colegios Calendario A y B, SuperAdmin, Rectores, Docentes y Estudiantes) sembrado exitosamente.")
