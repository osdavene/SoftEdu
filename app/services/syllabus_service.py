"""
Capa de Servicio de Dominio para el Sílabo Vectorizado, Asistente Curricular y Tutor RAG.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_service import AcademicAIService
from app.core.exceptions import BusinessRuleViolationError, EntityNotFoundError
from app.models.academic import SyllabusTopic, SyllabusUnit
from app.repositories.syllabus_repository import SyllabusRepository
from app.schemas.syllabus import (
    CurricularMaterialGenerationRequest,
    CurricularMaterialGenerationResponse,
    RAGTutorQueryRequest,
    RAGTutorQueryResponse,
    RetrievedSyllabusContextItem,
    SubjectSyllabusTreeResponse,
    SyllabusTopicCreate,
    SyllabusTopicResponse,
    SyllabusUnitCreate,
    SyllabusUnitWithTopicsResponse,
)


class SyllabusService:
    """
    Orquesta la gestión jerárquica del sílabo (`Materia -> Unidad -> Tema`),
    la generación de material curricular para docentes y las consultas al Tutor RAG.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SyllabusRepository(session)

    async def create_syllabus_unit(
        self, payload: SyllabusUnitCreate
    ) -> SyllabusUnitWithTopicsResponse:
        """
        Registra una nueva Unidad Temática validando la existencia de la Materia
        y la unicidad del número de unidad (`unit_number`).
        """
        subject = await self._repo.get_subject_by_id(payload.subject_id)
        if subject is None:
            raise EntityNotFoundError("Subject", payload.subject_id)

        already_exists = await self._repo.exists_unit_number_in_subject(
            subject_id=payload.subject_id,
            unit_number=payload.unit_number,
        )
        if already_exists:
            raise BusinessRuleViolationError(
                message=(
                    f"La asignatura '{subject.name}' ya tiene registrada una "
                    f"Unidad número {payload.unit_number}."
                ),
                rule_code="DUPLICATE_SYLLABUS_UNIT_NUMBER",
            )

        new_unit = SyllabusUnit(
            subject_id=payload.subject_id,
            unit_number=payload.unit_number,
            title=payload.title,
            learning_objective=payload.learning_objective,
            estimated_weeks=payload.estimated_weeks,
        )
        created_unit = await self._repo.create_unit(new_unit)
        await self._session.commit()

        return SyllabusUnitWithTopicsResponse(
            id=created_unit.id,
            subject_id=created_unit.subject_id,
            unit_number=created_unit.unit_number,
            title=created_unit.title,
            learning_objective=created_unit.learning_objective,
            estimated_weeks=created_unit.estimated_weeks,
            topics=[],
        )

    async def create_syllabus_topic(
        self, payload: SyllabusTopicCreate
    ) -> SyllabusTopicResponse:
        """
        Registra un nuevo Tema (`SyllabusTopic`) dentro de una Unidad y confirma
        la transacción para que `BackgroundTasks` proceda a su vectorización en `pgvector`.
        """
        unit = await self._repo.get_unit_with_subject(payload.unit_id)
        if unit is None:
            raise EntityNotFoundError("SyllabusUnit", payload.unit_id)

        already_exists = await self._repo.exists_topic_number_in_unit(
            unit_id=payload.unit_id,
            topic_number=payload.topic_number,
        )
        if already_exists:
            raise BusinessRuleViolationError(
                message=(
                    f"La Unidad {unit.unit_number} ('{unit.title}') ya posee un "
                    f"Tema número {payload.topic_number}."
                ),
                rule_code="DUPLICATE_SYLLABUS_TOPIC_NUMBER",
            )

        new_topic = SyllabusTopic(
            unit_id=payload.unit_id,
            topic_number=payload.topic_number,
            title=payload.title,
            content_description=payload.content_description,
            key_concepts=payload.key_concepts,
            bibliography_references=payload.bibliography_references,
        )
        created_topic = await self._repo.create_topic(new_topic)
        await self._session.commit()

        return self._map_topic_to_dto(created_topic)

    async def get_subject_syllabus_tree(
        self, subject_id: uuid.UUID
    ) -> SubjectSyllabusTreeResponse:
        """
        Retorna la estructura jerárquica completa del sílabo de una asignatura
        (`Materia -> Unidades -> Temas`) junto con métricas de vectorización.
        """
        subject = await self._repo.get_subject_with_full_syllabus(subject_id)
        if subject is None:
            raise EntityNotFoundError("Subject", subject_id)

        active_units = [u for u in subject.syllabus_units if u.is_active]
        units_dto: list[SyllabusUnitWithTopicsResponse] = []
        total_topics = 0
        vectorized_count = 0

        for unit in active_units:
            active_topics = [t for t in unit.topics if t.is_active]
            topics_dto = [self._map_topic_to_dto(t) for t in active_topics]
            total_topics += len(topics_dto)
            vectorized_count += sum(1 for t in topics_dto if t.is_vectorized)

            units_dto.append(
                SyllabusUnitWithTopicsResponse(
                    id=unit.id,
                    subject_id=unit.subject_id,
                    unit_number=unit.unit_number,
                    title=unit.title,
                    learning_objective=unit.learning_objective,
                    estimated_weeks=unit.estimated_weeks,
                    topics=topics_dto,
                )
            )

        return SubjectSyllabusTreeResponse(
            subject_id=subject.id,
            subject_code=subject.code,
            subject_name=subject.name,
            credits=subject.credits,
            weekly_hours=subject.weekly_hours,
            total_units=len(units_dto),
            total_topics=total_topics,
            vectorized_topics_count=vectorized_count,
            units=units_dto,
        )

    async def generate_curricular_material_for_teacher(
        self,
        topic_id: uuid.UUID,
        params: CurricularMaterialGenerationRequest,
        ai_service: AcademicAIService,
    ) -> CurricularMaterialGenerationResponse:
        """
        Caso de Uso IA #2 (Asistente Curricular para el Docente):
        Recupera el `SyllabusTopic` con su contexto curricular e invoca al motor de IA
        para producir una planeación de clase, rúbrica y cuestionario tipo test en JSON.
        """
        topic = await self._repo.get_topic_with_unit_and_subject(topic_id)
        if topic is None:
            raise EntityNotFoundError("SyllabusTopic", topic_id)

        proposal, model_used = await ai_service.generate_curricular_proposal_for_topic(
            topic=topic,
            params=params,
        )

        return CurricularMaterialGenerationResponse(
            topic_id=topic.id,
            topic_title=topic.title,
            unit_title=f"Unidad {topic.unit.unit_number}: {topic.unit.title}",
            subject_name=f"{topic.unit.subject.name} ({topic.unit.subject.code})",
            llm_model_used=model_used,
            generated_at=datetime.now(timezone.utc),
            curricular_proposal=proposal,
        )

    async def ask_syllabus_rag_tutor(
        self,
        payload: RAGTutorQueryRequest,
        ai_service: AcademicAIService,
    ) -> RAGTutorQueryResponse:
        """
        Caso de Uso IA #3 (Tutor RAG Basado en el Sílabo):
        1. Verifica que la materia exista.
        2. Convierte la pregunta del alumno en un vector semántico (`embedding`).
        3. Ejecuta búsqueda vectorial por similitud coseno en `pgvector`.
        4. Invoca al LLM con Grounding estricto sobre los temas oficiales recuperados.
        """
        subject = await self._repo.get_subject_by_id(payload.subject_id)
        if subject is None:
            raise EntityNotFoundError("Subject", payload.subject_id)

        query_embedding = await ai_service.generate_embedding_resilient(
            payload.question
        )

        matched_topics_with_scores = await self._repo.search_topics_by_cosine_similarity(
            subject_id=subject.id,
            query_embedding=query_embedding,
            top_k=payload.top_k_topics,
        )

        retrieved_sources = [
            RetrievedSyllabusContextItem(
                topic_id=topic_obj.id,
                unit_number=topic_obj.unit.unit_number,
                unit_title=topic_obj.unit.title,
                topic_number=topic_obj.topic_number,
                topic_title=topic_obj.title,
                content_description=topic_obj.content_description,
                key_concepts=topic_obj.key_concepts,
                cosine_similarity=sim_score,
            )
            for topic_obj, sim_score in matched_topics_with_scores
        ]

        rag_answer, model_used = await ai_service.generate_rag_tutor_answer(
            subject=subject,
            student_question=payload.question,
            retrieved_sources=retrieved_sources,
        )

        return RAGTutorQueryResponse(
            subject_id=subject.id,
            subject_code=subject.code,
            subject_name=subject.name,
            student_question=payload.question,
            retrieved_syllabus_sources=retrieved_sources,
            ai_tutor_response=rag_answer,
            llm_model_used=model_used,
            answered_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _map_topic_to_dto(topic: SyllabusTopic) -> SyllabusTopicResponse:
        return SyllabusTopicResponse(
            id=topic.id,
            unit_id=topic.unit_id,
            topic_number=topic.topic_number,
            title=topic.title,
            content_description=topic.content_description,
            key_concepts=topic.key_concepts,
            bibliography_references=topic.bibliography_references,
            is_vectorized=(topic.embedding is not None),
            created_at=topic.created_at,
        )
