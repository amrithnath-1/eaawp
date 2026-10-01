"""
EAAWP Phase N — Observability Middleware.

Structured per-request logging with request_id, tenant, duration.
Uses pure ASGI middleware (no BaseHTTPMiddleware) to avoid anyio conflicts.

NEVER LOGS: Authorization headers, passwords, tokens, API keys.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

logger = logging.getLogger("eaawp.access")

_SENSITIVE_PATHS = frozenset(["/auth/token", "/auth/refresh"])


class ObservabilityMiddleware:
    """
    Pure ASGI observability middleware.
    Compatible with anyio / asyncio event loop management.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:8]
        start = time.monotonic()

        # Extract safe headers
        headers = dict(scope.get("headers", []))
        tenant_id = headers.get(b"x-tenant-id", b"").decode("utf-8", errors="ignore")[:36]
        user_agent = headers.get(b"user-agent", b"").decode("utf-8", errors="ignore")[:80]
        path = scope.get("path", "")
        method = scope.get("method", "")

        # Store request_id in scope state for downstream use
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                # Inject X-Request-ID response header
                headers_list = list(message.get("headers", []))
                headers_list.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers_list}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error(
                "rid=%s method=%s path=%s duration_ms=%d ERROR",
                request_id, method, path, elapsed,
            )
            raise

        elapsed = int((time.monotonic() - start) * 1000)
        is_sensitive = any(s in path for s in _SENSITIVE_PATHS)
        if not is_sensitive:
            logger.info(
                "rid=%s method=%s path=%s status=%d duration_ms=%d tenant=%s",
                request_id, method, path, status_code, elapsed, tenant_id,
            )
