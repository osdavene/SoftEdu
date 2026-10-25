"""Controlador HTTP Asíncrono para Autenticación JWT y Perfil RBAC."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import get_current_active_user
from app.models.academic import User
from app.schemas.management import LoginRequest, TokenResponse, UserProfileResponse
from app.services.academic_management_service import AcademicManagementService

router = APIRouter(
    prefix="/auth",
    tags=["Autenticación JWT & RBAC"],
)


def get_management_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AcademicManagementService:
    return AcademicManagementService(session=session)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Iniciar sesión y obtener token Bearer JWT",
)
async def login_access_token(
    payload: LoginRequest,
    service: Annotated[AcademicManagementService, Depends(get_management_service)],
) -> TokenResponse:
    """Autentica las credenciales del usuario y retorna un token JWT con su rol RBAC."""
    return await service.authenticate_user(payload=payload)


@router.get(
    "/me",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener perfil del usuario actualmente autenticado",
)
async def get_authenticated_user_profile(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserProfileResponse:
    """Retorna los datos e identificadores académicos del usuario autenticado."""
    return AcademicManagementService.map_user_to_profile_dto(current_user)
