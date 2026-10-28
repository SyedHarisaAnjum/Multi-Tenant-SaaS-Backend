"""One error shape for every failure:

    {"error": {"code": "PROJECT_NOT_FOUND", "message": "...", "request_id": "...",
               "details": [...]}}   # details only for validation-style errors

Clients branch on `code`; `message` is for humans. Nothing internal (stack traces, SQL,
constraint names, submitted values) is ever placed in a response; it goes to the log,
tagged with the same request_id.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if headers is not None:
            self.headers = headers
        self.details = details


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "NOT_AUTHENTICATED"
    headers = {"WWW-Authenticate": "Bearer"}


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class NotFoundError(AppError):
    """Also used for resources the caller may not see, so their existence isn't revealed."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class GoneError(AppError):
    status_code = status.HTTP_410_GONE
    code = "GONE"


class UnprocessableError(AppError):
    """Well-formed request that fails a business rule (e.g. invalid status transition)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "UNPROCESSABLE"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "Too many requests. Please try again later.",
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"error": body},
        headers={**(headers or {}), REQUEST_ID_HEADER: request_id},
    )


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # registered only for AppError
        raise exc
    return error_response(
        request,
        exc.status_code,
        exc.code,
        exc.message,
        headers=exc.headers,
        details=exc.details,
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    # Pydantic errors carry the submitted `input` (which may be a password) and `ctx`;
    # return only where and what.
    details = [
        {
            "field": ".".join(str(part) for part in err.get("loc", ())),
            "message": err.get("msg", "Invalid value."),
            "type": err.get("type", "value_error"),
        }
        for err in exc.errors()
    ]
    return error_response(
        request,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "The request is invalid.",
        details=details,
    )


_HTTP_CODES = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "NOT_AUTHENTICATED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "UNSUPPORTED_MEDIA_TYPE",
}


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    """Framework-raised errors, e.g. unknown route (404) or wrong method (405)."""
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(
        request,
        exc.status_code,
        _HTTP_CODES.get(exc.status_code, "HTTP_ERROR"),
        message,
        headers=dict(exc.headers) if exc.headers else None,
    )


async def _integrity_error(request: Request, exc: Exception) -> JSONResponse:
    """A constraint the service layer didn't anticipate (or a race it lost)."""
    constraint = getattr(getattr(getattr(exc, "orig", None), "diag", None), "constraint_name", None)
    logger.warning(
        "Integrity error on %s %s (constraint=%s)", request.method, request.url.path, constraint
    )
    return error_response(
        request,
        status.HTTP_409_CONFLICT,
        "CONFLICT",
        "The request conflicts with existing data.",
    )


async def _stale_data_error(request: Request, exc: Exception) -> JSONResponse:
    """Optimistic-lock failure detected at flush time: someone else saved first."""
    return error_response(
        request,
        status.HTTP_409_CONFLICT,
        "VERSION_CONFLICT",
        "This resource was modified by someone else. Reload it and try again.",
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(IntegrityError, _integrity_error)
    app.add_exception_handler(StaleDataError, _stale_data_error)
    app.add_exception_handler(Exception, _unhandled_error)
