"""
Digital Marketing Manager -> Google Analytics 4, request to answer.

What is REAL here: the FastAPI app, auth, the execution router, the planner,
the tool engine, dynamic tool adapters, capability grants, the Integration
Manager, credential encryption, the GA4 provider code, and the SQLite schema.

What is FAKED (only at the two network boundaries):
  * the LLM (``ScriptedChatModel``) - deterministic, it plans and then echoes
    the data it was given, so a wrong/ungrounded answer cannot come from it;
  * Google's APIs (``googleapiclient.discovery.build`` and token refresh).

Nothing in this file proves the integration works against live Google.  It
proves our code sends the right requests, enforces permissions, and reports
only what the (fake) API returned.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.integration_models import (
    CapabilityGrant,
    DynamicToolAuditLog,
    Integration,
)
from app.integrations import manager as mgr
from app.schemas.integration_framework import CapabilityGrantCreate, IntegrationCreate

DMM = "DIGITAL_MARKETING_MANAGER"
ACCESS = "ya29.FAKE-ga-access-0001"
REFRESH = "1//FAKE-ga-refresh-0001"
CLIENT_SECRET = "FAKE-ga-client-secret"
PROMPT = "How did our website traffic do over the last 7 days, and which channels drove the most sessions?"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── fake LLM ──────────────────────────────────────────────────────────────────
class ScriptedChatModel:
    """Plans a GA4 report, then restates only what the tool returned."""

    def __init__(self, log: list, plan=None, synth=None):
        self.log = log
        self.plan = plan
        self.synth = synth

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, *a, **k):
        system = str(messages[0].content)
        human = str(messages[-1].content)
        self.log.append((system[:60], human))
        if "planning assistant" in system:
            m = re.search(r"(integration_[0-9a-f]{8}_run_report)", human)
            tool = m.group(1) if m else None
            steps = []
            if self.plan is not None:
                return AIMessage(content=json.dumps(self.plan(tool)))
            if tool:
                steps.append({
                    "step_index": 0, "step_type": "read",
                    "description": "Pull sessions by channel for the last 7 days from Google Analytics",
                    "tool_name": tool,
                    "arguments": {
                        "start_date": "7daysAgo", "end_date": "yesterday",
                        "metrics": ["sessions", "activeUsers"],
                        "dimensions": ["sessionMedium"],
                    },
                    "depends_on": [],
                })
            steps.append({
                "step_index": len(steps), "step_type": "response",
                "description": "Report the result", "tool_name": None, "arguments": {},
                "depends_on": [len(steps) - 1] if steps else [],
            })
            return AIMessage(content=json.dumps({"objective": "Website traffic last 7 days", "steps": steps}))
        if "Information gathered" in human:
            gathered = human.split("Information gathered:\n", 1)[1].split("\n\nUsing the information", 1)[0]
            if self.synth is not None:
                return AIMessage(content=self.synth(gathered))
            return AIMessage(content="Here is what Google Analytics returned:\n" + gathered)
        # intent parsing and anything else -> not an integration request
        return AIMessage(content='{"intent_type": "UNKNOWN", "confidence": 0.0, "reasoning": "n/a"}')


@pytest.fixture()
def llm(monkeypatch):
    log: list = []
    holder = SimpleNamespace(log=log, plan=None, synth=None)
    from app.llm.gateway import LLMGateway

    def _model(self, *a, **k):
        return ScriptedChatModel(log, holder.plan, holder.synth)

    monkeypatch.setattr(LLMGateway, "get_chat_model", _model)
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", _model)
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return holder


# ── fake Google API boundary ──────────────────────────────────────────────────
class _Req:
    def __init__(self, calls, kind, payload):
        self.calls, self.kind, self.payload = calls, kind, payload

    def execute(self):
        self.calls.append(self.kind)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


REPORT = {
    "dimensionHeaders": [{"name": "sessionMedium"}],
    "metricHeaders": [{"name": "sessions"}, {"name": "activeUsers"}],
    "rows": [
        {"dimensionValues": [{"value": "organic"}], "metricValues": [{"value": "1842"}, {"value": "1310"}]},
        {"dimensionValues": [{"value": "cpc"}], "metricValues": [{"value": "977"}, {"value": "801"}]},
        {"dimensionValues": [{"value": "email"}], "metricValues": [{"value": "406"}, {"value": "355"}]},
    ],
}
SUMMARIES = {
    "accountSummaries": [{
        "account": "accounts/1", "displayName": "Acme",
        "propertySummaries": [{"property": "properties/424242", "displayName": "Acme Web"}],
    }]
}


@pytest.fixture()
def ga_api(monkeypatch):
    calls = SimpleNamespace(log=[], reports=[], summaries=SUMMARIES, report=REPORT)

    def build(api, version, **kw):
        if api == "analyticsdata":
            def run_report(property, body):
                calls.reports.append((property, body))
                return _Req(calls.log, "runReport", calls.report)
            return SimpleNamespace(properties=lambda: SimpleNamespace(runReport=run_report))
        if api == "analyticsadmin":
            return SimpleNamespace(
                accountSummaries=lambda: SimpleNamespace(list=lambda **k: _Req(calls.log, "accountSummaries", calls.summaries)),
                accounts=lambda: SimpleNamespace(list=lambda **k: _Req(calls.log, "accounts", {"accounts": []})),
            )
        raise AssertionError(api)

    import googleapiclient.discovery as discovery
    monkeypatch.setattr(discovery, "build", build)
    return calls


def _creds(expiry_minutes=60):
    return {
        "access_token": ACCESS, "refresh_token": REFRESH, "client_id": "fake.apps.example.test",
        "client_secret": CLIENT_SECRET,
        "token_expiry": (datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)).isoformat(),
    }


def connect_ga(world, tenant=None, grants=("run_report",), role=DMM, status="connected", enabled=True):
    tenant = tenant or world.tenant_a

    async def go():
        async with world.maker() as s:
            out = await mgr.create_integration(
                IntegrationCreate(provider_type="google_analytics", display_name="Google Analytics",
                                  credentials=_creds(), created_by="test"),
                tenant, s)
            row = (await s.execute(select(Integration).where(Integration.id == out.id))).scalar_one()
            row.status, row.is_enabled = status, enabled
            for cap in grants:
                await mgr.create_capability_grant(
                    out.id, CapabilityGrantCreate(role_key=role, capability_key=cap, is_granted=True, granted_by="test"),
                    tenant, s)
            await s.commit()
            return out.id
    return run(go())


def stored_secrets_are_encrypted(world, integration_id):
    async def go():
        async with world.maker() as s:
            return (await s.execute(select(Integration.encrypted_credentials).where(Integration.id == integration_id))).scalar_one()
    blob = run(go())
    assert ACCESS not in blob and REFRESH not in blob and CLIENT_SECRET not in blob


def blueprint(tenant):
    return {
        "agent_id": "dmm-1", "role_name": "Digital Marketing Manager", "system_persona": "You are the DMM.",
        "allowed_tools": ["create_internal_task", "draft_email"], "guarded_tools": ["send_email"],
        "tenant_id": tenant,
    }


def ask(world, who="a_employee", prompt=PROMPT):
    return world.client.post(
        "/api/v1/agent/execute", headers=world.auth(who),
        json={"blueprint": blueprint(world.users[who]["tenant_id"]), "user_prompt": prompt})



def plan_for(tool_args, tool_suffix="run_report"):
    def build(_tool):
        m = _tool
        return {"objective": "Website traffic", "steps": [
            {"step_index": 0, "step_type": "read", "description": "Pull the GA report", "tool_name": m,
             "arguments": tool_args, "depends_on": []},
            {"step_index": 1, "step_type": "response", "description": "Report", "tool_name": None,
             "arguments": {}, "depends_on": [0]}]}
    return build


def plan_row(world, plan_id):
    from app.db.models import ExecutionPlan, PlanStep

    async def go():
        async with world.maker() as s:
            steps = (await s.execute(select(PlanStep).where(PlanStep.plan_id == plan_id).order_by(PlanStep.step_index))).scalars().all()
            return [(x.status, x.result_summary or "") for x in steps]
    return run(go())


def audit_rows(world):
    async def go():
        async with world.maker() as s:
            return (await s.execute(select(DynamicToolAuditLog))).scalars().all()
    return run(go())


class TestHappyPath:
    def test_traffic_question_returns_real_ga_numbers(self, world, llm, ga_api):
        iid = connect_ga(world)
        r = ask(world)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan_status"] == "completed", body
        msg = body["message"]
        for n in ("1842", "977", "406", "3,225"):          # rows and the computed total
            assert n in msg, msg
        assert "57.1%" in msg                               # organic share, computed in code
        assert msg.rstrip().splitlines()[-1].startswith("Data source: Google Analytics 4 property 424242")
        stored_secrets_are_encrypted(world, iid)

    def test_relative_dates_become_real_dates_and_property_is_discovered(self, world, llm, ga_api):
        connect_ga(world)
        assert ask(world).status_code == 200
        prop, req = ga_api.reports[0]
        assert prop == "properties/424242"
        today = datetime.utcnow().date()
        dr = req["dateRanges"][0]
        assert dr["startDate"] == (today - timedelta(days=7)).isoformat()
        assert dr["endDate"] == (today - timedelta(days=1)).isoformat()
        assert [m["name"] for m in req["metrics"]] == ["sessions", "activeUsers"]
        assert [d["name"] for d in req["dimensions"]] == ["sessionMedium"]
        assert "accountSummaries" in ga_api.log     # discovery used the unfiltered summaries call

    def test_single_argument_plans_reach_the_tool_as_json(self, world, llm, ga_api):
        connect_ga(world)
        llm.plan = plan_for({"property_id": "424242"})
        body = ask(world).json()
        assert body["plan_status"] == "completed", body
        assert ga_api.reports and ga_api.reports[0][0] == "properties/424242"

    def test_every_call_is_audited_without_data_or_credentials(self, world, llm, ga_api):
        connect_ga(world)
        assert ask(world).status_code == 200
        rows = audit_rows(world)
        assert len(rows) == 1 and rows[0].success is True and rows[0].row_count == 3
        assert rows[0].role_key == DMM and rows[0].tenant_id == world.tenant_a
        blob = json.dumps([r.error_message or "" for r in rows])
        assert ACCESS not in blob and CLIENT_SECRET not in blob

    def test_credentials_never_reach_the_model_or_the_response(self, world, llm, ga_api):
        connect_ga(world)
        r = ask(world)
        everything = r.text + json.dumps(llm.log)
        for secret in (ACCESS, REFRESH, CLIENT_SECRET):
            assert secret not in everything


class TestTruthfulWhenThingsGoWrong:
    def _http_error(self, status, text):
        from googleapiclient.errors import HttpError
        return HttpError(SimpleNamespace(status=status, reason=text), text.encode())

    def test_google_denies_access_no_numbers_are_invented(self, world, llm, ga_api):
        connect_ga(world)
        ga_api.report = self._http_error(403, "The caller does not have permission")
        body = ask(world).json()
        assert body["plan_status"] == "failed"
        assert "403" in body["message"] and "No figures were produced" in body["message"]
        assert not re.search(r"\d{3,}", body["message"].replace("403", ""))

    def test_expired_authorisation_tells_the_user_to_reconnect(self, world, llm, ga_api):
        connect_ga(world)
        ga_api.report = self._http_error(401, "invalid credentials")
        body = ask(world).json()
        assert body["plan_status"] == "failed" and "Reconnect" in body["message"]

    def test_api_not_enabled_is_explained(self, world, llm, ga_api):
        connect_ga(world)
        ga_api.report = self._http_error(403, "Google Analytics Data API has not been used in project 1 before or it is disabled")
        assert "not enabled" in ask(world).json()["message"]

    def test_empty_report_says_so(self, world, llm, ga_api):
        connect_ga(world)
        ga_api.report = {"dimensionHeaders": [{"name": "sessionMedium"}], "metricHeaders": [{"name": "sessions"}], "rows": []}
        body = ask(world).json()
        assert body["plan_status"] == "completed"
        assert "Rows: 0" in body["message"]

    def test_model_inventing_a_figure_is_caught_and_data_shown_instead(self, world, llm, ga_api):
        connect_ga(world)
        llm.synth = lambda gathered: "Great news: sessions grew 38% to 12,345 last week."
        body = ask(world).json()
        assert "12,345" not in body["message"] and "38%" not in body["message"]
        assert "couldn’t verify my own summary" in body["message"]
        assert "1842" in body["message"]
        steps = plan_row(world, body["plan_id"])
        assert "Grounding: replaced" in steps[-1][1]

    def test_faithful_summary_with_rounding_is_allowed(self, world, llm, ga_api):
        connect_ga(world)
        llm.synth = lambda g: "Organic search led with 1,842 sessions, about 57% of the 3,225 total."
        body = ask(world).json()
        assert "couldn’t verify" not in body["message"] and "about 57%" in body["message"]

    def test_several_properties_the_ai_asks_instead_of_guessing(self, world, llm, ga_api):
        connect_ga(world)
        ga_api.summaries = {"accountSummaries": [{"account": "accounts/1", "displayName": "Acme", "propertySummaries": [
            {"property": "properties/1", "displayName": "Shop"}, {"property": "properties/2", "displayName": "Blog"}]}]}
        body = ask(world).json()
        assert body["plan_status"] == "failed"
        assert "Shop (1)" in body["message"] and "Blog (2)" in body["message"]
        assert not ga_api.reports

    def test_bad_property_id_cannot_be_used_to_reach_other_api_paths(self, world, llm, ga_api):
        connect_ga(world)
        llm.plan = plan_for({"property_id": "1/../../x", "start_date": "7daysAgo", "end_date": "yesterday"})
        body = ask(world).json()
        assert body["plan_status"] == "failed" and not ga_api.reports


class TestAuthorizationAndTenancy:
    def test_connected_but_not_granted_to_the_role_never_calls_google(self, world, llm, ga_api):
        connect_ga(world, grants=())
        body = ask(world).json()
        assert body["plan_status"] == "awaiting_setup" and body["pending_task_id"]
        assert not ga_api.log
        assert "GRANT_REQUIRED" not in body["message"]

    def test_grant_for_a_different_role_does_not_help(self, world, llm, ga_api):
        connect_ga(world, role="FINANCIAL_ANALYST")
        assert ask(world).json()["plan_status"] == "awaiting_setup"
        assert not ga_api.log

    def test_other_tenants_integration_is_never_used(self, world, llm, ga_api):
        connect_ga(world, tenant=world.tenant_b)
        body = ask(world).json()                      # asked by tenant A
        assert body["plan_status"] == "awaiting_setup"
        assert not ga_api.log and not ga_api.reports
        # A must be told to set GA up from scratch - it must not "see" B's connection.
        task = world.client.get("/api/v1/agent/pending-tasks", headers=world.auth("a_admin")).json()[0]
        assert task["blocking_state"] in ("needs_configuration", "needs_authorization"), task
        assert "integration_id" not in task["action_data"]

    def test_disabled_integration_is_not_used(self, world, llm, ga_api):
        connect_ga(world, enabled=False)
        assert ask(world).json()["plan_status"] == "awaiting_setup"
        assert not ga_api.log

    def test_disconnected_integration_is_not_used(self, world, llm, ga_api):
        connect_ga(world, status="failed")
        assert ask(world).json()["plan_status"] == "awaiting_setup"

    def test_a_revoked_grant_stops_a_previously_working_flow(self, world, llm, ga_api):
        iid = connect_ga(world)
        assert ask(world).json()["plan_status"] == "completed"

        async def revoke():
            async with world.maker() as s:
                for g in (await s.execute(select(CapabilityGrant).where(CapabilityGrant.integration_id == iid))).scalars():
                    g.is_granted = False
                await s.commit()
        run(revoke())
        ga_api.log.clear()
        assert ask(world).json()["plan_status"] == "awaiting_setup"
        assert not ga_api.log

    def test_unrelated_questions_are_not_gated(self, world, llm, ga_api):
        body = ask(world, prompt="Write a friendly welcome message for new subscribers").json()
        assert body["plan_status"] != "awaiting_setup"


GOOD_CLIENT_ID = "1234567890-abcdefghijk.apps.googleusercontent.com"
STORED_SECRET = "GOCSPX-FAKE-tenant-stored-secret"


@pytest.fixture()
def google_oauth(monkeypatch, ga_api):
    """Env has NO Google config: everything must come from the tenant's stored settings."""
    from app.config import settings
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    monkeypatch.setattr(settings, "google_redirect_uri", "")
    import google_auth_oauthlib.flow as flow_mod
    import google.oauth2.credentials as gcreds
    seen = SimpleNamespace(client_ids=[], secrets=[])

    def fake_fetch(self, **kw):
        seen.client_ids.append(self.client_config["client_id"])
        seen.secrets.append(self.client_config["client_secret"])
        self.oauth2session.token = {"access_token": ACCESS, "refresh_token": REFRESH, "token_type": "Bearer",
                                    "expires_at": datetime.now().timestamp() + 3600,
                                    "scope": ["https://www.googleapis.com/auth/analytics.readonly"]}
    monkeypatch.setattr(flow_mod.Flow, "fetch_token", fake_fetch)
    return seen


class TestAdminAssistedSetupThenResume:
    def test_full_journey_from_nothing_to_a_real_answer(self, world, llm, ga_api, google_oauth):
        from urllib.parse import parse_qs, urlparse
        c, emp, adm = world.client, "a_employee", "a_admin"

        # 1. An employee asks while nothing is configured.
        b = ask(world, emp).json()
        assert b["plan_status"] == "awaiting_setup" and b["pending_task_id"]
        assert "administrator" in b["message"] and "GOCSPX" not in b["message"]
        tid = b["pending_task_id"]
        assert "ADMIN_REQUIRED" in b["sources"][0]
        assert not ga_api.log

        # 2. The same request from the admin offers the secure config form.
        b2 = ask(world, adm).json()
        assert "CONFIGURATION_REQUIRED" in b2["sources"][0]
        assert "client_id" in b2["sources"][0] and "client_secret" in b2["sources"][0]

        # 3. Admin submits the Google OAuth app settings (stored encrypted, never echoed).
        r = c.post("/api/v1/admin/provider-config/google_analytics", headers=world.auth(adm), json={"fields": {
            "client_id": GOOD_CLIENT_ID, "client_secret": STORED_SECRET,
            "redirect_uri": "http://testserver/api/v1/oauth/google/callback"}})
        assert r.status_code == 200, r.text
        assert STORED_SECRET not in r.text

        # 4. The waiting request now needs Google authorisation (admin sees the OAuth step).
        mine = c.get("/api/v1/agent/pending-tasks", headers=world.auth(adm)).json()
        assert {t["id"]: t["next_action"] for t in mine}[tid] == "REDIRECT_TO_OAUTH"

        # 5. Admin authorises with Google - and the tenant's stored client is what is used.
        auth = c.get("/api/v1/oauth/google/analytics/authorize", headers=world.auth(adm))
        assert auth.status_code == 200, auth.text
        url = auth.json()["authorization_url"]
        assert parse_qs(urlparse(url).query)["client_id"] == [GOOD_CLIENT_ID]
        state = parse_qs(urlparse(url).query)["state"][0]
        cb = c.get(f"/api/v1/oauth/google/callback?code=4/FAKE&state={state}", follow_redirects=False)
        assert cb.status_code == 302 and "success=true" in cb.headers["location"], cb.headers.get("location")
        assert google_oauth.client_ids == [GOOD_CLIENT_ID] and google_oauth.secrets == [STORED_SECRET]

        # 6. Connected, but the AI employee still has no permission: explicit admin approval.
        t = {x["id"]: x for x in c.get("/api/v1/agent/pending-tasks", headers=world.auth(adm)).json()}[tid]
        assert t["next_action"] == "GRANT_REQUIRED" and not t["ready"]
        # the employee cannot approve their own access
        assert c.post(f"/api/v1/agent/pending-tasks/{tid}/authorize", headers=world.auth(emp)).status_code == 403
        # resuming before approval is refused, with the next step
        early = c.post(f"/api/v1/agent/pending-tasks/{tid}/resume", headers=world.auth(emp))
        assert early.status_code == 409 and early.json()["detail"]["next_action"] == "ADMIN_REQUIRED"
        ok = c.post(f"/api/v1/agent/pending-tasks/{tid}/authorize", headers=world.auth(adm))
        assert ok.status_code == 200 and ok.json()["ready"] is True

        # 7. The employee resumes the ORIGINAL request - real tool call, real numbers.
        res = c.post(f"/api/v1/agent/pending-tasks/{tid}/resume", headers=world.auth(emp))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["plan_status"] == "completed" and "1842" in body["message"]
        assert ga_api.reports and ga_api.reports[0][0] == "properties/424242"
        assert any(m for m in llm.log if PROMPT in m[1])      # the saved text, not a paraphrase

        # 8. Closed: it cannot be run twice, and is no longer listed.
        assert c.post(f"/api/v1/agent/pending-tasks/{tid}/resume", headers=world.auth(emp)).status_code == 409
        assert c.get("/api/v1/agent/pending-tasks", headers=world.auth(emp)).json() == []

        # 9. Stored secrets are encrypted at rest.
        async def stored():
            async with world.maker() as s:
                from app.db.provider_config_models import ProviderServerConfig
                rows = (await s.execute(select(ProviderServerConfig.encrypted_value))).scalars().all()
                creds = (await s.execute(select(Integration.encrypted_credentials))).scalars().all()
                return rows + creds
        blob = " ".join(run(stored()))
        assert STORED_SECRET not in blob and ACCESS not in blob and REFRESH not in blob

    def test_asking_twice_keeps_one_waiting_request(self, world, llm, ga_api):
        a = ask(world).json()["pending_task_id"]
        b = ask(world).json()["pending_task_id"]
        assert a == b
        assert len(world.client.get("/api/v1/agent/pending-tasks", headers=world.auth("a_employee")).json()) == 1

    def test_pending_tasks_are_private_to_owner_and_tenant(self, world, llm, ga_api):
        tid = ask(world, "a_employee").json()["pending_task_id"]
        c = world.client
        # another tenant's admin cannot see, resume, cancel or authorise it
        assert c.get("/api/v1/agent/pending-tasks", headers=world.auth("b_admin")).json() == []
        for verb in ("resume", "cancel", "authorize"):
            assert c.post(f"/api/v1/agent/pending-tasks/{tid}/{verb}", headers=world.auth("b_admin")).status_code == 404
        # a different employee of the same tenant cannot either
        # (a_admin sees it - admins manage the company's requests)
        assert [t["id"] for t in c.get("/api/v1/agent/pending-tasks", headers=world.auth("a_admin")).json()] == [tid]
        assert c.post(f"/api/v1/agent/pending-tasks/{tid}/cancel", headers=world.auth("b_employee")).status_code == 404
        # unauthenticated
        assert c.get("/api/v1/agent/pending-tasks").status_code == 401

    def test_cancel(self, world, llm, ga_api):
        tid = ask(world).json()["pending_task_id"]
        assert world.client.post(f"/api/v1/agent/pending-tasks/{tid}/cancel", headers=world.auth("a_employee")).json()["status"] == "cancelled"
        assert world.client.get("/api/v1/agent/pending-tasks", headers=world.auth("a_employee")).json() == []
        assert world.client.post(f"/api/v1/agent/pending-tasks/{tid}/resume", headers=world.auth("a_employee")).status_code == 409

    def test_one_click_approval_is_limited_to_read_only_low_risk(self):
        from app.services.task_readiness import Requirement, grantable
        assert grantable(Requirement("google_analytics", ("run_report",), ""))[0]
        ok, why = grantable(Requirement("github", ("create_issue",), ""))
        assert not ok, why
        assert not grantable(Requirement("nonexistent", ("x",), ""))[0]
        assert not grantable(Requirement("google_analytics", ("nope",), ""))[0]


class TestGoogleAnalyticsProviderUnit:
    def test_relative_dates(self):
        from datetime import date
        from app.integrations.providers.google_analytics_provider import GAApiError, resolve_report_date
        t = date(2026, 10, 21)
        assert resolve_report_date("today", t) == t
        assert resolve_report_date("yesterday", t) == date(2026, 10, 20)
        assert resolve_report_date("30daysAgo", t) == date(2026, 9, 21)
        assert resolve_report_date("2026-01-05", t) == date(2026, 1, 5)
        for bad in ("next week", "2026-13-40", "", "7 days ago; drop table"):
            with pytest.raises(GAApiError):
                resolve_report_date(bad, t) if bad else resolve_report_date("garbage", t)

    def test_property_id_normalisation(self):
        from app.integrations.providers.google_analytics_provider import GAApiError, normalise_property_id
        assert normalise_property_id("properties/123") == "123" and normalise_property_id(" 456 ") == "456"
        for bad in ("", "abc", "1/2", "../x", "12 34", "1" * 30):
            with pytest.raises(GAApiError):
                normalise_property_id(bad)

    def test_future_end_date_and_oversized_range_are_rejected(self, world, llm, ga_api):
        connect_ga(world)
        for args in ({"start_date": "2020-01-01", "end_date": "2024-01-01"},
                     {"start_date": "yesterday", "end_date": "2099-01-01"}):
            llm.plan = plan_for(args)
            assert ask(world).json()["plan_status"] == "failed"
        assert not ga_api.reports


class TestToolLayerDefenceInDepth:
    """The readiness gate is a convenience; these hold even if it were bypassed."""

    def _defn(self, integration_id, tenant, **kw):
        from app.tools.dynamic_tool import DynamicToolDefinition, make_tool_key
        base = dict(
            tool_key=make_tool_key(integration_id, "run_report"), integration_id=integration_id, tenant_id=tenant,
            role_key=DMM, capability_key="run_report", provider_type="google_analytics",
            integration_name="Google Analytics", description="GA4 report", risk_level="low",
            is_read_only=True, input_schema=None, is_enabled=True)
        base.update(kw)
        return DynamicToolDefinition(**base)

    def _call(self, world, defn, args, tenant=None, role=DMM):
        from app.tools.dynamic_tool import build_dynamic_tool_adapter
        from app.tools.registry import clear_tool_context, set_tool_context

        async def go():
            async with world.maker() as s:
                set_tool_context(db_session=s, tenant_id=tenant or world.tenant_a, role_key=role,
                                 allowed_tools=[], guarded_tools=[], dynamic_tools={})
                try:
                    out = await build_dynamic_tool_adapter(defn).ainvoke({"params_json": json.dumps(args)})
                    await s.commit()
                    return out
                finally:
                    clear_tool_context()
        return run(go())

    def test_calling_a_tool_without_a_grant_is_denied_and_audited(self, world, ga_api):
        iid = connect_ga(world, grants=())
        out = self._call(world, self._defn(iid, world.tenant_a), {"start_date": "7daysAgo", "end_date": "yesterday"})
        assert out.startswith("[PERMISSION DENIED]") and not ga_api.log
        rows = audit_rows(world)
        assert len(rows) == 1 and rows[0].success is False

    def test_tenant_b_cannot_run_tenant_a_integration_even_with_its_id(self, world, ga_api):
        iid = connect_ga(world)                       # belongs to tenant A
        out = self._call(world, self._defn(iid, world.tenant_a), {"start_date": "7daysAgo", "end_date": "yesterday"},
                         tenant=world.tenant_b)
        assert out.startswith(("[INTEGRATION ERROR]", "[PERMISSION DENIED]")) and not ga_api.log

    def test_high_risk_capability_is_blocked_on_the_async_path(self, world, ga_api):
        iid = connect_ga(world)
        out = self._call(world, self._defn(iid, world.tenant_a, risk_level="high"), {})
        assert out.startswith("[GOVERNANCE REQUIRED]") and not ga_api.log

    def test_credential_looking_and_tenant_arguments_are_rejected(self, world, ga_api):
        iid = connect_ga(world)
        for bad in ({"access_token": "x"}, {"tenant_id": world.tenant_b}, {"client_secret": "x"}):
            out = self._call(world, self._defn(iid, world.tenant_a), bad)
            assert out.startswith("[VALIDATION ERROR]"), out
        assert not ga_api.log
