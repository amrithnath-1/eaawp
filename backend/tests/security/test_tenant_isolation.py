"""
Tenant-isolation and authentication regression tests (Phase 2).

These run the REAL app with REAL JWT verification against a temporary
database holding two companies.  Nothing in the auth path is mocked.

Covered:
  1. A bare X-Tenant-ID header never authenticates.
  2. Invalid / expired / malformed / forged tokens are rejected.
  3. The header cannot switch tenants for an authenticated user.
  4. Tenant A cannot read, update or delete Tenant B's records.
  5. Users cannot elevate their role or switch tenants via request data.
  6. Same-tenant requests keep working.
  7. Onboarding endpoints are tenant-bound.
  8. Agent execution takes tenant and permissions from the token.
  9. OAuth authorize/callback bind tenant AND user.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests.security.helpers import TEST_SECRET, forge_token

# A representative spread of endpoints from every router family that used to
# trust the header (the exhaustive list is enforced by test_route_auth_inventory).
GET_ENDPOINTS = [
    "/api/v1/audit",
    "/api/v1/campaigns",
    "/api/v1/notifications",
    "/api/v1/schedules",
    "/api/v1/ai-employees",
    "/api/v1/content",
    "/api/v1/strategy/objectives",
    "/api/v1/monitoring/rules",
    "/api/v1/integrations/connections",
    "/api/v1/data/mappings",
    "/api/v1/email/drafts",
    "/api/v1/channels",
    "/api/v1/roles/DIGITAL_MARKETING_MANAGER",
    "/api/v1/employees",
    "/api/v1/integration-manager/providers",
    "/api/v1/llm/status",
    "/api/v1/llm-models",
    "/api/v1/actions/tools",
    "/api/v1/oauth/google/authorize",
    "/api/v1/agent/config",
]


# ════════════════════════════════════════════════════════════════════════════
# 1. Bare header / no credentials
# ════════════════════════════════════════════════════════════════════════════
class TestBareHeaderRejected:
    @pytest.mark.parametrize("path", GET_ENDPOINTS)
    def test_header_only_is_401(self, world, path):
        r = world.client.get(path, headers={"X-Tenant-ID": world.tenant_b})
        assert r.status_code == 401, f"{path} -> {r.status_code} {r.text[:120]}"

    @pytest.mark.parametrize("path", GET_ENDPOINTS)
    def test_no_credentials_is_401(self, world, path):
        assert world.client.get(path).status_code == 401

    def test_agent_execute_header_only_is_401(self, world):
        r = world.client.post(
            "/api/v1/agent/execute",
            headers={"X-Tenant-ID": world.tenant_b},
            json={"blueprint": _blueprint(world.tenant_b), "user_prompt": "hello"},
        )
        assert r.status_code == 401

    def test_header_only_cannot_write(self, world):
        r = world.client.post(
            "/api/v1/campaigns",
            headers={"X-Tenant-ID": world.tenant_b},
            json={"name": "injected"},
        )
        assert r.status_code == 401

    def test_legacy_demo_tenant_literals_do_not_authenticate(self, world):
        for t in ("default-tenant", "demo-company-001", world.tenant_a):
            r = world.client.get("/api/v1/audit", headers={"X-Tenant-ID": t})
            assert r.status_code == 401

    def test_empty_bearer_is_401(self, world):
        r = world.client.get("/api/v1/campaigns", headers={"Authorization": "Bearer "})
        assert r.status_code == 401


# ════════════════════════════════════════════════════════════════════════════
# 2. Invalid tokens
# ════════════════════════════════════════════════════════════════════════════
class TestInvalidTokens:
    def _get(self, world, token, extra=None):
        h = {"Authorization": f"Bearer {token}"}
        h.update(extra or {})
        return world.client.get("/api/v1/campaigns", headers=h)

    @pytest.mark.parametrize("token", ["", "abc", "a.b.c", "not a jwt", "eyJhbGciOiJIUzI1NiJ9.e30.", "x" * 600])
    def test_malformed_token(self, world, token):
        assert self._get(world, token).status_code == 401

    def test_malformed_token_with_valid_looking_header_does_not_fall_back(self, world):
        r = self._get(world, "garbage", {"X-Tenant-ID": world.tenant_a})
        assert r.status_code == 401

    def test_expired_token(self, world):
        u = world.users["a_admin"]
        past = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp())
        tok = forge_token({"sub": u["id"], "tid": u["tenant_id"], "exp": past})
        assert self._get(world, tok).status_code == 401

    def test_token_signed_with_wrong_secret(self, world):
        u = world.users["a_admin"]
        tok = forge_token({"sub": u["id"], "tid": u["tenant_id"]}, secret="attacker-secret-" + "z" * 24)
        assert self._get(world, tok).status_code == 401

    def test_refresh_token_cannot_be_used_as_access_token(self, world):
        u = world.users["a_admin"]
        tok = forge_token({"sub": u["id"], "tid": u["tenant_id"], "type": "refresh"})
        assert self._get(world, tok).status_code == 401

    def test_token_without_expiry_is_rejected(self, world):
        u = world.users["a_admin"]
        tok = forge_token({"sub": u["id"], "tid": u["tenant_id"]}, drop=("exp",))
        assert self._get(world, tok).status_code == 401

    def test_token_without_subject_is_rejected(self, world):
        tok = forge_token({"tid": world.tenant_a}, drop=("sub",))
        assert self._get(world, tok).status_code == 401

    def test_alg_none_token_is_rejected(self, world):
        import base64, json

        def b64(d):
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

        u = world.users["a_admin"]
        tok = b64({"alg": "none", "typ": "JWT"}) + "." + b64(
            {"sub": u["id"], "tid": u["tenant_id"], "type": "access",
             "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())}
        ) + "."
        assert self._get(world, tok).status_code == 401

    def test_tampered_payload_is_rejected(self, world):
        good = world.token("a_admin")
        head, _payload, sig = good.split(".")
        import base64, json

        evil = base64.urlsafe_b64encode(json.dumps(
            {"sub": world.users["b_admin"]["id"], "tid": world.tenant_b, "type": "access",
             "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())}
        ).encode()).rstrip(b"=").decode()
        assert self._get(world, f"{head}.{evil}.{sig}").status_code == 401

    def test_token_for_unknown_user_is_rejected(self, world):
        tok = forge_token({"sub": str(uuid.uuid4()), "tid": world.tenant_a})
        assert self._get(world, tok).status_code == 401

    def test_token_for_deactivated_user_is_rejected(self, world):
        import asyncio
        from app.db.models import User

        async def deactivate():
            async with world.maker() as s:
                u = (await s.execute(select(User).where(User.id == world.users["a_employee"]["id"]))).scalar_one()
                u.is_active = False
                await s.commit()

        asyncio.new_event_loop().run_until_complete(deactivate())
        assert self._get(world, world.token("a_employee")).status_code == 401


# ════════════════════════════════════════════════════════════════════════════
# 3. The header must never switch tenants
# ════════════════════════════════════════════════════════════════════════════
class TestHeaderCannotSwitchTenant:
    def test_header_for_other_tenant_is_ignored(self, world):
        c = world.client
        assert c.post("/api/v1/campaigns", headers=world.auth("a_admin"), json={"name": "A-only"}).status_code in (200, 201)
        # B asks for tenant A's data by header while holding a valid B token.
        r = c.get("/api/v1/campaigns", headers={**world.auth("b_admin"), "X-Tenant-ID": world.tenant_a})
        assert r.status_code == 200
        assert "A-only" not in r.text
        # A, claiming to be B by header, still only sees A.
        r = c.get("/api/v1/campaigns", headers={**world.auth("a_admin"), "X-Tenant-ID": world.tenant_b})
        assert "A-only" in r.text

    def test_token_tid_claim_cannot_override_user_tenant(self, world):
        """A token whose ``tid`` claims tenant B but whose subject is an A user acts as A."""
        c = world.client
        c.post("/api/v1/campaigns", headers=world.auth("a_admin"), json={"name": "A-secret"})
        c.post("/api/v1/campaigns", headers=world.auth("b_admin"), json={"name": "B-secret"})
        u = world.users["a_admin"]
        tok = forge_token({"sub": u["id"], "tid": world.tenant_b, "role": "Company Admin"}, secret=TEST_SECRET)
        r = c.get("/api/v1/campaigns", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert "A-secret" in r.text and "B-secret" not in r.text


# ════════════════════════════════════════════════════════════════════════════
# 4. Cross-tenant read / update / delete by resource id
# ════════════════════════════════════════════════════════════════════════════
def _blueprint(tenant_id):
    return {
        "agent_id": "marketing-intelligence-agent",
        "role_name": "Digital Marketing Manager",
        "system_persona": "p",
        "allowed_tools": ["query_campaign_analytics"],
        "guarded_tools": [],
        "tenant_id": tenant_id,
    }


def _ok(r):
    return r.status_code in (200, 201)


class TestCrossTenantResourceAccess:
    """B owns the resources; A (an admin, so role is not the barrier) probes by id."""

    def _make_b_resources(self, world):
        c, h = world.client, world.auth("b_admin")
        ids = {}
        r = c.post("/api/v1/campaigns", headers=h, json={"name": "B-campaign", "objective": "original"})
        assert _ok(r), r.text
        ids["campaign"] = r.json()["id"]
        r = c.post(f"/api/v1/campaigns/{ids['campaign']}/metrics", headers=h,
                   json={"metric_name": "clicks", "metric_value": 4242, "metric_date": "2026-10-01"})
        assert _ok(r), r.text
        r = c.post("/api/v1/strategy/objectives", headers=h, json={"name": "B-objective"})
        assert _ok(r), r.text
        ids["objective"] = r.json()["id"]
        r = c.post("/api/v1/ai-employees", headers=h, json={"role_key": "DIGITAL_MARKETING_MANAGER", "name": "B-emp"})
        assert _ok(r), r.text
        ids["employee"] = r.json()["id"]
        r = c.post(f"/api/v1/schedules?ai_employee_id={ids['employee']}", headers=h,
                   json={"task_name": "B-task", "frequency": "daily"})
        assert _ok(r), r.text
        ids["schedule"] = r.json()["id"]
        r = c.post("/api/v1/integrations/connections", headers=h, json={
            "display_name": "B-db", "db_type": "postgresql", "host": "db.example.test",
            "port": 5432, "database_name": "d", "username": "u", "password": "pw-B-secret"})
        assert _ok(r), r.text
        ids["connection"] = r.json()["id"]
        return ids

    def test_cannot_read_update_or_delete_other_tenants_records(self, world):
        c = world.client
        ids = self._make_b_resources(world)
        a = world.auth("a_admin")

        probes = [
            ("GET", f"/api/v1/campaigns/{ids['campaign']}", None),
            ("PATCH", f"/api/v1/campaigns/{ids['campaign']}", {"objective": "HACKED"}),
            ("GET", f"/api/v1/campaigns/{ids['campaign']}/summary", None),
            ("POST", f"/api/v1/campaigns/{ids['campaign']}/metrics",
             {"metric_name": "clicks", "metric_value": 1, "metric_date": "2026-10-02"}),
            ("DELETE", f"/api/v1/campaigns/{ids['campaign']}", None),
            ("GET", f"/api/v1/strategy/objectives/{ids['objective']}", None),
            ("PATCH", f"/api/v1/strategy/objectives/{ids['objective']}", {"name": "HACKED"}),
            ("PATCH", f"/api/v1/schedules/{ids['schedule']}/toggle", None),
            ("GET", f"/api/v1/ai-employees/{ids['employee']}", None),
            ("PATCH", f"/api/v1/ai-employees/{ids['employee']}/status", {"status": "PAUSED"}),
            ("GET", f"/api/v1/integrations/connections/{ids['connection']}", None),
            ("PATCH", f"/api/v1/integrations/connections/{ids['connection']}", {"display_name": "HACKED"}),
            ("GET", f"/api/v1/integrations/connections/{ids['connection']}/entities", None),
            ("POST", f"/api/v1/integrations/connections/{ids['connection']}/test", None),
            ("DELETE", f"/api/v1/integrations/connections/{ids['connection']}", None),
        ]
        for method, path, body in probes:
            r = c.request(method, path, headers=a, json=body) if body is not None else c.request(method, path, headers=a)
            assert r.status_code in (403, 404, 405, 422), f"LEAK {method} {path} -> {r.status_code}: {r.text[:150]}"
            assert r.status_code != 200 and r.status_code != 201 and r.status_code != 204, f"{method} {path}"

        # Metrics for B's campaign read as empty for A (never B's numbers).
        m = c.get(f"/api/v1/campaigns/{ids['campaign']}/metrics", headers=a)
        assert m.status_code in (200, 403, 404) and "4242" not in m.text and m.json() in ([], {"detail": "Campaign not found."}) or m.status_code in (403, 404)

        # B's data is untouched after every attempt.
        b = world.auth("b_admin")
        assert len(c.get(f"/api/v1/campaigns/{ids['campaign']}/metrics", headers=b).json()) == 1
        camp = c.get(f"/api/v1/campaigns/{ids['campaign']}", headers=b)
        assert camp.status_code == 200 and camp.json()["objective"] == "original"
        assert c.get(f"/api/v1/strategy/objectives/{ids['objective']}", headers=b).json()["name"] == "B-objective"
        assert c.get(f"/api/v1/integrations/connections/{ids['connection']}", headers=b).json()["display_name"] == "B-db"
        assert c.get(f"/api/v1/ai-employees/{ids['employee']}", headers=b).status_code == 200

    def test_list_endpoints_never_include_other_tenants_rows(self, world):
        self._make_b_resources(world)
        a = world.auth("a_admin")
        for path in ("/api/v1/campaigns", "/api/v1/strategy/objectives", "/api/v1/schedules",
                     "/api/v1/ai-employees", "/api/v1/integrations/connections", "/api/v1/audit"):
            r = world.client.get(path, headers=a)
            assert r.status_code == 200, path
            assert "B-" not in r.text, f"{path} leaked tenant B data"
            assert "pw-B-secret" not in r.text

    def test_role_configuration_is_per_tenant(self, world):
        c = world.client
        base = c.get("/api/v1/roles/DIGITAL_MARKETING_MANAGER", headers=world.auth("b_admin"))
        assert base.status_code == 200
        original = base.json().get("system_persona")
        r = c.patch("/api/v1/roles/DIGITAL_MARKETING_MANAGER", headers=world.auth("a_admin"),
                    json={"system_persona": "TENANT A ONLY PERSONA"})
        assert r.status_code in (200, 422), r.text
        after = c.get("/api/v1/roles/DIGITAL_MARKETING_MANAGER", headers=world.auth("b_admin")).json()
        assert after.get("system_persona") == original
        assert "TENANT A ONLY PERSONA" not in str(after)


# ════════════════════════════════════════════════════════════════════════════
# 5. Role / tenant escalation through request data
# ════════════════════════════════════════════════════════════════════════════
class TestNoEscalation:
    def test_employee_cannot_create_users(self, world):
        r = world.client.post("/api/v1/users", headers=world.auth("a_employee"), json={
            "email": "new@example.test", "name": "n", "password": "Password-12345", "role": "Company Admin"})
        assert r.status_code == 403

    def test_admin_cannot_mint_superadmin(self, world):
        r = world.client.post("/api/v1/users", headers=world.auth("a_admin"), json={
            "email": "root@example.test", "name": "n", "password": "Password-12345", "role": "superadmin"})
        assert r.status_code == 400

    def test_admin_cannot_create_user_in_another_tenant(self, world):
        import asyncio
        from app.db.models import User

        r = world.client.post("/api/v1/users", headers=world.auth("a_admin"), json={
            "email": "x-tenant@example.test", "name": "n", "password": "Password-12345",
            "role": "Employee", "tenant_id": world.tenant_b})
        assert r.status_code in (200, 201, 422), r.text

        async def lookup():
            async with world.maker() as s:
                return (await s.execute(select(User).where(User.email == "x-tenant@example.test"))).scalar_one_or_none()

        u = asyncio.new_event_loop().run_until_complete(lookup())
        if u is not None:  # created -> must be in the caller's tenant, never B
            assert u.tenant_id == world.tenant_a

    def test_forged_admin_role_claim_does_not_grant_admin(self, world):
        """Role comes from the user record, not from the (signed) token claim."""
        u = world.users["a_employee"]
        tok = forge_token({"sub": u["id"], "tid": u["tenant_id"], "role": "Company Admin"})
        r = world.client.post("/api/v1/users", headers={"Authorization": f"Bearer {tok}"}, json={
            "email": "n@example.test", "name": "n", "password": "Password-12345", "role": "Employee"})
        assert r.status_code == 403

    def test_employee_cannot_approve_config_proposals_or_blueprints(self, world):
        c, e = world.client, world.auth("a_employee")
        r1 = c.post("/api/v1/employees/blueprints/any/approve", headers=e,
                    json={"decision": "approve", "reviewed_by": "someone-else"})
        r2 = c.post("/api/v1/employees/blueprints/any/reject", headers=e,
                    json={"decision": "reject", "reviewed_by": "someone-else"})
        r3 = c.post("/api/v1/roles/DIGITAL_MARKETING_MANAGER/proposals/any/approve", headers=e,
                    json={"decision": "approve", "reviewed_by": "someone-else"})
        r4 = c.post("/api/v1/roles/DIGITAL_MARKETING_MANAGER/proposals/any/reject", headers=e,
                    json={"decision": "reject", "reviewed_by": "someone-else"})
        assert [r.status_code for r in (r1, r2, r3, r4)] == [403, 403, 403, 403]

    def test_admin_cannot_use_other_tenants_proposal_ids(self, world):
        c, a = world.client, world.auth("a_admin")
        for path in ("/api/v1/employees/blueprints/does-not-exist/approve",
                     "/api/v1/roles/DIGITAL_MARKETING_MANAGER/proposals/does-not-exist/approve"):
            r = c.post(path, headers=a, json={"decision": "approve", "reviewed_by": "forged@example.test"})
            assert r.status_code == 404, (path, r.status_code, r.text[:100])


# ════════════════════════════════════════════════════════════════════════════
# 6. Authorised same-tenant requests still work
# ════════════════════════════════════════════════════════════════════════════
class TestSameTenantStillWorks:
    @pytest.mark.parametrize("who", ["a_admin", "a_employee"])
    def test_authenticated_reads_succeed(self, world, who):
        for path in ("/api/v1/campaigns", "/api/v1/notifications", "/api/v1/schedules",
                     "/api/v1/integration-manager/providers", "/api/v1/llm-models", "/api/v1/actions/tools"):
            r = world.client.get(path, headers=world.auth(who))
            assert r.status_code == 200, (path, r.status_code, r.text[:120])

    def test_crud_round_trip_in_own_tenant(self, world):
        c, h = world.client, world.auth("a_admin")
        r = c.post("/api/v1/campaigns", headers=h, json={"name": "Mine", "objective": "o"})
        assert _ok(r)
        cid = r.json()["id"]
        assert c.get(f"/api/v1/campaigns/{cid}", headers=h).status_code == 200
        assert c.patch(f"/api/v1/campaigns/{cid}", headers=h, json={"objective": "changed"}).status_code == 200
        assert c.get(f"/api/v1/campaigns/{cid}", headers=h).json()["objective"] == "changed"
        assert c.delete(f"/api/v1/campaigns/{cid}", headers=h).status_code in (200, 204)

    def test_login_still_works_and_token_authenticates(self, world):
        from tests.conftest import PASSWORD

        u = world.users["a_admin"]
        r = world.client.post("/api/v1/auth/token", json={
            "email": u["email"], "password": PASSWORD, "company_id": u["tenant_id"]})
        assert r.status_code == 200, r.text
        tok = r.json()["access_token"]
        assert world.client.get("/api/v1/campaigns", headers={"Authorization": f"Bearer {tok}"}).status_code == 200

    def test_public_endpoints_stay_public(self, world):
        assert world.client.get("/health").status_code == 200
        r = world.client.post("/api/v1/onboarding/company", json={
            "company_name": "Fresh Co", "admin_name": "Ada", "admin_email": "ada@fresh.test",
            "admin_password": "Password-12345"})
        assert r.status_code == 201, r.text


# ════════════════════════════════════════════════════════════════════════════
# 7. Onboarding endpoints
# ════════════════════════════════════════════════════════════════════════════
class TestOnboardingTenantBinding:
    def test_status_requires_auth(self, world):
        assert world.client.get(f"/api/v1/onboarding/status/{world.tenant_a}").status_code == 401

    def test_status_for_other_tenant_is_404(self, world):
        r = world.client.get(f"/api/v1/onboarding/status/{world.tenant_b}", headers=world.auth("a_admin"))
        assert r.status_code == 404

    def test_status_for_own_tenant_works(self, world):
        r = world.client.get(f"/api/v1/onboarding/status/{world.tenant_a}", headers=world.auth("a_employee"))
        assert r.status_code == 200 and r.json()["tenant_id"] == world.tenant_a

    def test_activate_requires_admin(self, world):
        assert world.client.post("/api/v1/onboarding/activate-dmm", json={}).status_code == 401
        r = world.client.post("/api/v1/onboarding/activate-dmm", headers=world.auth("a_employee"), json={})
        assert r.status_code == 403

    def test_activate_cannot_target_other_tenant(self, world):
        import asyncio
        from app.db.models import AIEmployee

        r = world.client.post("/api/v1/onboarding/activate-dmm", headers=world.auth("a_admin"),
                              json={"tenant_id": world.tenant_b})
        assert r.status_code == 404

        async def count():
            async with world.maker() as s:
                rows = (await s.execute(select(AIEmployee).where(AIEmployee.tenant_id == world.tenant_b))).scalars().all()
                return len(rows)

        assert asyncio.new_event_loop().run_until_complete(count()) == 0


# ════════════════════════════════════════════════════════════════════════════
# 8. Agent execution
# ════════════════════════════════════════════════════════════════════════════
class TestAgentExecution:
    def _tenants_with_role_config(self, world):
        import asyncio
        from app.db.models import RoleConfiguration

        async def go():
            async with world.maker() as s:
                rows = (await s.execute(select(RoleConfiguration))).scalars().all()
                return {r.tenant_id for r in rows}

        return asyncio.new_event_loop().run_until_complete(go())

    def test_execute_ignores_tenant_in_request_body(self, world):
        """The body names tenant B, the token is tenant A: only A is touched."""
        r = world.client.post(
            "/api/v1/agent/execute", headers=world.auth("a_employee"),
            json={"blueprint": _blueprint(world.tenant_b), "user_prompt": "hello"},
        )
        assert r.status_code == 200, r.text
        tenants = self._tenants_with_role_config(world)
        assert world.tenant_a in tenants
        assert world.tenant_b not in tenants

    def test_execute_ignores_client_supplied_tool_permissions(self, world):
        bp = _blueprint(world.tenant_a)
        bp["allowed_tools"] = ["send_email", "query_company_data"]
        bp["guarded_tools"] = []
        r = world.client.post("/api/v1/agent/execute", headers=world.auth("a_employee"),
                              json={"blueprint": bp, "user_prompt": "hello"})
        assert r.status_code == 200
        assert r.json().get("tool_calls") == []

    def test_execute_with_expired_token_is_401(self, world):
        u = world.users["a_admin"]
        past = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
        tok = forge_token({"sub": u["id"], "tid": u["tenant_id"], "exp": past})
        r = world.client.post("/api/v1/agent/execute", headers={"Authorization": f"Bearer {tok}"},
                              json={"blueprint": _blueprint(world.tenant_a), "user_prompt": "hello"})
        assert r.status_code == 401

    def test_plan_lookup_is_tenant_scoped(self, world):
        import asyncio
        from app.db.models import ExecutionPlan

        pid = str(uuid.uuid4())

        async def seed():
            async with world.maker() as s:
                s.add(ExecutionPlan(id=pid, tenant_id=world.tenant_b, role_key="DIGITAL_MARKETING_MANAGER",
                                    session_id="s", objective="b-plan", status="awaiting_approval"))
                await s.commit()

        asyncio.new_event_loop().run_until_complete(seed())
        assert world.client.get(f"/api/v1/planning/plans/{pid}", headers=world.auth("a_admin")).status_code == 404
        assert world.client.get(f"/api/v1/planning/plans/{pid}", headers=world.auth("b_admin")).status_code == 200


# ════════════════════════════════════════════════════════════════════════════
# 9. OAuth authorize + callback
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def google_configured(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "google_client_id", "client-id.apps.example.test", raising=False)
    monkeypatch.setattr(config.settings, "google_client_secret", "client-secret", raising=False)
    monkeypatch.setattr(config.settings, "google_redirect_uri",
                        "http://testserver/api/v1/oauth/google/callback", raising=False)


class TestOAuthBinding:
    def _states(self, world):
        import asyncio
        from app.db.oauth_models import OAuthState

        async def go():
            async with world.maker() as s:
                return list((await s.execute(select(OAuthState))).scalars().all())

        return asyncio.new_event_loop().run_until_complete(go())

    def test_authorize_requires_jwt(self, world, google_configured):
        for p in ("/api/v1/oauth/google/authorize", "/api/v1/oauth/google/analytics/authorize"):
            assert world.client.get(p, headers={"X-Tenant-ID": world.tenant_a}).status_code == 401

    def test_authorize_binds_state_to_token_tenant_and_user(self, world, google_configured):
        r = world.client.get("/api/v1/oauth/google/authorize",
                             headers={**world.auth("a_admin"), "X-Tenant-ID": world.tenant_b})
        assert r.status_code == 200, r.text
        states = self._states(world)
        assert len(states) == 1
        assert states[0].tenant_id == world.tenant_a          # not the header's tenant
        assert states[0].initiated_by_user_id == world.users["a_admin"]["id"]

    def _make_state(self, world, *, user_key="a_admin", tenant=None, expired=False, used=False, no_user=False):
        import asyncio
        from app.db.models import DataConnection  # noqa: F401
        from app.db.oauth_models import OAuthState
        from app.integrations.manager import create_integration
        from app.schemas.integration_framework import IntegrationCreate

        token = uuid.uuid4().hex + uuid.uuid4().hex
        tid = tenant or world.users[user_key]["tenant_id"]

        async def go():
            async with world.maker() as s:
                integ = await create_integration(
                    IntegrationCreate(provider_type="google_search_console", display_name="GSC", credentials={}),
                    tenant_id=tid, db=s)
                s.add(OAuthState(
                    state_token=token, tenant_id=tid,
                    initiated_by_user_id=None if no_user else world.users[user_key]["id"],
                    integration_id=integ.id, provider_type="google_search_console",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=-5 if expired else 10),
                    used=used))
                await s.commit()
                return integ.id

        return token, asyncio.new_event_loop().run_until_complete(go())

    def _callback(self, world, state):
        return world.client.get(f"/api/v1/oauth/google/callback?code=abc&state={state}", follow_redirects=False)

    @pytest.mark.parametrize("kw", [
        {"expired": True}, {"used": True}, {"no_user": True},
    ])
    def test_callback_rejects_bad_states(self, world, google_configured, kw):
        token, _ = self._make_state(world, **kw)
        r = self._callback(world, token)
        assert r.status_code in (302, 307)
        assert "error=" in r.headers["location"]

    def test_callback_rejects_unknown_state(self, world, google_configured):
        r = self._callback(world, "does-not-exist")
        assert r.status_code in (302, 307) and "error=" in r.headers["location"]

    def test_callback_rejects_state_of_deactivated_user_and_burns_it(self, world, google_configured):
        import asyncio
        from app.db.models import User
        from app.db.oauth_models import OAuthState

        token, _ = self._make_state(world, user_key="a_employee")

        async def deactivate():
            async with world.maker() as s:
                u = (await s.execute(select(User).where(User.id == world.users["a_employee"]["id"]))).scalar_one()
                u.is_active = False
                await s.commit()

        asyncio.new_event_loop().run_until_complete(deactivate())
        r = self._callback(world, token)
        assert "error=" in r.headers["location"]

        async def used():
            async with world.maker() as s:
                return (await s.execute(select(OAuthState).where(OAuthState.state_token == token))).scalar_one().used

        assert asyncio.new_event_loop().run_until_complete(used()) is True

    def test_callback_rejects_initiator_from_a_different_tenant_than_state(self, world, google_configured):
        """State says tenant A, but the recorded user belongs to tenant B -> rejected."""
        import asyncio
        from app.db.oauth_models import OAuthState

        token, _ = self._make_state(world, user_key="a_admin")

        async def corrupt():
            async with world.maker() as s:
                st = (await s.execute(select(OAuthState).where(OAuthState.state_token == token))).scalar_one()
                st.initiated_by_user_id = world.users["b_admin"]["id"]
                await s.commit()

        asyncio.new_event_loop().run_until_complete(corrupt())
        assert "error=" in self._callback(world, token).headers["location"]

    def test_callback_does_not_log_state_token(self, world, google_configured, caplog):
        import logging

        caplog.set_level(logging.DEBUG)
        token, _ = self._make_state(world, expired=True)
        self._callback(world, token)
        # Our own loggers (not third-party client/driver debug output) must not
        # contain the secret state token.
        ours = [r.getMessage() for r in caplog.records if r.name.startswith(("app", "eaawp"))]
        assert ours, "expected the callback to log a rejection"
        assert not any(token in m for m in ours)

    def test_sql_parameters_are_not_logged(self, world):
        """Engine must not echo bound parameters (hashes, tokens, personal data)."""
        from app.db.session import engine

        assert engine.sync_engine.hide_parameters is True
        assert engine.sync_engine.echo is False
