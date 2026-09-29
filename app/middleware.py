from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

from .pii import scrub_text


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _get_correlation_id(request: Request) -> str:
    candidate = request.headers.get("x-request-id", "").strip()
    if (
        candidate
        and candidate != "MISSING"
        and _SAFE_REQUEST_ID.fullmatch(candidate)
        and scrub_text(candidate) == candidate
    ):
        return candidate
    return f"req-{uuid.uuid4().hex[:8]}"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()
        correlation_id = _get_correlation_id(request)
        bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)
        response_time_ms = (time.perf_counter() - start) * 1000
        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = f"{response_time_ms:.2f}"

        return response
