# SoftEdu — Sistema de Gestión Académica y Control Educativo Inteligente (AI-Powered LMS/SIS)

Backend empresarial **100% asíncrono** construido con **Python 3.11+**, **FastAPI**, **SQLAlchemy 2.0 (`AsyncSession` + `asyncpg`)**, **PostgreSQL con `pgvector`** y un **Motor de Copiloto IA** compatible con **Google Gemini (`google-genai`)** y **OpenAI SDK** con **Structured Outputs (Pydantic v2)** y **RAG (Retrieval-Augmented Generation)**.

---

## 🏗️ Arquitectura en Capas Orientada a Dominios

1. **API / Routers (`app/api/v1/routers/`)**: Controladores HTTP asíncronos, control de acceso basado en roles (**RBAC**: `ADMIN`, `TEACHER`, `STUDENT`) con JWT y disparo de análisis de IA en segundo plano (`BackgroundTasks`).
2. **Services (`app/services/`)**: Reglas de negocio académicas, validación de cruces de bloques horarios (`schedule_blocks`), cálculo ponderado en escala `0.00` a `5.00` (nota mínima aprobatoria `3.00`) y orquestación de casos de uso.
3. **AI Engine (`app/ai/ai_service.py`)**: Capa aislada bajo patrón **Strategy/Adapter** (`GoogleGeminiAdapter` / `OpenAIAdapter`), generación de embeddings en `pgvector`, control de timeouts (`asyncio.wait_for`) y *Circuit Breaker Fallback* para nunca interrumpir las transacciones académicas.
4. **Repositories (`app/repositories/`)**: Consultas SQL asíncronas con carga ansiosa (`selectinload` / `joinedload`) y búsqueda semántica por distancia coseno (`<=>`) sobre índices vectoriales **HNSW** en `pgvector`.
5. **Models & Schemas (`app/models/` y `app/schemas/`)**: 12 entidades ORM SQLAlchemy 2.0 con auditoría transversal (`created_at`, `updated_at`, `is_active`) y contratos Pydantic v2.

---

## 🤖 Los 3 Casos de Uso Reales del Copiloto IA

1. **Alerta Temprana de Riesgo Académico (Predictivo/Analítico):**
   - Al registrar una calificación (`POST /api/v1/grades`) o una inasistencia (`POST /api/v1/academic/attendances`), `BackgroundTasks` analiza el promedio ponderado acumulado, el % de fallas y los temas reprobados, generando un diagnóstico estructurado (`AIRiskAssessmentSchema`) que se almacena en `student_ai_insights` y se consulta en el boletín (`GET /api/v1/grades/enrollments/{enrollment_id}/report-card`).
2. **Asistente Curricular para el Docente (Generativo):**
   - El endpoint `POST /api/v1/syllabus/topics/{topic_id}/curricular-assistant` recibe un tema oficial del sílabo (`SyllabusTopic`) y genera mediante el LLM una planeación de clase en 3 fases, una rúbrica analítica (escala `0.0` a `5.0`) y un banco de preguntas tipo test alineado a la **Taxonomía de Bloom** (`AICurriculumAssistantSchema`).
3. **Tutor RAG Basado en el Sílabo (`pgvector`):**
   - El endpoint `POST /api/v1/syllabus/rag-tutor/ask` convierte la duda del alumno en un vector de embeddings, busca por similitud coseno en `pgvector` los temas oficiales de la asignatura y responde con *grounding* estricto citando las unidades y temas empleados (`RAGStructuredAnswerSchema`).

---

## 🚀 Ejecución Local

1. Instala las dependencias:
   ```powershell
   pip install -r requirements.txt
   ```
2. Inicia el servidor con doble clic en **`iniciar_softedu.bat`** o por terminal:
   ```powershell
   python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```
3. Abre la documentación interactiva OpenAPI / Swagger UI:
   👉 **http://127.0.0.1:8000/docs**

### Credenciales Semilla por Defecto (Creadas automáticamente al iniciar)
- **Administrador (`ADMIN`)**: `admin@softedu.edu.co` / `admin12345`
- **Docente (`TEACHER`)**: `docente@softedu.edu.co` / `docente123`
- **Estudiante (`STUDENT`)**: `estudiante@softedu.edu.co` / `estudiante123`

---

## ☁️ Despliegue Automático en AWS (GitHub Actions + SSH)

El proyecto incluye el flujo `.github/workflows/deploy.yml` (siguiendo el mismo estándar de `Dian2676Py`) y el script de aprovisionamiento `deploy/aws_setup_softedu.sh`:

- **Secrets en GitHub (`Settings -> Secrets and variables -> Actions`):**
  - `AWS_HOST`: IP elástica o dominio del servidor AWS EC2.
  - `AWS_USER`: Usuario SSH con permisos sudo.
  - `AWS_SSH_KEY`: Clave privada SSH (`.pem`).
  - `AWS_PORT`: Puerto SSH (por defecto `22`).
  - Opcionales: `AWS_SITE_DIR` (por defecto `/home/softedu/htdocs/softedu.duckdns.org`) y `AWS_SITE_USER` (por defecto `softedu`).
