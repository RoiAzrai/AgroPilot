"""Every error leaves the service as application/problem+json (RFC 9457).

Endpoints raise AppError; the handlers registered here render it, together with
FastAPI's own validation errors, its default 404/405 responses, database failures
and, as a last resort, any unexpected exception.
"""

import logging
import sqlite3
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from db import is_unavailable

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
RETRY_AFTER_SECONDS = 5

# 405 has no code of its own in the spec; VALIDATION is the client-request-error code.
_HTTP_CODES = {404: "NOT_FOUND", 405: "VALIDATION", 409: "CONFLICT", 503: "UNAVAILABLE"}

_UNIQUE_DETAILS = {
    "plots.farm_id, plots.name": "A plot with this name already exists in this farm",
}


class AppError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def not_found(detail: str) -> AppError:
    return AppError(404, "NOT_FOUND", detail)


def conflict(detail: str) -> AppError:
    return AppError(409, "CONFLICT", detail)


def validation(detail: str) -> AppError:
    return AppError(422, "VALIDATION", detail)


def problem(
    status: int, code: str, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "code": code,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    return problem(exc.status, exc.code, exc.detail)


async def _request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    detail = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
    return problem(422, "VALIDATION", detail)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if exc.status_code == 404 and detail == HTTPStatus.NOT_FOUND.phrase:
        detail = f"No route matches {request.url.path}"
    elif exc.status_code == 405 and detail == HTTPStatus.METHOD_NOT_ALLOWED.phrase:
        detail = f"{request.method} is not allowed on {request.url.path}"
    code = _HTTP_CODES.get(exc.status_code, "VALIDATION")
    return problem(exc.status_code, code, detail, headers=exc.headers)


async def _integrity_error(request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
    # Only UNIQUE is mapped here. A FOREIGN KEY failure means different things per
    # endpoint (422 on a plot write, 409 on a farm delete), so endpoints handle it.
    message = str(exc)
    prefix = "UNIQUE constraint failed: "
    if not message.startswith(prefix):
        raise exc
    detail = _UNIQUE_DETAILS.get(message.removeprefix(prefix), "Record already exists")
    return problem(409, "CONFLICT", detail)


async def _database_error(request: Request, exc: sqlite3.Error) -> JSONResponse:
    # Classified by SQLite error code: a missing table is also an OperationalError,
    # but it is a bug, so anything not environmental goes on to the 500 handler.
    if not is_unavailable(exc):
        raise exc
    logger.warning(
        "Database unavailable on %s %s: %s %s",
        request.method, request.url.path, exc.sqlite_errorname, exc,
    )
    return problem(
        503, "UNAVAILABLE", "Database unavailable",
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # The client gets a generic body; the details stay in the server log.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return problem(500, "UNAVAILABLE", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(sqlite3.IntegrityError, _integrity_error)
    app.add_exception_handler(sqlite3.Error, _database_error)
    app.add_exception_handler(Exception, _unexpected_error)
