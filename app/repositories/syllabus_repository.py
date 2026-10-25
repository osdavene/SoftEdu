"""
Repositorio Asíncrono para el Sílabo Vectorizado y Búsqueda Semántica (`pgvector`).
"""

import math
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.database import is_pgvector_enabled
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
        operador de distancia coseno (`<=>`). Si el servidor local no tiene la extensión
        nativa C `vector`, calcula la similitud coseno exacta sobre los vectores almacenados.
        """
        if is_pgvector_enabled():
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

        # Modo híbrido / compatibilidad local: cálculo exacto de similitud coseno
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
        )
        all_topics = list((await self._session.execute(fallback_stmt)).scalars().all())
        scored: list[tuple[SyllabusTopic, float]] = []
        for t in all_topics:
            if t.embedding:
                sim = self._compute_cosine_similarity(query_embedding, list(t.embedding))
            else:
                sim = 0.50
            scored.append((t, round(max(0.0, min(1.0, sim)), 4)))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.50
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
        norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
        raw = dot / (norm_a * norm_b)
        return (raw + 1.0) / 2.0 if raw < 0 else raw
