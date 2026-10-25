"""
Repositorio Asíncrono para el Sílabo Vectorizado y Búsqueda Semántica (`pgvector`).
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.academic import Subject, SyllabusTopic, SyllabusUnit


class SyllabusRepository:
    """
    Encapsula las operaciones CRUD jerárquicas (`Subject -> SyllabusUnit -> SyllabusTopic`)
    y las consultas de similitud vectorial (`pgvector`) para el motor RAG.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_subject_by_id(self, subject_id: uuid.UUID) -> Subject | None:
        """Recupera una materia activa por su UUID."""
        stmt = select(Subject).where(
            Subject.id == subject_id,
            Subject.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_subject_with_full_syllabus(
        self, subject_id: uuid.UUID
    ) -> Subject | None:
        """
        Recupera una materia cargando toda su jerarquía de unidades y temas ordenados.
        """
        stmt = (
            select(Subject)
            .options(
                selectinload(Subject.syllabus_units).selectinload(SyllabusUnit.topics)
            )
            .where(
                Subject.id == subject_id,
                Subject.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().unique().first()

    async def get_unit_with_subject(self, unit_id: uuid.UUID) -> SyllabusUnit | None:
        """Recupera una unidad del sílabo junto con su asignatura."""
        stmt = (
            select(SyllabusUnit)
            .options(joinedload(SyllabusUnit.subject))
            .where(
                SyllabusUnit.id == unit_id,
                SyllabusUnit.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def exists_unit_number_in_subject(
        self, subject_id: uuid.UUID, unit_number: int
    ) -> bool:
        """Verifica si ya existe ese número de unidad dentro de la materia."""
        stmt = select(SyllabusUnit.id).where(
            SyllabusUnit.subject_id == subject_id,
            SyllabusUnit.unit_number == unit_number,
            SyllabusUnit.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalars().first() is not None

    async def create_unit(self, unit: SyllabusUnit) -> SyllabusUnit:
        """Persiste una nueva unidad temática en la sesión actual."""
        self._session.add(unit)
        await self._session.flush()
        await self._session.refresh(unit)
        return unit

    async def exists_topic_number_in_unit(
        self, unit_id: uuid.UUID, topic_number: int
    ) -> bool:
        """Verifica si ya existe ese número de tema dentro de la unidad."""
        stmt = select(SyllabusTopic.id).where(
            SyllabusTopic.unit_id == unit_id,
            SyllabusTopic.topic_number == topic_number,
            SyllabusTopic.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalars().first() is not None

    async def create_topic(self, topic: SyllabusTopic) -> SyllabusTopic:
        """Persiste un nuevo tema del sílabo en la sesión actual."""
        self._session.add(topic)
        await self._session.flush()
        await self._session.refresh(topic)
        return topic

    async def get_topic_with_unit_and_subject(
        self, topic_id: uuid.UUID
    ) -> SyllabusTopic | None:
        """
        Obtiene un `SyllabusTopic` cargando su `SyllabusUnit` y su `Subject`.
        """
        stmt = (
            select(SyllabusTopic)
            .options(
                joinedload(SyllabusTopic.unit).joinedload(SyllabusUnit.subject)
            )
            .where(
                SyllabusTopic.id == topic_id,
                SyllabusTopic.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def update_topic_embedding(
        self,
        topic_id: uuid.UUID,
        embedding_vector: list[float],
    ) -> None:
        """Actualiza la columna vectorial `embedding` en `pgvector` para un tema."""
        stmt = (
            update(SyllabusTopic)
            .where(SyllabusTopic.id == topic_id)
            .values(embedding=embedding_vector)
        )
        await self._session.execute(stmt)

    async def search_topics_by_cosine_similarity(
        self,
        subject_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 3,
    ) -> list[tuple[SyllabusTopic, float]]:
        """
        Ejecuta búsqueda semántica vectorial en PostgreSQL (`pgvector`) usando el
        operador de distancia coseno (`<=>`).
        Retorna una lista de tuplas `(SyllabusTopic, cosine_similarity_score)`.
        """
        distance_expr = SyllabusTopic.embedding.cosine_distance(query_embedding)
        similarity_expr = (1.0 - distance_expr).label("cosine_similarity")

        stmt = (
            select(SyllabusTopic, similarity_expr)
            .join(SyllabusUnit, SyllabusTopic.unit_id == SyllabusUnit.id)
            .options(joinedload(SyllabusTopic.unit))
            .where(
                SyllabusUnit.subject_id == subject_id,
                SyllabusUnit.is_active.is_(True),
                SyllabusTopic.is_active.is_(True),
                SyllabusTopic.embedding.is_not(None),
            )
            .order_by(distance_expr.asc())
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        matched_with_scores: list[tuple[SyllabusTopic, float]] = []
        for topic_obj, raw_sim in rows:
            clamped_sim = max(0.0, min(1.0, float(raw_sim or 0.0)))
            matched_with_scores.append((topic_obj, round(clamped_sim, 4)))

        if matched_with_scores:
            return matched_with_scores

        # Contingencia: si aún hay temas sin vectorizar, recupera los primeros temas activos de la materia
        fallback_stmt = (
            select(SyllabusTopic)
            .join(SyllabusUnit, SyllabusTopic.unit_id == SyllabusUnit.id)
            .options(joinedload(SyllabusTopic.unit))
            .where(
                SyllabusUnit.subject_id == subject_id,
                SyllabusUnit.is_active.is_(True),
                SyllabusTopic.is_active.is_(True),
            )
            .order_by(SyllabusUnit.unit_number.asc(), SyllabusTopic.topic_number.asc())
            .limit(top_k)
        )
        fallback_res = await self._session.execute(fallback_stmt)
        return [(topic, 0.50) for topic in fallback_res.scalars().all()]
