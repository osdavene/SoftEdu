"""Contratos Pydantic v2 para Structured Outputs del Motor de IA y diagnósticos."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.academic import RiskLevel


# =====================================================================
# 1. CONTRATOS IA: ALERTA TEMPRANA DE RIESGO ACADÉMICO (CASO DE USO #1)
# =====================================================================
class SuggestedActionPlanSchema(BaseModel):
    """Sub-esquema estructurado con planes de intervención diferenciados."""

    model_config = ConfigDict(extra="forbid")

    acciones_docente: list[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Estrategias pedagógicas concretas sugeridas al docente titular.",
    )
    acciones_estudiante: list[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Hábitos, ejercicios y pasos accionables dirigidos al alumno.",
    )
    temas_refuerzo_prioritarios: list[str] = Field(
        default_factory=list,
        description="Títulos de unidades o temas del sílabo que el estudiante debe reforzar.",
    )
    meta_nota_restante_sugerida: float = Field(
        ...,
        ge=0.0,
        le=5.0,
        description="Nota promedio mínima que debe alcanzar en el porcentaje restante para aprobar (>=3.0).",
    )


class AIRiskAssessmentSchema(BaseModel):
    """
    Contrato estricto de salida (Structured Output) exigido al LLM (Gemini / OpenAI)
    para el sistema de Alerta Temprana de Riesgo Académico.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    nivel_riesgo: RiskLevel = Field(
        ...,
        description="Clasificación del riesgo: BAJO, MEDIO, ALTO o CRITICO.",
    )
    resumen_ejecutivo: str = Field(
        ...,
        min_length=20,
        max_length=800,
        description="Síntesis diagnóstica del estado académico y de asistencia del estudiante.",
    )
    factores_detectados: list[str] = Field(
        ...,
        min_length=1,
        max_length=8,
        description="Factores cuantitativos y cualitativos de riesgo (ej. baja nota en Corte 1, % de inasistencias).",
    )
    plan_accion_sugerido: SuggestedActionPlanSchema = Field(
        ...,
        description="Plan de intervención pedagógica estructurado para el docente y el estudiante.",
    )

    @field_validator("factores_detectados")
    @classmethod
    def validate_non_empty_factors(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("El diagnóstico de IA debe incluir al menos un factor detectado válido.")
        return cleaned


class StudentAcademicContextDTO(BaseModel):
    """
    DTO interno inmutable que consolida todo el contexto académico del alumno
    para ser inyectado en el prompt del servicio de IA en segundo plano.
    """

    model_config = ConfigDict(frozen=True)

    enrollment_id: uuid.UUID
    triggered_by_grade_id: uuid.UUID
    student_full_name: str
    student_code: str
    current_semester: int
    subject_code: str
    subject_name: str
    academic_period_code: str
    accumulated_weighted_average: Decimal
    evaluated_weight_percentage: Decimal
    remaining_weight_percentage: Decimal
    minimum_score_needed_to_pass: Decimal
    total_sessions_recorded: int
    absent_sessions_count: int
    absence_percentage: Decimal
    max_absence_allowed_percentage: Decimal
    grades_breakdown: list[dict[str, str | float | int]]
    weak_syllabus_topics: list[str]


class StudentAIInsightResponse(BaseModel):
    """DTO de respuesta para exponer el diagnóstico vigente de IA en el boletín."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    enrollment_id: uuid.UUID
    triggered_by_grade_id: uuid.UUID | None
    risk_level: RiskLevel
    accumulated_weighted_average: Decimal
    evaluated_weight_percentage: Decimal
    absence_percentage: Decimal
    detected_factors: list[str]
    suggested_action_plan: SuggestedActionPlanSchema
    executive_summary: str
    llm_model_used: str
    is_current_insight: bool
    created_at: datetime


# =====================================================================
# 2. CONTRATOS IA: ASISTENTE CURRICULAR PARA EL DOCENTE (CASO DE USO #2)
# =====================================================================
class ClassSessionPhaseSchema(BaseModel):
    """Fase secuencial dentro de la planeación didáctica de una sesión de clase."""

    model_config = ConfigDict(extra="forbid")

    fase: Literal["INICIO_APERTURA", "DESARROLLO_CENTRAL", "CIERRE_EVALUACION"] = Field(
        ..., description="Etapa metodológica de la sesión de clase."
    )
    duracion_minutos: int = Field(
        ..., ge=5, le=240, description="Tiempo estimado en minutos para esta fase."
    )
    actividad_docente: str = Field(
        ..., min_length=10, description="Acción pedagógica que ejecuta el profesor."
    )
    actividad_estudiantes: str = Field(
        ..., min_length=10, description="Rol activo y práctica que realizan los alumnos."
    )
    recursos_didacticos: list[str] = Field(
        default_factory=list,
        description="Materiales, herramientas o software requerido en la fase.",
    )


class EvaluationRubricCriterionSchema(BaseModel):
    """Fila de criterio de evaluación con niveles de desempeño en escala 0.0 a 5.0."""

    model_config = ConfigDict(extra="forbid")

    criterio: str = Field(
        ..., min_length=5, description="Dimensión o competencia evaluada."
    )
    peso_porcentual: float = Field(
        ..., gt=0.0, le=100.0, description="Porcentaje del criterio en la rúbrica (suma 100%)."
    )
    nivel_excelente_45_a_50: str = Field(
        ..., description="Descriptor de dominio sobresaliente (4.5 a 5.0)."
    )
    nivel_aprobatorio_30_a_44: str = Field(
        ..., description="Descriptor de dominio satisfactorio/estándar (3.0 a 4.4)."
    )
    nivel_insuficiente_00_a_29: str = Field(
        ..., description="Descriptor de desempeño en desarrollo o insuficiente (0.0 a 2.9)."
    )


class MultipleChoiceQuestionSchema(BaseModel):
    """Pregunta tipo test (opción múltiple con única respuesta) alineada a taxonomía de Bloom."""

    model_config = ConfigDict(extra="forbid")

    enunciado: str = Field(
        ..., min_length=15, description="Planteamiento o caso de la pregunta."
    )
    opciones: list[str] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Exactamente 4 opciones de respuesta (A, B, C, D).",
    )
    indice_respuesta_correcta: int = Field(
        ...,
        ge=0,
        le=3,
        description="Índice basado en cero (0 a 3) que señala la opción correcta en `opciones`.",
    )
    nivel_taxonomia_bloom: Literal[
        "RECORDAR", "COMPRENDER", "APLICAR", "ANALIZAR", "EVALUAR"
    ] = Field(..., description="Nivel cognitivo evaluado según Bloom.")
    justificacion_pedagogica: str = Field(
        ...,
        min_length=15,
        description="Explicación de por qué la opción correcta es válida y por qué los distractores fallan.",
    )


class AICurriculumAssistantSchema(BaseModel):
    """
    Contrato estricto de salida (Structured Output) para el Asistente Curricular Docente.
    Genera planeación de clase, rúbrica analítica y banco de preguntas listos para BD.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    titulo_sesion_propuesta: str = Field(
        ..., min_length=10, max_length=250, description="Título didáctico de la sesión."
    )
    objetivo_aprendizaje_especifico: str = Field(
        ..., min_length=20, description="Resultado de aprendizaje medible para la sesión."
    )
    fases_planeacion_clase: list[ClassSessionPhaseSchema] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Las 3 fases secuenciales de la clase (Inicio, Desarrollo, Cierre).",
    )
    rubrica_evaluacion: list[EvaluationRubricCriterionSchema] = Field(
        ...,
        min_length=2,
        max_length=6,
        description="Matriz de rúbrica analítica para evaluar el tema.",
    )
    banco_preguntas_test: list[MultipleChoiceQuestionSchema] = Field(
        ...,
        min_length=1,
        max_length=15,
        description="Banco de preguntas tipo test de selección múltiple.",
    )


# =====================================================================
# 3. CONTRATOS IA: TUTOR RAG BASADO EN EL SÍLABO (CASO DE USO #3)
# =====================================================================
class RAGStructuredAnswerSchema(BaseModel):
    """
    Contrato estricto de salida (Structured Output) para el Tutor RAG.
    Garantiza que el LLM responda únicamente con base en los temas oficiales del sílabo.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    esta_dentro_del_silabo: bool = Field(
        ...,
        description=(
            "True si la duda del alumno se puede responder con los fragmentos del sílabo "
            "recuperados; False si la pregunta es ajena a la materia."
        ),
    )
    respuesta_tutor: str = Field(
        ...,
        min_length=20,
        description="Explicación pedagógica clara, rigurosa y basada estrictamente en el sílabo.",
    )
    conceptos_clave_abordados: list[str] = Field(
        default_factory=list,
        description="Lista de conceptos oficiales del sílabo empleados en la explicación.",
    )
    unidades_y_temas_citados: list[str] = Field(
        default_factory=list,
        description="Referencias exactas a las unidades y temas del sílabo usados como fuente.",
    )
    ejercicio_autoevaluacion_sugerido: str = Field(
        ...,
        min_length=10,
        description="Pequeño reto o pregunta reflexiva para que el estudiante compruebe lo aprendido.",
    )

    @model_validator(mode="after")
    def ensure_citations_when_in_syllabus(self) -> "RAGStructuredAnswerSchema":
        if self.esta_dentro_del_silabo and not self.unidades_y_temas_citados:
            self.unidades_y_temas_citados = ["Contenido oficial del sílabo recuperado"]
        return self
