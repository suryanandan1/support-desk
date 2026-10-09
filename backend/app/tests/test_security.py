"""Unit tests for password hashing, JWT helpers, and log redaction."""

import logging
from datetime import timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.logging import JsonFormatter, TextFormatter, redact
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_round_trip():
    password_hash = hash_password("CorrectHorse9")

    assert verify_password("CorrectHorse9", password_hash)
    assert not verify_password("WrongHorse9", password_hash)


def test_hashes_are_salted():
    assert hash_password("SamePassword1") != hash_password("SamePassword1")


@pytest.mark.parametrize("bad_hash", ["", "not-a-hash", "$argon2id$v=19$garbage"])
def test_verify_against_corrupt_hash_returns_false_instead_of_crashing(bad_hash):
    assert verify_password("anything1", bad_hash) is False


def test_access_token_round_trip():
    token, expires_in = create_access_token(42, "agent")
    payload = decode_access_token(token)

    assert payload["sub"] == "42"
    assert payload["role"] == "agent"
    assert payload["type"] == "access"
    assert expires_in == get_settings().access_token_expire_minutes * 60


def test_expired_token_raises():
    token, _ = create_access_token(1, "customer", expires_delta=timedelta(seconds=-5))

    with pytest.raises(TokenError, match="expired"):
        decode_access_token(token)


def test_token_of_another_type_is_rejected():
    settings = get_settings()
    token = jwt.encode(
        {"sub": "1", "type": "refresh", "iat": 1, "exp": 9999999999},
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(token)


def test_token_missing_required_claims_is_rejected():
    settings = get_settings()
    token = jwt.encode(
        {"sub": "1", "type": "access"},  # no exp / iat
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(token)


# --------------------------------------------------------------------------- redaction

JWT_SAMPLE = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (f"Authorization: Bearer {JWT_SAMPLE}", JWT_SAMPLE),
        ("Bearer abc123opaque", "abc123opaque"),
        ("password=hunter2 user=bob", "hunter2"),
        ('{"api_key": "sk-live-123"}', "sk-live-123"),
        ("secret_key: s3cr3t", "s3cr3t"),
        ("calling with key AIzaSyA1234567890abcdefghijklmnopqrstu", "AIzaSyA1234567890abcdefghijklmnopqrstu"),
    ],
)
def test_redact_masks_secrets(text, secret):
    redacted = redact(text)

    assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_redact_leaves_ordinary_text_alone():
    text = "GET /api/v1/tickets -> 200 | duration_ms=12.5"

    assert redact(text) == text


@pytest.mark.parametrize("formatter", [TextFormatter(), JsonFormatter()])
def test_formatters_redact_messages_and_tracebacks(formatter):
    try:
        raise ValueError(f"token={JWT_SAMPLE}")
    except ValueError as exc:
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "login with password=%s", ("hunter2",), None
        )
        record.exc_info = (type(exc), exc, exc.__traceback__)
        record.request_id = "req-1"

    output = formatter.format(record)

    assert "hunter2" not in output
    assert JWT_SAMPLE not in output
    assert "req-1" in output
