"""
Tool, approval and operation status shown in the chat header: computed from server state, never fixed numbers.
Approval records carry what they are about (AI employee, tool, risk, redacted parameters, reason, outcome, people).

FAKED: the language model only.
"""
from __future__ import annotations

from sqlalchemy import select

from tests.conftest import _run
from tests.test_role_intelligence import _connect_github, _propose_objective, objective_model, pick  # noqa: F401

T = "/api/v1/workspace/tools"
DMM = "DIGITAL_MARKETING_MANAGER"


def tools(w, who):
    r = w.client.get(T, headers=w.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


def test_no_selection_means_no_tools_claimed(world):
    body = tools(world, "a_employee")
    assert body["role_key"] is None and body["tools"] == [] and body["counts"] == {}


def test_counts_match_the_roles_saved_configuration(world):
    pick(world, "a_employee", DMM)
    body = tools(world, "a_employee")
    c = body["counts"]
    assert (c["available"], c["requires_approval"], c["blocked"]) == (23, 5, 0)
    gated = sorted(t["key"] for t in body["tools"] if t["status"] == "requires_approval")
    assert gated == ["create_campaign", "create_marketing_objective", "send_email", "update_campaign",
                     "update_marketing_objective"]
    assert all(t["description"] for t in body["tools"]), [t["key"] for t in body["tools"] if not t["description"]]
    assert body["approvals"] == {"pending": 0, "can_decide": False}


def test_turning_a_tool_off_in_the_role_configuration_changes_the_count(world):
    pick(world, "a_admin", DMM)
    cfg = world.client.get(f"/api/v1/roles/{DMM}", headers=world.auth("a_admin"))
    assert cfg.status_code == 200, cfg.text
    data = cfg.json()
    for s in data["tool_scopes"]:
        if s["tool_key"] == "send_email":
            s["governance"] = "disabled"
    r = world.client.put(f"/api/v1/roles/{DMM}", json=data, headers=world.auth("a_admin"))
    assert r.status_code == 200, r.text
    body = tools(world, "a_admin")
    send = next(t for t in body["tools"] if t["key"] == "send_email")
    assert send["status"] == "disabled" and body["counts"]["requires_approval"] == 5  # 4 role tools + customize_eaawp (admin) and body["counts"]["blocked"] == 1


def test_integration_tools_follow_live_connection_state_and_risk(world):
    from app.db.integration_models import Integration

    pick(world, "a_admin", DMM)
    iid = _connect_github(world, grants=("list_repositories", "create_issue"))
    body = tools(world, "a_admin")
    gh = {t["key"]: t for t in body["tools"] if t["source"] == "integration"}
    assert gh["list_repositories"]["status"] == "available"
    assert gh["create_issue"]["status"] == "blocked_high_risk"
    assert gh["list_repositories"]["integration"]["provider_type"] == "github"
    assert "ghp_" not in str(body)
    assert body["counts"]["integration_available"] == 1

    async def switch_off():
        async with world.maker() as s:
            row = (await s.execute(select(Integration).where(Integration.id == iid))).scalar_one()
            row.is_enabled = False
            await s.commit()
    _run(switch_off())
    gh = {t["key"]: t for t in tools(world, "a_admin")["tools"] if t["source"] == "integration"}
    assert gh["list_repositories"]["status"] == "integration_disabled"


def test_pending_approvals_and_operations_are_real_and_approvals_are_described(world, objective_model):
    body = _propose_objective(world)   # admin's DMM chat proposes a guarded action
    st = tools(world, "a_admin")
    assert st["approvals"] == {"pending": 1, "can_decide": True}
    assert st["operations"]["awaiting_approval"] == 1 and st["operations"]["scope"] == "company"

    lst = world.client.get("/api/v1/approvals?status=pending", headers=world.auth("a_admin")).json()
    assert len(lst) == 1
    a = lst[0]
    assert a["ai_employee"] == "Digital Marketing Manager" and a["tool_name"] == "create_marketing_objective"
    assert a["risk_level"] == "medium" and a["parameters"]["name"] == "Brand awareness"
    assert a["reason"] and a["plan_id"] == body["plan_id"] and a["plan_status"] == "awaiting_approval"
    assert a["requested_for"] == "a_admin"
    assert a["execution_status"] == "pending"

    decided = world.client.post(f"/api/v1/approvals/{a['id']}/decide", json={"decision": "approved"},
                                headers=world.auth("a_admin"))
    assert decided.status_code == 200, decided.text
    d = decided.json()
    assert d["status"] == "approved" and d["execution_status"] == "executed" and d["plan_status"] == "completed"
    assert d["reviewer_name"] == "a_admin"
    st = tools(world, "a_admin")
    assert st["approvals"]["pending"] == 0 and st["operations"]["completed"] == 1


def test_employees_see_only_their_own_operations(world, objective_model):
    _propose_objective(world)                   # the admin's operation
    pick(world, "a_employee", DMM)
    ops = tools(world, "a_employee")["operations"]
    assert ops["scope"] == "mine" and ops["awaiting_approval"] == 0


def test_credential_like_parameters_never_reach_approval_records():
    from app.services.action_governance import _sanitise_arguments
    out = _sanitise_arguments({"name": "ok", "github_token": "x", "access_token": "y", "API_KEY": "z",
                               "db_password": "p", "Authorization": "Bearer q"})
    assert out == {"name": "ok"}
