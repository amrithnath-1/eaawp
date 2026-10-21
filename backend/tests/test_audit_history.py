"""Audit history (Phase M): filters, paging, CSV export. Admin-only, tenant-scoped, injection-safe, exported events are themselves audited."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import AuditLog
from tests.conftest import _run

A = "/api/v1/audit"


def add(w, tenant, event, actor="AI", department="workflows", status="ok", at=None):
    async def go():
        async with w.maker() as s:
            s.add(AuditLog(id=str(uuid.uuid4()), tenant_id=tenant, actor=actor, event=event, department=department, status=status,
                           **({"created_at": at} if at else {})))
            await s.commit()
    _run(go())


def get(w, who="a_admin", path=A, **params):
    return w.client.get(path, params=params, headers=w.auth(who))


def events(r):
    assert r.status_code == 200, r.text
    return [x["event"] for x in r.json()]


def test_text_search_actor_department_and_status_filters(world):
    add(world, world.tenant_a, "campaign launched", actor="AI", department="marketing", status="ok")
    add(world, world.tenant_a, "workflow failed badly", actor="workflow-runner", department="workflows", status="warning")
    add(world, world.tenant_a, "invoice issued", actor=world.users["a_employee"]["id"], department="clerk", status="ok")
    assert events(get(world, q="LAUNCH")) == ["campaign launched"]                         # case-insensitive
    assert events(get(world, actor="workflow-runner")) == ["workflow failed badly"]
    assert events(get(world, department="clerk")) == ["invoice issued"]
    assert events(get(world, status="warning")) == ["workflow failed badly"]
    assert events(get(world, status="warning", department="marketing")) == []              # filters combine (AND)
    assert events(get(world, q="nothing like this")) == []


def test_search_treats_percent_and_underscore_literally(world):
    add(world, world.tenant_a, "discount of 50% applied")
    add(world, world.tenant_a, "plain event")
    add(world, world.tenant_a, "snake_case name")
    assert events(get(world, q="%")) == ["discount of 50% applied"]                          # not "match everything"
    assert events(get(world, q="_")) == ["snake_case name"]
    assert events(get(world, q="a_e")) == []                                                 # "_" is not a wildcard


def test_date_range_is_inclusive_by_day_and_validated(world):
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    add(world, world.tenant_a, "old", at=now - timedelta(days=10))
    add(world, world.tenant_a, "mid", at=now - timedelta(days=3))
    add(world, world.tenant_a, "new", at=now)
    d = lambda n: (now - timedelta(days=n)).strftime("%Y-%m-%d")
    assert events(get(world, since=d(5))) == ["new", "mid"]
    assert events(get(world, until=d(3))) == ["mid", "old"]                                  # the 'until' day is included
    assert events(get(world, since=d(3), until=d(3))) == ["mid"]
    assert get(world, since="not-a-date").status_code == 422
    assert get(world, until="2026-13-45").status_code == 422


def test_paging_is_stable_complete_and_bounded(world):
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(25):
        add(world, world.tenant_a, f"e{i:02d}", at=base + timedelta(minutes=i))
    p1, p2, p3 = (events(get(world, limit=10, offset=o)) for o in (0, 10, 20))
    assert [len(p1), len(p2), len(p3)] == [10, 10, 5]
    assert p1 + p2 + p3 == [f"e{i:02d}" for i in range(24, -1, -1)]                           # newest first, no gaps, no repeats
    assert get(world, offset=-1).status_code == 422 and get(world, offset=10**9).status_code == 422
    assert get(world, limit=501).status_code == 422


def test_filters_never_cross_companies(world):
    add(world, world.tenant_b, "secret B campaign", department="marketing")
    add(world, world.tenant_a, "A campaign", department="marketing")
    assert events(get(world, q="campaign")) == ["A campaign"]
    assert events(get(world, who="b_admin", q="campaign")) == ["secret B campaign"]
    assert "secret B" not in get(world, path=f"{A}/export").text


def test_employees_cannot_filter_or_export(world):
    add(world, world.tenant_a, "private thing")
    for path in (A, f"{A}/export"):
        r = get(world, "a_employee", path=path, q="private")
        assert r.status_code == 403 and "private thing" not in r.text
    assert world.client.get(f"{A}/export").status_code in (401, 403)


def rows_of(r):
    assert r.status_code == 200, r.text
    return list(csv.reader(io.StringIO(r.text)))


def test_csv_export_content_headers_and_filters(world):
    add(world, world.tenant_a, "campaign launched", actor=world.users["a_admin"]["id"], department="marketing")
    add(world, world.tenant_a, "other event", department="workflows")
    r = get(world, path=f"{A}/export", department="marketing")
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    rows = rows_of(r)
    assert rows[0] == ["time_utc", "actor", "actor_id", "event", "department", "status"]
    assert len(rows) == 2 and rows[1][1] == "a_admin" and rows[1][3] == "campaign launched" and rows[1][4] == "marketing"
    assert rows[1][0].endswith("+00:00")


def test_csv_export_blocks_spreadsheet_formula_injection(world):
    add(world, world.tenant_a, '=HYPERLINK("http://evil.example","click")')
    add(world, world.tenant_a, "+1 555 call me", actor="-cmd")
    add(world, world.tenant_a, "@SUM(A1)", department="=1+1")
    add(world, world.tenant_a, 'has "quotes", commas,\nand a newline')
    body = rows_of(get(world, path=f"{A}/export"))[1:]
    cells = [c for row in body for c in row[1:]]
    assert not [c for c in cells if c[:1] in "=+-@\t\r"], cells                               # nothing a spreadsheet would execute
    assert any(c == "'=HYPERLINK(\"http://evil.example\",\"click\")" for c in cells)
    assert any(c == 'has "quotes", commas,\nand a newline' for c in cells)                  # normal text survives intact


def test_csv_export_is_bounded_and_itself_audited(world, monkeypatch):
    from app.api.routers import audit as mod
    monkeypatch.setattr(mod, "EXPORT_MAX_ROWS", 3)
    for i in range(6):
        add(world, world.tenant_a, f"row {i}")
    assert len(rows_of(get(world, path=f"{A}/export"))) == 1 + 3
    async def ev():
        async with world.maker() as s:
            return [a.event for a in (await s.execute(select(AuditLog).where(AuditLog.department == "audit"))).scalars().all()]
    assert _run(ev()) == ["exported the audit log (3 rows)"]
