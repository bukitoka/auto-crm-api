"""Domain exceptions and their mapping to HTTP responses.

Services and repositories raise these; they never raise `HTTPException`.
A single handler turns them into `{"detail": "..."}` responses.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    default_message: str = "Bad request"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "Bad request"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "Not authenticated"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "Permission denied"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "Not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    default_message = "Conflict"


class AIResponseError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_message = "The AI provider returned an invalid response"


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    default_message = "The uploaded file is too large"


class StorageError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_message = "File storage is not reachable. Is MinIO running?"


class EmailDeliveryError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_message = "The email could not be sent. Is the mail server (Mailpit) running?"


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "Service unavailable"


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.message}, headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
