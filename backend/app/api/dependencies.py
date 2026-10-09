"""Shared FastAPI dependencies: database session, current user, role checks."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories import user_repository

# auto_error=False lets us return our own 401 body instead of FastAPI's default.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Paste the access_token returned by POST /api/v1/auth/login",
)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise AuthenticationError("Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc
    except ValueError as exc:
        raise AuthenticationError("Invalid authentication token") from exc

    # Always load the user fresh: a deactivation or role change applies immediately,
    # even to tokens issued before it.
    user = user_repository.get_by_id(db, user_id)
    if user is None:
        raise AuthenticationError("Invalid authentication token")
    if not user.is_active:
        raise AuthenticationError("This account has been deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory: allow the request only if the user has one of ``roles``."""

    def check_role(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("You do not have permission to perform this action")
        return user

    return check_role


AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def get_client_ip(request: Request) -> str | None:
    # X-Forwarded-For is deliberately ignored: without a trusted proxy in front of
    # the app, any client could forge it.
    return request.client.host if request.client else None


ClientIp = Annotated[str | None, Depends(get_client_ip)]
