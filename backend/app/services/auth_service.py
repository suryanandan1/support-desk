"""Registration and login."""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.db.base import utcnow
from app.models.user import User, UserRole
from app.repositories import audit_repository, user_repository
from app.schemas.auth import TokenResponse, UserLogin, UserRead, UserRegister

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Incorrect email or password"


def issue_token(user: User) -> TokenResponse:
    token, expires_in = create_access_token(user.id, user.role.value)
    return TokenResponse(
        access_token=token, expires_in=expires_in, user=UserRead.model_validate(user)
    )


def register(db: Session, data: UserRegister, ip_address: str | None = None) -> TokenResponse:
    """Create a customer account and log it in. Staff roles are granted by an admin only."""
    if user_repository.get_by_email(db, data.email) is not None:
        raise ConflictError("An account with this email already exists")

    try:
        user = user_repository.create(
            db,
            email=data.email,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            role=UserRole.CUSTOMER,
        )
        user.last_login_at = utcnow()
        audit_repository.record(
            db,
            action="auth.register",
            actor_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip_address=ip_address,
        )
        db.commit()
    except IntegrityError as exc:
        # Two simultaneous sign-ups with the same email: the unique index catches it.
        db.rollback()
        raise ConflictError("An account with this email already exists") from exc

    logger.info("User registered", extra={"user_id": user.id})
    return issue_token(user)


def login(db: Session, data: UserLogin, ip_address: str | None = None) -> TokenResponse:
    user = user_repository.get_by_email(db, data.email)
    if user is None:
        burn_password_check(data.password)
        logger.info("Login failed: unknown account")
        raise AuthenticationError(INVALID_CREDENTIALS)

    if not verify_password(data.password, user.hashed_password):
        audit_repository.record(
            db,
            action="auth.login_failed",
            actor_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip_address=ip_address,
        )
        db.commit()
        logger.info("Login failed: wrong password", extra={"user_id": user.id})
        raise AuthenticationError(INVALID_CREDENTIALS)

    # Checked only after the password is verified, so it does not reveal
    # which emails belong to disabled accounts.
    if not user.is_active:
        raise PermissionDeniedError("This account has been deactivated")

    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(data.password)
    user.last_login_at = utcnow()
    audit_repository.record(
        db,
        action="auth.login",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
    )
    db.commit()
    logger.info("User logged in", extra={"user_id": user.id})
    return issue_token(user)
