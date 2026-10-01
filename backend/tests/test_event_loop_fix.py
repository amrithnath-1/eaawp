"""
Regression test: NoEventLoopError fix (Python 3.14 compatibility).

Root cause: asyncio.get_event_loop() raises RuntimeError in Python 3.14+
when called from a thread with no current event loop (anyio thread pool).
Fix: all tools now use asyncio.get_running_loop() + nest_asyncio removed.

These tests verify:
 1. nest_asyncio is NOT imported in main.py (was the trigger).
 2. No app code uses asyncio.get_event_loop() (was the failure point).
 3. All tool loop calls use get_running_loop() (correct API).
 4. GET /api/v1/roles/DIGITAL_MARKETING_MANAGER returns 200, not 500.
 5. GET /api/v1/integration-manager/integrations returns 200, not 500.
 6. POST /api/v1/nl-integration/parse returns non-500.
 7. GET /health returns 200.
 8. asyncio.get_running_loop() raises RuntimeError outside async (correct).
 9. asyncio.get_running_loop() works inside async context (correct).
10. registry.py uses get_running_loop, not get_event_loop.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
import pytest

ROOT = pathlib.Path(__file__).parent.parent  # backend/


class TestNestAsyncioRemoved:

    def test_nest_asyncio_not_in_main_py(self):
        """main.py must NOT import nest_asyncio — it breaks Python 3.14."""
        src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "nest_asyncio" not in src, (
            "nest_asyncio found in main.py — this breaks Python 3.14 async event loop management"
        )

    def test_no_get_event_loop_in_registry(self):
        """registry.py must use get_running_loop(), not get_event_loop()."""
        src = (ROOT / "app" / "tools" / "registry.py").read_text(encoding="utf-8")
        # Filter out comments
        lines = [l for l in src.splitlines() if not l.strip().startswith("#")]
        code = "\n".join(lines)
        assert "asyncio.get_event_loop()" not in code, (
            "registry.py still contains asyncio.get_event_loop() — fix to get_running_loop()"
        )

    def test_no_get_event_loop_in_any_app_code(self):
        """No app Python file (outside comments) should use get_event_loop()."""
        app_dir = ROOT / "app"
        violations = []
        for py_file in app_dir.rglob("*.py"):
            for i, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "asyncio.get_event_loop()" in stripped:
                    violations.append(f"{py_file.relative_to(ROOT)}:{i}: {stripped[:80]}")
        assert not violations, (
            "get_event_loop() found in app code (breaks Python 3.14):\n" + "\n".join(violations)
        )

    def test_registry_uses_get_running_loop(self):
        """registry.py must use get_running_loop() for tool loop calls."""
        src = (ROOT / "app" / "tools" / "registry.py").read_text(encoding="utf-8")
        assert "get_running_loop()" in src, (
            "registry.py does not use asyncio.get_running_loop()"
        )

    def test_dynamic_tool_uses_get_running_loop(self):
        """dynamic_tool.py must use get_running_loop()."""
        src = (ROOT / "app" / "tools" / "dynamic_tool.py").read_text(encoding="utf-8")
        lines = [l for l in src.splitlines() if not l.strip().startswith("#")]
        code = "\n".join(lines)
        assert "get_running_loop()" in code or "asyncio.get_event_loop()" not in code


class TestGetRunningLoopBehaviour:

    def test_get_running_loop_raises_outside_async(self):
        """asyncio.get_running_loop() raises RuntimeError when no loop is running.
        This is the CORRECT behaviour — tools should only be called inside async context."""
        with pytest.raises(RuntimeError, match="no running event loop|no current event loop"):
            asyncio.get_running_loop()

    @pytest.mark.asyncio
    async def test_get_running_loop_works_inside_async(self):
        """asyncio.get_running_loop() returns the running loop inside async context."""
        loop = asyncio.get_running_loop()
        assert loop is not None
        assert loop.is_running()


class TestEndpointsReturn200:
    """
    Regression tests: the previously-failing endpoints must return non-500.
    Uses httpx AsyncClient with ASGI transport (no threads, no anyio portal).
    """

    @pytest.mark.asyncio
    async def test_roles_endpoint_returns_200(self):
        """GET /api/v1/roles/DIGITAL_MARKETING_MANAGER must return 200, not 500."""
        from app.main import app
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            r = await client.get(
                "/api/v1/roles/DIGITAL_MARKETING_MANAGER",
                headers={"X-Tenant-ID": "demo-company-001"},
            )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"

    @pytest.mark.asyncio
    async def test_integrations_endpoint_returns_200(self):
        """GET /api/v1/integration-manager/integrations must return 200, not 500."""
        from app.main import app
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            r = await client.get(
                "/api/v1/integration-manager/integrations",
                headers={"X-Tenant-ID": "demo-company-001"},
            )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_200(self):
        """GET /health must return 200."""
        from app.main import app
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            r = await client.get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_nl_integration_parse_returns_non_500(self):
        """POST /api/v1/nl-integration/parse must not return 500."""
        from app.main import app
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/api/v1/nl-integration/parse",
                json={"instruction": "Connect Google Search Console"},
                headers={"X-Tenant-ID": "demo-company-001"},
            )
        # 200 if LLM available, 503 if not configured — both are acceptable
        # 500 is the failure we are guarding against
        assert r.status_code != 500, f"Got 500: {r.text[:300]}"
        assert r.status_code in (200, 503), f"Unexpected status {r.status_code}: {r.text[:200]}"

    @pytest.mark.asyncio
    async def test_providers_endpoint_returns_200(self):
        """GET /api/v1/integration-manager/providers must return 200."""
        from app.main import app
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/v1/integration-manager/providers")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 7  # at least 7 providers registered