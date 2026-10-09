"""Password hashing (Argon2id) and JWT access tokens."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_password_hasher = PasswordHasher()

# Verifying against this when an email is unknown makes a failed login take the same
# time whether or not the account exists, so timing does not leak registered emails.
_DUMMY_HASH = _password_hasher.hash("timing-attack-dummy-password")


class TokenError(Exception):
    """Raised when a JWT is malformed, expired, or otherwise unusable."""


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker Argon2 parameters than the current ones."""
    return _password_hasher.check_needs_rehash(password_hash)


def burn_password_check(password: str) -> None:
    """Spend the time of a real verification without checking anything."""
    verify_password(password, _DUMMY_HASH)


def create_access_token(
    user_id: int, role: str, expires_delta: timedelta | None = None
) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``.

    The role claim is informational only. Authorization always re-reads the current
    role from the database, so a role change takes effect on the very next request.
    """
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + expires_delta,
    }
    token = jwt.encode(
        payload, settings.secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid authentication token") from exc

    if payload.get("type") != "access":
        raise TokenError("Invalid authentication token")
    return payload
