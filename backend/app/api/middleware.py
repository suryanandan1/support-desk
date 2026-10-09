"""HTTP middleware: gives each request an id, logs its outcome, and converts crashes
into the standard error envelope."""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.api.error_handlers import error_response, internal_error_response
from app.core.config import get_settings
from app.core.logging import request_id_ctx

logger = logging.getLogger("app.request")

# A caller-supplied id is reused only if it is short and plain, so it is safe to log.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
    request.state.request_id = request_id
    context_token = request_id_ctx.set(request_id)
    started = time.perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception:
            # Answering here (instead of re-raising) keeps the response inside the CORS
            # middleware, so browsers see the real 500 instead of a CORS failure.
            logger.exception("Unhandled error", extra={"path": request.url.path})
            response = internal_error_response(request)

        response.headers["X-Request-ID"] = request_id
        # Path only; query strings are never logged.
        logger.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"duration_ms": round((time.perf_counter() - started) * 1000, 1)},
        )
        return response
    finally:
        request_id_ctx.reset(context_token)


async def upload_size_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reject oversized uploads from their Content-Length, before the body is read."""
    if request.method == "POST" and request.url.path.endswith("/documents/upload"):
        settings = get_settings()
        limit = settings.max_upload_size_bytes * settings.max_files_per_upload + 1024 * 1024
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            return error_response(
                request,
                413,
                "payload_too_large",
                f"The upload is too large. Each file may be up to {settings.max_upload_size_mb} MB "
                f"and at most {settings.max_files_per_upload} files can be sent at once.",
            )
    return await call_next(request)
