"""Audit log visibility (Phase M): administrators only, readable actors, bounded size, tenant isolation."""
from __future__ import annotations

import uuid

from app.db.models import AuditLog
from tests.conftest import _run


def add(world, tenant, actor, event):
    async def go():
        async with world.maker() as s:
            s.add(AuditLog(id=str(uuid.uuid4()), tenant_id=tenant, actor=actor, event=event, department="test", status="ok"))
            await s.commit()
    _run(go())


def test_employees_cannot_read_the_company_audit_log(world):
    add(world, world.tenant_a, world.users["a_admin"]["id"], "admin did something private")
    for path in ("/api/v1/audit", "/api/v1/audit/traces"):
        r = world.client.get(path, headers=world.auth("a_employee"))
        assert r.status_code == 403 and "private" not in r.text
    assert world.client.get("/api/v1/audit", headers=world.auth("a_admin")).status_code == 200


def test_user_ids_become_names_and_other_actors_pass_through(world):
    add(world, world.tenant_a, world.users["a_employee"]["id"], "issued document X")
    add(world, world.tenant_a, "AI", "agent ran a report")
    add(world, world.tenant_a, "deleted-user-id", "old event")
    rows = {r["event"]: r for r in world.client.get("/api/v1/audit", headers=world.auth("a_admin")).json()}
    assert rows["issued document X"]["actor_name"] == "a_employee"                 # the seeded user's name
    assert rows["agent ran a report"]["actor_name"] == "AI"
    assert rows["old event"]["actor_name"] == "deleted-user-id"
    assert rows["issued document X"]["created_at"]


def test_other_tenants_user_ids_are_never_resolved_or_listed(world):
    add(world, world.tenant_b, world.users["b_admin"]["id"], "B-only event")
    add(world, world.tenant_a, world.users["b_admin"]["id"], "A event naming a B user id")      # must not reveal B's user name
    r = world.client.get("/api/v1/audit", headers=world.auth("a_admin")).json()
    assert "B-only event" not in str(r)
    named = [x for x in r if x["event"] == "A event naming a B user id"][0]
    assert named["actor_name"] == world.users["b_admin"]["id"]                    # unresolved: shown as the raw id, not B's name


def test_limit_is_bounded(world):
    h = world.auth("a_admin")
    assert world.client.get("/api/v1/audit?limit=0", headers=h).status_code == 422
    assert world.client.get("/api/v1/audit?limit=100000", headers=h).status_code == 422
    assert world.client.get("/api/v1/audit?limit=500", headers=h).status_code == 200
