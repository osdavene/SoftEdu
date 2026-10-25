"""Seguridad JWT, Hashing Bcrypt y Control de Acceso Basado en Roles (RBAC) para FastAPI."""

from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
import uuid

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.database import get_db_session
from app.core.exceptions import UnauthorizedAccessError
from app.models.academic import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    """Estructura decodificada del JWT."""

    sub: uuid.UUID
    role: UserRole
    exp: int


def hash_password(plain_password: str) -> str:
    """Genera un hash seguro con Bcrypt compatible con $2b$ / $2y$."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña en texto plano contra su hash Bcrypt."""
    try:
        normalized_hash = hashed_password
        if normalized_hash.startswith("$2y$"):
            normalized_hash = "$2b$" + normalized_hash[4:]
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            normalized_hash.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(user_id: uuid.UUID, role: UserRole) -> str:
    """Genera un token JWT firmado para autenticación stateless."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "role": role.value,
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


async def get_current_active_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """
    Valida el token Bearer JWT y recupera el usuario activo desde PostgreSQL
    cargando sus perfiles asociados (`teacher_profile` y `student_profile`).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales de autenticación no proporcionadas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload_data = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        token_data = TokenPayload.model_validate(payload_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT inválido o expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    stmt = (
        select(User)
        .options(
            joinedload(User.teacher_profile),
            joinedload(User.student_profile),
        )
        .where(
            User.id == token_data.sub,
            User.is_active.is_(True),
        )
    )
    result = await session.execute(stmt)
    user = result.scalars().first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o inexistente.",
        )
    return user


def _expand_equivalent_roles(allowed_roles: tuple[UserRole, ...]) -> set[UserRole]:
    """Expande los grupos jerárquicos de roles institucionales."""
    expanded: set[UserRole] = set(allowed_roles)
    if UserRole.ADMIN in expanded:
        expanded.update(
            {
                UserRole.RECTOR,
                UserRole.COORDINADOR,
                UserRole.SECRETARIA,
            }
        )
    if UserRole.TEACHER in expanded or UserRole.DOCENTE in expanded:
        expanded.update(
            {
                UserRole.TEACHER,
                UserRole.DOCENTE,
                UserRole.COORDINADOR,
                UserRole.RECTOR,
                UserRole.ORIENTADOR,
            }
        )
    if UserRole.STUDENT in expanded or UserRole.ESTUDIANTE in expanded:
        expanded.update(
            {
                UserRole.STUDENT,
                UserRole.ESTUDIANTE,
                UserRole.ORIENTADOR,
                UserRole.SECRETARIA,
                UserRole.COORDINADOR,
                UserRole.RECTOR,
            }
        )
    return expanded


def require_roles(
    *allowed_roles: UserRole,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """
    Fábrica de dependencias RBAC que restringe el acceso a los roles autorizados.
    """
    effective_roles = _expand_equivalent_roles(allowed_roles)

    async def role_checker(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if current_user.role not in effective_roles:
            raise UnauthorizedAccessError(
                message=(
                    f"Operación restringida para su rol actual ('{current_user.role.value}'). "
                    f"Se requiere autorización de: {[r.value for r in effective_roles]}."
                )
            )
        return current_user

    return role_checker
