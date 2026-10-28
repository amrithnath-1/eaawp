"""
Digital Marketing Manager -> Google Search Console, request to answer.

REAL here: FastAPI app, auth, execution router, readiness gate, planner, tool
engine, dynamic tool adapters, capability grants, Integration Manager,
credential encryption, the Search Console provider code, SQLite schema.

FAKED (only at the two network boundaries): the LLM (ScriptedChatModel) and
Google's APIs (``googleapiclient.discovery.build`` + the OAuth token exchange).

Nothing here proves the integration works against live Google; it proves our
code sends the right requests, enforces permissions and reports only what the
(fake) API returned.  Live verification is a separate, explicit step.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.integration_models import CapabilityGrant, Integration
from app.integrations import manager as mgr
from app.schemas.integration_framework import CapabilityGrantCreate, IntegrationCreate
from tests.test_marketing_analytics_e2e import (
    ACCESS, CLIENT_SECRET, DMM, GOOD_CLIENT_ID, REFRESH, STORED_SECRET,
    _Req, audit_rows, blueprint, google_oauth, plan_row, run,
)

PROMPT = ("What were our top search queries in Google Search Console over the last 28 days? "
          "Show clicks, impressions, CTR and average position.")
SITE = "sc-domain:example.com"
SITE_2 = "https://blog.example.com/"

ROWS = {"rows": [
    {"keys": ["running shoes"], "clicks": 320, "impressions": 8000, "ctr": 0.04, "position": 4.2},
    {"keys": ["trail shoes"], "clicks": 150, "impressions": 5000, "ctr": 0.03, "position": 6.8},
    {"keys": ["shoe sale"], "clicks": 90, "impressions": 1200, "ctr": 0.075, "position": 9.1},
]}
ONE_SITE = {"siteEntry": [{"siteUrl": SITE, "permissionLevel": "siteOwner"}]}
TWO_SITES = {"siteEntry": [
    {"siteUrl": SITE, "permissionLevel": "siteOwner"},
    {"siteUrl": SITE_2, "permissionLevel": "siteFullUser"},
    {"siteUrl": "https://not-mine.example.org/", "permissionLevel": "siteUnverifiedUser"},
]}


# ── fakes ─────────────────────────────────────────────────────────────────────
class ScriptedChatModel:
    def __init__(self, log, holder):
        self.log, self.h = log, holder

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, *a, **k):
        system, human = str(messages[0].content), str(messages[-1].content)
        self.log.append((system[:60], human))
        if "planning assistant" in system:
            m = re.search(r"(integration_[0-9a-f]{8}_get_search_analytics)", human)
            tool = m.group(1) if m else None
            args = self.h.args if self.h.args is not None else {
                "dimensions": ["query"], "start_date": "28daysAgo", "end_date": "3daysAgo", "row_limit": 10}
            steps = []
            if tool:
                steps.append({"step_index": 0, "step_type": "read", "description": "Pull search performance",
                              "tool_name": tool, "arguments": args, "depends_on": []})
            steps.append({"step_index": len(steps), "step_type": "response", "description": "Report",
                          "tool_name": None, "arguments": {}, "depends_on": [len(steps) - 1] if steps else []})
            self.h.today_seen = re.findall(r"Today \(UTC\): (\S+)", human)
            return AIMessage(content=json.dumps({"objective": "Search performance", "steps": steps}))
        if "Information gathered" in human:
            gathered = human.split("Information gathered:\n", 1)[1].split("\n\nUsing the information", 1)[0]
            if self.h.synth:
                return AIMessage(content=self.h.synth(gathered))
            return AIMessage(content="Here is what Search Console returned:\n" + gathered)
        return AIMessage(content='{"intent_type": "UNKNOWN", "confidence": 0.0, "reasoning": "n/a"}')


@pytest.fixture()
def llm(monkeypatch):
    log: list = []
    holder = SimpleNamespace(log=log, args=None, synth=None, today_seen=[])
    from app.llm.gateway import LLMGateway
    model = lambda self, *a, **k: ScriptedChatModel(log, holder)  # noqa: E731
    monkeypatch.setattr(LLMGateway, "get_chat_model", model)
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", model)
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return holder


@pytest.fixture()
def gsc_api(monkeypatch):
    st = SimpleNamespace(log=[], queries=[], sites=ONE_SITE, rows=ROWS, threads=[], site_gets=[])

    def build(api, version, **kw):
        assert api == "searchconsole", api
        st.threads.append(threading.current_thread())

        def query(siteUrl, requestBody):
            st.queries.append((siteUrl, requestBody))
            return _Req(st.log, "query", st.rows)

        def get(siteUrl):
            st.site_gets.append(siteUrl)
            return _Req(st.log, "get", {"siteUrl": siteUrl, "permissionLevel": "siteOwner"})

        return SimpleNamespace(
            sites=lambda: SimpleNamespace(list=lambda **k: _Req(st.log, "list", st.sites), get=get),
            searchAnalytics=lambda: SimpleNamespace(query=query),
        )

    import googleapiclient.discovery as discovery
    monkeypatch.setattr(discovery, "build", build)
    return st


@pytest.fixture()
def ga_api(gsc_api):
    """The shared ``google_oauth`` fixture asks for this name; same Google boundary fake."""
    return gsc_api


def _creds():
    return {"access_token": ACCESS, "refresh_token": REFRESH, "client_id": "fake.apps.example.test",
            "client_secret": CLIENT_SECRET,
            "token_expiry": (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat()}


def connect_gsc(world, tenant=None, grants=("get_search_analytics",), role=DMM, status="connected",
                enabled=True, default_property=None):
    tenant = tenant or world.tenant_a

    async def go():
        async with world.maker() as s:
            out = await mgr.create_integration(
                IntegrationCreate(provider_type="google_search_console", display_name="Search Console",
                                  credentials=_creds(), created_by="test"), tenant, s)
            row = (await s.execute(select(Integration).where(Integration.id == out.id))).scalar_one()
            row.status, row.is_enabled = status, enabled
            if default_property:
                row.account_info_json = json.dumps({"default_property": default_property})
            for cap in grants:
                await mgr.create_capability_grant(
                    out.id, CapabilityGrantCreate(role_key=role, capability_key=cap, is_granted=True, granted_by="test"),
                    tenant, s)
            await s.commit()
            return out.id
    return run(go())


def stored_info(world, iid):
    async def go():
        async with world.maker() as s:
            return json.loads((await s.execute(select(Integration.account_info_json).where(Integration.id == iid))).scalar_one())
    return run(go())


def ask(world, who="a_employee", prompt=PROMPT):
    return world.client.post("/api/v1/agent/execute", headers=world.auth(who),
                             json={"blueprint": blueprint(world.users[who]["tenant_id"]), "user_prompt": prompt})


def http_error(status, text):
    from googleapiclient.errors import HttpError
    return HttpError(SimpleNamespace(status=status, reason=text), text.encode())


def tasks(world, who="a_admin"):
    return world.client.get("/api/v1/agent/pending-tasks", headers=world.auth(who)).json()


# ═════════════════════════════════════════════════════════════════════════════
class TestHappyPath:
    def test_seo_question_returns_the_real_numbers(self, world, llm, gsc_api):
        iid = connect_gsc(world)
        r = ask(world)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan_status"] == "completed", body
        msg = body["message"]
        for text in ("running shoes", "320", "8000", "0.04", "4.2", "trail shoes", "150", "9.1"):
            assert text in msg, (text, msg)
        assert "Total clicks across the 3 rows above: 560" in msg
        assert "Overall CTR across these rows (total clicks / total impressions): 3.94%" in msg
        last = msg.rstrip().splitlines()[-1]
        assert last.startswith("Data source: Google Search Console (property sc-domain:example.com")
        assert "2-3 day delay" in last
        for secret in (ACCESS, REFRESH, CLIENT_SECRET):
            assert secret not in r.text + json.dumps(llm.log)
        blob = run(_blob(world, iid))
        assert ACCESS not in blob and REFRESH not in blob and CLIENT_SECRET not in blob

    def test_request_to_google_has_real_dates_dimensions_and_site(self, world, llm, gsc_api):
        connect_gsc(world)
        assert ask(world).status_code == 200
        site, req = gsc_api.queries[0]
        today = datetime.utcnow().date()
        assert site == SITE
        assert req["startDate"] == (today - timedelta(days=28)).isoformat()
        assert req["endDate"] == (today - timedelta(days=3)).isoformat()
        assert req["dimensions"] == ["query"] and req["rowLimit"] == 10
        assert req["dimensionFilterGroups"] == []             # unfiltered, read-only
        assert llm.today_seen and llm.today_seen[0] == today.isoformat()

    def test_dates_default_to_a_sensible_window_when_the_plan_gives_none(self, world, llm, gsc_api):
        connect_gsc(world)
        llm.args = {"dimensions": ["page"]}
        assert ask(world).json()["plan_status"] == "completed"
        _, req = gsc_api.queries[0]
        today = datetime.utcnow().date()
        assert (req["startDate"], req["endDate"]) == ((today - timedelta(days=28)).isoformat(), (today - timedelta(days=3)).isoformat())

    def test_the_only_property_is_selected_automatically_and_remembered(self, world, llm, gsc_api):
        iid = connect_gsc(world)
        assert ask(world).json()["plan_status"] == "completed"
        assert stored_info(world, iid)["default_property"] == SITE

    def test_audited_without_data_or_credentials(self, world, llm, gsc_api):
        connect_gsc(world)
        ask(world)
        rows = audit_rows(world)
        assert len(rows) == 1 and rows[0].success is True and rows[0].row_count == 3
        assert rows[0].role_key == DMM and rows[0].tenant_id == world.tenant_a
        assert ACCESS not in json.dumps([r.error_message or "" for r in rows])

    def test_selected_default_is_used_when_the_plan_names_no_site(self, world, llm, gsc_api):
        connect_gsc(world, default_property=SITE_2)
        gsc_api.sites = TWO_SITES
        assert ask(world).json()["plan_status"] == "completed"
        assert gsc_api.queries[0][0] == SITE_2

    def test_date_dimension_reports_the_days_present(self, world, llm, gsc_api):
        connect_gsc(world)
        llm.args = {"dimensions": ["date"], "start_date": "2026-10-01", "end_date": "2026-10-03"}
        gsc_api.rows = {"rows": [
            {"keys": ["2026-10-01"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.5},
            {"keys": ["2026-10-02"], "clicks": 20, "impressions": 200, "ctr": 0.1, "position": 5.0},
        ]}
        msg = ask(world).json()["message"]
        assert "Dates with data: 2026-10-01 to 2026-10-02 (2 days)" in msg
        assert "date: 2026-10-01" in msg and "dimensions:" not in msg


async def _blob(world, iid):
    async with world.maker() as s:
        return (await s.execute(select(Integration.encrypted_credentials).where(Integration.id == iid))).scalar_one()


# ═════════════════════════════════════════════════════════════════════════════
class TestTruthfulWhenThingsGoWrong:
    def test_permission_denied_no_numbers_invented(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.rows = http_error(403, "User does not have sufficient permission for site")
        body = ask(world).json()
        assert body["plan_status"] == "failed"
        assert "403" in body["message"] and "No figures were produced" in body["message"]
        assert not re.search(r"\d{3,}", body["message"].replace("403", ""))

    def test_expired_authorisation_says_reconnect(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.rows = http_error(401, "invalid credentials")
        body = ask(world).json()
        assert body["plan_status"] == "failed" and "reconnect" in body["message"].lower()

    def test_api_not_enabled_is_explained(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.rows = http_error(403, "Search Console API has not been used in project 1 before or it is disabled")
        assert "not enabled" in ask(world).json()["message"]

    def test_rate_limit_is_explained(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.rows = http_error(429, "Quota exceeded")
        body = ask(world).json()
        assert body["plan_status"] == "failed" and "rate-limiting" in body["message"]

    def test_unknown_site_404(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.rows = http_error(404, "Site not found")
        assert "could not find that property" in ask(world).json()["message"]

    def test_no_data_says_so_and_invents_nothing(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.rows = {}                               # Google omits "rows" when there is no data
        body = ask(world).json()
        assert body["plan_status"] == "completed" and "Rows: 0" in body["message"]
        assert "Total clicks" not in body["message"]

    def test_unsupported_claim_figures_are_caught(self, world, llm, gsc_api):
        connect_gsc(world)
        llm.synth = lambda g: "Great news: clicks grew 38% to 12,345 and CTR reached 9.99%."
        body = ask(world).json()
        assert "12,345" not in body["message"] and "9.99" not in body["message"]
        assert "couldn’t verify my own summary" in body["message"] and "320" in body["message"]
        assert "Grounding: replaced" in plan_row(world, body["plan_id"])[-1][1]

    def test_fabricated_position_is_caught(self, world, llm, gsc_api):
        connect_gsc(world)
        llm.synth = lambda g: "Average position for running shoes was 1.5."
        assert "1.5." not in ask(world).json()["message"].split("Data source")[0].replace("4.2", "")

    def test_wrong_date_range_claim_is_caught(self, world, llm, gsc_api):
        connect_gsc(world)
        llm.synth = lambda g: "Between 2020-01-01 and 2020-01-28 we got 560 clicks."
        msg = ask(world).json()["message"]
        assert "2020-01-01" not in msg and "couldn’t verify" in msg

    def test_faithful_summary_with_rounding_and_the_real_range_is_allowed(self, world, llm, gsc_api):
        connect_gsc(world)
        llm.synth = lambda g: "‘running shoes’ led with 320 clicks from 8,000 impressions (a 4% CTR, position about 4.2); overall CTR about 3.9%."
        msg = ask(world).json()["message"]
        assert "couldn’t verify" not in msg and "position about 4.2" in msg

    def test_several_properties_and_no_default_never_guesses(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.sites = TWO_SITES
        body = ask(world).json()
        assert body["plan_status"] == "awaiting_setup"
        assert not gsc_api.queries

    def test_plan_site_url_must_be_a_property_not_arbitrary_text(self, world, llm, gsc_api):
        connect_gsc(world)
        # (A bare name of a VERIFIED site, e.g. "example.com", is resolved to that property: see
        # TestModelSpellingOfParameters. Text that names no verified property is still refused.)
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "sc-domain:", "unknown-site.org", "http://x y/"):
            llm.args = {"site_url": bad}
            assert ask(world).json()["plan_status"] == "failed", bad
        assert not gsc_api.queries

    def test_future_and_oversized_ranges_rejected_before_calling_google(self, world, llm, gsc_api):
        connect_gsc(world)
        future = (datetime.utcnow().date() + timedelta(days=5)).isoformat()
        for args in ({"end_date": future}, {"start_date": "2020-01-01", "end_date": "2024-01-01"},
                     {"start_date": "2026-10-10", "end_date": "2026-10-01"}):
            llm.args = args
            assert ask(world).json()["plan_status"] == "failed", args
        assert not gsc_api.queries


# ═════════════════════════════════════════════════════════════════════════════
class TestPermissionsAndTenancy:
    def test_not_granted_to_the_role_never_calls_google(self, world, llm, gsc_api):
        connect_gsc(world, grants=())
        body = ask(world).json()
        assert body["plan_status"] == "awaiting_setup" and body["pending_task_id"]
        assert not gsc_api.log

    def test_grant_for_another_role_does_not_help(self, world, llm, gsc_api):
        connect_gsc(world, role="FINANCIAL_ANALYST")
        assert ask(world).json()["plan_status"] == "awaiting_setup"
        assert not gsc_api.log

    def test_a_different_capability_grant_does_not_help(self, world, llm, gsc_api):
        connect_gsc(world, grants=("list_sites",))
        assert ask(world).json()["plan_status"] == "awaiting_setup"
        assert not gsc_api.queries

    def test_disabled_or_failed_integration_is_not_used(self, world, llm, gsc_api):
        connect_gsc(world, enabled=False)
        connect_gsc(world, status="failed")
        assert ask(world).json()["plan_status"] == "awaiting_setup"
        assert not gsc_api.log

    def test_revoked_grant_stops_a_working_flow(self, world, llm, gsc_api):
        iid = connect_gsc(world)
        assert ask(world).json()["plan_status"] == "completed"

        async def revoke():
            async with world.maker() as s:
                for g in (await s.execute(select(CapabilityGrant).where(CapabilityGrant.integration_id == iid))).scalars():
                    g.is_granted = False
                await s.commit()
        run(revoke())
        gsc_api.log.clear()
        assert ask(world).json()["plan_status"] == "awaiting_setup"
        assert not gsc_api.log

    def test_other_tenants_connection_and_selected_site_are_never_used(self, world, llm, gsc_api):
        connect_gsc(world, tenant=world.tenant_b, default_property="https://b-secret.example.com/")
        body = ask(world).json()                              # asked by tenant A
        assert body["plan_status"] == "awaiting_setup"
        assert not gsc_api.log and not gsc_api.queries
        t = tasks(world, "a_admin")[0]
        assert t["blocking_state"] in ("needs_configuration", "needs_authorization")
        assert "integration_id" not in t["action_data"]
        assert "b-secret" not in json.dumps(t) + json.dumps(body)

    def test_tool_layer_refuses_a_foreign_integration_id(self, world, gsc_api):
        iid = connect_gsc(world)

        async def go():
            async with world.maker() as s:
                with pytest.raises(LookupError):
                    await mgr.execute_capability(iid, "get_search_analytics", {}, DMM, world.tenant_b, s)
        run(go())
        assert not gsc_api.log

    def test_read_only_capabilities_only(self):
        from app.integrations.integration_registry import integration_registry
        from app.integrations.provider import CapabilityCategory, RiskLevel
        p = integration_registry.get("google_search_console")
        assert p.property_parameter == "site_url"
        for cap in p.get_capabilities():
            assert cap.risk_level == RiskLevel.LOW
            assert cap.category in (CapabilityCategory.READ, CapabilityCategory.ANALYTICS)

    def test_one_click_approval_covers_search_console_read_only(self):
        from app.services.task_readiness import GSC_SEO, grantable
        assert grantable(GSC_SEO)[0]


# ═════════════════════════════════════════════════════════════════════════════
class TestDetection:
    @pytest.mark.parametrize("prompt", [
        "Show me our top queries in Search Console",
        "What is our average position for 'running shoes'?",
        "Which pages get the most organic clicks from Google search?",
        "How many search impressions did we get last month?",
        "What are our top search queries?",
        "Give me GSC data for last week",
    ])
    def test_seo_requests_are_gated(self, world, llm, gsc_api, prompt):
        assert ask(world, prompt=prompt).json()["plan_status"] == "awaiting_setup"

    @pytest.mark.parametrize("prompt", [
        "How many impressions did our Facebook ad get?",
        "What's the click-through rate on our email campaign?",
        "Write a friendly welcome message for new subscribers",
    ])
    def test_non_seo_requests_are_not_gated_by_search_console(self, world, llm, gsc_api, prompt):
        t = ask(world, prompt=prompt).json()
        assert t["plan_status"] != "awaiting_setup", t

    def test_google_analytics_requests_still_route_to_analytics(self, world, llm, gsc_api):
        ask(world, prompt="How many sessions did the site get last week?")
        assert tasks(world, "a_employee")[0]["action_data"]["provider_type"] == "google_analytics"

    def test_only_the_marketing_role_is_gated(self, world, llm, gsc_api):
        from app.services.task_readiness import detect_requirements

        async def go():
            async with world.maker() as s:
                return await detect_requirements(PROMPT, world.tenant_a, "FINANCIAL_ANALYST", s)
        assert run(go()) == []


# ═════════════════════════════════════════════════════════════════════════════
class TestAdminAssistedSetupThenResume:
    def test_full_journey_with_two_properties(self, world, llm, gsc_api, google_oauth):
        from urllib.parse import parse_qs, urlparse
        c, emp, adm = world.client, "a_employee", "a_admin"
        gsc_api.sites = TWO_SITES

        # 1. Employee asks with nothing configured -> saved, truthful, nothing called.
        b = ask(world, emp).json()
        tid = b["pending_task_id"]
        assert b["plan_status"] == "awaiting_setup" and "ADMIN_REQUIRED" in b["sources"][0]
        assert not gsc_api.log

        # 2. Admin: secure config form -> stored client -> Google authorisation.
        assert "CONFIGURATION_REQUIRED" in ask(world, adm).json()["sources"][0]
        r = c.post("/api/v1/admin/provider-config/google_search_console", headers=world.auth(adm), json={"fields": {
            "client_id": GOOD_CLIENT_ID, "client_secret": STORED_SECRET,
            "redirect_uri": "http://testserver/api/v1/oauth/google/callback"}})
        assert r.status_code == 200 and STORED_SECRET not in r.text
        assert {t["id"]: t["next_action"] for t in tasks(world, adm)}[tid] == "REDIRECT_TO_OAUTH"
        url = c.get("/api/v1/oauth/google/authorize", headers=world.auth(adm)).json()["authorization_url"]
        assert parse_qs(urlparse(url).query)["client_id"] == [GOOD_CLIENT_ID]
        state = parse_qs(urlparse(url).query)["state"][0]
        cb = c.get(f"/api/v1/oauth/google/callback?code=4/FAKE&state={state}", follow_redirects=False)
        assert cb.status_code == 302 and "success=true" in cb.headers["location"], cb.headers.get("location")

        # 3. Connected; role still has no permission -> explicit read-only approval.
        t = {x["id"]: x for x in tasks(world, adm)}[tid]
        assert t["next_action"] == "GRANT_REQUIRED"
        assert c.post(f"/api/v1/agent/pending-tasks/{tid}/authorize", headers=world.auth(emp)).status_code == 403
        assert c.post(f"/api/v1/agent/pending-tasks/{tid}/authorize", headers=world.auth(adm)).status_code == 200

        # 4. Two verified sites -> admin must choose. Unverified site is not offered.
        t = {x["id"]: x for x in tasks(world, adm)}[tid]
        assert t["next_action"] == "SELECT_PROPERTY" and t["blocking_state"] == "needs_property"
        offered = {p["id"] for p in t["action_data"]["properties"]}
        assert offered == {SITE, SITE_2}
        early = c.post(f"/api/v1/agent/pending-tasks/{tid}/resume", headers=world.auth(emp))
        assert early.status_code == 409 and early.json()["detail"]["next_action"] == "ADMIN_REQUIRED"
        sel = f"/api/v1/agent/pending-tasks/{tid}/select-property"
        assert c.post(sel, headers=world.auth(emp), json={"property_id": SITE_2}).status_code == 403
        for forged in ("https://not-mine.example.org/", "https://evil.example.net/", ""):
            assert c.post(sel, headers=world.auth(adm), json={"property_id": forged}).status_code == 422, forged
        assert not gsc_api.queries
        ok = c.post(sel, headers=world.auth(adm), json={"property_id": SITE_2})
        assert ok.status_code == 200 and ok.json()["ready"] is True

        # 5. The employee resumes the ORIGINAL request: real call, chosen site, real numbers.
        res = c.post(f"/api/v1/agent/pending-tasks/{tid}/resume", headers=world.auth(emp))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["plan_status"] == "completed" and "320" in body["message"]
        assert gsc_api.queries[0][0] == SITE_2
        assert any(PROMPT in m[1] for m in llm.log)

        # 6. Closed; no longer listed; cannot be run twice.
        assert c.post(f"/api/v1/agent/pending-tasks/{tid}/resume", headers=world.auth(emp)).status_code == 409
        assert tasks(world, emp) == []

        # 7. The choice survives a connection re-test.
        iid = run(_only_integration(world))
        assert c.post(f"/api/v1/integration-manager/integrations/{iid}/test", headers=world.auth(adm)).status_code == 200
        assert stored_info(world, iid)["default_property"] == SITE_2

    def test_select_property_is_tenant_scoped(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.sites = TWO_SITES
        tid = ask(world).json()["pending_task_id"]
        r = world.client.post(f"/api/v1/agent/pending-tasks/{tid}/select-property",
                              headers=world.auth("b_admin"), json={"property_id": SITE})
        assert r.status_code == 404

    def test_select_property_when_none_needed_is_refused(self, world, llm, gsc_api):
        connect_gsc(world, grants=())
        tid = ask(world).json()["pending_task_id"]
        r = world.client.post(f"/api/v1/agent/pending-tasks/{tid}/select-property",
                              headers=world.auth("a_admin"), json={"property_id": SITE})
        assert r.status_code == 409

    def test_property_choice_is_audited(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.sites = TWO_SITES
        tid = ask(world).json()["pending_task_id"]
        assert world.client.post(f"/api/v1/agent/pending-tasks/{tid}/select-property",
                                 headers=world.auth("a_admin"), json={"property_id": SITE}).status_code == 200

        async def go():
            from app.db.models import AuditLog
            async with world.maker() as s:
                return [a.event for a in (await s.execute(select(AuditLog))).scalars()]
        assert any("selected google_search_console property" in e for e in run(go()))


async def _only_integration(world):
    async with world.maker() as s:
        return (await s.execute(select(Integration.id).where(Integration.provider_type == "google_search_console"))).scalar_one()


# ═════════════════════════════════════════════════════════════════════════════
class TestProviderUnit:
    def _p(self):
        from app.integrations.providers.google_search_console_provider import GoogleSearchConsoleProvider
        return GoogleSearchConsoleProvider()

    def test_site_url_validation(self):
        from app.integrations.providers.google_search_console_provider import GSCApiError
        v = self._p()._validate_site_url
        assert v("sc-domain:example.com") == "sc-domain:example.com"
        assert v(" https://www.example.com/ ") == "https://www.example.com/"
        for bad in ("", "example.com", "ftp://x.com/", "javascript:x", "sc-domain:", "https://a b/"):
            with pytest.raises(GSCApiError):
                v(bad)

    def test_list_properties_excludes_unverified(self, gsc_api):
        gsc_api.sites = TWO_SITES
        props = run(self._p().list_properties(_creds()))
        assert [p["id"] for p in props] == [SITE, SITE_2]

    def test_google_client_is_built_off_the_event_loop(self, gsc_api):
        run(self._p().list_properties(_creds()))
        assert gsc_api.threads and all(t is not threading.main_thread() for t in gsc_api.threads)

    def test_timezone_aware_expiry_does_not_crash(self):
        p = self._p()
        soon = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        assert run(p._should_refresh_token({"token_expiry": soon})) is True
        assert run(p._should_refresh_token({"token_expiry": later})) is False
        assert run(p._should_refresh_token({"token_expiry": later.replace("+00:00", "Z")})) is False

    def test_errors_never_contain_tokens(self, gsc_api):
        gsc_api.rows = http_error(403, f"denied token={ACCESS} secret={CLIENT_SECRET}")
        res = run(self._p().execute("get_search_analytics", _creds(), {"site_url": SITE}))
        assert res.error and ACCESS not in res.error and CLIENT_SECRET not in res.error

    def test_site_metadata_uses_default_resolution(self, gsc_api):
        res = run(self._p().execute("get_site_metadata", _creds(), {}))
        assert res.success and gsc_api.site_gets == [SITE]

    def test_named_columns_and_raw_dimensions_both_present(self, gsc_api):
        res = run(self._p().execute("get_search_analytics", _creds(),
                                    {"site_url": SITE, "dimensions": ["query", "device"]}))
        gsc_api.rows = ROWS
        res = run(self._p().execute("get_search_analytics", _creds(), {"site_url": SITE, "dimensions": ["query"]}))
        row = res.data[0]
        assert row["query"] == "running shoes" and row["dimensions"] == ["running shoes"] and row["clicks"] == 320


# ═════════════════════════════════════════════════════════════════════════════
class TestSiteNamedInTheRequest:
    """Seen live: "…for gecservices.in" was still answered with "choose which property" when two sites exist."""

    def test_a_site_named_in_the_message_is_used_without_a_default(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.sites = TWO_SITES
        b = ask(world, prompt="What were the top search queries for blog.example.com in the last 28 days? "
                              "Show clicks, impressions, CTR and average position.").json()
        assert b["plan_status"] == "completed", b
        assert gsc_api.queries and gsc_api.queries[0][0] == SITE_2

    def test_the_domain_property_wins_over_a_url_property_of_the_same_site(self):
        from app.services.task_readiness import property_named_in
        props = [{"id": "https://gecservices.in/"}, {"id": "sc-domain:gecservices.in"}, {"id": "https://other.in/"}]
        assert property_named_in("CTR for https://www.gecservices.in/contact", props) == "sc-domain:gecservices.in"
        assert property_named_in("CTR for other.in please", props) == "https://other.in/"
        assert property_named_in("What is my CTR", props) is None

    def test_without_a_named_site_the_reply_lists_the_sites(self, world, llm, gsc_api):
        connect_gsc(world)
        gsc_api.sites = TWO_SITES
        b = ask(world, who="a_admin").json()
        assert b["plan_status"] == "awaiting_setup"
        assert "blog.example.com" in b["message"] and "Say which one in your message" in b["message"]


class TestModelSpellingOfParameters:
    """Seen live: "Unknown parameter(s): ['endDate', 'rowLimit', 'siteUrl', 'startDate']"."""

    def test_provider_api_spelling_is_accepted(self):
        from app.tools.dynamic_tool import validate_tool_arguments
        schema = {"properties": {"site_url": {}, "start_date": {}, "end_date": {}, "row_limit": {}, "dimensions": {}}}
        ok, err, args = validate_tool_arguments(
            {"siteUrl": "sc-domain:example.com", "startDate": "90daysAgo", "endDate": "3daysAgo", "rowLimit": 10,
             "dimensions": ["query"]}, "get_search_analytics", schema)
        assert ok, err
        assert args == {"site_url": "sc-domain:example.com", "start_date": "90daysAgo", "end_date": "3daysAgo",
                        "row_limit": 10, "dimensions": ["query"]}
        ok, err, _ = validate_tool_arguments({"siteId": "x"}, "get_search_analytics", schema)
        assert not ok and "Unknown parameter" in err                      # still strict for real unknowns

    @pytest.mark.parametrize("given,expected", [("example.com", SITE), ("https://www.example.com", SITE),
                                                ("https://blog.example.com", SITE_2), (SITE_2, SITE_2)])
    def test_a_site_name_resolves_to_the_verified_property(self, world, llm, gsc_api, given, expected):
        connect_gsc(world, default_property=SITE)
        gsc_api.sites = TWO_SITES
        llm.args = {"site_url": given}
        assert ask(world).json()["plan_status"] == "completed"
        assert gsc_api.queries[0][0] == expected
