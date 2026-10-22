"""Post-registration AI role selection: onboarding, persistence, switching, module/permission gates, tenant isolation,
role-specific navigation and AI context, and direct API authorization."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AuditLog
from app.db.workspace_models import UserWorkspace
from tests.conftest import PASSWORD, _run

W = "/api/v1/workspace"
ROLES = {"DIGITAL_MARKETING_MANAGER", "INSTITUTIONAL_CLERK", "MEDICAL_ASSISTANT", "DATA_INTELLIGENCE_ANALYST"}
ROLE_ONLY_NAV = {"customize", "clerk", "clinic", "data"}


def state(w, who):
    r = w.client.get(W, headers=w.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


def pick(w, who, key):
    return w.client.put(W, json={"role_key": key}, headers=w.auth(who))


def module(w, key, on, who="a_admin"):
    r = w.client.post(f"/api/v1/modules/{key}/{'activate' if on else 'deactivate'}", headers=w.auth(who))
    assert r.status_code == 200, r.text


def rows(w):
    async def go():
        async with w.maker() as s:
            return (await s.execute(select(UserWorkspace))).scalars().all()
    return _run(go())


def audit(w, tenant):
    async def go():
        async with w.maker() as s:
            return [e.event for e in (await s.execute(select(AuditLog).where(
                AuditLog.tenant_id == tenant, AuditLog.department == "workspace"))).scalars().all()]
    return _run(go())


# ── onboarding ────────────────────────────────────────────────────────────────

def test_new_user_must_select_and_sees_four_complete_role_cards(world):
    s = state(world, "a_employee")
    assert s["needs_selection"] is True and s["selected"] is None and s["navigation"] == [] and s["ai"] is None
    assert {r["key"] for r in s["roles"]} == ROLES
    for card in s["roles"]:
        assert card["purpose"] and card["capabilities"] and card["knowledge_domain"] and card["main_tools"]
        assert card["available"] is True and card["unavailable_reason"] is None
    assert s["can_switch"] is True


def test_selection_is_persisted_server_side_and_survives_a_real_login(world):
    r = pick(world, "a_employee", "INSTITUTIONAL_CLERK")
    assert r.status_code == 200, r.text
    assert r.json()["needs_selection"] is False and r.json()["selected"]["role_key"] == "INSTITUTIONAL_CLERK"
    assert r.json()["selected"]["source"] == "user"

    login = world.client.post("/api/v1/auth/token", json={"email": "a_employee@example.test", "password": PASSWORD,
                                                           "company_id": world.tenant_a})
    assert login.status_code == 200, login.text
    again = world.client.get(W, headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    assert again["needs_selection"] is False and again["selected"]["role_key"] == "INSTITUTIONAL_CLERK"
    assert [(x.user_id, x.role_key) for x in rows(world)] == [(world.users["a_employee"]["id"], "INSTITUTIONAL_CLERK")]
    assert audit(world, world.tenant_a) == ["workspace selected: Institutional Clerk"]


def test_selecting_configures_the_role_for_the_company(world):
    from app.db.models import RoleConfiguration

    async def keys():
        async with world.maker() as s:
            return {r.role_key for r in (await s.execute(select(RoleConfiguration).where(
                RoleConfiguration.tenant_id == world.tenant_a))).scalars().all()}
    assert "MEDICAL_ASSISTANT" not in _run(keys())
    assert pick(world, "a_employee", "MEDICAL_ASSISTANT").status_code == 200
    assert "MEDICAL_ASSISTANT" in _run(keys())


# ── switching ─────────────────────────────────────────────────────────────────

def test_switching_updates_navigation_and_ai_context_and_keeps_data(world):
    pick(world, "a_employee", "INSTITUTIONAL_CLERK")
    filed = world.client.post("/api/v1/clerk/requests", json={"request_type": "certificate", "title": "Bonafide",
                                                               "details": "for the bank"}, headers=world.auth("a_employee"))
    assert filed.status_code in (200, 201), filed.text

    s = pick(world, "a_employee", "DATA_INTELLIGENCE_ANALYST").json()
    assert s["selected"]["role_key"] == "DATA_INTELLIGENCE_ANALYST"
    assert "data" in s["navigation"] and "clerk" not in s["navigation"]
    assert s["ai"]["role_key"] == "DATA_INTELLIGENCE_ANALYST" and "analyze_dataset" in s["ai"]["allowed_tools"]
    assert "list_service_requests" not in s["ai"]["allowed_tools"]

    pick(world, "a_employee", "INSTITUTIONAL_CLERK")
    mine = world.client.get("/api/v1/clerk/requests", headers=world.auth("a_employee")).json()
    assert [r["id"] for r in mine] == [filed.json()["id"]]                                  # nothing deleted by switching
    assert audit(world, world.tenant_a) == ["workspace selected: Institutional Clerk",
                                            "workspace switched from Institutional Clerk to Data Analyst",
                                            "workspace switched from Data Analyst to Institutional Clerk"]
    assert len(rows(world)) == 1                                                            # one row per person


def test_reselecting_the_same_role_is_idempotent_and_not_double_audited(world):
    pick(world, "a_employee", "DIGITAL_MARKETING_MANAGER")
    assert pick(world, "a_employee", "DIGITAL_MARKETING_MANAGER").status_code == 200
    assert audit(world, world.tenant_a) == ["workspace selected: Digital Marketing Manager"]


# ── module activation and authorization ──────────────────────────────────────

def test_disabled_module_cannot_be_selected_and_is_marked_unavailable(world):
    module(world, "MEDICAL_ASSISTANT", False)
    r = pick(world, "a_employee", "MEDICAL_ASSISTANT")
    assert r.status_code == 403 and "not activated" in r.json()["detail"]
    card = next(c for c in state(world, "a_employee")["roles"] if c["key"] == "MEDICAL_ASSISTANT")
    assert card["available"] is False and "Marketplace" in card["unavailable_reason"]
    assert rows(world) == []


def test_deactivating_the_selected_module_sends_the_user_back_to_selection(world):
    pick(world, "a_employee", "MEDICAL_ASSISTANT")
    module(world, "MEDICAL_ASSISTANT", False)
    s = state(world, "a_employee")
    assert s["needs_selection"] is True and s["selected"] is None and s["navigation"] == [] and s["ai"] is None
    assert "Medical Assistant" in s["notice"] and "not activated" in s["notice"]
    assert len(rows(world)) == 1                                                            # saved choice kept, not deleted
    module(world, "MEDICAL_ASSISTANT", True)
    assert state(world, "a_employee")["selected"]["role_key"] == "MEDICAL_ASSISTANT"         # comes back when re-activated


def test_paused_ai_employee_cannot_be_selected(world):
    from app.db.models import AIEmployee
    import uuid

    async def add():
        async with world.maker() as s:
            s.add(AIEmployee(id=str(uuid.uuid4()), tenant_id=world.tenant_a, role_key="DATA_INTELLIGENCE_ANALYST",
                             name="Analyst", status="PAUSED", is_active=True))
            await s.commit()
    _run(add())
    r = pick(world, "a_employee", "DATA_INTELLIGENCE_ANALYST")
    assert r.status_code == 403 and "paused" in r.json()["detail"]


@pytest.mark.parametrize("key,code", [("HR_MANAGER", 404), ("NOT_A_ROLE", 404), ("CUSTOM_BUILDER_ROLE", 404)])
def test_only_the_four_built_in_roles_are_workspaces(world, key, code):
    assert pick(world, "a_employee", key).status_code == code
    assert pick(world, "a_employee", "").status_code == 422
    assert rows(world) == []


def test_unauthenticated_requests_are_refused(world):
    assert world.client.get(W).status_code == 401
    assert world.client.put(W, json={"role_key": "INSTITUTIONAL_CLERK"}).status_code == 401


def test_a_workspace_choice_grants_no_admin_or_module_permission(world):
    pick(world, "a_employee", "DATA_INTELLIGENCE_ANALYST")
    # admin features stay admin-only whatever workspace is selected
    assert world.client.post("/api/v1/modules/MEDICAL_ASSISTANT/deactivate", headers=world.auth("a_employee")).status_code == 403
    assert world.client.get("/api/v1/audit", headers=world.auth("a_employee")).status_code == 403
    # a disabled module's API is refused even to someone whose saved workspace is that module
    module(world, "DATA_INTELLIGENCE_ANALYST", False)
    r = world.client.get("/api/v1/datasets", headers=world.auth("a_employee"))
    assert r.status_code == 403 and "not activated" in r.json()["detail"]


@pytest.mark.parametrize("key,path", [
    ("DATA_INTELLIGENCE_ANALYST", "/api/v1/datasets"),
    ("DIGITAL_MARKETING_MANAGER", "/api/v1/campaigns"),
    ("DIGITAL_MARKETING_MANAGER", "/api/v1/content"),
    ("INSTITUTIONAL_CLERK", "/api/v1/clerk/requests"),
    ("MEDICAL_ASSISTANT", "/api/v1/clinic/meta"),
])
def test_direct_api_access_to_a_disabled_module_is_refused(world, key, path):
    assert world.client.get(path, headers=world.auth("a_employee")).status_code == 200
    module(world, key, False)
    assert world.client.get(path, headers=world.auth("a_employee")).status_code == 403
    assert world.client.get(path, headers=world.auth("b_employee")).status_code == 200      # other company unaffected


# ── tenant isolation ─────────────────────────────────────────────────────────

def test_selections_and_module_state_are_isolated_between_companies(world):
    pick(world, "a_employee", "INSTITUTIONAL_CLERK")
    assert state(world, "b_employee")["needs_selection"] is True                            # A's choice is not B's
    module(world, "INSTITUTIONAL_CLERK", False, who="b_admin")
    assert state(world, "a_employee")["selected"]["role_key"] == "INSTITUTIONAL_CLERK"     # B's switch-off is not A's
    assert pick(world, "b_employee", "INSTITUTIONAL_CLERK").status_code == 403
    assert audit(world, world.tenant_b) == []
    assert {(r.tenant_id, r.user_id) for r in rows(world)} == {(world.tenant_a, world.users["a_employee"]["id"])}


def test_a_selection_recorded_under_another_company_is_never_used(world):
    import uuid

    async def forge():
        async with world.maker() as s:
            s.add(UserWorkspace(id=str(uuid.uuid4()), tenant_id=world.tenant_b, user_id=world.users["a_employee"]["id"],
                                role_key="INSTITUTIONAL_CLERK", source="user"))
            await s.commit()
    _run(forge())
    s = state(world, "a_employee")
    assert s["needs_selection"] is True and s["selected"] is None

def test_the_ai_context_comes_from_the_callers_own_company_configuration(world):
    # Company B customises its clerk; company A must still get its own (default) configuration.
    pick(world, "b_admin", "INSTITUTIONAL_CLERK")
    r = world.client.patch("/api/v1/roles/INSTITUTIONAL_CLERK", json={"quick_prompts": ["B only prompt"]},
                           headers=world.auth("b_admin"))
    assert r.status_code == 200, r.text
    assert state(world, "b_admin")["ai"]["quick_prompts"] == ["B only prompt"]
    a = pick(world, "a_employee", "INSTITUTIONAL_CLERK").json()
    assert "B only prompt" not in a["ai"]["quick_prompts"]


# ── navigation and AI tool permissions ───────────────────────────────────────

@pytest.mark.parametrize("key,own", [
    ("DIGITAL_MARKETING_MANAGER", "customize"), ("INSTITUTIONAL_CLERK", "clerk"),
    ("MEDICAL_ASSISTANT", "clinic"), ("DATA_INTELLIGENCE_ANALYST", "data"),
])
def test_navigation_shows_only_the_selected_roles_features(world, key, own):
    nav = pick(world, "a_employee", key).json()["navigation"]
    assert nav[:2] == ["cabin", "workspace"] and own in nav
    assert not (ROLE_ONLY_NAV - {own}) & set(nav)
    assert not {"team", "marketplace", "audit", "employees", "connections"} & set(nav)      # employees see no admin pages


def test_administrators_also_get_company_administration_entries(world):
    nav = pick(world, "a_admin", "MEDICAL_ASSISTANT").json()["navigation"]
    assert {"team", "marketplace", "audit", "employees", "connections"} <= set(nav)
    assert "clinic" in nav and "data" not in nav and "clerk" not in nav


@pytest.mark.parametrize("key,must,never", [
    ("DIGITAL_MARKETING_MANAGER", "query_campaign_analytics", "list_appointments"),
    ("INSTITUTIONAL_CLERK", "list_service_requests", "analyze_dataset"),
    ("MEDICAL_ASSISTANT", "list_appointments", "send_email"),
    ("DATA_INTELLIGENCE_ANALYST", "analyze_dataset", "list_service_requests"),
])
def test_ai_context_matches_the_server_role_configuration(world, key, must, never):
    ai = pick(world, "a_employee", key).json()["ai"]
    bp = world.client.get(f"/api/v1/roles/{key}/blueprint", headers=world.auth("a_employee")).json()
    assert set(ai["allowed_tools"]) == set(bp["allowed_tools"]) and set(ai["guarded_tools"]) == set(bp["guarded_tools"])
    tools = set(ai["allowed_tools"]) | set(ai["guarded_tools"])
    assert must in tools and never not in tools
    assert ai["knowledge_scope"] == key and ai["safety_rules"]


def test_medical_workspace_carries_its_clinical_safety_rules(world):
    ai = pick(world, "a_employee", "MEDICAL_ASSISTANT").json()["ai"]
    text = " ".join(ai["safety_rules"]).lower()
    assert "never diagnoses" in text and "emergency" in text and "approval" in text
    assert "update_appointment_status" in ai["guarded_tools"] and "update_appointment_status" not in ai["allowed_tools"]


def test_agent_execution_still_refuses_a_disabled_module_after_selection(world):
    pick(world, "a_employee", "MEDICAL_ASSISTANT")
    module(world, "MEDICAL_ASSISTANT", False)
    body = {"blueprint": {"agent_id": "x", "role_name": "Medical Assistant", "role_key": "MEDICAL_ASSISTANT",
                          "system_persona": "p", "allowed_tools": ["send_email"], "guarded_tools": [], "tenant_id": world.tenant_b},
            "user_prompt": "Hello there"}
    r = world.client.post("/api/v1/agent/execute", json=body, headers=world.auth("a_employee"))
    assert r.status_code == 403 and "not activated" in r.json()["detail"]
