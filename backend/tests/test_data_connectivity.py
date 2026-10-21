"""
Company database connectivity hardening (Phase K): column-level blocking, outbound-host guard, safe parameter binding.
Real API, auth, tenancy, DB; the EXTERNAL database driver is replaced by a recorder (a real PostgreSQL run is in
tests/test_data_connectivity_live_pg.py, skipped unless a server is configured).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import AuditLog, DataAccessAudit, SchemaEntity
from app.integrations.connector import ColumnMeta, EntityMeta, TestResult
from tests.test_marketing_analytics_e2e import run

INT = "/api/v1/integrations"
CFG = {"display_name": "Shop DB", "db_type": "postgresql", "host": "db.shop.test", "port": 5432, "database_name": "shop",
       "username": "ro", "password": "scratch-not-a-real-secret", "ssl_required": False}


def cols(*names):
    return [ColumnMeta(name=n, data_type="text") for n in names]


class FakeConnector:
    def __init__(self, entities):
        self.entities, self.tested, self.discovered = entities, 0, 0

    async def test_connection(self, **kw):
        self.tested += 1
        return TestResult(success=True, server_version="fake 1.0")

    async def discover_schema(self, **kw):
        self.discovered += 1
        return self.entities


@pytest.fixture()
def shop(world, monkeypatch):
    """A connected connection with one discovered entity ('customers'), driver faked, SQL recorded."""
    fc = FakeConnector([EntityMeta("public", "customers", "table", cols("id", "name", "city", "ssn", "password_hash"))])
    monkeypatch.setattr("app.api.routers.integrations.get_connector", lambda t: fc)
    seen = {"sql": [], "params": []}

    async def fake_run(**kw):
        seen["sql"].append(kw["sql"]); seen["params"].append(kw["params"])
        return [{"id": 1, "name": "Asha", "city": "Kochi"}]
    monkeypatch.setattr("app.services.data_access._run_query_sync", fake_run)
    h = world.auth("a_admin")
    conn = world.client.post(f"{INT}/connections", json=CFG, headers=h).json()
    assert world.client.post(f"{INT}/connections/{conn['id']}/test", headers=h).json()["success"] is True
    ents = world.client.post(f"{INT}/connections/{conn['id']}/discover", headers=h).json()
    return SimpleNamespace(world=world, conn=conn, ent=ents[0], fc=fc, seen=seen, h=h)


def allow(s, value=True):
    return s.world.client.patch(f"{INT}/entities/{s.ent['id']}/permission", json={"is_allowed": value}, headers=s.h)


def set_blocked(s, names, who="a_admin"):
    return s.world.client.patch(f"{INT}/entities/{s.ent['id']}/columns", json={"blocked_columns": names}, headers=s.world.auth(who))


def query(s, who="a_admin", **body):
    return s.world.client.post("/api/v1/data/query", json={"connection_id": s.conn["id"], "entity_id": s.ent["id"], **body}, headers=s.world.auth(who))


def audit_text(world):
    async def go():
        async with world.maker() as sess:
            return " | ".join(a.event for a in (await sess.execute(select(AuditLog))).scalars().all())
    return run(go())


class TestColumnBlocking:
    def test_sensitive_looking_columns_are_blocked_at_discovery(self, shop):
        assert sorted(shop.ent["blocked_columns"]) == ["password_hash", "ssn"]

    def test_all_columns_query_leaves_out_blocked_columns(self, shop):
        allow(shop)
        r = query(shop)
        assert r.status_code == 200, r.text
        assert sorted(r.json()["fields_returned"]) == ["city", "id", "name"]
        sql = shop.seen["sql"][-1]
        assert '"ssn"' not in sql and '"password_hash"' not in sql

    def test_blocked_column_cannot_be_selected_filtered_or_sorted(self, shop):
        allow(shop)
        for body in ({"fields": ["name", "ssn"]},
                     {"fields": ["name"], "filters": [{"field": "ssn", "operator": "=", "value": "111-22-3333"}]},
                     {"fields": ["name"], "sort": [{"field": "password_hash", "direction": "ASC"}]}):
            r = query(shop, **body)
            assert r.status_code == 403 and "blocked" in r.json()["detail"], body
        assert shop.seen["sql"] == []                      # never reached the database

    def test_admin_can_unblock_and_block(self, shop):
        allow(shop)
        assert set_blocked(shop, ["password_hash"]).json()["blocked_columns"] == ["password_hash"]
        assert query(shop, fields=["ssn"]).status_code == 200
        assert set_blocked(shop, ["password_hash", "city"]).status_code == 200
        assert query(shop, fields=["city"]).status_code == 403
        assert "blocked ['city']" in audit_text(shop.world)

    def test_rediscovery_keeps_admin_choices_and_blocks_only_new_sensitive_columns(self, shop):
        set_blocked(shop, [])                               # admin deliberately unblocks everything
        shop.fc.entities = [EntityMeta("public", "customers", "table", cols("id", "name", "city", "ssn", "password_hash", "api_token", "region"))]
        ent = shop.world.client.post(f"{INT}/connections/{shop.conn['id']}/discover", headers=shop.h).json()[0]
        assert ent["blocked_columns"] == ["api_token"]      # new + sensitive-looking; old ssn stays as the admin left it

    def test_blocked_list_drops_columns_that_no_longer_exist(self, shop):
        shop.fc.entities = [EntityMeta("public", "customers", "table", cols("id", "name"))]
        ent = shop.world.client.post(f"{INT}/connections/{shop.conn['id']}/discover", headers=shop.h).json()[0]
        assert ent["blocked_columns"] == []

    def test_only_admins_edit_columns_and_only_real_columns(self, shop):
        assert set_blocked(shop, [], who="a_employee").status_code == 403
        assert set_blocked(shop, ["nope"]).status_code == 400
        assert set_blocked(shop, [], who="b_admin").status_code == 404      # another company's entity

    def test_semantic_mapping_to_a_blocked_column_is_refused(self, shop):
        from app.db.models import SemanticMapping
        allow(shop)

        async def mk():
            async with shop.world.maker() as s:
                s.add(SemanticMapping(id="sm1", tenant_id=shop.world.tenant_a, semantic_concept="customer_ssn", connection_id=shop.conn["id"],
                                      entity_id=shop.ent["id"], field_name="ssn", created_by="t"))
                await s.commit()
        run(mk())
        r = shop.world.client.post("/api/v1/data/query", json={"semantic_concept": "customer_ssn"}, headers=shop.h)
        assert r.status_code == 403

    def test_other_company_cannot_query_the_entity(self, shop):
        allow(shop)
        assert query(shop, who="b_admin").status_code == 403

    def test_refused_queries_are_audited(self, shop):
        allow(shop)
        query(shop, fields=["ssn"])
        async def rows():
            async with shop.world.maker() as s:
                return (await s.execute(select(DataAccessAudit))).scalars().all()
        assert any(a.success is False for a in run(rows()))


class TestConnectionState:
    def test_query_needs_a_connected_connection(self, shop):
        allow(shop)
        shop.world.client.patch(f"{INT}/connections/{shop.conn['id']}", json={"database_name": "other"}, headers=shop.h)
        r = query(shop)
        assert r.status_code == 403 and "connected" in r.json()["detail"]

    def test_changing_the_target_requires_a_new_test(self, shop):
        resp = shop.world.client.patch(f"{INT}/connections/{shop.conn['id']}", json={"host": "db2.shop.test"}, headers=shop.h)
        assert resp.status_code == 200, resp.text
        conn = resp.json()
        assert conn["status"] == "not_tested"
        assert shop.world.client.post(f"{INT}/connections/{shop.conn['id']}/discover", headers=shop.h).status_code == 400
        shop.world.client.post(f"{INT}/connections/{shop.conn['id']}/test", headers=shop.h)
        renamed = shop.world.client.patch(f"{INT}/connections/{shop.conn['id']}", json={"display_name": "Renamed"}, headers=shop.h).json()
        assert renamed["status"] == "connected"               # a rename is not a new target

    def test_password_is_never_returned(self, shop):
        assert CFG["password"] not in shop.world.client.get(f"{INT}/connections", headers=shop.h).text


class TestHostGuard:
    def test_metadata_and_link_local_hosts_are_always_refused(self, world):
        for host in ("169.254.169.254", "metadata.google.internal", "db.corp.internal", "169.254.10.10", "0.0.0.0"):
            r = world.client.post(f"{INT}/connections", json={**CFG, "host": host}, headers=world.auth("a_admin"))
            assert r.status_code == 400, host

    def test_loopback_and_private_are_allowed_in_development_only(self, world, monkeypatch):
        h = world.auth("a_admin")
        assert world.client.post(f"{INT}/connections", json={**CFG, "host": "127.0.0.1"}, headers=h).status_code == 201
        from app import config
        monkeypatch.setattr(config.settings, "environment", "production")
        for host in ("127.0.0.1", "localhost", "10.0.0.5", "192.168.1.20", "172.16.3.4", "mydb.local"):
            assert world.client.post(f"{INT}/connections", json={**CFG, "host": host}, headers=h).status_code == 400, host
        monkeypatch.setattr(config.settings, "allow_private_db_hosts", True)
        assert world.client.post(f"{INT}/connections", json={**CFG, "host": "10.0.0.5"}, headers=h).status_code == 201
        assert world.client.post(f"{INT}/connections", json={**CFG, "host": "169.254.169.254"}, headers=h).status_code == 400   # opt-out never unlocks metadata

    def test_stored_bad_host_is_not_contacted_on_test_discover_or_query(self, shop, monkeypatch):
        allow(shop)

        async def poison():
            from app.db.models import DataConnection
            async with shop.world.maker() as s:
                c = (await s.execute(select(DataConnection))).scalar_one()
                c.host = "169.254.169.254"
                c.status = "connected"
                await s.commit()
        run(poison())
        tested = shop.fc.tested
        t = shop.world.client.post(f"{INT}/connections/{shop.conn['id']}/test", headers=shop.h).json()
        assert t["success"] is False and shop.fc.tested == tested
        assert shop.world.client.post(f"{INT}/connections/{shop.conn['id']}/discover", headers=shop.h).status_code in (400,)
        run(poison())
        assert query(shop).status_code == 403 and shop.seen["sql"] == []

    def test_update_to_a_bad_host_is_refused(self, shop):
        r = shop.world.client.patch(f"{INT}/connections/{shop.conn['id']}", json={"host": "169.254.169.254"}, headers=shop.h)
        assert r.status_code == 400


class TestSqlBuilding:
    def test_bind_replaces_whole_tokens_only(self):
        from app.services.data_access import _bind
        sql = " AND ".join(f'"c" = :p{i}' for i in range(12))
        out, params = _bind(sql, {f"p{i}": i for i in range(12)})
        assert "%(p1)s" in out and "%(p10)s" in out and "%(p11)s" in out and "%(p1)s0" not in out and ":p" not in out

    def test_bind_leaves_unknown_markers_and_escapes_percent(self):
        from app.services.data_access import _bind
        out, _ = _bind('SELECT "100%" FROM t WHERE a = :p0 AND b = :p9', {"p0": 1})
        assert "%%" in out and "%(p0)s" in out and ":p9" in out

    def test_identifiers_are_quoted_and_quotes_doubled(self):
        from app.services.data_access import _q
        assert _q("a") == '"a"' and _q('we"ird') == '"we""ird"'

    def test_twelve_filters_through_the_real_pipeline(self, shop):
        allow(shop)
        flts = [{"field": "city", "operator": "!=", "value": f"c{i}"} for i in range(10)]      # 10 is the API maximum
        r = query(shop, fields=["name"], filters=flts)
        assert r.status_code == 200, r.text
        assert shop.seen["params"][-1] == {f"p{i}": f"c{i}" for i in range(10)}
        assert shop.seen["sql"][-1].count("%(p") == 0 and shop.seen["sql"][-1].count(":p") == 10   # SQL keeps :pN; binding happens in the driver call


def test_blocked_columns_migration_is_additive_and_reversible():
    import pathlib, re
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("migrations/versions/f9a3b48c0d56_add_blocked_columns.py").read_text()
    assert 'down_revision: Union[str, None] = "e8f2a37b9c45"' in src and "drop_column" in src and 'server_default="[]"' in src
    assert not re.search(r"drop_table|alter_column", src)
