"""Every error leaves the service as application/problem+json (RFC 9457).

Same body shape as weather-service/errors.py (copied, never imported): exactly
`type`, `title`, `status`, `detail`, `code`. No upstream text and no internals ever reach
a body; details stay in the log (P6, design 5.6).
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from engine.crops import UnknownCrop
from upstream import PlotNotFound, UnexpectedUpstream, UpstreamUnavailable

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"

# 405 has no code of its own in the spec; VALIDATION is the client-request-error code.
_HTTP_CODES = {404: "NOT_FOUND", 405: "VALIDATION"}


class AppError(Exception):
    def __init__(
        self, status: int, code: str, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = headers


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
    return problem(exc.status, exc.code, exc.detail, exc.headers)


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


async def _upstream_unavailable(request: Request, exc: UpstreamUnavailable) -> JSONResponse:
    logger.warning("%s is unavailable, answering 503 (retry after %ss)", exc.service, exc.retry_after)
    return problem(
        503,
        "UPSTREAM_UNAVAILABLE",
        f"{exc.service} is unavailable",
        headers={"Retry-After": str(exc.retry_after)},
    )


async def _plot_not_found(request: Request, exc: PlotNotFound) -> JSONResponse:
    return problem(404, "NOT_FOUND", "Plot not found")


async def _unknown_crop(request: Request, exc: UnknownCrop) -> JSONResponse:
    logger.error("Crop %s has no coefficients in the engine table", exc)
    return problem(
        422,
        "VALIDATION",
        "The plot's crop has no irrigation coefficients in the planner. "
        "This is a data problem, not a request problem.",
    )


async def _unexpected_upstream(request: Request, exc: UnexpectedUpstream) -> JSONResponse:
    # Its message names the fault; it stays in the log. A distinct code from an outage.
    logger.error("Unexpected upstream answer on %s: %s", request.url.path, exc)
    return problem(500, "INTERNAL", "Internal server error")


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return problem(500, "INTERNAL", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(UpstreamUnavailable, _upstream_unavailable)
    app.add_exception_handler(PlotNotFound, _plot_not_found)
    app.add_exception_handler(UnknownCrop, _unknown_crop)
    app.add_exception_handler(UnexpectedUpstream, _unexpected_upstream)
    app.add_exception_handler(Exception, _unexpected_error)
