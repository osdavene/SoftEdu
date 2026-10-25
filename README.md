# SoftEdu K-12 Cloud — Plataforma de Gestión Escolar y Sistema Académico Inteligente

Plataforma empresarial de gestión educativa **SaaS Multi-Colegio** y **LMS/SIS integral** diseñada bajo la normativa del **Ministerio de Educación Nacional de Colombia (MEN)**, **Ley 115 de 1994**, **Decreto 1860**, **Decreto 1290 de 2009**, **Resolución 4210 de 1996** y estándares del **SIMAT**.

Abarca el ciclo escolar completo desde **Primera Infancia (Maternal)** hasta **Educación Media Vocacional (Grado 11°)** con un motor de **Inteligencia Artificial Copiloto Escolar** basado en **Google Gemini** y **OpenAI**, **Structured Outputs (Pydantic v2)** y **RAG (Retrieval-Augmented Generation)** sobre **PostgreSQL**.

---

## 🏛️ Ecosistema Normativo y Arquitectura por Niveles (Maternal a 11°)

| Etapa Educativa | Grados Oficiales MEN | Lógica Académica y Regla de Negocio |
| :--- | :--- | :--- |
| **Primera Infancia** | Maternal, Párvulos, Prejardín, Jardín y Transición | Juicios valorativos por **Dimensiones del Desarrollo** (Cognitiva, Comunicativa, Corporal, Socioafectiva). Control estricto de **persona autorizada para retirar al menor**, carnet de vacunación, control de crecimiento y desarrollo, y ficha médica de alergias. |
| **Básica Primaria** | 1°, 2°, 3°, 4° y 5° | Evaluación por Áreas y Asignaturas (escala `0.00` a `5.00`, mínima aprobatoria `3.00`). Seguimiento de inasistencias y alertas tempranas de deserción. |
| **Básica Secundaria** | 6°, 7°, 8° y 9° | Agrupación curricular, control de promoción escolar, comités de evaluación y actas de recuperación (Decreto 1290). |
| **Media Vocacional** | 10° y 11° | Control de requisitos legales de graduación: **80 horas de Servicio Social Estudiantil Obligatorio (Res. 4210)**, registro y puntaje **ICFES Saber 11**, legajo de certificados de 5° a 10°, paz y salvo administrativo y expedición de Acta de Grado y Diploma con número de folio y libro. |

---

## 🚀 Módulos Funcionales de la Plataforma

```
[ SoftEdu K-12 Cloud Workspace ]
├── 🌐 1. SuperPanel SaaS Multi-Colegio (SuperAdmin Global)
├── 🏛️ 2. Rectoría y Gobierno Escolar (Directivos y Coordinación)
├── 📋 3. Secretaría Académica Integral (SIMAT, Legajos, Grado 11, Constancias)
│   ├── 1. Salones y Grupos por Grado (Cursos 6-1, 6-2, 6-3, 11-1...)
│   ├── 2. Matrícula Oficial SIMAT (TI, RC, CC, PEP, PPT, RH, EPS, Estrato DANE)
│   ├── 3. Legajo y Expediente Documental Dinámico (Checklist por nivel)
│   ├── 4. Acudientes Desacoplados (Responsable Financiero / Retiro de Menores)
│   ├── 5. Control de Grado 11° (80h Servicio Social + Pruebas ICFES Saber 11)
│   ├── 6. Constancias y Certificados Oficiales con Código QR de Autenticidad
│   ├── 7. Ventanilla de Calificaciones (Apertura y Cierre de Notas por Período)
│   └── 8. Exportador Oficial de Archivo Plano SIMAT (CSV UTF-8 BOM)
├── 📅 4. Horarios Escolares y Malla Semanal (3 Perspectivas Interactivas)
│   ├── Perspectiva por Salón / Grupo (Carga horaria, aula y director)
│   ├── Perspectiva por Docente Titular (Asignaturas y salones asignados)
│   └── Perspectiva por Aula / Espacio Físico (Ocupación y disponibilidad)
├── 📝 5. Planilla Masiva de Asistencia Escolar (Presente, Falla, Tarde, Excusa)
├── 📊 6. Calificaciones y Boletines Oficiales Decreto 1290 (Superior, Alto, Básico, Bajo)
└── 🤖 7. Centro Copiloto IA Escolar (3 Motores de Inteligencia Artificial)
    ├── Motor 1: Alerta Temprana de Riesgo Académico y Deserción
    ├── Motor 2: Asistente Curricular Docente (Planeación Didáctica y Rúbricas MEN)
    └── Motor 3: Tutor Escolar RAG (Vectorización del Plan de Estudios)
```

---

## 🔐 Matriz de Control de Acceso Basada en Roles (RBAC)

La plataforma aplica permisos estrictos de navegación e interfaz según el rol del usuario autenticado:

| Rol del Usuario | Colegios SaaS | Rectoría | Secretaría | Horarios | Asistencia | Calificaciones | Copiloto IA |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`SUPERADMIN`** | ✅ Total | ❌ Bloqueado | ❌ Bloqueado | ❌ Bloqueado | ❌ Bloqueado | ❌ Bloqueado | ❌ Bloqueado |
| **`RECTOR`** | ❌ Oculto | ✅ Total | ✅ Total | ✅ Total | ✅ Total | ✅ Total | ✅ Total |
| **`COORDINADOR`** | ❌ Oculto | ✅ Total | ✅ Total | ✅ Total | ✅ Total | ✅ Total | ✅ Total |
| **`SECRETARIA`** | ❌ Oculto | ✅ Lectura | ✅ **Módulo Principal** | ✅ Total | ✅ Total | ✅ Auditoría | ✅ Total |
| **`DOCENTE`** | ❌ Oculto | ❌ Oculto | ❌ Oculto | ✅ Horario Propio | ✅ Registrar | ✅ Subir Notas | ✅ Asistente MEN |
| **`ESTUDIANTE`** | ❌ Oculto | ❌ Oculto | ❌ Oculto | ✅ Horario Salón | ❌ Oculto | ✅ Ver Notas | ✅ Tutor RAG |

> [!IMPORTANT]
> **Privacidad y Protección de Menores en SuperAdmin**: Por diseño de arquitectura y cumplimiento de la Ley de Protección de Datos (Habeas Data), el `SUPERADMIN` gestiona colegios, asigna rectores y habilita grados; **nunca tiene acceso a los expedientes personales, datos de acudientes ni calificaciones de los estudiantes**.

---

## 📋 Detalle de la Secretaría Académica (Módulo Central)

### 1. Salones y Cursos por Grado (`ClassroomGroup`)
- Creación de cursos según la demanda de matrícula: para Grado 6° se crean ordenadamente `6-1`, `6-2`, `6-3` sucesivamente.
- Cada grupo registra: grado oficial, código del salón, cupo máximo (ej: 35 alumnos), jornada escolar (`MAÑANA`, `TARDE`, `UNICA`, `COMPLETA`), aula física y **Docente Director(a) de Grupo**.
- Indicador visual en tiempo real de cupos disponibles y porcentaje de ocupación con barra de color.

### 2. Formalización de Matrícula y Variables Oficiales SIMAT
- **Tipos de documento legal:** `RC` (Registro Civil), `TI` (Tarjeta de Identidad), `CC` (Cédula de Ciudadanía), `PPT` (Permiso por Protección Temporal), `PEP`, `CE`.
- **Variables demográficas obligatorias DANE/MEN:**
  - Grupo sanguíneo y factor RH (`O+`, `O-`, `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`).
  - Entidad prestadora de salud (EPS de afiliación).
  - Estrato socioeconómico (1 al 6).
  - Condición de discapacidad o capacidades excepcionales.
  - **Ficha médica y de alergias:** Alertas médicas para Primera Infancia.

### 3. Acudientes Desacoplados (`Guardian`)
- Separación formal de datos en la base de datos (relación muchos a muchos).
- Identificación de parentesco: `MADRE`, `PADRE`, `ACUDIENTE_LEGAL`, `FAMILIAR_AUTORIZADO`.
- Flags específicos:
  - `is_financial_responsible`: Quien firma el pagaré de matrícula y responde por pensiones.
  - `is_authorized_pickup`: Persona con autorización legal para retirar al menor del plantel (Maternal a Transición).

### 4. Legajo y Checklist Documental Dinámico (`StudentDocument`)
- Adaptación automática de los requisitos según el nivel escolar:
  - **Maternal y Preescolar:** Carnet de Vacunación al día, Certificado de Control de Crecimiento y Desarrollo, Registro Civil de Nacimiento.
  - **Primaria y Bachillerato:** Tarjeta de Identidad, Certificados de Calificaciones de años anteriores (5° a 10°) y Paz y Salvo del colegio de procedencia.
- Estados de gestión: `PENDIENTE`, `CARGADO`, `APROBADO`, `RECHAZADO`.
- Verificación en un solo clic con registro inmutable de auditoría.

### 5. Control de Grado 11° y Servicio Social (`GraduationRequirement`)
- Control de cumplimiento del **Servicio Social Estudiantil Obligatorio** (mínimo 80 horas de ley) con barra de progreso porcentual.
- Registro de inscripción ante el ICFES y puntaje global en pruebas **Saber 11** (escala de 0 a 500 puntos).
- Verificación de certificados oficiales de 5° a 10° completos y paz y salvo financiero.
- Dictamen de promoción oficial: **`APTO PARA GRADO`** o **`EN TRÁMITE`**.
- Asignación de número de folio en el libro oficial de actas de grado.

### 6. Certificaciones y Constancias Oficiales (`OfficialCertificate`)
- Emisión instantánea de:
  - **Constancia de Estudio Vigente** (para Cajas de Compensación, EPS, subsidios o visas).
  - **Certificado Oficial de Calificaciones**.
  - **Acta de Grado de Bachiller**.
- **Bloqueo preventivo por Cartera:** El sistema valida el estado financiero; si el estudiante no tiene paz y salvo, bloquea la expedición alertando a secretaría.
- **Validador de Autenticidad QR / Código Alfanumérico:** Cada documento incluye un código único (ej: `CERT-2026-LROD-8821`). Terceros pueden verificar la autenticidad del documento sin llamadas ni sellos físicos en `GET /api/v1/academic/certificates/verify/{code}`.
- Vista previa imprimible lista para papel membretado o exportación PDF.

### 7. Ventanilla de Calificaciones por Período (`GradingWindow`)
- Fechas de apertura y cierre para que los docentes suban valoraciones de cada período lectivo (1°, 2°, 3°, 4°).
- Conmutador en tiempo real: Si la ventanilla está cerrada, los docentes tienen permiso de solo lectura. Solo la Secretaría puede habilitar extemporaneidades.

### 8. Exportador Plano SIMAT
- Endpoint `GET /api/v1/academic/simat/export` que genera un archivo plano `.csv` con codificación `UTF-8 con BOM` para Excel y software del MEN, conteniendo códigos DANE, identificación, estratificación, EPS, RH, grado y salón sin reprocesos.

---

## 🤖 Los 3 Motores del Copiloto IA Escolar

1. **Motor 1: Alerta Temprana de Riesgo Académico (Predictivo):**
   - Procesa notas parciales e inasistencias en tiempo real mediante `BackgroundTasks`.
   - Genera un diagnóstico con Structured Outputs (`AIRiskAssessmentSchema`), clasificando el nivel de riesgo (`BAJO`, `MEDIO`, `ALTO`, `CRITICO`) y sugiriendo planes de nivelación remedial según el Decreto 1290.

2. **Motor 2: Asistente Curricular Docente (Generativo):**
   - Recibe una unidad temática del sílabo oficial y genera una planeación didáctica en 3 fases (Inicio, Desarrollo y Cierre), rúbricas analíticas MEN y bancos de preguntas tipo Saber 11 estructuradas bajo la Taxonomía de Bloom (`AICurriculumAssistantSchema`).

3. **Motor 3: Tutor Escolar RAG (`pgvector` + Cosine Similarity):**
   - Convierte las consultas del estudiante en embeddings y realiza una búsqueda vectorial sobre el plan de estudios del colegio, respondiendo con *grounding* estricto y citando las unidades curriculares correspondientes (`RAGStructuredAnswerSchema`).

---

## 🛠️ Stack Tecnológico

- **Backend:** Python 3.11+, FastAPI (asíncrono), Pydantic v2.
- **ORM & Base de Datos:** SQLAlchemy 2.0 (`AsyncSession` + `asyncpg`), PostgreSQL 15+ con extensión `pgvector` (con fallback transparente JSONB Cosine).
- **Seguridad y Criptografía:** JWT (JSON Web Tokens), `passlib` con `bcrypt`, control de acceso basado en roles (RBAC).
- **Inteligencia Artificial:** Google Gemini SDK (`google-genai`), OpenAI SDK, Embeddings vectoriales.
- **Frontend:** HTML5 semántico, CSS3 moderno con variables de diseño, JavaScript nativo sin dependencias pesadas, FontAwesome 6.5.

---

## 🚀 Puesta en Marcha Local

### 1. Requisitos Previos
- Python 3.11 o superior instalado.
- Servidor PostgreSQL en ejecución.

### 2. Instalación de Dependencias
```powershell
pip install -r requirements.txt
```

### 3. Configuración de Variables de Entorno (`.env`)
```env
DATABASE_URL=postgresql+asyncpg://postgres:tu_password@localhost:5432/softedu_db
SECRET_KEY=clave_secreta_jwt_softedu_2026_super_segura
GEMINI_API_KEY=tu_clave_gemini_aqui
OPENAI_API_KEY=tu_clave_openai_aqui
```

### 4. Iniciar el Servidor
Puedes hacer doble clic en **`iniciar_softedu.bat`** o ejecutar por terminal:
```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Acceso al aplicativo web:
👉 **http://127.0.0.1:8000**

Documentación interactiva de la API (Swagger UI):
👉 **http://127.0.0.1:8000/docs**

---

## 🔑 Credenciales Institucionales de Prueba (Sembradas en Base de Datos)

Todas las cuentas se inicializan con la contraseña estándar: **`SoftEdu2026*`**

| Rol Escolar | Nombre Completo | Correo Institucional | Panel / Vista Principal |
| :--- | :--- | :--- | :--- |
| **SuperAdmin** | Ing. Carlos Mendoza | `admin@softedu.edu.co` | **SuperPanel SaaS Global** (Gestión de colegios y rectores) |
| **Rectoría** | Dr. Roberto Gómez Bolaños | `rector@gimnasiosanangel.edu.co` | **Rectoría y Gobierno Escolar** (Colegio San Ángel - Cal. A) |
| **Secretaría** | Lic. Martha Lucía Pineda | `secretaria@gimnasiosanangel.edu.co` | **Secretaría Académica** (Expedientes, SIMAT, Grado 11°) |
| **Coordinador** | Lic. Ana María Torres | `coordinador@gimnasiosanangel.edu.co` | **Gobierno y Convivencia Escolar** |
| **Docente (Mat)** | Prof. María Camila Duque | `camila.duque@gimnasiosanangel.edu.co` | **Asistencia, Horario y Notas** (Cálculo y Álgebra) |
| **Docente (Cien)** | Prof. Juan David Henao | `juan.henao@gimnasiosanangel.edu.co` | **Asistencia y Notas** (Física Mecánica y Termodinámica) |
| **Estudiante** | Laura Sofía Rodríguez | `laura.rodriguez@gimnasiosanangel.edu.co` | **Boletín Decreto 1290 y Horario** (Salón 11-1) |
| **Estudiante** | Mateo Gómez | `mateo.gomez@gimnasiosanangel.edu.co` | **Boletín Decreto 1290** (En seguimiento de riesgo IA) |

---

## 🧪 Pruebas Automatizadas

El proyecto incluye suites de pruebas de extremo a extremo (E2E) que verifican la integridad de las rutas, autenticación y reglas de negocio:

```powershell
# Ejecutar prueba completa del ciclo de Secretaría Académica (SIMAT, 11°, Constancias, Ventanilla):
python test_secretaria_e2e.py
```

---

## ☁️ Despliegue en Servidor AWS EC2

El repositorio incluye automatización completa en `.github/workflows/deploy.yml` y script de aprovisionamiento en `deploy/aws_setup_softedu.sh`:

- **Configuración de Secrets en GitHub (`Settings -> Secrets and variables -> Actions`):**
  - `AWS_HOST`: IP elástica o DNS público del servidor EC2.
  - `AWS_USER`: Usuario SSH con privilegios sudo (ej. `ubuntu` o `softedu`).
  - `AWS_SSH_KEY`: Clave privada SSH (`.pem`).
  - `AWS_PORT`: Puerto SSH (`22`).
- Al realizar `git push origin main`, GitHub Actions actualiza el código, migra la base de datos y reinicia el servicio `systemd` sin tiempo de inactividad.
