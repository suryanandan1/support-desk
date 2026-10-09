"""Domain exceptions raised by services.

Services stay independent of HTTP: they raise these, and a single exception handler in
``app.main`` turns them into JSON error responses with the right status code.
"""

from typing import Any


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class AuthenticationError(AppError):
    status_code = 401
    code = "not_authenticated"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class BusinessRuleError(AppError):
    """A well-formed request that breaks a business rule (e.g. demoting yourself)."""

    status_code = 400
    code = "business_rule_violation"
