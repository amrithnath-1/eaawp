"""
Phase D - reliable workflows and scheduling.

REAL: FastAPI app, auth, workflow API, the shared runner, execute_agent (readiness
gate, role config, grants, planner, tool engine, manager, encryption), scheduler
tick logic, SQLite schema.
FAKED: the LLM (scripted) and Google's HTTP APIs (same fakes as the Search
Console suite).  Time is passed into ``tick(now=...)`` so schedules are tested
deterministically; no real scheduler loop or clock is involved.

This proves our scheduling, de-duplication, permission re-checks, retries and
recovery.  It does not prove behaviour against live Google or a live LLM.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import AuditLog, Company, ExecutionPlan, User, Workflow
from app.db.workflow_run_models import WorkflowRun
from app.services import workflow_runner as wr
from tests.test_marketing_analytics_e2e import ACCESS, CLIENT_SECRET, REFRESH, run
from tests.test_search_console_seo_e2e import (  # noqa: F401  (fixtures are used by name)
    ROWS, connect_gsc, gsc_api, http_error, llm,
)

ROLE = "Digital Marketing Manager"
STEP = "Pull the top search queries from Google Search Console with clicks, impressions, CTR and average position"
# 2026-10-26 is a Monday; the scheduler's weekday 0 == Monday.
MON_9 = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
CRON = "0 9 * * 0"


@pytest.fixture(autouse=True)
def runner_uses_test_db(world, monkeypatch):
    monkeypatch.setattr(wr, "AsyncSessionLocal", world.maker)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """The runner's notion of 'now' follows the time passed to tick(), so retries/backoff are deterministic."""
    state = {"now": datetime.now(timezone.utc)}
    monkeypatch.setattr(wr, "_now", lambda: state["now"])
    global _CLOCK
    _CLOCK = state
    return state


_CLOCK: dict = {}


def create_wf(world, who="a_admin", **over):
    body = {
        "name": "Weekly SEO report", "trigger": "scheduled", "schedule_cron": CRON,
        "role_name": ROLE, "steps": [{"step_index": 0, "step_type": "tool", "description": STEP}],
    }
    body.update(over)
    r = world.client.post("/api/v1/workflows", headers=world.auth(who), json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def tick(now):
    _CLOCK["now"] = now
    return run(wr.tick(now))


def runs(world, wf_id, who="a_admin"):
    r = world.client.get(f"/api/v1/workflows/{wf_id}/runs", headers=world.auth(who))
    assert r.status_code == 200, r.text
    return r.json()


def db_runs(world, wf_id):
    async def go():
        async with world.maker() as s:
            return (await s.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == wf_id)
                                    .order_by(WorkflowRun.attempt))).scalars().all()
    return run(go())


def mutate(world, model, key, **fields):
    async def go():
        async with world.maker() as s:
            row = await s.get(model, key)
            for k, v in fields.items():
                setattr(row, k, v)
            await s.commit()
    run(go())


def wf_row(world, wf_id):
    async def go():
        async with world.maker() as s:
            return await s.get(Workflow, wf_id)
    return run(go())


def user_id(world, who):
    return world.users[who]["id"]


# ═════════════════════════════════════════════════════════════════════════════
class TestScheduledRunExecutesForReal:
    def test_due_schedule_runs_the_report_through_the_normal_agent_path(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        stats = tick(MON_9)
        assert stats["claimed"] == 1 and stats["executed"] == 1
        history = runs(world, wf)
        assert len(history) == 1 and history[0]["status"] == "completed" and history[0]["trigger"] == "scheduled"
        assert history[0]["plan_id"] and history[0]["detail"].startswith("Here is what Search Console returned")

        async def final_message():
            async with world.maker() as s:
                return (await s.get(ExecutionPlan, history[0]["plan_id"])).final_message
        assert "320" in run(final_message())                       # the persisted plan holds the real figures
        assert len(gsc_api.queries) == 1                           # a real tool call happened
        assert wf_row(world, wf).status == "completed"

    def test_runs_as_the_configured_role_with_real_grants_not_a_made_up_role(self, world, llm, gsc_api):
        connect_gsc(world)                                         # grant exists for the DMM role only
        create_wf(world, role_name="Financial Analyst")            # a role with no grant
        tick(MON_9)
        assert not gsc_api.queries                                 # the grant is for another role

    def test_not_due_means_no_run(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        assert tick(MON_9 + timedelta(minutes=1))["claimed"] == 0                 # 09:01
        assert tick(MON_9 + timedelta(days=1))["claimed"] == 0                    # Tuesday 09:00
        assert runs(world, wf) == [] and not gsc_api.queries

    def test_timezone_is_honoured(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, timezone="Asia/Kolkata")             # 09:00 IST == 03:30 UTC
        assert tick(MON_9)["claimed"] == 0
        assert tick(MON_9.replace(hour=3, minute=30))["claimed"] == 1
        assert len(runs(world, wf)) == 1

    def test_invalid_timezone_and_limits_are_rejected(self, world):
        for bad in ({"timezone": "Mars/Base"}, {"max_retries": 6}, {"retry_delay_minutes": 0},
                    {"schedule_cron": "0-5 9 * * 0"}):
            r = world.client.post("/api/v1/workflows", headers=world.auth("a_admin"), json={
                "name": "x", "trigger": "scheduled", "schedule_cron": CRON, **bad})
            assert r.status_code == 422, bad

    def test_disabled_workflow_never_runs(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, is_enabled=False)
        assert tick(MON_9)["claimed"] == 0 and runs(world, wf) == []


# ═════════════════════════════════════════════════════════════════════════════
class TestNoDuplicateRuns:
    def test_ticking_twice_in_the_same_minute_runs_once(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        tick(MON_9)
        again = tick(MON_9 + timedelta(seconds=30))
        assert again["claimed"] == 0
        assert len(runs(world, wf)) == 1 and len(gsc_api.queries) == 1

    def test_two_workers_ticking_at_once_still_run_once(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)

        async def both():
            await asyncio.gather(wr.tick(MON_9), wr.tick(MON_9))
        run(both())
        assert len(db_runs(world, wf)) == 1 and len(gsc_api.queries) == 1

    def test_a_restart_does_not_repeat_the_slot(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        tick(MON_9)
        run(wr.recover_interrupted(MON_9 + timedelta(seconds=5)))   # what startup does
        tick(MON_9 + timedelta(seconds=10))
        assert len(runs(world, wf)) == 1 and len(gsc_api.queries) == 1

    def test_database_rejects_a_second_run_for_the_same_slot(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        tick(MON_9)

        async def dup():
            async with world.maker() as s:
                w = await s.get(Workflow, wf)
                return await wr.claim_run(s, w, trigger="scheduled", slot=wr.slot_for(MON_9))
        assert run(dup()) is None

    def test_a_run_still_in_progress_makes_the_next_slot_skip_not_overlap(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        mutate(world, Workflow, wf, status="running")
        tick(MON_9)
        h = runs(world, wf)
        assert [r["status"] for r in h] == ["skipped"] and "already running" in h[0]["detail"]
        assert not gsc_api.queries


# ═════════════════════════════════════════════════════════════════════════════
class TestSetupAndPermissionsAreRevalidatedEveryRun:
    def test_missing_integration_waits_for_setup_and_never_guesses(self, world, llm, gsc_api):
        wf = create_wf(world)                                      # nothing connected
        tick(MON_9)
        h = runs(world, wf)
        assert h[0]["status"] == "waiting_setup" and h[0]["pending_task_id"]
        assert not gsc_api.log
        assert wf_row(world, wf).status == "idle"                  # not stuck
        pend = world.client.get("/api/v1/agent/pending-tasks", headers=world.auth("a_admin")).json()
        assert [p["id"] for p in pend] == [h[0]["pending_task_id"]]

    def test_next_week_runs_once_setup_is_done(self, world, llm, gsc_api):
        wf = create_wf(world)
        tick(MON_9)
        connect_gsc(world)
        tick(MON_9 + timedelta(days=7))
        assert [r["status"] for r in runs(world, wf)] == ["completed", "waiting_setup"]
        assert len(gsc_api.queries) == 1

    def test_revoking_the_grant_stops_the_next_run(self, world, llm, gsc_api):
        from app.db.integration_models import CapabilityGrant
        connect_gsc(world)
        wf = create_wf(world)
        tick(MON_9)
        assert len(gsc_api.queries) == 1

        async def revoke():
            async with world.maker() as s:
                for g in (await s.execute(select(CapabilityGrant))).scalars():
                    g.is_granted = False
                await s.commit()
        run(revoke())
        tick(MON_9 + timedelta(days=7))
        assert runs(world, wf)[0]["status"] == "waiting_setup" and len(gsc_api.queries) == 1

    def test_deactivated_owner_skips(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        mutate(world, User, user_id(world, "a_admin"), is_active=False)
        tick(MON_9)
        h = runs(world, wf, "a_employee")
        assert h[0]["status"] == "skipped" and "deactivated" in h[0]["detail"] and not gsc_api.queries

    def test_owner_demoted_from_admin_skips(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        mutate(world, User, user_id(world, "a_admin"), role="Employee")
        tick(MON_9)
        assert runs(world, wf)[0]["status"] == "skipped" and not gsc_api.queries

    def test_owner_moved_to_another_company_skips(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        mutate(world, User, user_id(world, "a_admin"), tenant_id=world.tenant_b)
        tick(MON_9)
        assert runs(world, wf, "a_employee")[0]["status"] == "skipped" and not gsc_api.queries

    def test_inactive_company_skips(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        mutate(world, Company, world.tenant_a, is_active=False)
        tick(MON_9)
        assert runs(world, wf)[0]["status"] == "skipped" and "inactive" in runs(world, wf)[0]["detail"]

    def test_legacy_workflow_without_an_owner_is_skipped_not_run_anonymously(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        mutate(world, Workflow, wf, run_as_user_id=None)
        tick(MON_9)
        assert runs(world, wf)[0]["status"] == "skipped" and not gsc_api.queries

    def test_owner_cannot_be_chosen_by_the_request_body(self, world):
        r = world.client.post("/api/v1/workflows", headers=world.auth("a_admin"), json={
            "name": "x", "trigger": "manual", "run_as_user_id": user_id(world, "b_admin")})
        wf = r.json()["id"]
        assert wf_row(world, wf).run_as_user_id == user_id(world, "a_admin")


# ═════════════════════════════════════════════════════════════════════════════
class TestRetriesAreExplicit:
    def test_failure_is_retried_with_backoff_then_succeeds(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, max_retries=2, retry_delay_minutes=10)
        gsc_api.rows = http_error(403, "denied")
        tick(MON_9)
        h = db_runs(world, wf)
        assert [r.status for r in h] == ["failed", "queued"] and h[1].attempt == 2
        due = h[1].not_before if h[1].not_before.tzinfo else h[1].not_before.replace(tzinfo=timezone.utc)
        assert due == MON_9 + timedelta(minutes=10)                 # 10 min x attempt 1
        calls = len(gsc_api.queries)
        tick(MON_9 + timedelta(minutes=5))                          # backoff has not elapsed
        assert len(gsc_api.queries) == calls and db_runs(world, wf)[1].status == "queued"
        gsc_api.rows = ROWS                                         # Google recovers
        tick(MON_9 + timedelta(minutes=11))
        assert [r.status for r in db_runs(world, wf)] == ["failed", "completed"]

    def test_retries_stop_at_the_limit(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, max_retries=1, retry_delay_minutes=1)
        gsc_api.rows = http_error(403, "denied")
        tick(MON_9)
        tick(MON_9 + timedelta(minutes=5))
        tick(MON_9 + timedelta(minutes=10))
        assert [r.status for r in db_runs(world, wf)] == ["failed", "failed"]   # 1 run + 1 retry, no third

    def test_default_is_no_retry(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        gsc_api.rows = http_error(403, "denied")
        tick(MON_9)
        assert [r.status for r in db_runs(world, wf)] == ["failed"]

    def test_setup_problems_are_not_retried(self, world, llm, gsc_api):
        wf = create_wf(world, max_retries=3)
        tick(MON_9)
        assert [r.status for r in db_runs(world, wf)] == ["waiting_setup"]

    def test_failure_is_reported_honestly_with_no_invented_numbers(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        gsc_api.rows = http_error(401, "invalid credentials")
        tick(MON_9)
        h = runs(world, wf)[0]
        assert h["status"] == "failed" and "320" not in h["detail"]
        assert wf_row(world, wf).last_run_status == "failed"


# ═════════════════════════════════════════════════════════════════════════════
class TestCrashRecoveryAndApprovals:
    def _stuck(self, world, wf, minutes_ago):
        async def go():
            async with world.maker() as s:
                w = await s.get(Workflow, wf)
                w.status = "running"
                s.add(WorkflowRun(
                    id=str(uuid.uuid4()), tenant_id=w.tenant_id, workflow_id=wf, trigger="scheduled",
                    slot="2026-10-19T09:00", status="running",
                    started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
                await s.commit()
        run(go())

    def test_interrupted_run_is_failed_and_the_workflow_released(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        self._stuck(world, wf, 45)
        assert run(wr.recover_interrupted()) == 1
        r = db_runs(world, wf)[0]
        assert r.status == "failed" and "Interrupted" in r.detail
        assert wf_row(world, wf).status == "failed"            # no longer 'running'
        tick(MON_9)                                            # and it can run again
        assert any(x.status == "completed" for x in db_runs(world, wf))

    def test_a_fresh_running_run_is_left_alone(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        self._stuck(world, wf, 2)
        assert run(wr.recover_interrupted()) == 0
        assert db_runs(world, wf)[0].status == "running"

    def test_interrupted_run_gets_its_retry_when_the_policy_allows(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, max_retries=1)
        self._stuck(world, wf, 45)
        run(wr.recover_interrupted())
        assert [r.status for r in db_runs(world, wf)] == ["failed", "queued"]

    def test_decided_approval_releases_the_workflow_with_the_real_outcome(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)

        async def go():
            async with world.maker() as s:
                w = await s.get(Workflow, wf)
                plan_id = str(uuid.uuid4())
                s.add(ExecutionPlan(id=plan_id, tenant_id=w.tenant_id, role_key="X", objective="o",
                                    status="awaiting_approval"))
                s.add(WorkflowRun(id="r-appr", tenant_id=w.tenant_id, workflow_id=wf, trigger="scheduled",
                                  slot="2026-10-19T09:00", status="awaiting_approval", plan_id=plan_id))
                w.status = "awaiting_approval"
                await s.commit()
                return plan_id
        plan_id = run(go())
        assert run(wr.reconcile_approvals()) == 0               # still waiting: untouched
        assert wf_row(world, wf).status == "awaiting_approval"
        mutate(world, ExecutionPlan, plan_id, status="completed")
        assert run(wr.reconcile_approvals()) == 1
        assert db_runs(world, wf)[0].status == "completed" and wf_row(world, wf).status == "completed"

    def test_rejected_approval_is_recorded_as_failed_not_success(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)

        async def go():
            async with world.maker() as s:
                w = await s.get(Workflow, wf)
                s.add(ExecutionPlan(id="p-rej", tenant_id=w.tenant_id, role_key="X", objective="o", status="rejected"))
                s.add(WorkflowRun(id="r-rej", tenant_id=w.tenant_id, workflow_id=wf, trigger="manual",
                                  slot="manual:x", status="awaiting_approval", plan_id="p-rej"))
                await s.commit()
        run(go())
        run(wr.reconcile_approvals())
        assert db_runs(world, wf)[0].status == "failed"

    def test_next_slot_while_awaiting_approval_is_skipped_and_recorded(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        mutate(world, Workflow, wf, status="awaiting_approval")
        tick(MON_9)
        h = runs(world, wf)
        assert h[0]["status"] == "skipped" and "approval" in h[0]["detail"]


# ═════════════════════════════════════════════════════════════════════════════
class TestApiPermissionsTenancyAndManualRuns:
    def test_manual_trigger_uses_the_same_path_and_is_recorded(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, trigger="manual", schedule_cron=None)
        r = world.client.post(f"/api/v1/workflows/{wf}/trigger", headers=world.auth("a_admin"))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed" and "320" in r.json()["message"]
        h = runs(world, wf)
        assert h[0]["trigger"] == "manual" and h[0]["status"] == "completed"
        assert len(gsc_api.queries) == 1

    def test_manual_trigger_without_setup_says_so(self, world, llm, gsc_api):
        wf = create_wf(world, trigger="manual", schedule_cron=None)
        r = world.client.post(f"/api/v1/workflows/{wf}/trigger", headers=world.auth("a_admin"))
        assert r.json()["status"] == "waiting_setup" and not gsc_api.log

    def test_manual_trigger_permissions_and_tenancy(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, trigger="manual", schedule_cron=None)
        url = f"/api/v1/workflows/{wf}/trigger"
        assert world.client.post(url, headers=world.auth("a_employee")).status_code == 403
        assert world.client.post(url, headers=world.auth("b_admin")).status_code == 404
        assert world.client.post(url).status_code == 401
        assert not gsc_api.queries

    def test_disabled_workflow_cannot_be_triggered(self, world, llm, gsc_api):
        wf = create_wf(world, trigger="manual", schedule_cron=None, is_enabled=False)
        assert world.client.post(f"/api/v1/workflows/{wf}/trigger", headers=world.auth("a_admin")).status_code == 409

    def test_history_is_tenant_scoped(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        tick(MON_9)
        assert world.client.get(f"/api/v1/workflows/{wf}/runs", headers=world.auth("b_admin")).status_code == 404
        assert world.client.get(f"/api/v1/workflows/{wf}/runs").status_code == 401
        assert len(runs(world, wf, "a_employee")) == 1                 # members may read their company's history

    def test_cancel_a_queued_retry(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world, max_retries=1)
        gsc_api.rows = http_error(403, "denied")
        tick(MON_9)
        queued = [r for r in runs(world, wf) if r["status"] == "queued"][0]
        url = f"/api/v1/workflows/{wf}/runs/{queued['id']}/cancel"
        assert world.client.post(url, headers=world.auth("a_employee")).status_code == 403
        assert world.client.post(url, headers=world.auth("b_admin")).status_code == 404
        assert world.client.post(url, headers=world.auth("a_admin")).json()["status"] == "cancelled"
        before = len(gsc_api.queries)
        tick(MON_9 + timedelta(hours=2))
        assert len(gsc_api.queries) == before                           # cancelled retry never ran

    def test_finished_runs_cannot_be_cancelled(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        tick(MON_9)
        rid = runs(world, wf)[0]["id"]
        r = world.client.post(f"/api/v1/workflows/{wf}/runs/{rid}/cancel", headers=world.auth("a_admin"))
        assert r.status_code == 409

    def test_no_credentials_in_history_or_audit(self, world, llm, gsc_api):
        connect_gsc(world)
        wf = create_wf(world)
        tick(MON_9)

        async def audits():
            async with world.maker() as s:
                return [a.event for a in (await s.execute(select(AuditLog))).scalars()]
        blob = json.dumps(runs(world, wf)) + json.dumps(run(audits()))
        for secret in (ACCESS, REFRESH, CLIENT_SECRET):
            assert secret not in blob
        assert any("workflow 'Weekly SEO report'" in e and "completed" in e for e in run(audits()))
