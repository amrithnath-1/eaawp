"""Notifications (Phase M): per-recipient privacy, tenant isolation, and double-opt-in email (company authorization + personal consent)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.email_models import EmailAuditLog
from app.db.models import AuditLog, User
from app.db.notification_models import Notification
from app.services import notification_service as ns
from tests.conftest import _run

N = "/api/v1/notifications"
SECRET_DETAIL = "payroll file q3-confidential.xlsx"


class FakeProvider:
    def __init__(self, ok=True, boom=False):
        self.sent, self.ok, self.boom = [], ok, boom

    async def send(self, recipients, subject, body, reply_to=None):
        from app.integrations.email_provider import SendResult
        if self.boom:
            raise RuntimeError("smtp password=hunter2 exploded")
        self.sent.append((list(recipients), subject, body))
        return SendResult(success=self.ok, message_id="<m>", error_message=None if self.ok else "Sender address was refused.")


def provider(monkeypatch, prov):
    async def fake(tenant_id, db):
        return prov
    monkeypatch.setattr("app.integrations.email_provider.get_email_provider", fake)


def run_db(w, fn):
    async def go():
        async with w.maker() as s:
            out = await fn(s)
            await s.commit()
            return out
    return _run(go())


def emit(w, tenant, category="approval_requested", title="Approval needed: send_email", message=SECRET_DETAIL):
    return run_db(w, lambda s: ns.notify_admins(s, tenant, category, title, message, severity="warning"))


def deliver(w):
    return run_db(w, lambda s: ns.deliver_pending_emails(s))


def rows(w):
    async def q(s):
        return [(n.user_id, n.tenant_id, n.email_status, n.email_attempts) for n in (await s.execute(select(Notification))).scalars().all()]
    return run_db(w, q)


def mine(w, who, **p):
    r = w.client.get(N, params=p, headers=w.auth(who)); assert r.status_code == 200, r.text
    return r.json()


def add_admin(w, key="a_admin2"):
    async def mk(s):
        from tests.conftest import _password_hash
        uid = str(uuid.uuid4())
        s.add(User(id=uid, tenant_id=w.tenant_a, email=f"{key}@example.test", name=key, role="Company Admin",
                   hashed_password=_password_hash(), status="Active", is_active=True))
        w.users[key] = {"id": uid, "email": f"{key}@example.test", "tenant_id": w.tenant_a, "role": "Company Admin"}
    run_db(w, mk)


def authorize(w, on=True):
    return w.client.put(f"{N}/settings", json={"email_enabled": on}, headers=w.auth("a_admin"))


def opt(w, who, category="approval_requested", email=True, in_app=True):
    return w.client.put(f"{N}/preferences", json={"category": category, "email": email, "in_app": in_app}, headers=w.auth(who))


# ── privacy / isolation ───────────────────────────────────────────────────────

def test_admin_events_go_to_active_admins_only(world):
    assert emit(world, world.tenant_a) == 1
    assert len(mine(world, "a_admin")) == 1
    assert mine(world, "a_employee") == []
    assert mine(world, "b_admin") == []                       # other company never sees it
    assert world.client.get(f"{N}/unread-count", headers=world.auth("a_employee")).json() == {"unread": 0}


def test_read_state_is_per_person(world):
    add_admin(world)
    assert emit(world, world.tenant_a) == 2
    first = mine(world, "a_admin")[0]["id"]
    assert world.client.post(f"{N}/{first}/read", headers=world.auth("a_admin")).status_code == 200
    assert world.client.get(f"{N}/unread-count", headers=world.auth("a_admin")).json()["unread"] == 0
    assert world.client.get(f"{N}/unread-count", headers=world.auth("a_admin2")).json()["unread"] == 1   # the other admin still has it unread


def test_cannot_read_or_mark_someone_elses_notification(world):
    add_admin(world)
    emit(world, world.tenant_a)
    theirs = mine(world, "a_admin")[0]["id"]
    for who in ("a_admin2", "a_employee", "b_admin"):
        assert world.client.post(f"{N}/{theirs}/read", headers=world.auth(who)).status_code == 404
    assert mine(world, "a_admin", unread_only="true")[0]["id"] == theirs     # still unread
    assert world.client.post(f"{N}/read-all", headers=world.auth("a_employee")).json() == {"marked_read": 0}
    assert len(mine(world, "a_admin", unread_only="true")) == 1


def test_deactivated_admin_gets_nothing(world):
    add_admin(world)
    async def off(s):
        u = (await s.execute(select(User).where(User.email == "a_admin2@example.test"))).scalar_one()
        u.is_active = False
    run_db(world, off)
    assert emit(world, world.tenant_a) == 1


def test_requires_login(world):
    for path in ("", "/unread-count", "/preferences", "/settings"):
        assert world.client.get(f"{N}{path}").status_code in (401, 403)


def test_limit_is_bounded(world):
    assert world.client.get(N, params={"limit": 100000}, headers=world.auth("a_admin")).status_code == 422


# ── a real producer, end to end ───────────────────────────────────────────────

def test_member_joined_is_delivered_by_the_real_invitation_flow(world):
    r = world.client.post("/api/v1/team/invitations", json={"email": "new@a.test", "role": "Employee"}, headers=world.auth("a_admin"))
    tok = r.json()["token"]
    assert world.client.post("/api/v1/team/invitations/accept", json={"token": tok, "name": "Nia New", "password": "Sturdy-Pass-42"}).status_code == 201
    got = mine(world, "a_admin")
    assert [n["category"] for n in got] == ["member_joined"] and "Nia New" in got[0]["title"]
    assert mine(world, "a_employee") == []


# ── email: double opt-in ──────────────────────────────────────────────────────

def test_email_is_off_by_default_and_nothing_is_queued(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    emit(world, world.tenant_a)
    assert [x[2] for x in rows(world)] == ["none"]
    assert deliver(world) == {"sent": 0, "failed": 0, "skipped": 0, "deferred": 0} and prov.sent == []


def test_company_authorization_alone_is_not_enough(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    assert authorize(world).status_code == 200
    emit(world, world.tenant_a)
    assert [x[2] for x in rows(world)] == ["none"] and deliver(world)["sent"] == 0 and prov.sent == []


def test_personal_opt_in_alone_is_not_enough(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    assert opt(world, "a_admin").status_code == 200
    emit(world, world.tenant_a)
    assert [x[2] for x in rows(world)] == ["none"] and prov.sent == []


def test_both_consents_send_a_generic_email_to_that_person_only(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    add_admin(world)
    assert authorize(world).status_code == 200 and opt(world, "a_admin").status_code == 200      # a_admin2 did NOT opt in
    emit(world, world.tenant_a)
    assert sorted(x[2] for x in rows(world)) == ["none", "pending"]
    assert deliver(world)["sent"] == 1
    (to, subject, body), = prov.sent
    assert to == ["a_admin@example.test"] and "Company A" in subject
    assert SECRET_DETAIL not in body and SECRET_DETAIL not in subject and "send_email" not in body     # generic content only
    assert "Settings > Notifications" in body
    assert sorted(x[2] for x in rows(world)) == ["none", "sent"]
    assert deliver(world)["sent"] == 0 and len(prov.sent) == 1                                      # not sent twice
    async def audits(s):
        return [(a.role_key, a.success, a.recipient_count) for a in (await s.execute(select(EmailAuditLog))).scalars().all()]
    assert run_db(world, audits) == [("notification", True, 1)]


def test_switching_the_company_authorization_off_stops_queued_mail(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    authorize(world); opt(world, "a_admin")
    emit(world, world.tenant_a)
    assert [x[2] for x in rows(world)] == ["pending"]
    assert authorize(world, False).status_code == 200
    assert deliver(world)["skipped"] == 1 and prov.sent == []
    assert [x[2] for x in rows(world)] == ["skipped"]


def test_withdrawing_personal_consent_stops_queued_mail(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    authorize(world); opt(world, "a_admin")
    emit(world, world.tenant_a)
    opt(world, "a_admin", email=False)
    assert deliver(world)["skipped"] == 1 and prov.sent == []


def test_deactivated_recipient_is_not_emailed(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    authorize(world); opt(world, "a_admin")
    emit(world, world.tenant_a)
    async def off(s):
        (await s.execute(select(User).where(User.id == world.users["a_admin"]["id"]))).scalar_one().is_active = False
    run_db(world, off)
    assert deliver(world)["skipped"] == 1 and prov.sent == []


def test_one_companys_authorization_never_applies_to_another(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    authorize(world)                                              # company A only
    w = world.client.put(f"{N}/preferences", json={"category": "approval_requested", "email": True, "in_app": True}, headers=world.auth("b_admin"))
    assert w.status_code == 200
    emit(world, world.tenant_b)
    assert [x[2] for x in rows(world)] == ["none"] and prov.sent == []
    assert world.client.get(f"{N}/settings", headers=world.auth("b_admin")).json()["email_enabled"] is False


def test_failed_sends_are_retried_then_given_up_without_leaking_details(world, monkeypatch):
    prov = FakeProvider(boom=True); provider(monkeypatch, prov)
    authorize(world); opt(world, "a_admin")
    emit(world, world.tenant_a)
    for _ in range(ns.EMAIL_MAX_ATTEMPTS):
        deliver(world)
    assert rows(world)[0][2:] == ("failed", ns.EMAIL_MAX_ATTEMPTS)
    async def errs(s):
        return [a.error_message for a in (await s.execute(select(EmailAuditLog))).scalars().all()]
    assert all("hunter2" not in (e or "") for e in run_db(world, errs))
    assert deliver(world)["failed"] == 0                                   # no more attempts


def test_hourly_cap_defers_instead_of_flooding(world, monkeypatch):
    prov = FakeProvider(); provider(monkeypatch, prov)
    monkeypatch.setattr(ns, "EMAIL_HOURLY_CAP", 2)
    authorize(world); opt(world, "a_admin")
    for _ in range(4):
        emit(world, world.tenant_a)
    c = deliver(world)
    assert c["sent"] == 2 and c["deferred"] == 2 and len(prov.sent) == 2
    assert sorted(x[2] for x in rows(world)) == ["pending", "pending", "sent", "sent"]


# ── settings / preferences API ────────────────────────────────────────────────

def test_only_admins_can_authorize_company_email(world, monkeypatch):
    provider(monkeypatch, FakeProvider())
    assert world.client.put(f"{N}/settings", json={"email_enabled": True}, headers=world.auth("a_employee")).status_code == 403
    assert world.client.get(f"{N}/settings", headers=world.auth("a_employee")).status_code == 403
    assert authorize(world).status_code == 200
    s = world.client.get(f"{N}/settings", headers=world.auth("a_admin")).json()
    assert s["email_enabled"] is True and s["email_provider_ready"] is True


def test_cannot_authorize_without_a_working_email_connection(world, monkeypatch):
    provider(monkeypatch, None)
    r = authorize(world)
    assert r.status_code == 400 and "email connection" in r.json()["detail"].lower()
    assert world.client.get(f"{N}/settings", headers=world.auth("a_admin")).json()["email_enabled"] is False
    assert authorize(world, False).status_code == 200                      # switching OFF is always allowed


def test_authorization_and_preferences_are_audited(world, monkeypatch):
    provider(monkeypatch, FakeProvider())
    authorize(world); opt(world, "a_admin"); authorize(world, False)
    async def ev(s):
        return [a.event for a in (await s.execute(select(AuditLog).where(AuditLog.department == "notifications"))).scalars().all()]
    events = run_db(world, ev)
    assert any("authorized for the company" in e for e in events) and any("switched off" in e for e in events)
    assert any("email=on" in e for e in events)


def test_employees_cannot_subscribe_to_admin_events(world):
    prefs = world.client.get(f"{N}/preferences", headers=world.auth("a_employee")).json()
    assert prefs["categories"] == []
    assert opt(world, "a_employee").status_code == 404
    assert len(world.client.get(f"{N}/preferences", headers=world.auth("a_admin")).json()["categories"]) == len(ns.CATEGORIES)


def test_preferences_validate_input_and_default_to_email_off(world):
    p = world.client.get(f"{N}/preferences", headers=world.auth("a_admin")).json()
    assert p["company_email_enabled"] is False and all(c["email"] is False and c["in_app"] is True for c in p["categories"])
    assert opt(world, "a_admin", category="nope").status_code == 404
    assert world.client.put(f"{N}/preferences", json={"category": "approval_requested", "email": True, "extra": 1}, headers=world.auth("a_admin")).status_code == 422
    assert opt(world, "a_admin").status_code == 200
    got = {c["category"]: c for c in world.client.get(f"{N}/preferences", headers=world.auth("a_admin")).json()["categories"]}
    assert got["approval_requested"]["email"] is True and got["workflow_failed"]["email"] is False


def test_in_app_off_creates_no_row_unless_email_is_wanted(world):
    opt(world, "a_admin", email=False, in_app=False)
    assert emit(world, world.tenant_a) == 0 and mine(world, "a_admin") == []


def test_legacy_company_wide_rows_are_admin_only(world):
    async def legacy(s):
        s.add(Notification(id=str(uuid.uuid4()), tenant_id=world.tenant_a, user_id=None, title="old", message="", severity="info", category="agent_decision"))
    run_db(world, legacy)
    assert [n["title"] for n in mine(world, "a_admin")] == ["old"] and mine(world, "a_employee") == []


def test_fan_out_failure_never_breaks_the_caller(world, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db exploded")
    monkeypatch.setattr(ns, "_deliver_to", boom)
    assert emit(world, world.tenant_a) == 0                                  # swallowed
