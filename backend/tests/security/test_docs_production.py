"""API documentation must be unreachable in production, however it is registered."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.config import settings
from app.middleware.docs_guard import ProductionDocsGuard, is_doc_path

DOC_PATHS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/docs/", "/DOCS", "//docs",
             "/Redoc", "/OpenAPI.json"]


def test_docs_are_available_in_development(world):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert world.client.get(p).status_code == 200, p


@pytest.mark.parametrize("env", ["production", "Production", " PRODUCTION ", "prod"])
@pytest.mark.parametrize("path", DOC_PATHS)
def test_default_routes_blocked_even_though_registered(world, monkeypatch, env, path):
    """The app object was built in development (routes ARE registered); the guard still blocks."""
    monkeypatch.setattr(settings, "environment", env)
    r = world.client.get(path)
    assert r.status_code == 404, f"{path} reachable in {env!r}"
    assert "openapi" not in r.text.lower() and "swagger" not in r.text.lower()


def test_real_api_keeps_working_in_production(world, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    assert world.client.get("/health").status_code == 200
    assert world.client.get("/api/v1/campaigns", headers=world.auth("a_admin")).status_code == 200
    # path segments that merely CONTAIN "doc" are not documentation
    assert world.client.get("/api/v1/knowledge/documents", headers=world.auth("a_admin")).status_code == 200


def test_custom_documentation_routes_are_blocked(monkeypatch):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/openapi.json")
    def schema():
        return {"openapi": "3.1.0", "paths": {"/secret": {}}}

    @app.get("/api/docs", response_class=HTMLResponse)
    def custom_swagger():
        return "<html>swagger-ui</html>"

    @app.get("/internal/swagger/index")
    def nested():
        return {"x": 1}

    @app.get("/ok")
    def ok():
        return {"ok": True}

    app.add_middleware(ProductionDocsGuard)
    client = TestClient(app)

    monkeypatch.setattr(settings, "environment", "development")
    assert client.get("/openapi.json").status_code == 200   # guard is inert outside production

    monkeypatch.setattr(settings, "environment", "production")
    for p in ("/openapi.json", "/api/docs", "/internal/swagger/index"):
        assert client.get(p).status_code == 404, p
    assert client.get("/ok").status_code == 200


def test_mounted_subapp_documentation_is_blocked(monkeypatch):
    sub = FastAPI()          # its own default /docs, /openapi.json
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/v2", sub)
    app.add_middleware(ProductionDocsGuard)
    client = TestClient(app)
    monkeypatch.setattr(settings, "environment", "production")
    assert client.get("/v2/docs").status_code == 404
    assert client.get("/v2/openapi.json").status_code == 404


@pytest.mark.parametrize("p,expected", [
    ("/docs", True), ("/api/v1/docs", True), ("/redoc/", True), ("/swagger-ui", True),
    ("/api/v1/knowledge/documents", False), ("/api/v1/docsets", False), ("/health", False),
])
def test_doc_path_matcher(p, expected):
    assert is_doc_path(p) is expected


@pytest.mark.parametrize("env", ["production", "Production"])
def test_app_built_in_production_registers_no_doc_routes(env):
    """Fresh interpreter: the application factory itself must not register docs routes."""
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {backend!r})
        import json
        from app.main import app
        from fastapi.routing import APIRoute
        from starlette.routing import Route
        paths = sorted(getattr(r, "path", "") for r in app.routes)
        print(json.dumps({{"docs": app.docs_url, "redoc": app.redoc_url, "openapi": app.openapi_url,
                          "paths": [p for p in paths if p in ("/docs", "/redoc", "/openapi.json")]}}))
    """)
    envv = {**os.environ, "ENVIRONMENT": env, "SECRET_KEY": "p" * 40, "GEMINI_API_KEY": "x"}
    out = subprocess.run([sys.executable, "-I", "-c", code], env=envv, capture_output=True, text=True,
                         cwd=backend, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data == {"docs": None, "redoc": None, "openapi": None, "paths": []}
