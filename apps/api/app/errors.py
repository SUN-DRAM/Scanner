"""The error envelope and the closed error-code set from contract §7.4.

Every non-2xx response uses `ErrorEnvelope`. `ApiException` is the one way
application code should raise a conforming error; the handlers registered
here via `register_exception_handlers` guarantee nothing else can escape
as a bare string or an HTML error page.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("app.errors")

REQUEST_ID_HEADER = "X-Request-ID"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_HOSTNAME = "INVALID_HOSTNAME"
    BLOCKED_TARGET = "BLOCKED_TARGET"
    RATE_LIMITED = "RATE_LIMITED"
    SCAN_NOT_FOUND = "SCAN_NOT_FOUND"
    SCAN_FAILED = "SCAN_FAILED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_CODE_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.INVALID_HOSTNAME: status.HTTP_400_BAD_REQUEST,
    ErrorCode.BLOCKED_TARGET: status.HTTP_400_BAD_REQUEST,
    ErrorCode.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.SCAN_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    # SCAN_FAILED is never an HTTP error status — it only ever appears inside
    # Scan.error with the Scan response itself returned as 200.
    ErrorCode.UPSTREAM_TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class ApiError(BaseModel):
    """The `error` object — used standalone as `Scan.error` and nested in `ErrorEnvelope`."""

    model_config = ConfigDict(from_attributes=True)

    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None
    request_id: str


class ErrorEnvelope(BaseModel):
    """The full body of every non-2xx response."""

    error: ApiError


class ApiException(Exception):
    """Raise this anywhere in application code to produce a conforming error response."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code or ERROR_CODE_HTTP_STATUS[code]


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else "req_unknown"


_JSON_SAFE_SCALAR_TYPES = (str, int, float, bool, type(None))


def _json_safe(value: Any) -> tuple[bool, Any]:
    """Recursively determines whether `value` survives JSON encoding as-is,
    returning `(is_safe, sanitized_value)`. Dicts and lists keep only their
    JSON-safe members rather than being dropped wholesale for one bad leaf."""
    if isinstance(value, _JSON_SAFE_SCALAR_TYPES):
        return True, value
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            item_is_safe, sanitized_item = _json_safe(item)
            if item_is_safe:
                sanitized[key] = sanitized_item
        return True, sanitized
    if isinstance(value, (list, tuple)):
        sanitized_list = []
        for item in value:
            item_is_safe, sanitized_item = _json_safe(item)
            if item_is_safe:
                sanitized_list.append(sanitized_item)
        return True, sanitized_list
    return False, None


def _sanitize_validation_errors(errors: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """`RequestValidationError.errors()` embeds the raw exception object under
    `ctx.error` for any validator that raises a plain `ValueError` (the
    documented Pydantic way to fail a `field_validator`) — pydantic_core
    can't serialize that back out through `ApiError.details`, and the 422
    this is supposed to produce becomes an unhandled 500 instead. `msg`
    already carries the human-readable text ("Value error, ..."), so that
    one key is safe to drop. But `ctx` isn't only exception objects — a
    numeric constraint (`Field(ge=0)`) puts a plain int there (`{"ge": 0}`),
    genuinely useful evidence a caller could use to build a better error
    message, and stripping the whole key throws that away along with the
    one bad leaf. Recursively keep whatever in `ctx` is actually JSON-safe
    instead."""
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        clean = {key: value for key, value in error.items() if key != "ctx"}
        raw_ctx = error.get("ctx")
        if isinstance(raw_ctx, dict):
            _, safe_ctx = _json_safe(raw_ctx)
            if safe_ctx:
                clean["ctx"] = safe_ctx
        sanitized.append(clean)
    return sanitized


def _envelope(
    code: ErrorCode, message: str, details: dict[str, Any] | None, request_id: str
) -> dict[str, Any]:
    return ErrorEnvelope(
        error=ApiError(code=code, message=message, details=details, request_id=request_id)
    ).model_dump(mode="json")


def register_exception_handlers(app: FastAPI) -> None:
    """Wire every exception path to the closed error envelope. No exceptions escape unformatted."""

    @app.exception_handler(ApiException)
    async def api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(
                ErrorCode.VALIDATION_ERROR,
                "The request body failed validation.",
                {"errors": _sanitize_validation_errors(exc.errors())},
                _request_id(request),
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            try:
                code = ErrorCode(str(detail["code"]))
            except ValueError:
                code = ErrorCode.INTERNAL_ERROR
            message = str(detail["message"])
            details = detail.get("details")
        else:
            code = ErrorCode.INTERNAL_ERROR
            message = str(detail)
            details = None
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, message, details, _request_id(request)),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception("unhandled_exception", extra={"request_id": request_id})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                ErrorCode.INTERNAL_ERROR,
                "Something went wrong on our end. Try again shortly.",
                None,
                request_id,
            ),
        )
