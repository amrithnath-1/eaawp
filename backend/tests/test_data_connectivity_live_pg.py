"""
LIVE PostgreSQL verification of company database connectivity (Phase K). Skipped unless a server is configured:

  EAAWP_TEST_PG_PORT=5433 EAAWP_TEST_PG_DB=shop EAAWP_TEST_PG_RO_USER=app_ro EAAWP_TEST_PG_RO_PASSWORD=... \
  EAAWP_TEST_PG_ADMIN_USER=... EAAWP_TEST_PG_ADMIN_PASSWORD=...  pytest tests/test_data_connectivity_live_pg.py

Expected database: tables customers(id,name,email,city,ssn) and orders(id,customer_id,amount,status,placed_at); the RO role has SELECT only;
the ADMIN role can write (used to prove the platform's own session is read-only regardless of the role's privileges).
Uses the REAL connector, REAL driver, REAL query path. Only the secrets come from the environment; nothing is hard-coded.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.db.models import DataAccessAudit
from tests.test_marketing_analytics_e2e import run

PORT = os.environ.get("EAAWP_TEST_PG_PORT")
pytestmark = pytest.mark.skipif(not PORT, reason="no live PostgreSQL configured (EAAWP_TEST_PG_PORT)")

INT = "/api/v1/integrations"


def cfg(user_env="RO", **over):
    return {"display_name": "Live shop", "db_type": "postgresql", "host": os.environ.get("EAAWP_TEST_PG_HOST", "127.0.0.1"), "port": int(PORT or 0),
            "database_name": os.environ.get("EAAWP_TEST_PG_DB", "shop"), "username": os.environ[f"EAAWP_TEST_PG_{user_env}_USER"],
            "password": os.environ[f"EAAWP_TEST_PG_{user_env}_PASSWORD"], "ssl_required": False, **over}


@pytest.fixture()
def live(world):
    h = world.auth("a_admin")
    c = world.client.post(f"{INT}/connections", json=cfg(), headers=h)
    assert c.status_code == 201, c.text
    conn = c.json()
    t = world.client.post(f"{INT}/connections/{conn['id']}/test", headers=h).json()
    assert t["success"] is True, t
    ents = {e["entity_name"]: e for e in world.client.post(f"{INT}/connections/{conn['id']}/discover", headers=h).json()}
    for e in ents.values():
        world.client.patch(f"{INT}/entities/{e['id']}/permission", json={"is_allowed": True}, headers=h)
    return type("Live", (), {"world": world, "h": h, "conn": conn, "ents": ents, "test": t})


def q(live, entity, who="a_admin", **body):
    return live.world.client.post("/api/v1/data/query", json={"connection_id": live.conn["id"], "entity_id": live.ents[entity]["id"], **body},
                                  headers=live.world.auth(who))


def test_connect_and_discover_against_a_real_server(live):
    assert "PostgreSQL" in (live.test["server_version"] or "")
    assert {"customers", "orders"} <= set(live.ents)
    assert {c["name"] for c in live.ents["customers"]["columns"]} == {"id", "name", "email", "city", "ssn"}
    assert live.ents["customers"]["blocked_columns"] == ["ssn"]


def test_real_rows_filter_sort_limit(live):
    r = q(live, "orders", fields=["id", "amount", "status"], filters=[{"field": "status", "operator": "=", "value": "paid"}],
          sort=[{"field": "amount", "direction": "DESC"}], limit=2)
    assert r.status_code == 200, r.text
    b = r.json()
    assert [float(x["amount"]) for x in b["rows"]] == [120.5, 80.0] and b["truncated"] is True and b["row_count"] == 2
    assert q(live, "orders", fields=["id"], filters=[{"field": "amount", "operator": "IS NULL"}]).json()["row_count"] == 0
    assert q(live, "customers", fields=["name"], filters=[{"field": "city", "operator": "LIKE", "value": "Koch%"}]).json()["row_count"] == 2


def test_blocked_ssn_is_never_returned_by_the_real_database_path(live):
    rows = q(live, "customers").json()["rows"]
    assert rows and all("ssn" not in r for r in rows) and "111-22-3333" not in str(rows)
    assert q(live, "customers", fields=["name", "ssn"]).status_code == 403
    assert q(live, "customers", fields=["name"], filters=[{"field": "ssn", "operator": "=", "value": "111-22-3333"}]).status_code == 403


def test_sql_injection_in_a_value_is_just_a_value(live):
    r = q(live, "customers", fields=["name"], filters=[{"field": "name", "operator": "=", "value": "Asha' OR '1'='1"}])
    assert r.status_code == 200 and r.json()["row_count"] == 0
    assert q(live, "customers", fields=["name"]).json()["row_count"] == 3            # table intact


def test_member_of_another_company_gets_nothing(live):
    assert q(live, "orders", who="b_admin").status_code == 403


def test_platform_session_is_read_only_even_for_a_role_that_can_write():
    import psycopg2
    from app.services.data_access import _run_query_sync_blocking as run_sql
    c = cfg("ADMIN")
    args = dict(db_type="postgresql", host=c["host"], port=c["port"], database=c["database_name"], username=c["username"], password=c["password"], ssl=False)
    with pytest.raises(psycopg2.Error) as e:
        run_sql(**args, sql="INSERT INTO customers(name) VALUES ('mallory') RETURNING id", params={})
    assert "read-only" in str(e.value).lower()
    with pytest.raises(psycopg2.Error):
        run_sql(**args, sql="DELETE FROM orders", params={})
    assert len(run_sql(**args, sql="SELECT id FROM customers", params={})) == 3


def test_wrong_password_fails_safely(world):
    h = world.auth("a_admin")
    bad = cfg(password="definitely-wrong-pw-123")
    conn = world.client.post(f"{INT}/connections", json=bad, headers=h).json()
    t = world.client.post(f"{INT}/connections/{conn['id']}/test", headers=h).json()
    assert t["success"] is False and t["status"] == "failed"
    assert "definitely-wrong-pw-123" not in str(t) and bad["password"] not in world.client.get(f"{INT}/connections", headers=h).text


def test_every_query_attempt_is_audited_without_values_or_secrets(live):
    q(live, "orders", fields=["id"])
    q(live, "customers", fields=["ssn"])                 # refused

    async def rows():
        async with live.world.maker() as s:
            return (await s.execute(select(DataAccessAudit))).scalars().all()
    audits = run(rows())
    assert any(a.success for a in audits) and any(not a.success for a in audits)
    blob = " ".join(f"{a.requested_fields_json} {a.error_message}" for a in audits)
    assert os.environ["EAAWP_TEST_PG_RO_PASSWORD"] not in blob and "111-22-3333" not in blob
