"""Role-based access control, enforced by the backend on /api/v1/users (admin only)."""

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.tests.conftest import TEST_PASSWORD

USERS = "/api/v1/users"


# --------------------------------------------------------------------------- who may call


def test_listing_users_requires_authentication(client):
    response = client.get(USERS)

    assert response.status_code == 401


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.AGENT])
def test_non_admins_are_forbidden_server_side(client, make_user, auth_headers, role):
    user = make_user(role)

    list_response = client.get(USERS, headers=auth_headers(user))
    patch_response = client.patch(
        f"{USERS}/{user.id}", json={"role": "admin"}, headers=auth_headers(user)
    )

    assert list_response.status_code == 403
    assert list_response.json()["error"]["code"] == "permission_denied"
    # Not even on their own account: a customer cannot promote themselves.
    assert patch_response.status_code == 403


def test_auth_is_checked_before_body_validation(client, customer, auth_headers):
    # A forbidden caller gets 403, not a 422 that would reveal the expected body shape.
    response = client.patch(f"{USERS}/1", json={"bogus": True}, headers=auth_headers(customer))

    assert response.status_code == 403


# --------------------------------------------------------------------------- listing


def test_admin_can_list_users_with_pagination(client, admin, make_user, auth_headers):
    for _ in range(11):
        make_user(UserRole.CUSTOMER)  # 12 users in total including the admin

    first = client.get(USERS, params={"page": 1, "page_size": 5}, headers=auth_headers(admin))
    last = client.get(USERS, params={"page": 3, "page_size": 5}, headers=auth_headers(admin))

    assert first.status_code == 200
    body = first.json()
    assert (body["total"], body["page"], body["page_size"], body["pages"]) == (12, 1, 5, 3)
    assert len(body["items"]) == 5
    assert len(last.json()["items"]) == 2
    assert "hashed_password" not in body["items"][0]


def test_admin_can_filter_by_role_and_status(client, admin, make_user, auth_headers):
    make_user(UserRole.AGENT)
    make_user(UserRole.AGENT, is_active=False)
    make_user(UserRole.CUSTOMER)

    agents = client.get(USERS, params={"role": "agent"}, headers=auth_headers(admin)).json()
    active_agents = client.get(
        USERS, params={"role": "agent", "is_active": "true"}, headers=auth_headers(admin)
    ).json()

    assert agents["total"] == 2
    assert {u["role"] for u in agents["items"]} == {"agent"}
    assert active_agents["total"] == 1


def test_search_matches_email_or_name_and_escapes_wildcards(client, admin, make_user, auth_headers):
    make_user(email="jane.doe@example.com", full_name="Jane Doe")
    make_user(email="john@example.com", full_name="John Smith")

    by_name = client.get(USERS, params={"search": "smith"}, headers=auth_headers(admin)).json()
    by_email = client.get(USERS, params={"search": "JANE.DOE"}, headers=auth_headers(admin)).json()
    percent = client.get(USERS, params={"search": "%"}, headers=auth_headers(admin)).json()
    underscore = client.get(USERS, params={"search": "_"}, headers=auth_headers(admin)).json()

    assert [u["email"] for u in by_name["items"]] == ["john@example.com"]
    assert [u["email"] for u in by_email["items"]] == ["jane.doe@example.com"]
    # LIKE wildcards are matched literally; unescaped, each would match every user.
    assert percent["total"] == 0
    assert underscore["total"] == 0


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"role": "superuser"}]
)
def test_invalid_list_parameters_are_rejected(client, admin, auth_headers, params):
    response = client.get(USERS, params=params, headers=auth_headers(admin))

    assert response.status_code == 422


# --------------------------------------------------------------------------- updating


def test_admin_can_promote_a_customer_and_it_applies_to_existing_tokens(
    client, admin, customer, auth_headers
):
    customer_headers = auth_headers(customer)
    assert client.get(USERS, headers=customer_headers).status_code == 403

    response = client.patch(
        f"{USERS}/{customer.id}", json={"role": "admin"}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    # Same token as before, new permissions: roles are always read from the database.
    assert client.get(USERS, headers=customer_headers).status_code == 200


def test_demoted_admin_loses_access_immediately(client, admin, make_user, auth_headers):
    other_admin = make_user(UserRole.ADMIN)
    other_headers = auth_headers(other_admin)
    assert client.get(USERS, headers=other_headers).status_code == 200

    client.patch(f"{USERS}/{other_admin.id}", json={"role": "agent"}, headers=auth_headers(admin))

    assert client.get(USERS, headers=other_headers).status_code == 403


def test_deactivated_user_is_locked_out(client, admin, customer, auth_headers):
    customer_headers = auth_headers(customer)

    response = client.patch(
        f"{USERS}/{customer.id}", json={"is_active": False}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert client.get("/api/v1/auth/me", headers=customer_headers).status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"email": customer.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 403


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"role": "customer"}, "You cannot change your own role"),
        ({"is_active": False}, "You cannot deactivate your own account"),
    ],
)
def test_admin_cannot_lock_themselves_out(client, admin, auth_headers, payload, message):
    response = client.patch(f"{USERS}/{admin.id}", json=payload, headers=auth_headers(admin))

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "business_rule_violation",
        "message": message,
        "request_id": response.headers["X-Request-ID"],
    }


def test_admin_can_still_rename_themselves(client, admin, auth_headers):
    response = client.patch(
        f"{USERS}/{admin.id}",
        json={"full_name": "  Renamed   Admin ", "role": "admin"},  # unchanged role is fine
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Renamed Admin"


def test_update_of_unknown_user_is_404(client, admin, auth_headers):
    response = client.patch(f"{USERS}/99999", json={"role": "agent"}, headers=auth_headers(admin))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "payload",
    [
        {},  # nothing to change
        {"email": "hijack@example.com"},  # not an editable field
        {"hashed_password": "x"},  # mass-assignment attempt
        {"role": "superuser"},  # not a real role
    ],
)
def test_invalid_updates_are_rejected(client, admin, customer, auth_headers, payload):
    response = client.patch(f"{USERS}/{customer.id}", json=payload, headers=auth_headers(admin))

    assert response.status_code == 422


def test_role_change_is_audited_with_before_and_after(client, db, admin, customer, auth_headers):
    client.patch(f"{USERS}/{customer.id}", json={"role": "agent"}, headers=auth_headers(admin))

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "user.updated"))
    assert entry is not None
    assert entry.actor_id == admin.id
    assert (entry.entity_type, entry.entity_id) == ("user", str(customer.id))
    assert entry.details == {"role": {"from": "customer", "to": "agent"}}


def test_no_op_update_writes_no_audit_entry(client, db, admin, customer, auth_headers):
    client.patch(f"{USERS}/{customer.id}", json={"role": "customer"}, headers=auth_headers(admin))

    db.expire_all()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "user.updated")) is None
    assert db.get(User, customer.id).role == UserRole.CUSTOMER
