"""Capa de Repositorio para Matrículas, Calificaciones, Asistencia, Vector Search e Insights de IA."""

from decimal import Decimal
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.academic import (
    CourseOffering,
    Enrollment,
    Grade,
    Student,
    StudentAIInsight,
    SyllabusTopic,
    SyllabusUnit,
)


class GradesRepository:
    """
    Repositorio asíncrono que encapsula todas las operaciones de persistencia
    y consultas analíticas/vectoriales relacionadas con calificaciones y boletines.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_enrollment_with_full_academic_context(
        self, enrollment_id: uuid.UUID
    ) -> Enrollment | None:
        """
        Obtiene una matrícula activa cargando de forma ansiosa (eager loading)
        estudiante, usuario, oferta de curso, materia, período, notas, asistencias e insights.
        """
        stmt = (
            select(Enrollment)
            .options(
                joinedload(Enrollment.student).joinedload(Student.user),
                joinedload(Enrollment.course_offering).joinedload(CourseOffering.subject),
                joinedload(Enrollment.course_offering).joinedload(
                    CourseOffering.academic_period
                ),
                selectinload(Enrollment.grades).joinedload(Grade.syllabus_topic),
                selectinload(Enrollment.attendances),
                selectinload(Enrollment.ai_insights),
            )
            .where(
                Enrollment.id == enrollment_id,
                Enrollment.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().unique().first()

    async def get_syllabus_topic_for_subject(
        self, topic_id: uuid.UUID, subject_id: uuid.UUID
    ) -> SyllabusTopic | None:
        """
        Verifica que un `SyllabusTopic` exista, esté activo y pertenezca a la materia
        de la oferta de curso en la que está matriculado el estudiante.
        """
        stmt = (
            select(SyllabusTopic)
            .join(SyllabusUnit, SyllabusTopic.unit_id == SyllabusUnit.id)
            .where(
                SyllabusTopic.id == topic_id,
                SyllabusUnit.subject_id == subject_id,
                SyllabusTopic.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_accumulated_weight_percentage(
        self, enrollment_id: uuid.UUID
    ) -> Decimal:
        """Calcula la suma actual de los pesos porcentuales registrados en la matrícula."""
        stmt = select(
            func.coalesce(func.sum(Grade.weight_percentage), Decimal("0.00"))
        ).where(
            Grade.enrollment_id == enrollment_id,
            Grade.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        total = result.scalar_one()
        return Decimal(str(total)).quantize(Decimal("0.01"))

    async def exists_evaluation_in_cut(
        self,
        enrollment_id: uuid.UUID,
        evaluation_cut: int,
        evaluation_name: str,
    ) -> bool:
        """Verifica si ya existe una nota con el mismo nombre y corte para esa matrícula."""
        stmt = select(Grade.id).where(
            Grade.enrollment_id == enrollment_id,
            Grade.evaluation_cut == evaluation_cut,
            func.lower(Grade.evaluation_name) == evaluation_name.lower(),
            Grade.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalars().first() is not None

    async def create_grade(self, grade: Grade) -> Grade:
        """Persiste una nueva calificación en la sesión actual."""
        self._session.add(grade)
        await self._session.flush()
        await self._session.refresh(grade)
        return grade

    async def search_similar_syllabus_topics(
        self,
        subject_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 3,
    ) -> list[SyllabusTopic]:
        """
        Realiza una búsqueda semántica vectorial en PostgreSQL (`pgvector`) usando
        distancia coseno (`<=>`) sobre los temas del sílabo de la asignatura.
        """
        stmt = (
            select(SyllabusTopic)
            .join(SyllabusUnit, SyllabusTopic.unit_id == SyllabusUnit.id)
            .where(
                SyllabusUnit.subject_id == subject_id,
                SyllabusTopic.is_active.is_(True),
                SyllabusTopic.embedding.is_not(None),
            )
            .order_by(SyllabusTopic.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def save_student_ai_insight(
        self, insight: StudentAIInsight
    ) -> StudentAIInsight:
        """
        Desmarca los diagnósticos previos de la matrícula (`is_current_insight = False`)
        y guarda el nuevo diagnóstico estructurado del Copiloto de IA como vigente.
        """
        await self._session.execute(
            update(StudentAIInsight)
            .where(
                StudentAIInsight.enrollment_id == insight.enrollment_id,
                StudentAIInsight.is_current_insight.is_(True),
            )
            .values(is_current_insight=False)
        )
        self._session.add(insight)
        await self._session.flush()
        await self._session.refresh(insight)
        return insight
