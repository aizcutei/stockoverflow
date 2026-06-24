"""Unified error handling — consistent JSON error responses."""

from __future__ import annotations

import logging
import traceback

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stockoverflow")


class AppError(Exception):
    """Application-level error with structured response."""

    def __init__(self, message: str, code: str = "INTERNAL", status: int = 500, detail: str = ""):
        self.message = message
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message=message, code="NOT_FOUND", status=404, detail=detail)


class UpstreamError(AppError):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message=message, code="UPSTREAM_ERROR", status=502, detail=detail)


class ValidationError(AppError):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message=message, code="VALIDATION_ERROR", status=422, detail=detail)


def _format_error(code: str, message: str, detail: str = "") -> dict:
    """Standard error response format."""
    resp = {"error": message, "code": code}
    if detail:
        resp["detail"] = detail
    return resp


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    logger.warning("AppError: code=%s message=%s detail=%s", exc.code, exc.message, exc.detail)
    return JSONResponse(
        status_code=exc.status,
        content=_format_error(exc.code, exc.message, exc.detail),
    )


async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning("HTTPException: status=%s detail=%s", exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_format_error("HTTP_ERROR", str(exc.detail)),
    )


async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    logger.error("Unhandled exception: %s\n%s", exc, "".join(tb))
    return JSONResponse(
        status_code=500,
        content=_format_error("INTERNAL", "Internal server error", str(exc)),
    )
