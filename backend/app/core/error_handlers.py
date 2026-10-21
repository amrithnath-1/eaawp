"""
Error responses that the browser can actually read.

Starlette runs the handler for a plain ``Exception`` *outside* CORSMiddleware, so
an uncaught server error reaches the browser with no ``Access-Control-Allow-Origin``
header and the user only sees "Failed to fetch" / a CORS error, hiding the real
problem.  These handlers return a JSON body and, for the generic case, add the
CORS headers for **allowed origins only** (never a wildcard).

Nothing here weakens authentication: 401/403 responses are produced elsewhere.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.core.schema_check import MIGRATE_HINT, is_schema_error, safe_db_error_text

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    state = request.scope.get("state") or {}
    return str(state.get("request_id", ""))


def _cors_headers(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin", "")
    if origin and origin in settings.cors_origins_list:
        return {"access-control-allow-origin": origin, "access-control-allow-credentials": "true", "vary": "Origin"}
    return {}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        rid = _request_id(request)
        if is_schema_error(exc):
            logger.error(
                "Database schema is behind the code: %s %s -> %s [request_id=%s]. %s",
                request.method, request.url.path, safe_db_error_text(exc), rid, MIGRATE_HINT,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "The database schema is out of date for this version of EAAWP. "
                              "An administrator must run the database migrations. " + MIGRATE_HINT,
                    "code": "schema_out_of_date",
                    "request_id": rid,
                },
                headers=_cors_headers(request),
            )
        logger.error(
            "Database error: %s %s -> %s: %s [request_id=%s]",
            request.method, request.url.path, type(exc).__name__, safe_db_error_text(exc), rid,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "A database error occurred.", "code": "database_error", "request_id": rid},
            headers=_cors_headers(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = _request_id(request)
        # Log the type and traceback (no request body, headers or parameters).
        logger.error(
            "Unhandled error: %s %s -> %s [request_id=%s]",
            request.method, request.url.path, type(exc).__name__, rid, exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "code": "internal_error", "request_id": rid},
            headers=_cors_headers(request),
        )
