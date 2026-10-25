"""Configuración centralizada del sistema mediante Pydantic Settings v2."""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variables de entorno y configuración global de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Entorno y Aplicación ---
    PROJECT_NAME: str = "SoftEdu AI-Powered LMS/SIS"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True

    # --- Base de Datos (PostgreSQL + asyncpg + pgvector) ---
    POSTGRES_HOST: str = Field(default="127.0.0.1", description="Host de PostgreSQL")
    POSTGRES_PORT: int = Field(default=5432, ge=1, le=65535)
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(default="7420")
    POSTGRES_DB: str = Field(default="softedu_db")
    DATABASE_URL: str | None = Field(
        default=None,
        description="URL directa opcional (ej. AWS / RDS postgresql+asyncpg://...)",
    )
    DB_POOL_SIZE: int = Field(default=20, ge=5, le=100)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=50)
    DB_POOL_TIMEOUT: int = Field(default=30, ge=5)
    DB_ECHO_SQL: bool = False

    # --- Seguridad y JWT ---
    JWT_SECRET_KEY: str = Field(
        default="softedu-enterprise-jwt-secret-key-2026-aws-production-ready",
        min_length=32,
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 horas

    # --- Motor de IA / LLM (Gemini / OpenAI) ---
    AI_PROVIDER: Literal["gemini", "openai"] = "gemini"
    AI_API_KEY: str = Field(
        default="AIzaSyDummyKeyForDevelopmentReplaceInEnv",
        description="API Key del proveedor LLM (Google Gemini o OpenAI)",
    )
    AI_MODEL_NAME: str = Field(
        default="gemini-2.5-flash",
        description="Modelo generativo principal con soporte para Structured Outputs",
    )
    AI_EMBEDDING_MODEL_NAME: str = Field(
        default="text-embedding-004",
        description="Modelo para generación de vectores semánticos (Sílabo RAG)",
    )
    AI_EMBEDDING_DIMENSION: int = Field(
        default=768,
        description="Dimensión del vector en pgvector (768 para text-embedding-004, 1536 para OpenAI)",
    )
    AI_REQUEST_TIMEOUT_SECONDS: float = Field(
        default=25.0,
        ge=5.0,
        le=120.0,
        description="Timeout máximo por inferencia de IA para evitar bloqueos",
    )
    AI_TEMPERATURE: float = Field(default=0.2, ge=0.0, le=1.0)

    # --- Reglas de Negocio Académicas ---
    MIN_GRADE_SCALE: float = 0.0
    MAX_GRADE_SCALE: float = 5.0
    MIN_PASSING_GRADE: float = 3.0
    MAX_ABSENCE_PERCENTAGE_ALLOWED: float = 20.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Construye el DSN asíncrono `postgresql+asyncpg://` escapando credenciales."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+asyncpg://", 1)
            if url.startswith("postgres://"):
                return url.replace("postgres://", "postgresql+asyncpg://", 1)
            return url

        encoded_password = quote_plus(self.POSTGRES_PASSWORD)
        dsn = PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=encoded_password,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )
        return str(dsn)


@lru_cache
def get_settings() -> Settings:
    """Retorna una instancia singleton en caché de la configuración."""
    return Settings()


settings = get_settings()
