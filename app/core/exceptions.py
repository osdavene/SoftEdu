"""Excepciones de dominio y de infraestructura del sistema."""

from typing import Any


class SoftEduError(Exception):
    """Excepción base de la aplicación."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class EntityNotFoundError(SoftEduError):
    """Se lanza cuando un recurso solicitado no existe o está inactivo."""

    def __init__(self, entity_name: str, identifier: Any) -> None:
        super().__init__(
            message=f"{entity_name} con identificador '{identifier}' no fue encontrado.",
            status_code=404,
            details={"entity": entity_name, "identifier": str(identifier)},
        )


class BusinessRuleViolationError(SoftEduError):
    """Se lanza cuando una operación infringe una regla de negocio académica."""

    def __init__(
        self,
        message: str,
        rule_code: str = "ACADEMIC_RULE_VIOLATION",
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {"rule_code": rule_code, **(details or {})}
        super().__init__(message=message, status_code=422, details=payload)


class UnauthorizedAccessError(SoftEduError):
    """Se lanza cuando el usuario carece de permisos RBAC para la operación."""

    def __init__(self, message: str = "No tiene permisos suficientes para esta operación.") -> None:
        super().__init__(message=message, status_code=403)


class AIServiceExecutionError(SoftEduError):
    """Excepción controlada para fallos o timeouts del proveedor LLM."""

    def __init__(self, message: str, provider: str, original_error: str | None = None) -> None:
        super().__init__(
            message=message,
            status_code=503,
            details={"provider": provider, "error": original_error},
        )
