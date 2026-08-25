from __future__ import annotations

import contextvars
import logging
import re
import sys
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# Hunar live secret keys and NVIDIA keys, plus a generic catch-all for common
# "key/token/authorization" fields, so a stray secret never reaches log output.
_SECRET_PATTERNS = [
    re.compile(r"hunar_va_live_sk_[A-Za-z0-9_-]+"),
    re.compile(r"nvapi-[A-Za-z0-9_-]+"),
    re.compile(
        r'(?i)("?(?:api[_-]?key|authorization|x-api-key|token)"?\s*[:=]\s*"?)'
        r"[^\s\"',}]+"
    ),
]

_REDACTED = "[REDACTED]"


def _redact(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS[:2]:
        redacted = pattern.sub(_REDACTED, redacted)
    redacted = _SECRET_PATTERNS[2].sub(rf"\1{_REDACTED}", redacted)
    return redacted


def redact_secrets_processor(
    logger: object, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = _redact(value)
    return event_dict


def add_request_id(
    logger: object, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level)

    structlog.configure(
        processors=[
            add_request_id,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_secrets_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Binds a request id to a contextvar for the life of the request, so every
    log line emitted while handling it carries it, regardless of which module logs."""

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(self._header_name) or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[self._header_name] = request_id
        return response
