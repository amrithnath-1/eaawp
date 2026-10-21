"""
Local-runtime failures seen in the browser: CORS errors + 500 on pending-tasks.

Root cause: a database behind the code (missing ``pending_tasks`` table).  The 500
was returned by Starlette's outermost error layer, outside CORSMiddleware, so it
carried no Access-Control-Allow-Origin header and the browser reported a CORS
error / "Failed to fetch" instead of the real problem.

Real SQLite + real FastAPI app; nothing external is faked.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.config import settings
from app.core.schema_check import expected_head, is_schema_error, safe_db_error_text, schema_status

ORIGIN = "http://localhost:5173"
URL = "/api/v1/agent/pending-tasks"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def drop_table(world, name):
    async def go():
        async with world.maker() as s:
            await s.execute(text(f"DROP TABLE {name}"))
            await s.commit()
    run(go())


class TestSchemaBehindTheCode:
    def test_missing_table_is_a_readable_503_not_an_opaque_500(self, world):
        drop_table(world, "pending_tasks")
        r = world.client.get(URL, headers={**world.auth("a_employee"), "Origin": ORIGIN})
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["code"] == "schema_out_of_date"
        assert "alembic upgrade head" in body["detail"]
        assert "pending_tasks" not in r.text and "SELECT" not in r.text   # no SQL / table names to the client

    def test_browser_can_read_that_error_from_the_dev_origin(self, world):
        drop_table(world, "pending_tasks")
        r = world.client.get(URL, headers={**world.auth("a_employee"), "Origin": ORIGIN})
        assert r.headers.get("access-control-allow-origin") == ORIGIN
        assert r.headers.get("access-control-allow-credentials") == "true"

    def test_unlisted_origin_still_gets_no_allow_origin_header(self, world):
        drop_table(world, "pending_tasks")
        r = world.client.get(URL, headers={**world.auth("a_employee"), "Origin": "http://evil.example"})
        assert r.status_code == 503
        assert "access-control-allow-origin" not in r.headers

    def test_healthy_database_still_works(self, world):
        r = world.client.get(URL, headers={**world.auth("a_employee"), "Origin": ORIGIN})
        assert r.status_code == 200 and r.json() == []
        assert r.headers.get("access-control-allow-origin") == ORIGIN


class TestAuthenticationIsUnchanged:
    def test_unauthenticated_is_401_with_cors_headers(self, world):
        r = world.client.get(URL, headers={"Origin": ORIGIN})
        assert r.status_code == 401
        assert r.headers.get("access-control-allow-origin") == ORIGIN

    def test_garbage_token_is_401(self, world):
        r = world.client.get(URL, headers={"Authorization": "Bearer not.a.token", "Origin": ORIGIN})
        assert r.status_code == 401

    def test_cors_is_never_a_wildcard(self):
        assert "*" not in settings.cors_origins_list
        assert ORIGIN in settings.cors_origins_list


class TestUnhandledErrors:
    @pytest.fixture()
    def boom_routes(self):
        from app.main import app

        async def explode():
            raise RuntimeError("super-secret-token=abc123 should never reach the client")

        async def db_explode():
            raise OperationalError("SELECT secret FROM t WHERE k = ?", {"k": "hunter2"}, Exception("disk I/O error"))

        app.add_api_route("/__test/boom", explode)
        app.add_api_route("/__test/dboom", db_explode)
        try:
            yield
        finally:
            app.router.routes[:] = [r for r in app.router.routes if not str(getattr(r, "path", "")).startswith("/__test/")]

    def test_generic_500_is_json_has_cors_for_allowed_origin_and_leaks_nothing(self, world, boom_routes):
        r = world.client.get("/__test/boom", headers={"Origin": ORIGIN})
        assert r.status_code == 500
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["code"] == "internal_error"
        assert "abc123" not in r.text and "RuntimeError" not in r.text and "Traceback" not in r.text
        assert r.headers.get("access-control-allow-origin") == ORIGIN

    def test_generic_500_gives_unlisted_origins_nothing(self, world, boom_routes):
        r = world.client.get("/__test/boom", headers={"Origin": "http://evil.example"})
        assert r.status_code == 500 and "access-control-allow-origin" not in r.headers

    def test_other_database_errors_do_not_leak_sql_or_parameters(self, world, boom_routes):
        r = world.client.get("/__test/dboom", headers={"Origin": ORIGIN})
        assert r.status_code == 500 and r.json()["code"] == "database_error"
        assert "hunter2" not in r.text and "SELECT" not in r.text
        assert r.headers.get("access-control-allow-origin") == ORIGIN

    def test_server_log_is_sanitised(self, world, boom_routes, caplog):
        with caplog.at_level("ERROR"):
            world.client.get("/__test/dboom", headers={"Origin": ORIGIN})
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "hunter2" not in logged and "database_error" not in logged   # parameters never logged
        assert "OperationalError" in logged and "disk I/O error" in logged


class TestSchemaCheck:
    def test_pattern_detection(self):
        for msg in ("no such table: pending_tasks", "no such column: oauth_states.initiating_user_id",
                    'relation "pending_tasks" does not exist', "Unknown column 'x' in 'field list'",
                    "table t has no column named c"):
            assert is_schema_error(Exception(msg)), msg
        for msg in ("database is locked", "UNIQUE constraint failed: users.email", "disk I/O error"):
            assert not is_schema_error(Exception(msg)), msg

    def test_safe_text_ignores_sql_and_params(self):
        exc = OperationalError("SELECT * FROM t WHERE p = ?", {"p": "secret"}, Exception("no such table: t"))
        assert safe_db_error_text(exc) == "no such table: t"

    def test_status_reports_behind_then_current(self, tmp_path):
        from sqlalchemy.ext.asyncio import create_async_engine
        eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")

        async def go(rev):
            async with eng.begin() as c:
                await c.execute(text("DROP TABLE IF EXISTS alembic_version"))
                await c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
                await c.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": rev})
            return await schema_status(eng)

        behind = run(go("u8v2w37x9y15"))
        assert behind["up_to_date"] is False and behind["current"] == "u8v2w37x9y15"
        assert behind["expected"] == expected_head() != ""
        assert run(go(expected_head()))["up_to_date"] is True
        run(eng.dispose())

    def test_unstamped_database_is_reported_behind(self, tmp_path):
        from sqlalchemy.ext.asyncio import create_async_engine
        eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'n.db'}")
        st = run(schema_status(eng))
        assert st["current"] is None and st["up_to_date"] is False
        run(eng.dispose())

    def test_health_reports_schema_state_without_revision_hashes(self, world):
        r = world.client.get("/health")
        assert r.status_code == 200 and r.json()["database_schema"] in ("ok", "out_of_date", "unknown")
        assert expected_head() not in r.text


class TestSetupAndResumeStillWorksOnAMigratedDatabase:
    def test_pending_task_created_listed_and_cancelled(self, world, monkeypatch):
        from types import SimpleNamespace
        from app.llm.gateway import LLMGateway
        monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
        bp = {"agent_id": "d", "role_name": "Digital Marketing Manager", "system_persona": "x",
              "allowed_tools": [], "guarded_tools": [], "tenant_id": world.tenant_a}
        r = world.client.post("/api/v1/agent/execute", headers=world.auth("a_employee"), json={
            "blueprint": bp, "user_prompt": "Show our top search queries in Google Search Console"})
        assert r.status_code == 200 and r.json()["plan_status"] == "awaiting_setup"
        listed = world.client.get(URL, headers={**world.auth("a_employee"), "Origin": ORIGIN})
        assert listed.status_code == 200 and len(listed.json()) == 1
        tid = listed.json()[0]["id"]
        assert world.client.post(f"{URL}/{tid}/cancel", headers=world.auth("a_employee")).json()["status"] == "cancelled"
        cfg = world.client.get("/api/v1/admin/provider-config/google_search_console/status", headers={**world.auth("a_admin"), "Origin": ORIGIN})
        assert cfg.status_code == 200 and cfg.headers.get("access-control-allow-origin") == ORIGIN
