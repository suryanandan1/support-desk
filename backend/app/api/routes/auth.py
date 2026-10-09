from fastapi import APIRouter, status

from app.api.dependencies import ClientIp, CurrentUser, DbSession
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLogin, UserRead, UserRegister
from app.schemas.common import ErrorResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse, "description": "Email already registered"}},
)
def register(data: UserRegister, db: DbSession, ip_address: ClientIp) -> TokenResponse:
    """Create a **customer** account and return an access token for it."""
    return auth_service.register(db, data, ip_address)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Wrong email or password"},
        403: {"model": ErrorResponse, "description": "Account deactivated"},
    },
)
def login(data: UserLogin, db: DbSession, ip_address: ClientIp) -> TokenResponse:
    return auth_service.login(db, data, ip_address)


@router.get(
    "/me",
    response_model=UserRead,
    responses={401: {"model": ErrorResponse}},
)
def read_current_user(current_user: CurrentUser) -> User:
    return current_user
