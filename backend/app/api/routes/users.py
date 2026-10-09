from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import AdminUser, ClientIp, DbSession
from app.models.user import User
from app.schemas.auth import UserRead
from app.schemas.common import ErrorResponse, Page
from app.schemas.user import UserListParams, UserUpdate
from app.services import user_service

router = APIRouter(
    prefix="/users",
    tags=["Users (admin)"],
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Admins only"},
    },
)


@router.get("", response_model=Page[UserRead])
def list_users(
    params: Annotated[UserListParams, Query()], db: DbSession, _admin: AdminUser
) -> Page[UserRead]:
    return user_service.list_users(db, params)


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    responses={
        400: {"model": ErrorResponse, "description": "Would lock the admin out"},
        404: {"model": ErrorResponse},
    },
)
def update_user(
    user_id: int, data: UserUpdate, db: DbSession, admin: AdminUser, ip_address: ClientIp
) -> User:
    """Change a user's role, name, or active status."""
    return user_service.update_user(
        db, actor=admin, user_id=user_id, data=data, ip_address=ip_address
    )
