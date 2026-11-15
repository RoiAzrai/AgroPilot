"""Every error leaves the service as application/problem+json (RFC 9457).

Copied pattern from registry-service (never imported). The handlers render
AppError, FastAPI's validation errors, its default 404/405 responses, an
unavailable forecast and, as a last resort, any unexpected exception.
No provider text ever reaches a body.
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from forecasts import Unavailable

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"

# 405 has no code of its own in the spec; VALIDATION is the client-request-error code.
_HTTP_CODES = {404: "NOT_FOUND", 405: "VALIDATION", 503: "UNAVAILABLE"}


class AppError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


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


async def _unavailable(request: Request, exc: Unavailable) -> JSONResponse:
    # The reason was logged by the cache; the body stays generic.
    return problem(
        503, "UNAVAILABLE", "Forecast unavailable",
        headers={"Retry-After": str(exc.retry_after)},
    )


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # The client gets a generic body; the details stay in the server log.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return problem(500, "UNAVAILABLE", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Unavailable, _unavailable)
    app.add_exception_handler(Exception, _unexpected_error)
