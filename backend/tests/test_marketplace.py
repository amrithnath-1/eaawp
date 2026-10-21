"""Marketplace / module activation (Phase L): catalog, admin-only switch, tenant isolation, enforcement on real routes."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AuditLog

M = "/api/v1/modules"
AVAILABLE = {"DIGITAL_MARKETING_MANAGER", "DATA_INTELLIGENCE_ANALYST", "INSTITUTIONAL_CLERK", "MEDICAL_ASSISTANT"}


def listing(w, who):
    r = w.client.get(M, headers=w.auth(who))
    assert r.status_code == 200, r.text
    return {m["key"]: m for m in r.json()}


def act(w, who, key, on):
    return w.client.post(f"{M}/{key}/{'activate' if on else 'deactivate'}", headers=w.auth(who))


def exec_body(w, role_name, role_key):
    return {"blueprint": {"agent_id": "x", "role_name": role_name, "role_key": role_key, "system_persona": "p",
                          "allowed_tools": [], "guarded_tools": [], "tenant_id": w.tenant_a}, "user_prompt": "Hello there"}


def test_catalog_defaults_existing_companies_keep_their_modules(world):
    mods = listing(world, "a_employee")
    assert len(mods) == 9
    assert {k for k, m in mods.items() if m["active"]} == AVAILABLE
    assert all(m["status"] == "coming_soon" and not m["active"] for k, m in mods.items() if k not in AVAILABLE)


def test_only_admins_can_switch_modules(world):
    assert act(world, "a_employee", "INSTITUTIONAL_CLERK", False).status_code == 403
    assert listing(world, "a_admin")["INSTITUTIONAL_CLERK"]["active"] is True
    assert world.client.post(f"{M}/INSTITUTIONAL_CLERK/deactivate").status_code in (401, 403)


def test_deactivate_activate_roundtrip_is_idempotent_and_audited(world):
    r = act(world, "a_admin", "MEDICAL_ASSISTANT", False)
    assert r.status_code == 200 and r.json()["active"] is False and r.json()["changed_at"]
    assert act(world, "a_admin", "MEDICAL_ASSISTANT", False).json()["active"] is False          # repeat is harmless
    assert listing(world, "a_employee")["MEDICAL_ASSISTANT"]["active"] is False
    assert act(world, "a_admin", "MEDICAL_ASSISTANT", True).json()["active"] is True

    from tests.conftest import _run

    async def events():
        async with world.maker() as s:
            return [e.event for e in (await s.execute(select(AuditLog).where(
                AuditLog.tenant_id == world.tenant_a, AuditLog.department == "marketplace"))).scalars().all()]
    ev = _run(events())
    assert sorted(ev) == ["module Medical Assistant activated", "module Medical Assistant deactivated"]   # repeat not double-logged


def test_unknown_and_coming_soon_modules_cannot_be_activated(world):
    assert act(world, "a_admin", "NOT_A_MODULE", True).status_code == 404
    r = act(world, "a_admin", "HR_MANAGER", True)
    assert r.status_code == 409 and "not available yet" in r.json()["detail"]
    assert listing(world, "a_admin")["HR_MANAGER"]["active"] is False


def test_tenants_are_isolated(world):
    act(world, "a_admin", "DATA_INTELLIGENCE_ANALYST", False)
    assert listing(world, "a_admin")["DATA_INTELLIGENCE_ANALYST"]["active"] is False
    assert listing(world, "b_admin")["DATA_INTELLIGENCE_ANALYST"]["active"] is True
    assert act(world, "b_admin", "DATA_INTELLIGENCE_ANALYST", False).status_code == 200
    assert act(world, "a_admin", "DATA_INTELLIGENCE_ANALYST", True).status_code == 200
    assert listing(world, "b_admin")["DATA_INTELLIGENCE_ANALYST"]["active"] is False            # A's change did not touch B


@pytest.mark.parametrize("key,path", [("INSTITUTIONAL_CLERK", "/api/v1/clerk/meta"), ("MEDICAL_ASSISTANT", "/api/v1/clinic/meta")])
def test_deactivated_module_blocks_its_routes_then_resumes(world, key, path):
    assert world.client.get(path, headers=world.auth("a_employee")).status_code == 200
    act(world, "a_admin", key, False)
    r = world.client.get(path, headers=world.auth("a_employee"))
    assert r.status_code == 403 and "not activated" in r.json()["detail"]
    assert world.client.get(path, headers=world.auth("b_employee")).status_code == 200          # other company unaffected
    act(world, "a_admin", key, True)
    assert world.client.get(path, headers=world.auth("a_employee")).status_code == 200


def test_agent_execution_is_blocked_for_a_deactivated_module_only(world):
    act(world, "a_admin", "MEDICAL_ASSISTANT", False)
    r = world.client.post("/api/v1/agent/execute", json=exec_body(world, "Medical Assistant", "MEDICAL_ASSISTANT"), headers=world.auth("a_employee"))
    assert r.status_code == 403 and "Medical Assistant module is not activated" in r.json()["detail"]
    # a different module is unaffected by the gate
    r = world.client.post("/api/v1/agent/execute", json=exec_body(world, "Institutional Clerk", "INSTITUTIONAL_CLERK"), headers=world.auth("a_employee"))
    assert "not activated" not in str(r.json().get("detail", ""))
    # custom (builder) roles are never module-gated
    r = world.client.post("/api/v1/agent/execute", json=exec_body(world, "Custom Thing", "CUSTOM_THING"), headers=world.auth("a_employee"))
    assert "not activated" not in str(r.json().get("detail", ""))


def test_require_module_helper_unknown_or_future_module_is_inactive(world):
    from app.services.modules import is_module_active, module_for_role
    from tests.conftest import _run

    async def go():
        async with world.maker() as s:
            return (await is_module_active(s, world.tenant_a, "HR_MANAGER"), await is_module_active(s, world.tenant_a, "NOPE"))
    assert _run(go()) == (False, False)
    assert module_for_role("HR_MANAGER") is None and module_for_role("CUSTOM") is None and module_for_role("INSTITUTIONAL_CLERK")
