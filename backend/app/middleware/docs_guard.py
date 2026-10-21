"""
Production guard for interactive API documentation.

FastAPI's ``docs_url=None`` only removes the *default* routes.  A route added by
hand (a custom Swagger page, a copied ``/openapi.json``, a mounted sub-app) would
still serve the full API map.  This pure-ASGI middleware therefore answers 404
for anything that looks like API documentation whenever the environment is
production, no matter how it was registered.  The environment is read on every
request, so it cannot be bypassed by import-order or settings reloads.
"""
from __future__ import annotations

import json
import re

from app.config import settings

_PRODUCTION_NAMES = {"production", "prod"}
# Any path segment that names a documentation / schema resource.
_DOC_SEGMENT = re.compile(
    r"(^|/)(docs|redoc|swagger|swagger-ui|swagger-ui\.html|swagger\.json|openapi(\.json|\.yaml|\.yml)?|api-docs)(/|$)",
    re.IGNORECASE,
)


def is_production() -> bool:
    return settings.environment.strip().lower() in _PRODUCTION_NAMES


def is_doc_path(path: str) -> bool:
    # Collapse // and ./ tricks; match case-insensitively.
    normalized = re.sub(r"/{2,}", "/", path).replace("/./", "/")
    return bool(_DOC_SEGMENT.search(normalized))


class ProductionDocsGuard:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and is_production() and is_doc_path(scope.get("path", "")):
            body = json.dumps({"detail": "Not Found"}).encode()
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
