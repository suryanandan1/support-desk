"""Registration, login, and token validation for /api/v1/auth."""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.tests.conftest import TEST_PASSWORD

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def _register_payload(**overrides: str) -> dict[str, str]:
    payload = {"email": "new.user@example.com", "full_name": "New User", "password": "Password123"}
    payload.update(overrides)
    return payload


def _audit_actions(db, user_id: int) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).where(AuditLog.actor_id == user_id)))


def _b64url(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


# --------------------------------------------------------------------------- register


def test_register_creates_customer_and_returns_working_token(client):
    response = client.post(
        REGISTER, json=_register_payload(email="  New.User@Example.COM ", full_name="  New   User ")
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_expire_minutes * 60
    assert body["user"]["email"] == "new.user@example.com"
    assert body["user"]["full_name"] == "New User"
    assert body["user"]["role"] == "customer"
    assert "hashed_password" not in body["user"]

    me = client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def test_register_stores_only_an_argon2_hash(client, db):
    client.post(REGISTER, json=_register_payload())

    user = db.scalar(select(User).where(User.email == "new.user@example.com"))
    assert user is not None
    assert user.hashed_password.startswith("$argon2id$")
    assert "Password123" not in user.hashed_password


def test_register_rejects_duplicate_email_case_insensitively(client, make_user):
    make_user(email="taken@example.com")

    response = client.post(REGISTER, json=_register_payload(email="TAKEN@example.com"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    ("password", "expected_message"),
    [
        ("Short1", "at least 8 characters"),
        ("onlyletters", "one letter and one number"),
        ("12345678", "one letter and one number"),
        ("A1" + "x" * 127, "at most 128 characters"),
    ],
)
def test_register_rejects_weak_passwords(client, password, expected_message):
    response = client.post(REGISTER, json=_register_payload(password=password))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "password"
    assert expected_message in error["details"][0]["message"]
    # The rejected password is never echoed back to the client.
    assert password not in response.text


@pytest.mark.parametrize("bad_email", ["not-an-email", "a@b", "@example.com", ""])
def test_register_rejects_invalid_email(client, bad_email):
    response = client.post(REGISTER, json=_register_payload(email=bad_email))

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "email"


def test_register_cannot_choose_own_role(client, db):
    response = client.post(REGISTER, json={**_register_payload(), "role": "admin"})

    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(User)) == 0


def test_register_is_audited(client, db):
    user_id = client.post(REGISTER, json=_register_payload()).json()["user"]["id"]

    assert _audit_actions(db, user_id) == ["auth.register"]


# --------------------------------------------------------------------------- login


def test_login_returns_token_and_records_the_login(client, db, make_user):
    user = make_user(email="login@example.com")

    response = client.post(LOGIN, json={"email": "Login@Example.com", "password": TEST_PASSWORD})

    assert response.status_code == 200
    assert response.json()["user"]["id"] == user.id
    db.expire_all()
    last_login = db.get(User, user.id).last_login_at
    assert last_login is not None
    assert last_login.tzinfo is not None  # stored and returned as aware UTC
    assert abs(datetime.now(UTC) - last_login) < timedelta(minutes=1)
    assert _audit_actions(db, user.id) == ["auth.login"]


def test_wrong_password_and_unknown_email_are_indistinguishable(client, make_user):
    make_user(email="real@example.com")

    wrong_password = client.post(LOGIN, json={"email": "real@example.com", "password": "Wrong1234"})
    unknown_email = client.post(LOGIN, json={"email": "nobody@example.com", "password": "Wrong1234"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == "Incorrect email or password"
    assert unknown_email.json()["error"]["message"] == "Incorrect email or password"
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


def test_failed_login_is_audited(client, db, make_user):
    user = make_user(email="real@example.com")

    client.post(LOGIN, json={"email": "real@example.com", "password": "Wrong1234"})

    assert _audit_actions(db, user.id) == ["auth.login_failed"]


def test_deactivated_account_cannot_log_in(client, make_user):
    make_user(email="gone@example.com", is_active=False)

    correct = client.post(LOGIN, json={"email": "gone@example.com", "password": TEST_PASSWORD})
    wrong = client.post(LOGIN, json={"email": "gone@example.com", "password": "Wrong1234"})

    assert correct.status_code == 403
    assert correct.json()["error"]["code"] == "permission_denied"
    # Without the right password the response must not reveal the account is disabled.
    assert wrong.status_code == 401


# --------------------------------------------------------------------------- /me + tokens


def test_me_returns_the_current_user(client, agent, auth_headers):
    response = client.get(ME, headers=auth_headers(agent))

    assert response.status_code == 200
    assert response.json()["email"] == agent.email
    assert response.json()["role"] == "agent"


def test_me_without_token_is_401(client):
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization",
    ["Bearer not-a-jwt", "Bearer ", "Bearer a.b.c", "Basic dXNlcjpwYXNz", "Token abc", "bearer"],
)
def test_me_rejects_malformed_authorization_headers(client, authorization):
    response = client.get(ME, headers={"Authorization": authorization})

    assert response.status_code == 401


def test_me_rejects_expired_token(client, customer):
    token, _ = create_access_token(customer.id, "customer", expires_delta=timedelta(seconds=-1))

    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Token has expired"


def test_me_rejects_tampered_payload(client, customer, admin, auth_headers):
    header, _payload, signature = auth_headers(customer)["Authorization"].split()[1].split(".")
    # Claim to be the admin while keeping the customer's signature.
    forged_payload = _b64url(
        {"sub": str(admin.id), "role": "admin", "type": "access", "iat": 1, "exp": 9999999999}
    )

    response = client.get(
        ME, headers={"Authorization": f"Bearer {header}.{forged_payload}.{signature}"}
    )

    assert response.status_code == 401


def test_me_rejects_token_signed_with_another_key(client, customer):
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(customer.id), "type": "access", "iat": now, "exp": now + timedelta(hours=1)},
        "an-attacker-chosen-secret-key-that-is-long-enough",
        algorithm="HS256",
    )

    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_me_rejects_unsigned_alg_none_token(client, customer):
    now = int(datetime.now(UTC).timestamp())
    header = _b64url({"alg": "none", "typ": "JWT"})
    payload = _b64url({"sub": str(customer.id), "type": "access", "iat": now, "exp": now + 3600})

    response = client.get(ME, headers={"Authorization": f"Bearer {header}.{payload}."})

    assert response.status_code == 401


def test_me_rejects_token_with_non_numeric_subject(client):
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": "admin", "type": "access", "iat": now, "exp": now + timedelta(hours=1)},
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_me_rejects_token_of_a_user_that_no_longer_exists(client, db, customer, auth_headers):
    headers = auth_headers(customer)
    db.delete(customer)
    db.commit()

    assert client.get(ME, headers=headers).status_code == 401


def test_deactivation_revokes_existing_tokens_immediately(client, db, customer, auth_headers):
    headers = auth_headers(customer)
    assert client.get(ME, headers=headers).status_code == 200

    customer.is_active = False
    db.commit()

    response = client.get(ME, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "This account has been deactivated"


def test_role_is_read_from_database_not_from_token(client, db, customer, auth_headers):
    headers = auth_headers(customer)  # the token's role claim says "customer"

    customer.role = UserRole.AGENT
    db.commit()

    assert client.get(ME, headers=headers).json()["role"] == "agent"
