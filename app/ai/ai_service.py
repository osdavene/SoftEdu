"""
Motor de Inteligencia Artificial Aplicada (`app/ai/ai_service.py`).

Implementa el patrón Strategy/Adapter para soportar Google Gemini (`google-genai`)
y OpenAI SDK con Structured Outputs (Pydantic v2), generación de embeddings para
`pgvector` (RAG), Asistente Curricular y diagnóstico asíncrono en segundo plano.
"""

from abc import ABC, abstractmethod
import asyncio
from decimal import Decimal
import hashlib
import json
import logging
import math
from typing import TypeVar
import uuid

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_isolated_db_session
from app.core.exceptions import AIServiceExecutionError
from app.models.academic import RiskLevel, StudentAIInsight, Subject, SyllabusTopic
from app.repositories.grades_repository import GradesRepository
from app.repositories.syllabus_repository import SyllabusRepository
from app.schemas.ai_schemas import (
    AICurriculumAssistantSchema,
    AIRiskAssessmentSchema,
    ClassSessionPhaseSchema,
    EvaluationRubricCriterionSchema,
    MultipleChoiceQuestionSchema,
    RAGStructuredAnswerSchema,
    StudentAcademicContextDTO,
    SuggestedActionPlanSchema,
)
from app.schemas.syllabus import (
    CurricularMaterialGenerationRequest,
    RetrievedSyllabusContextItem,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# =====================================================================
# 1. PATRÓN STRATEGY / ADAPTER PARA PROVEEDORES LLM
# =====================================================================
class LLMAdapterStrategy(ABC):
    """Interfaz abstracta (Strategy) para desacoplar el motor de IA del proveedor."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identificador del proveedor configurado."""

    @abstractmethod
    async def generate_structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[T],
    ) -> T:
        """
        Invoca al LLM forzando la salida a cumplir estrictamente el esquema Pydantic `T`.
        """

    @abstractmethod
    async def generate_embedding(self, text_content: str) -> list[float]:
        """Genera la representación vectorial (embedding) de un texto para `pgvector`."""


class GoogleGeminiAdapter(LLMAdapterStrategy):
    """
    Adaptador asíncrono oficial para Google Gemini API utilizando `google-genai`.
    Soporta Structured Outputs nativos mediante `response_schema`.
    """

    def __init__(self, api_key: str, model_name: str, embedding_model: str) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._embedding_model = embedding_model

    @property
    def provider_name(self) -> str:
        return f"google-genai:{self._model_name}"

    async def generate_structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[T],
    ) -> T:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self._api_key)
            response = await client.aio.models.generate_content(
                model=self._model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=settings.AI_TEMPERATURE,
                ),
            )
            if not response.text:
                raise AIServiceExecutionError(
                    message="El proveedor Gemini devolvió una respuesta vacía.",
                    provider=self.provider_name,
                )
            return response_schema.model_validate_json(response.text)
        except ValidationError as val_err:
            raise AIServiceExecutionError(
                message="La respuesta del LLM no cumplió el contrato Pydantic.",
                provider=self.provider_name,
                original_error=str(val_err),
            ) from val_err
        except Exception as exc:
            if isinstance(exc, AIServiceExecutionError):
                raise
            raise AIServiceExecutionError(
                message="Error al invocar Google Gemini API.",
                provider=self.provider_name,
                original_error=str(exc),
            ) from exc

    async def generate_embedding(self, text_content: str) -> list[float]:
        try:
            from google import genai

            client = genai.Client(api_key=self._api_key)
            result = await client.aio.models.embed_content(
                model=self._embedding_model,
                contents=text_content,
            )
            if not result.embeddings or not result.embeddings[0].values:
                raise AIServiceExecutionError(
                    message="No se recibieron vectores desde Gemini Embeddings.",
                    provider=self.provider_name,
                )
            return list(result.embeddings[0].values)
        except Exception as exc:
            raise AIServiceExecutionError(
                message="Error generando embedding en Gemini.",
                provider=self.provider_name,
                original_error=str(exc),
            ) from exc


class OpenAIAdapter(LLMAdapterStrategy):
    """
    Adaptador asíncrono para OpenAI SDK (`AsyncOpenAI`) usando Structured Outputs (`parse`).
    """

    def __init__(self, api_key: str, model_name: str, embedding_model: str) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._embedding_model = embedding_model

    @property
    def provider_name(self) -> str:
        return f"openai:{self._model_name}"

    async def generate_structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[T],
    ) -> T:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._api_key)
            completion = await client.beta.chat.completions.parse(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_schema,
                temperature=settings.AI_TEMPERATURE,
            )
            parsed = completion.choices[0].message.parsed
            if parsed is None:
                raise AIServiceExecutionError(
                    message="OpenAI no pudo estructurar la salida según el esquema.",
                    provider=self.provider_name,
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, AIServiceExecutionError):
                raise
            raise AIServiceExecutionError(
                message="Error al invocar OpenAI API.",
                provider=self.provider_name,
                original_error=str(exc),
            ) from exc

    async def generate_embedding(self, text_content: str) -> list[float]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._api_key)
            response = await client.embeddings.create(
                model=self._embedding_model,
                input=text_content,
            )
            return list(response.data[0].embedding)
        except Exception as exc:
            raise AIServiceExecutionError(
                message="Error generando embedding en OpenAI.",
                provider=self.provider_name,
                original_error=str(exc),
            ) from exc


def build_llm_adapter() -> LLMAdapterStrategy:
    """Factory que instancia la estrategia LLM según `settings.AI_PROVIDER`."""
    if settings.AI_PROVIDER == "openai":
        return OpenAIAdapter(
            api_key=settings.AI_API_KEY,
            model_name=settings.AI_MODEL_NAME,
            embedding_model=settings.AI_EMBEDDING_MODEL_NAME,
        )
    return GoogleGeminiAdapter(
        api_key=settings.AI_API_KEY,
        model_name=settings.AI_MODEL_NAME,
        embedding_model=settings.AI_EMBEDDING_MODEL_NAME,
    )


# =====================================================================
# 2. SERVICIO PRINCIPAL DEL COPILOTO DE IA ACADÉMICA (3 CASOS DE USO)
# =====================================================================
class AcademicAIService:
    """
    Orquestador empresarial de las 3 capacidades del Copiloto de IA:
    1. Alerta Temprana de Riesgo Académico (Predictivo/Analítico en `BackgroundTasks`).
    2. Asistente Curricular para el Docente (Generativo con Structured Outputs).
    3. Tutor RAG Basado en el Sílabo (Búsqueda vectorial `pgvector` + Grounding estricto).
    """

    SYSTEM_PROMPT_RISK_ANALYST: str = (
        "Eres un Psicopedagogo Senior y Analista de Datos Educativos de un sistema LMS/SIS "
        "universitario. Tu objetivo es evaluar el riesgo académico de un estudiante con base "
        "en sus calificaciones ponderadas (escala 0.00 a 5.00, nota mínima aprobatoria 3.00), "
        "su porcentaje de inasistencias y los temas del sílabo donde presenta debilidades. "
        "Debes responder ÚNICAMENTE en español y ajustarte estrictamente al esquema JSON "
        "solicitado, proponiendo acciones concretas, empáticas y medibles tanto para el "
        "docente titular como para el estudiante."
    )

    SYSTEM_PROMPT_CURRICULAR_ASSISTANT: str = (
        "Eres un Diseñador Instruccional Universitario y Experto en Evaluación por Competencias. "
        "Tu objetivo es ayudar al docente a diseñar una sesión de clase magistral/práctica, "
        "una rúbrica analítica (escala 0.0 a 5.0) y un banco de preguntas tipo test alineado "
        "a la taxonomía de Bloom a partir de un tema oficial del sílabo (`SyllabusTopic`). "
        "Responde estrictamente en español siguiendo el contrato JSON proporcionado."
    )

    SYSTEM_PROMPT_RAG_TUTOR: str = (
        "Eres el Tutor Académico Oficial basado en RAG (Retrieval-Augmented Generation) "
        "del sistema SoftEdu. REGLA DE ORO DE GROUNDING: Debes responder a la duda del "
        "estudiante ÚNICAMENTE utilizando la información contenida en los fragmentos "
        "oficiales del sílabo recuperados desde la base vectorial (`pgvector`). "
        "Si la pregunta del estudiante trata sobre un tema que NO guarda relación con las "
        "unidades y temas del sílabo provistos, marca `esta_dentro_del_silabo = false` "
        "e indícale amablemente qué temas oficiales sí cubre la asignatura."
    )

    def __init__(self, llm_adapter: LLMAdapterStrategy | None = None) -> None:
        self._adapter = llm_adapter or build_llm_adapter()

    # -----------------------------------------------------------------
    # UTILIDAD: GENERACIÓN RESILIENTE DE EMBEDDINGS (PGVECTOR)
    # -----------------------------------------------------------------
    async def generate_embedding_resilient(self, text_content: str) -> list[float]:
        """
        Genera el vector de dimensión `settings.AI_EMBEDDING_DIMENSION` con timeout.
        Si el proveedor externo falla o no hay red, genera un vector unitario
        determinista basado en tokens para no interrumpir flujos de indexación o RAG.
        """
        try:
            vector = await asyncio.wait_for(
                self._adapter.generate_embedding(text_content),
                timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            )
            if len(vector) == settings.AI_EMBEDDING_DIMENSION:
                return vector
        except Exception as exc:
            logger.warning(
                "No se pudo obtener embedding remoto desde %s (%s). "
                "Generando vector determinista local (%d dims).",
                self._adapter.provider_name,
                str(exc),
                settings.AI_EMBEDDING_DIMENSION,
            )
        return self._build_deterministic_unit_vector(
            text_content, settings.AI_EMBEDDING_DIMENSION
        )

    @staticmethod
    def _build_deterministic_unit_vector(text: str, dimension: int) -> list[float]:
        """
        Construye un vector L2-normalizado determinista proyectando n-gramas del texto
        (Feature Hashing / Random Projection local) para contingencia sin red.
        """
        vec = [0.0] * dimension
        tokens = [t.lower().strip(".,;:()[]¿?¡!") for t in text.split() if len(t) > 2]
        if not tokens:
            tokens = [text.lower()]

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for i in range(0, len(digest), 4):
                idx = int.from_bytes(digest[i : i + 2], "big") % dimension
                sign = 1.0 if (digest[i + 2] % 2 == 0) else -1.0
                weight = (digest[i + 3] / 255.0) + 0.5
                vec[idx] += sign * weight

        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [round(v / norm, 6) for v in vec]

    async def vectorize_syllabus_topic_background(
        self,
        topic_id: uuid.UUID,
        external_session: AsyncSession | None = None,
    ) -> bool:
        """
        Tarea en segundo plano (`BackgroundTasks`) que construye la representación
        semántica de un `SyllabusTopic`, calcula su embedding y lo guarda en `pgvector`.
        """
        try:
            if external_session is not None:
                return await self._vectorize_and_persist_topic(
                    external_session, topic_id
                )

            async with get_isolated_db_session() as bg_session:
                success = await self._vectorize_and_persist_topic(bg_session, topic_id)
                await bg_session.commit()
                return success
        except Exception as exc:
            logger.error(
                "Error vectorizando SyllabusTopic %s en segundo plano: %s",
                topic_id,
                str(exc),
                exc_info=True,
            )
            return False

    async def _vectorize_and_persist_topic(
        self, session: AsyncSession, topic_id: uuid.UUID
    ) -> bool:
        repo = SyllabusRepository(session)
        topic = await repo.get_topic_with_unit_and_subject(topic_id)
        if topic is None:
            return False

        semantic_document = (
            f"Asignatura: {topic.unit.subject.name} ({topic.unit.subject.code})\n"
            f"Unidad {topic.unit.unit_number}: {topic.unit.title}\n"
            f"Objetivo de la Unidad: {topic.unit.learning_objective}\n"
            f"Tema {topic.topic_number}: {topic.title}\n"
            f"Contenido: {topic.content_description}\n"
            f"Conceptos Clave: {', '.join(topic.key_concepts)}\n"
            f"Bibliografía: {topic.bibliography_references or 'N/A'}"
        )
        embedding_vec = await self.generate_embedding_resilient(semantic_document)
        await repo.update_topic_embedding(topic.id, embedding_vec)
        logger.info(
            "SyllabusTopic '%s' (%s) vectorizado exitosamente (%d dimensiones).",
            topic.title,
            topic.id,
            len(embedding_vec),
        )
        return True

    # -----------------------------------------------------------------
    # CASO DE USO #1: ALERTA TEMPRANA DE RIESGO ACADÉMICO
    # -----------------------------------------------------------------
    def _build_risk_assessment_user_prompt(
        self, context: StudentAcademicContextDTO
    ) -> str:
        payload = {
            "estudiante": {
                "nombre": context.student_full_name,
                "codigo": context.student_code,
                "semestre_actual": context.current_semester,
            },
            "asignatura": {
                "codigo": context.subject_code,
                "nombre": context.subject_name,
                "periodo": context.academic_period_code,
            },
            "metricas_calificaciones": {
                "escala": "0.00 a 5.00 (Mínima aprobatoria: 3.00)",
                "promedio_ponderado_actual": float(context.accumulated_weighted_average),
                "porcentaje_evaluado_acumulado": float(context.evaluated_weight_percentage),
                "porcentaje_pendiente_por_evaluar": float(context.remaining_weight_percentage),
                "nota_minima_requerida_en_restante_para_aprobar": float(
                    context.minimum_score_needed_to_pass
                ),
                "historial_evaluaciones": context.grades_breakdown,
            },
            "metricas_asistencia": {
                "sesiones_registradas": context.total_sessions_recorded,
                "inasistencias_acumuladas": context.absent_sessions_count,
                "porcentaje_inasistencia_actual": float(context.absence_percentage),
                "limite_maximo_inasistencia_permitido": float(
                    context.max_absence_allowed_percentage
                ),
            },
            "temas_silabo_con_bajo_rendimiento": context.weak_syllabus_topics,
        }
        return (
            "Analiza el siguiente contexto académico actualizado tras el registro de una "
            "nueva calificación y genera el diagnóstico estructurado de riesgo:\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _build_contingency_fallback_assessment(
        self, context: StudentAcademicContextDTO
    ) -> AIRiskAssessmentSchema:
        avg = float(context.accumulated_weighted_average)
        abs_pct = float(context.absence_percentage)
        needed = min(max(float(context.minimum_score_needed_to_pass), 0.0), 5.0)

        factors: list[str] = []
        if avg < 2.5 or abs_pct >= float(context.max_absence_allowed_percentage):
            risk = RiskLevel.CRITICO
        elif avg < 3.0 or abs_pct >= 15.0:
            risk = RiskLevel.ALTO
        elif avg < 3.5 or abs_pct >= 10.0:
            risk = RiskLevel.MEDIO
        else:
            risk = RiskLevel.BAJO

        factors.append(
            f"Promedio ponderado actual de {avg:.2f}/5.00 sobre el {context.evaluated_weight_percentage}% evaluado."
        )
        if abs_pct > 0:
            factors.append(
                f"Porcentaje de inasistencia acumulado del {abs_pct:.1f}% (límite: {context.max_absence_allowed_percentage}%)."
            )
        if context.weak_syllabus_topics:
            factors.append(
                f"Temas críticos detectados en evaluaciones: {', '.join(context.weak_syllabus_topics)}."
            )

        return AIRiskAssessmentSchema(
            nivel_riesgo=risk,
            resumen_ejecutivo=(
                f"Diagnóstico preventivo automático para {context.student_full_name} en "
                f"{context.subject_name}. Nivel de riesgo {risk.value} con promedio "
                f"ponderado de {avg:.2f} y {abs_pct:.1f}% de inasistencias."
            ),
            factores_detectados=factors,
            plan_accion_sugerido=SuggestedActionPlanSchema(
                acciones_docente=[
                    "Realizar retroalimentación personalizada sobre los cortes evaluados con nota inferior a 3.00.",
                    "Verificar la asistencia del estudiante en las próximas sesiones prácticas.",
                ],
                acciones_estudiante=[
                    f"Alcanzar un promedio mínimo de {needed:.2f} en el {context.remaining_weight_percentage}% restante del curso.",
                    "Asistir a tutorías académicas para reforzar los temas evaluados recientemente.",
                ],
                temas_refuerzo_prioritarios=context.weak_syllabus_topics
                or ["Revisión general de contenidos del corte actual"],
                meta_nota_restante_sugerida=round(needed, 2),
            ),
        )

    async def evaluate_and_save_student_risk_background(
        self,
        context: StudentAcademicContextDTO,
        external_session: AsyncSession | None = None,
    ) -> StudentAIInsight | None:
        user_prompt = self._build_risk_assessment_user_prompt(context)
        model_label = self._adapter.provider_name

        try:
            assessment: AIRiskAssessmentSchema = await asyncio.wait_for(
                self._adapter.generate_structured_output(
                    system_prompt=self.SYSTEM_PROMPT_RISK_ANALYST,
                    user_prompt=user_prompt,
                    response_schema=AIRiskAssessmentSchema,
                ),
                timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Timeout (%ss) en diagnóstico IA para matrícula %s. Usando contingencia.",
                settings.AI_REQUEST_TIMEOUT_SECONDS,
                context.enrollment_id,
            )
            assessment = self._build_contingency_fallback_assessment(context)
            model_label = f"{self._adapter.provider_name}:fallback-timeout"
        except Exception as exc:
            logger.error(
                "Error en proveedor IA (%s) para matrícula %s: %s. Usando contingencia.",
                self._adapter.provider_name,
                context.enrollment_id,
                str(exc),
                exc_info=True,
            )
            assessment = self._build_contingency_fallback_assessment(context)
            model_label = f"{self._adapter.provider_name}:fallback-contingencia"

        try:
            if external_session is not None:
                return await self._persist_insight(
                    session=external_session,
                    context=context,
                    assessment=assessment,
                    model_label=model_label,
                )

            async with get_isolated_db_session() as bg_session:
                insight = await self._persist_insight(
                    session=bg_session,
                    context=context,
                    assessment=assessment,
                    model_label=model_label,
                )
                await bg_session.commit()
                return insight
        except Exception as db_exc:
            logger.critical(
                "Error persistiendo StudentAIInsight para matrícula %s: %s",
                context.enrollment_id,
                str(db_exc),
                exc_info=True,
            )
            return None

    async def _persist_insight(
        self,
        session: AsyncSession,
        context: StudentAcademicContextDTO,
        assessment: AIRiskAssessmentSchema,
        model_label: str,
    ) -> StudentAIInsight:
        repo = GradesRepository(session)
        new_insight = StudentAIInsight(
            enrollment_id=context.enrollment_id,
            triggered_by_grade_id=context.triggered_by_grade_id,
            risk_level=assessment.nivel_riesgo,
            accumulated_weighted_average=Decimal(
                str(context.accumulated_weighted_average)
            ),
            evaluated_weight_percentage=Decimal(
                str(context.evaluated_weight_percentage)
            ),
            absence_percentage=Decimal(str(context.absence_percentage)),
            detected_factors=assessment.factores_detectados,
            suggested_action_plan=assessment.plan_accion_sugerido.model_dump(
                mode="json"
            ),
            executive_summary=assessment.resumen_ejecutivo,
            llm_model_used=model_label,
            is_current_insight=True,
        )
        return await repo.save_student_ai_insight(new_insight)

    # -----------------------------------------------------------------
    # CASO DE USO #2: ASISTENTE CURRICULAR PARA EL DOCENTE (GENERATIVO)
    # -----------------------------------------------------------------
    async def generate_curricular_proposal_for_topic(
        self,
        topic: SyllabusTopic,
        params: CurricularMaterialGenerationRequest,
    ) -> tuple[AICurriculumAssistantSchema, str]:
        """
        Recibe una entidad `SyllabusTopic` (con su `SyllabusUnit` y `Subject`) y genera
        mediante el LLM una planeación de clase, rúbrica analítica y banco de preguntas
        tipo test forzados al esquema `AICurriculumAssistantSchema`.
        """
        prompt_payload = {
            "asignatura": {
                "codigo": topic.unit.subject.code,
                "nombre": topic.unit.subject.name,
                "creditos": topic.unit.subject.credits,
            },
            "unidad_tematica": {
                "numero": topic.unit.unit_number,
                "titulo": topic.unit.title,
                "objetivo_aprendizaje": topic.unit.learning_objective,
            },
            "tema_silabo": {
                "numero": topic.topic_number,
                "titulo": topic.title,
                "descripcion_contenido": topic.content_description,
                "conceptos_clave": topic.key_concepts,
                "bibliografia": topic.bibliography_references,
            },
            "parametros_solicitados_por_docente": {
                "duracion_total_minutos": params.session_duration_minutes,
                "cantidad_preguntas_test": params.num_quiz_questions,
                "nivel_dificultad": params.difficulty_level,
                "enfoque_pedagogico": params.pedagogical_focus
                or "Aprendizaje activo teórico-práctico",
            },
        }
        user_prompt = (
            "Diseña la propuesta curricular completa (planeación en 3 fases cuya suma de "
            f"minutos sea {params.session_duration_minutes}, rúbrica de evaluación en escala "
            f"0.0-5.0 y exactamente {params.num_quiz_questions} preguntas tipo test) para el "
            "siguiente tema oficial del sílabo:\n\n"
            f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
        )

        try:
            proposal = await asyncio.wait_for(
                self._adapter.generate_structured_output(
                    system_prompt=self.SYSTEM_PROMPT_CURRICULAR_ASSISTANT,
                    user_prompt=user_prompt,
                    response_schema=AICurriculumAssistantSchema,
                ),
                timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            )
            return proposal, self._adapter.provider_name
        except Exception as exc:
            logger.warning(
                "Fallo o timeout en LLM (%s) al generar diseño curricular para tema %s: %s. "
                "Generando propuesta estructurada de contingencia.",
                self._adapter.provider_name,
                topic.id,
                str(exc),
            )
            fallback_proposal = self._build_fallback_curricular_proposal(topic, params)
            return fallback_proposal, f"{self._adapter.provider_name}:fallback-curricular"

    @staticmethod
    def _build_fallback_curricular_proposal(
        topic: SyllabusTopic,
        params: CurricularMaterialGenerationRequest,
    ) -> AICurriculumAssistantSchema:
        total_min = params.session_duration_minutes
        intro_min = max(10, int(total_min * 0.15))
        close_min = max(10, int(total_min * 0.20))
        core_min = max(10, total_min - intro_min - close_min)

        concepts = topic.key_concepts or [topic.title]
        questions: list[MultipleChoiceQuestionSchema] = []
        for idx in range(params.num_quiz_questions):
            concept_focus = concepts[idx % len(concepts)]
            questions.append(
                MultipleChoiceQuestionSchema(
                    enunciado=(
                        f"[Pregunta {idx + 1} - {params.difficulty_level}] En el marco de "
                        f"'{topic.title}', ¿cuál es el propósito fundamental de aplicar '{concept_focus}'?"
                    ),
                    opciones=[
                        f"A) Garantizar la correcta implementación y análisis de {concept_focus} según el estándar de {topic.unit.subject.name}.",
                        f"B) Omitir las validaciones estructurales asociadas a {concept_focus}.",
                        f"C) Sustituir por completo los objetivos de la Unidad {topic.unit.unit_number}.",
                        "D) Ninguna de las anteriores aplica al contexto estudiado.",
                    ],
                    indice_respuesta_correcta=0,
                    nivel_taxonomia_bloom="APLICAR",
                    justificacion_pedagogica=(
                        f"La opción A integra directamente el concepto clave '{concept_focus}' "
                        f"con el objetivo de aprendizaje de la unidad '{topic.unit.title}'."
                    ),
                )
            )

        return AICurriculumAssistantSchema(
            titulo_sesion_propuesta=f"Sesión Magistral-Práctica: {topic.title}",
            objetivo_aprendizaje_especifico=(
                f"Comprender y aplicar los fundamentos de {topic.title} ({', '.join(concepts[:4])}) "
                f"en problemas prácticos de {topic.unit.subject.name}."
            ),
            fases_planeacion_clase=[
                ClassSessionPhaseSchema(
                    fase="INICIO_APERTURA",
                    duracion_minutos=intro_min,
                    actividad_docente=(
                        f"Presentación de caso disparador e introducción a {topic.title}."
                    ),
                    actividad_estudiantes=(
                        "Activación de saberes previos y discusión diagnóstica breve."
                    ),
                    recursos_didacticos=["Diapositivas guía", "Pizarra interactiva"],
                ),
                ClassSessionPhaseSchema(
                    fase="DESARROLLO_CENTRAL",
                    duracion_minutos=core_min,
                    actividad_docente=(
                        f"Modelado conceptual y demostración guiada de: {topic.content_description}."
                    ),
                    actividad_estudiantes=(
                        "Resolución colaborativa de ejercicios prácticos aplicando los conceptos clave."
                    ),
                    recursos_didacticos=["Entorno de laboratorio / Taller", "Guía práctica"],
                ),
                ClassSessionPhaseSchema(
                    fase="CIERRE_EVALUACION",
                    duracion_minutos=close_min,
                    actividad_docente=(
                        "Síntesis de conclusiones, retroalimentación de errores comunes y aplicación de mini-test."
                    ),
                    actividad_estudiantes=(
                        "Socialización de resultados y respuesta al cuestionario formativo."
                    ),
                    recursos_didacticos=["Banco de preguntas SoftEdu"],
                ),
            ],
            rubrica_evaluacion=[
                EvaluationRubricCriterionSchema(
                    criterio=f"Dominio conceptual de {topic.title}",
                    peso_porcentual=50.0,
                    nivel_excelente_45_a_50=(
                        "Explica y relaciona con rigor todos los conceptos clave del tema sin errores."
                    ),
                    nivel_aprobatorio_30_a_44=(
                        "Identifica los conceptos principales aunque presenta imprecisiones menores."
                    ),
                    nivel_insuficiente_00_a_29=(
                        "Evidencia confusión en los fundamentos teóricos básicos del tema."
                    ),
                ),
                EvaluationRubricCriterionSchema(
                    criterio="Aplicación práctica y resolución de problemas",
                    peso_porcentual=50.0,
                    nivel_excelente_45_a_50=(
                        "Resuelve el caso práctico de manera óptima, limpia y justificada."
                    ),
                    nivel_aprobatorio_30_a_44=(
                        "Resuelve el problema parcialmente cumpliendo los requisitos mínimos."
                    ),
                    nivel_insuficiente_00_a_29=(
                        "No logra estructurar una solución funcional al problema planteado."
                    ),
                ),
            ],
            banco_preguntas_test=questions,
        )

    # -----------------------------------------------------------------
    # CASO DE USO #3: TUTOR RAG BASADO EN EL SÍLABO (PGVECTOR)
    # -----------------------------------------------------------------
    async def generate_rag_tutor_answer(
        self,
        subject: Subject,
        student_question: str,
        retrieved_sources: list[RetrievedSyllabusContextItem],
    ) -> tuple[RAGStructuredAnswerSchema, str]:
        """
        Ejecuta la etapa de Generación Aumentada (RAG) inyectando los temas del sílabo
        recuperados desde PostgreSQL (`pgvector`) y forzando `RAGStructuredAnswerSchema`.
        """
        if not retrieved_sources:
            return (
                RAGStructuredAnswerSchema(
                    esta_dentro_del_silabo=False,
                    respuesta_tutor=(
                        f"Actualmente la asignatura '{subject.name}' ({subject.code}) no cuenta "
                        "con temas registrados en su sílabo oficial para responder tu consulta. "
                        "Por favor consulta con tu docente titular."
                    ),
                    conceptos_clave_abordados=[],
                    unidades_y_temas_citados=[],
                    ejercicio_autoevaluacion_sugerido=(
                        "Verifica el programa analítico del curso con el docente."
                    ),
                ),
                f"{self._adapter.provider_name}:no-syllabus-sources",
            )

        context_blocks = [
            {
                "referencia": f"Unidad {src.unit_number} ({src.unit_title}) -> Tema {src.topic_number} ({src.topic_title})",
                "similitud_vectorial_coseno": src.cosine_similarity,
                "contenido_oficial": src.content_description,
                "conceptos_clave": src.key_concepts,
            }
            for src in retrieved_sources
        ]
        user_prompt = (
            f"Asignatura: {subject.name} ({subject.code})\n"
            f"Pregunta del Estudiante: \"{student_question}\"\n\n"
            "Fragmentos Oficiales del Sílabo Recuperados (pgvector):\n"
            f"{json.dumps(context_blocks, ensure_ascii=False, indent=2)}\n\n"
            "Responde estrictamente con base en estos fragmentos siguiendo el contrato JSON."
        )

        try:
            rag_answer = await asyncio.wait_for(
                self._adapter.generate_structured_output(
                    system_prompt=self.SYSTEM_PROMPT_RAG_TUTOR,
                    user_prompt=user_prompt,
                    response_schema=RAGStructuredAnswerSchema,
                ),
                timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            )
            return rag_answer, self._adapter.provider_name
        except Exception as exc:
            logger.warning(
                "Fallo o timeout en LLM (%s) durante consulta Tutor RAG en materia %s: %s. "
                "Construyendo respuesta fundamentada con las fuentes de pgvector.",
                self._adapter.provider_name,
                subject.id,
                str(exc),
            )
            top_source = retrieved_sources[0]
            citations = [
                f"Unidad {s.unit_number}: {s.unit_title} - Tema {s.topic_number}: {s.topic_title}"
                for s in retrieved_sources
            ]
            fallback_rag = RAGStructuredAnswerSchema(
                esta_dentro_del_silabo=True,
                respuesta_tutor=(
                    f"Con base en el sílabo oficial de {subject.name}, tu consulta se relaciona "
                    f"directamente con la Unidad {top_source.unit_number} ({top_source.unit_title}), "
                    f"específicamente el Tema {top_source.topic_number}: '{top_source.topic_title}'. "
                    f"Según el contenido oficial del curso: {top_source.content_description}"
                ),
                conceptos_clave_abordados=top_source.key_concepts,
                unidades_y_temas_citados=citations,
                ejercicio_autoevaluacion_sugerido=(
                    f"Explica con tus propias palabras cómo se relacionan los conceptos "
                    f"{', '.join(top_source.key_concepts[:3]) or top_source.topic_title} "
                    f"dentro de la Unidad {top_source.unit_number}."
                ),
            )
            return fallback_rag, f"{self._adapter.provider_name}:fallback-rag"
