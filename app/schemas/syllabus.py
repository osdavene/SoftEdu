"""Esquemas Pydantic v2 para Sílabo Vectorizado, Asistente Curricular y Tutor RAG."""

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ai_schemas import (
    AICurriculumAssistantSchema,
    RAGStructuredAnswerSchema,
)


# =====================================================================
# 1. DTOS DE UNIDADES Y TEMAS DEL SÍLABO (JERARQUÍA CURRICULAR)
# =====================================================================
class SyllabusUnitCreate(BaseModel):
    """DTO para registrar una nueva unidad dentro del sílabo de una materia."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_id: uuid.UUID = Field(..., description="UUID de la asignatura.")
    unit_number: int = Field(
        ..., ge=1, le=30, description="Número secuencial de la unidad (ej. 1, 2, 3)."
    )
    title: str = Field(
        ..., min_length=3, max_length=200, description="Título de la unidad temática."
    )
    learning_objective: str = Field(
        ...,
        min_length=10,
        max_length=1500,
        description="Resultado u objetivo de aprendizaje esperado para la unidad.",
    )
    estimated_weeks: int = Field(
        default=4,
        ge=1,
        le=20,
        description="Semanas estimadas de dedicación a la unidad.",
    )


class SyllabusTopicCreate(BaseModel):
    """
    DTO para registrar un tema dentro de una unidad del sílabo.
    Su creación dispara automáticamente la vectorización (`pgvector`) en segundo plano.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    unit_id: uuid.UUID = Field(..., description="UUID de la unidad temática padre.")
    topic_number: int = Field(
        ..., ge=1, le=50, description="Número secuencial del tema dentro de la unidad."
    )
    title: str = Field(
        ..., min_length=3, max_length=220, description="Título oficial del tema."
    )
    content_description: str = Field(
        ...,
        min_length=20,
        max_length=5000,
        description="Descripción detallada del contenido teórico-práctico del tema.",
    )
    key_concepts: list[str] = Field(
        default_factory=list,
        max_length=25,
        description="Lista de conceptos clave o palabras técnicas para indexación semántica.",
    )
    bibliography_references: str | None = Field(
        default=None,
        max_length=1500,
        description="Bibliografía oficial recomendada para el tema.",
    )


class SyllabusTopicResponse(BaseModel):
    """DTO de salida de un tema del sílabo indicando el estado de su vector en `pgvector`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    unit_id: uuid.UUID
    topic_number: int
    title: str
    content_description: str
    key_concepts: list[str]
    bibliography_references: str | None
    is_vectorized: bool = Field(
        ...,
        description="True si la columna `embedding` ya fue generada y almacenada en pgvector.",
    )
    created_at: datetime


class SyllabusUnitWithTopicsResponse(BaseModel):
    """DTO de una unidad temática con su lista ordenada de temas."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_id: uuid.UUID
    unit_number: int
    title: str
    learning_objective: str
    estimated_weeks: int
    topics: list[SyllabusTopicResponse] = Field(default_factory=list)


class SubjectSyllabusTreeResponse(BaseModel):
    """Árbol jerárquico completo del sílabo (`Materia -> Unidad -> Tema`)."""

    subject_id: uuid.UUID
    subject_code: str
    subject_name: str
    credits: int
    weekly_hours: int
    total_units: int
    total_topics: int
    vectorized_topics_count: int
    units: list[SyllabusUnitWithTopicsResponse]


# =====================================================================
# 2. DTOS PARA ASISTENTE CURRICULAR DEL DOCENTE (CASO DE USO IA #2)
# =====================================================================
class CurricularMaterialGenerationRequest(BaseModel):
    """Parámetros de personalización pedagógica para el Asistente Curricular IA."""

    model_config = ConfigDict(extra="forbid")

    session_duration_minutes: int = Field(
        default=120,
        ge=30,
        le=300,
        description="Duración total de la sesión de clase en minutos (ej. 90 o 120).",
    )
    num_quiz_questions: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Cantidad de preguntas tipo test a generar.",
    )
    difficulty_level: Literal["BASICO", "INTERMEDIO", "AVANZADO"] = Field(
        default="INTERMEDIO",
        description="Nivel de exigencia académica para las actividades y el test.",
    )
    pedagogical_focus: str | None = Field(
        default=None,
        max_length=500,
        description="Enfoque metodológico opcional (ej. 'Aprendizaje Basado en Problemas con Python').",
    )


class CurricularMaterialGenerationResponse(BaseModel):
    """Respuesta completa del Asistente Curricular vinculada al `SyllabusTopic`."""

    topic_id: uuid.UUID
    topic_title: str
    unit_title: str
    subject_name: str
    llm_model_used: str
    generated_at: datetime
    curricular_proposal: AICurriculumAssistantSchema


# =====================================================================
# 3. DTOS PARA EL TUTOR RAG BASADO EN EL SÍLABO (CASO DE USO IA #3)
# =====================================================================
class RAGTutorQueryRequest(BaseModel):
    """Consulta académica de un estudiante dirigida al Tutor RAG."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_id: uuid.UUID = Field(
        ..., description="UUID de la asignatura sobre la cual consulta el estudiante."
    )
    question: str = Field(
        ...,
        min_length=8,
        max_length=1500,
        description="Pregunta o duda académica formulada por el estudiante.",
    )
    top_k_topics: int = Field(
        default=3,
        ge=1,
        le=8,
        description="Cantidad de temas del sílabo más similares a recuperar desde pgvector.",
    )


class RetrievedSyllabusContextItem(BaseModel):
    """Fragmento oficial del sílabo recuperado mediante similitud vectorial (`pgvector`)."""

    topic_id: uuid.UUID
    unit_number: int
    unit_title: str
    topic_number: int
    topic_title: str
    content_description: str
    key_concepts: list[str]
    cosine_similarity: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similitud coseno (0.0 a 1.0) entre la pregunta del alumno y el tema del sílabo.",
    )


class RAGTutorQueryResponse(BaseModel):
    """Respuesta fundamentada del Tutor RAG con trazabilidad de fuentes vectoriales."""

    subject_id: uuid.UUID
    subject_code: str
    subject_name: str
    student_question: str
    retrieved_syllabus_sources: list[RetrievedSyllabusContextItem]
    ai_tutor_response: RAGStructuredAnswerSchema
    llm_model_used: str
    answered_at: datetime
