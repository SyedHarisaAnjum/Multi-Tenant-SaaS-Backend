from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    headers: dict[str, str] | None = None

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"
    headers = {"WWW-Authenticate": "Bearer"}


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class NotFoundError(AppError):
    """Also used for resources the caller may not see, so their existence isn't revealed."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class GoneError(AppError):
    status_code = status.HTTP_410_GONE
    code = "gone"


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # registered only for AppError
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=exc.headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
