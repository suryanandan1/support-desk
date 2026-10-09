"""Structured logging with request ids and secret redaction.

Every log line passes through ``redact()`` after formatting, so a token, password, or
API key that slips into a message or traceback is masked before it reaches the output.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_REDACTED = "[REDACTED]"
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # JSON Web Tokens: three base64url segments, the first always starting with "eyJ".
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), _REDACTED),
    # Google API keys.
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), _REDACTED),
    # "Bearer <anything>".
    (re.compile(r"(?i)(bearer\s+)[^\s\"',;]+"), r"\1" + _REDACTED),
    # key=value / "key": "value" pairs whose key names a secret.
    (
        re.compile(
            r"(?i)(\"?\b(?:password|passwd|secret|secret_key|api[_-]?key|access_token|"
            r"refresh_token|token|authorization)\b\"?\s*[:=]\s*\"?)([^\s\"',;&}]+)"
        ),
        r"\1" + _REDACTED,
    ),
]

# Attributes every LogRecord has; anything else was passed through ``extra=``.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "request_id",
    "color_message",  # uvicorn's ANSI-coloured duplicate of the message
}


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _extras(record: logging.LogRecord) -> dict[str, object]:
    return {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extras(record)
        if extras:
            line += " | " + " ".join(f"{k}={v}" for k, v in extras.items())
        return redact(line)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return redact(json.dumps(entry, default=str))


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configure the root logger. Safe to call more than once."""
    root = logging.getLogger()
    # Remove only handlers this function added before, so test-capture handlers survive.
    for handler in list(root.handlers):
        if getattr(handler, "_app_handler", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler._app_handler = True  # type: ignore[attr-defined]
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if json_format else TextFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    # Route uvicorn's own logs through the handler above.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # The request-logging middleware already logs every request with an id and timing.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    # HTTP client libraries log every request URL at INFO; keep them quiet.
    for name in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
