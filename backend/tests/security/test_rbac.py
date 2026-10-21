"""
Role-based authorization: ordinary employees must not perform privileged actions.

Policy (see app/core/route_inventory.py):
  * every state-changing JWT route is either ``require_admin`` or listed in
    MEMBER_MUTATIONS with a reason;
  * every admin-only route answers 403 to an employee of the SAME tenant and is
    not blocked for that tenant's admin;
  * the role comes from the database user, never from the token's ``role`` claim.
"""
from __future__ import annotations

import re

import pytest

from app.core.route_inventory import MEMBER_MUTATIONS, build_inventory
from app.main import app
from tests.security.helpers import forge_token

_INV = build_inventory(app)
_ADMIN_ROUTES = [r for r in _INV if r.classification == "JWT" and r.access == "ADMIN"]
_MUTATING_MEMBER = [r for r in _INV if r.classification == "JWT" and r.access == "MEMBER" and r.method != "GET"]


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "does-not-exist", path)


def test_every_member_mutation_is_explicitly_allowlisted():
    unlisted = [f"{r.method} {r.path}" for r in _MUTATING_MEMBER if (r.method, r.path) not in MEMBER_MUTATIONS]
    assert not unlisted, (
        "State-changing endpoints callable by any employee but not allowlisted. "
        "Add require_admin or justify in MEMBER_MUTATIONS:\n  " + "\n  ".join(unlisted)
    )


def test_member_allowlist_has_no_stale_or_admin_entries():
    live = {(r.method, r.path): r for r in _INV}
    stale = [k for k in MEMBER_MUTATIONS if k not in live]
    assert not stale, f"MEMBER_MUTATIONS entries matching no route: {stale}"
    admin = [k for k in MEMBER_MUTATIONS if live[k].access == "ADMIN"]
    assert not admin, f"Allowlisted for members but admin-only (remove from allowlist): {admin}"


@pytest.mark.parametrize("who", ["a_admin", "b_admin"])
def test_privileged_categories_are_admin_only(who):
    """The categories called out in the review are all covered."""
    required = [
        ("POST", "/api/v1/integrations/connections"),
        ("DELETE", "/api/v1/integrations/connections/{conn_id}"),
        ("POST", "/api/v1/integration-manager/integrations"),
        ("DELETE", "/api/v1/integration-manager/integrations/{integration_id}"),
        ("PUT", "/api/v1/roles/{role_key}"),
        ("PATCH", "/api/v1/roles/{role_key}"),
        ("POST", "/api/v1/roles/{role_key}/nl-configure"),
        ("POST", "/api/v1/employees/build"),
        ("POST", "/api/v1/ai-employees"),
        ("PATCH", "/api/v1/agent/config"),
        ("POST", "/api/v1/users"),
        ("POST", "/api/v1/knowledge/upload"),
        ("GET", "/api/v1/oauth/google/authorize"),
        ("POST", "/api/v1/email/integration"),
        ("POST", "/api/v1/channels"),
        ("POST", "/api/v1/admin/provider-config/{provider_type}"),
    ]
    admin_paths = {(r.method, r.path) for r in _ADMIN_ROUTES}
    missing = [k for k in required if k not in admin_paths]
    assert not missing, missing


@pytest.mark.parametrize("route", _ADMIN_ROUTES, ids=lambda r: f"{r.method} {r.path}")
def test_employee_gets_403_admin_is_not_blocked(world, route):
    c = world.client
    kwargs = {} if route.method == "GET" else {"json": {}}

    r_emp = c.request(route.method, _url(route.path), headers=world.auth("a_employee"), **kwargs)
    assert r_emp.status_code == 403, f"employee reached {route.method} {route.path}: {r_emp.status_code}"

    r_adm = c.request(route.method, _url(route.path), headers=world.auth("a_admin"), **kwargs)
    assert r_adm.status_code not in (401, 403), (
        f"admin unexpectedly refused on {route.method} {route.path}: {r_adm.status_code}"
    )


def test_role_claim_in_token_cannot_elevate_an_employee(world):
    """A correctly signed token that CLAIMS an admin role is still an employee."""
    emp = world.users["a_employee"]
    token = forge_token({"sub": emp["id"], "tid": emp["tenant_id"], "role": "Company Admin"})
    r = world.client.post(
        "/api/v1/integrations/connections", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


def test_employee_still_reaches_day_to_day_endpoints(world):
    h = world.auth("a_employee")
    assert world.client.get("/api/v1/campaigns", headers=h).status_code == 200
    r = world.client.post("/api/v1/campaigns", headers=h, json={"name": "Spring launch"})
    assert r.status_code in (200, 201), r.text
    assert world.client.get("/api/v1/integrations/connections", headers=h).status_code == 200


def test_demoted_admin_loses_access_immediately(world):
    """Role is read from the DB on every request: demotion needs no new token."""
    import asyncio
    from sqlalchemy import update
    from app.db.models import User

    h = world.auth("a_admin")
    assert world.client.post("/api/v1/integrations/connections", json={}, headers=h).status_code != 403

    async def demote():
        async with world.maker() as s:
            await s.execute(update(User).where(User.id == world.users["a_admin"]["id"]).values(role="Employee"))
            await s.commit()

    asyncio.new_event_loop().run_until_complete(demote())
    assert world.client.post("/api/v1/integrations/connections", json={}, headers=h).status_code == 403
