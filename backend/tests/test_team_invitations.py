"""Team invitations and member administration (Phase J, part 1). Real API, auth, tenancy, DB; no external services."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.invitation_models import Invitation
from app.db.models import AuditLog, RefreshToken, User
from tests.test_marketing_analytics_e2e import run

API = "/api/v1/team"
PW = "Sturdy-Pass-42"


def invite(world, email="new@a.test", role="Employee", who="a_admin"):
    return world.client.post(f"{API}/invitations", json={"email": email, "role": role}, headers=world.auth(who))


def accept(world, token, name="New Person", password=PW):
    return world.client.post(f"{API}/invitations/accept", json={"token": token, "name": name, "password": password})


def login(world, email, tenant=None, password=PW):
    return world.client.post("/api/v1/auth/token", json={"email": email, "password": password, "company_id": tenant or world.tenant_a})


def fetch(world, model, **where):
    async def go():
        async with world.maker() as s:
            q = select(model)
            for k, v in where.items():
                q = q.where(getattr(model, k) == v)
            return (await s.execute(q)).scalars().all()
    return run(go())


def audit_text(world):
    return " | ".join(a.event for a in fetch(world, AuditLog))


class TestInvite:
    def test_admin_invites_and_new_person_can_sign_in(self, world):
        r = invite(world, role="Manager")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["token"] and body["accept_path"].endswith(body["token"])
        lk = world.client.post(f"{API}/invitations/lookup", json={"token": body["token"]})
        assert lk.status_code == 200 and lk.json()["email"] == "new@a.test" and lk.json()["company_name"] == "Company A"
        a = accept(world, body["token"])
        assert a.status_code == 201, a.text
        l = login(world, "new@a.test")
        assert l.status_code == 200 and l.json()["role"] == "Manager" and l.json()["tenant_id"] == world.tenant_a

    def test_token_is_stored_only_as_a_hash(self, world):
        tok = invite(world).json()["token"]
        (inv,) = fetch(world, Invitation)
        assert tok not in (inv.token_hash, inv.email) and len(inv.token_hash) == 64

    def test_token_is_single_use(self, world):
        tok = invite(world).json()["token"]
        assert accept(world, tok).status_code == 201
        assert accept(world, tok, name="Other").status_code == 404
        assert world.client.post(f"{API}/invitations/lookup", json={"token": tok}).status_code == 404

    def test_expired_invitation_is_refused_and_listed_as_expired(self, world):
        tok = invite(world).json()["token"]

        async def age():
            async with world.maker() as s:
                for i in (await s.execute(select(Invitation))).scalars().all():
                    i.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                await s.commit()
        run(age())
        assert accept(world, tok).status_code == 404
        listed = world.client.get(f"{API}/invitations", headers=world.auth("a_admin")).json()
        assert listed[0]["status"] == "expired"

    def test_all_invalid_states_give_the_same_error(self, world):
        tok = invite(world).json()["token"]
        inv_id = world.client.get(f"{API}/invitations", headers=world.auth("a_admin")).json()[0]["id"]
        world.client.post(f"{API}/invitations/{inv_id}/revoke", headers=world.auth("a_admin"))
        revoked = accept(world, tok)
        unknown = accept(world, "x" * 43)
        assert revoked.status_code == unknown.status_code == 404 and revoked.json() == unknown.json()

    def test_resend_invalidates_the_old_link(self, world):
        first = invite(world).json()
        second = world.client.post(f"{API}/invitations/{first['id']}/resend", headers=world.auth("a_admin")).json()
        assert second["token"] != first["token"]
        assert accept(world, first["token"]).status_code == 404
        assert accept(world, second["token"]).status_code == 201

    def test_revoked_invitation_cannot_be_used_or_resent(self, world):
        j = invite(world).json()
        assert world.client.post(f"{API}/invitations/{j['id']}/revoke", headers=world.auth("a_admin")).status_code == 200
        assert accept(world, j["token"]).status_code == 404
        assert world.client.post(f"{API}/invitations/{j['id']}/resend", headers=world.auth("a_admin")).status_code == 409

    def test_validation(self, world):
        assert invite(world, email="not-an-email").status_code == 400
        assert invite(world, role="superadmin").status_code == 400
        assert invite(world, role="Company Admin").status_code == 201
        tok = invite(world, email="p@a.test").json()["token"]
        assert accept(world, tok, password="short").status_code == 400
        assert accept(world, tok, password="p@a.test").status_code == 400
        assert accept(world, tok, name="  ").status_code == 400
        assert accept(world, tok).status_code == 201     # attempts above did not burn the token

    def test_duplicate_pending_and_existing_user_are_refused(self, world):
        assert invite(world).status_code == 201
        assert invite(world).status_code == 409
        assert invite(world, email=world.users["a_employee"]["email"].upper()).status_code == 409

    def test_email_is_normalised(self, world):
        tok = invite(world, email="  Mixed.Case@A.Test ").json()["token"]
        assert world.client.post(f"{API}/invitations/lookup", json={"token": tok}).json()["email"] == "mixed.case@a.test"

    def test_pending_cap(self, world):
        from app.services import team_service as ts
        for n in range(ts.MAX_PENDING):
            assert invite(world, email=f"u{n}@a.test").status_code == 201
        assert invite(world, email="one-more@a.test").status_code == 429

    def test_invited_person_lands_in_the_inviting_company_only(self, world):
        tok = invite(world, who="a_admin").json()["token"]
        accept(world, tok)
        assert login(world, "new@a.test", tenant=world.tenant_b).status_code == 401


class TestAuthorization:
    def test_non_admin_cannot_manage(self, world):
        h = world.auth("a_employee")
        assert world.client.get(f"{API}/members", headers=h).status_code == 403
        assert invite(world, who="a_employee").status_code == 403
        assert world.client.get(f"{API}/invitations", headers=h).status_code == 403
        assert world.client.post(f"{API}/members/{world.users['a_admin']['id']}/deactivate", headers=h).status_code == 403

    def test_unauthenticated_cannot_manage(self, world):
        assert world.client.get(f"{API}/members").status_code == 401
        assert world.client.post(f"{API}/invitations", json={"email": "a@b.co"}).status_code == 401

    def test_other_company_cannot_touch_invitations_or_members(self, world):
        j = invite(world).json()
        hb = world.auth("b_admin")
        assert world.client.get(f"{API}/invitations", headers=hb).json() == []
        assert world.client.post(f"{API}/invitations/{j['id']}/revoke", headers=hb).status_code == 404
        assert world.client.post(f"{API}/invitations/{j['id']}/resend", headers=hb).status_code == 404
        uid = world.users["a_employee"]["id"]
        assert world.client.post(f"{API}/members/{uid}/deactivate", headers=hb).status_code == 404
        assert world.client.post(f"{API}/members/{uid}/role", json={"role": "Manager"}, headers=hb).status_code == 404
        assert all(m["id"] != uid for m in world.client.get(f"{API}/members", headers=hb).json())


class TestMembers:
    def test_change_role(self, world):
        uid = world.users["a_employee"]["id"]
        r = world.client.post(f"{API}/members/{uid}/role", json={"role": "Manager"}, headers=world.auth("a_admin"))
        assert r.status_code == 200 and r.json()["role"] == "Manager"
        assert "Employee -> Manager" in audit_text(world)
        assert world.client.post(f"{API}/members/{uid}/role", json={"role": "superadmin"}, headers=world.auth("a_admin")).status_code == 400

    def test_cannot_change_or_deactivate_self(self, world):
        me = world.users["a_admin"]["id"]
        h = world.auth("a_admin")
        assert world.client.post(f"{API}/members/{me}/role", json={"role": "Employee"}, headers=h).status_code == 403
        assert world.client.post(f"{API}/members/{me}/deactivate", headers=h).status_code == 403

    def test_deactivate_blocks_login_and_existing_token_and_revokes_refresh(self, world):
        tok = invite(world).json()["token"]
        accept(world, tok)
        l = login(world, "new@a.test").json()
        uid = l["user_id"]
        assert world.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {l['access_token']}"}).status_code == 200
        assert world.client.post(f"{API}/members/{uid}/deactivate", headers=world.auth("a_admin")).status_code == 200
        assert login(world, "new@a.test").status_code == 401
        assert world.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {l['access_token']}"}).status_code == 401
        assert all(t.revoked for t in fetch(world, RefreshToken, user_id=uid))
        assert world.client.post(f"{API}/members/{uid}/reactivate", headers=world.auth("a_admin")).status_code == 200
        assert login(world, "new@a.test").status_code == 200

    def test_members_list_includes_deactivated_with_status(self, world):
        uid = world.users["a_employee"]["id"]
        world.client.post(f"{API}/members/{uid}/deactivate", headers=world.auth("a_admin"))
        rows = {m["id"]: m for m in world.client.get(f"{API}/members", headers=world.auth("a_admin")).json()}
        assert rows[uid]["status"] == "Deactivated" and rows[uid]["is_active"] is False
        assert "hashed_password" not in rows[uid]

    def test_accounts_with_other_roles_are_not_editable_here(self, world):
        async def mk():
            async with world.maker() as s:
                u = (await s.execute(select(User).where(User.id == world.users["a_employee"]["id"]))).scalar_one()
                u.role = "superadmin"
                await s.commit()
        run(mk())
        uid = world.users["a_employee"]["id"]
        assert world.client.post(f"{API}/members/{uid}/deactivate", headers=world.auth("a_admin")).status_code == 403
        assert world.client.post(f"{API}/members/{uid}/role", json={"role": "Employee"}, headers=world.auth("a_admin")).status_code == 403

    def test_invitation_events_are_audited(self, world):
        tok = invite(world).json()["token"]
        accept(world, tok)
        t = audit_text(world)
        assert "invited new@a.test" in t and "accepted invitation" in t
        assert tok not in t


def test_invitations_migration_is_additive_and_reversible():
    import pathlib, re
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("migrations/versions/d7e1f26a8b34_add_invitations.py").read_text()
    assert 'down_revision: Union[str, None] = "c6d0e15f7a23"' in src and "drop_table" in src and not re.search(r"drop_column|alter_column", src)
