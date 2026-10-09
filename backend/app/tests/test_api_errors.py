"""The error envelope, request ids, health check, and crash handling."""

import logging

from fastapi.testclient import TestClient


def test_health_reports_database_ok(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "Not Found"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_wrong_method_uses_error_envelope(client):
    response = client.delete("/api/v1/auth/me")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_validation_errors_list_fields_without_echoing_input(client):
    response = client.post(
        "/api/v1/auth/register", json={"email": "bad", "password": "SuperSecret99"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields = {detail["field"] for detail in error["details"]}
    assert fields == {"email", "full_name"}
    assert "SuperSecret99" not in response.text


def test_malformed_json_body_is_a_validation_error(client):
    response = client.post(
        "/api/v1/auth/login",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_request_id_is_generated_or_reused_when_safe(client):
    generated = client.get("/api/v1/health")
    reused = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc.123"})
    unsafe = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\nwith newline"})

    assert len(generated.headers["X-Request-ID"]) == 32
    assert reused.headers["X-Request-ID"] == "trace-abc.123"
    # Values that could break log lines are replaced, never logged as-is.
    assert unsafe.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(unsafe.headers["X-Request-ID"]) == 32


def test_unhandled_exception_returns_generic_500_and_logs_traceback(app, caplog):
    @app.get("/api/v1/test-only/crash")
    def crash() -> None:
        raise RuntimeError("internal detail: db password=hunter2")

    with TestClient(app) as client, caplog.at_level(logging.ERROR, logger="app.request"):
        response = client.get("/api/v1/test-only/crash", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "internal detail" not in response.text
    assert "hunter2" not in response.text
    # Still inside the CORS middleware, so a browser can read the error.
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    crash_logs = [r for r in caplog.records if r.getMessage() == "Unhandled error"]
    assert len(crash_logs) == 1
    assert crash_logs[0].exc_info is not None
    assert crash_logs[0].request_id == response.headers["X-Request-ID"]


def test_cors_allows_configured_origin_only(client):
    allowed = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    blocked = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in blocked.headers
