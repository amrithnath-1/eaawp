"""Internal messaging (Phase J, part 2): real API, auth, tenancy, DB."""
from __future__ import annotations

from sqlalchemy import select

from app.db.message_models import DirectMessage
from app.db.models import User
from tests.test_marketing_analytics_e2e import run

API = "/api/v1/messages"


def uid(world, who):
    return world.users[who]["id"]


def send(world, frm, to, body="hello there"):
    return world.client.post(f"{API}/with/{uid(world, to)}", json={"body": body}, headers=world.auth(frm))


def thread(world, who, other):
    return world.client.get(f"{API}/with/{uid(world, other)}", headers=world.auth(who))


def rows(world):
    async def go():
        async with world.maker() as s:
            return (await s.execute(select(DirectMessage))).scalars().all()
    return run(go())


class TestSendAndRead:
    def test_members_can_talk_and_unread_tracks(self, world):
        assert send(world, "a_employee", "a_admin", "Can you approve my leave?").status_code == 201
        assert world.client.get(f"{API}/unread-count", headers=world.auth("a_admin")).json() == {"unread": 1}
        assert world.client.get(f"{API}/unread-count", headers=world.auth("a_employee")).json() == {"unread": 0}
        convs = world.client.get(f"{API}/conversations", headers=world.auth("a_admin")).json()
        assert convs[0]["user_id"] == uid(world, "a_employee") and convs[0]["unread"] == 1 and "approve my leave" in convs[0]["last_body"]
        t = thread(world, "a_admin", "a_employee").json()
        assert [m["body"] for m in t["messages"]] == ["Can you approve my leave?"] and t["messages"][0]["from_me"] is False
        assert world.client.get(f"{API}/unread-count", headers=world.auth("a_admin")).json() == {"unread": 0}
        send(world, "a_admin", "a_employee", "Approved.")
        t2 = thread(world, "a_employee", "a_admin").json()
        assert [m["from_me"] for m in t2["messages"]] == [True, False]

    def test_reading_your_own_sent_messages_does_not_mark_the_other_sides_as_read(self, world):
        send(world, "a_employee", "a_admin")
        thread(world, "a_employee", "a_admin")
        assert world.client.get(f"{API}/unread-count", headers=world.auth("a_admin")).json()["unread"] == 1

    def test_opening_one_thread_leaves_other_senders_unread(self, world):
        async def mk():
            async with world.maker() as s:
                s.add(User(id="m3", tenant_id=world.tenant_a, email="m3@a.test", name="Third", hashed_password="x", role="Employee"))
                await s.commit()
        run(mk())
        send(world, "a_employee", "a_admin", "from employee")
        async def other():
            async with world.maker() as s:
                s.add(DirectMessage(id="dm-x", tenant_id=world.tenant_a, sender_id="m3", recipient_id=uid(world, "a_admin"), body="from third"))
                await s.commit()
        run(other())
        thread(world, "a_admin", "a_employee")
        assert world.client.get(f"{API}/unread-count", headers=world.auth("a_admin")).json()["unread"] == 1

    def test_sender_comes_from_the_token(self, world):
        r = world.client.post(f"{API}/with/{uid(world, 'a_admin')}", json={"body": "hi", "sender_id": uid(world, "b_admin")}, headers=world.auth("a_employee"))
        assert r.status_code == 201
        (m,) = rows(world)
        assert m.sender_id == uid(world, "a_employee") and m.tenant_id == world.tenant_a

    def test_validation(self, world):
        assert send(world, "a_employee", "a_employee").status_code == 400
        assert send(world, "a_employee", "a_admin", "").status_code == 422
        assert send(world, "a_employee", "a_admin", "x" * 2001).status_code == 422
        assert send(world, "a_employee", "a_admin", "\x00\x07  ").status_code == 400
        assert send(world, "a_employee", "a_admin", "a\x00b").status_code == 201 and rows(world)[0].body == "ab"

    def test_body_is_returned_as_plain_text_not_interpreted(self, world):
        send(world, "a_employee", "a_admin", "<img src=x onerror=alert(1)>")
        assert thread(world, "a_admin", "a_employee").json()["messages"][0]["body"] == "<img src=x onerror=alert(1)>"


class TestPrivacyAndTenancy:
    def test_admin_cannot_read_other_peoples_conversations(self, world):
        async def mk():
            async with world.maker() as s:
                s.add(User(id="m3", tenant_id=world.tenant_a, email="m3@a.test", name="Third", hashed_password="x", role="Employee"))
                await s.commit()
        run(mk())
        world.client.post(f"{API}/with/m3", json={"body": "secret between employees"}, headers=world.auth("a_employee"))
        # the admin's view of the same pair is the admin's own (empty) conversation with that person
        t = world.client.get(f"{API}/with/{uid(world, 'a_employee')}", headers=world.auth("a_admin")).json()
        assert t["messages"] == []
        assert world.client.get(f"{API}/conversations", headers=world.auth("a_admin")).json() == []
        assert "secret between employees" not in world.client.get(f"{API}/with/m3", headers=world.auth("a_admin")).text

    def test_other_company_is_invisible(self, world):
        assert send(world, "a_employee", "b_admin").status_code == 404
        assert thread(world, "a_employee", "b_admin").status_code == 404
        ids = [p["id"] for p in world.client.get(f"{API}/people", headers=world.auth("a_admin")).json()]
        assert uid(world, "b_admin") not in ids and uid(world, "a_admin") not in ids and uid(world, "a_employee") in ids
        assert rows(world) == []

    def test_requires_login(self, world):
        assert world.client.get(f"{API}/people").status_code == 401
        assert world.client.post(f"{API}/with/x", json={"body": "hi"}).status_code == 401

    def test_cannot_message_a_deactivated_person_but_history_stays_readable(self, world):
        send(world, "a_employee", "a_admin", "before")
        world.client.post(f"/api/v1/team/members/{uid(world, 'a_employee')}/deactivate", headers=world.auth("a_admin"))
        assert send(world, "a_admin", "a_employee", "after").status_code == 404
        t = thread(world, "a_admin", "a_employee").json()
        assert t["peer"]["active"] is False and [m["body"] for m in t["messages"]] == ["before"]
        assert uid(world, "a_employee") not in [p["id"] for p in world.client.get(f"{API}/people", headers=world.auth("a_admin")).json()]
        assert world.client.get(f"{API}/conversations", headers=world.auth("a_admin")).json()[0]["active"] is False


def test_messages_migration_is_additive_and_reversible():
    import pathlib, re
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("migrations/versions/e8f2a37b9c45_add_direct_messages.py").read_text()
    assert 'down_revision: Union[str, None] = "d7e1f26a8b34"' in src and "drop_table" in src and not re.search(r"drop_column|alter_column", src)
