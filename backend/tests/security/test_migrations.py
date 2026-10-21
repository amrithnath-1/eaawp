"""
Migration compatibility for the Phase 2 schema change (oauth_states.initiated_by_user_id):
clean database, and an existing database that already holds OAuth state rows.
Runs the real Alembic CLI against throw-away SQLite files.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
PREVIOUS = "u8v2w37x9y15"
HEAD = "a0b4c59d1e67"


def alembic(db: pathlib.Path, *args: str) -> str:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "SECRET_KEY": "m" * 40, "GEMINI_API_KEY": "x"}
    out = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                         capture_output=True, text=True, timeout=240)
    assert out.returncode == 0, f"alembic {' '.join(args)} failed:\n{out.stdout[-800:]}\n{out.stderr[-800:]}"
    return out.stdout + out.stderr


def cols(db, table):
    with sqlite3.connect(db) as c:
        return {r[1]: r for r in c.execute(f"pragma table_info({table})")}


def test_single_alembic_head():
    heads = [l for l in alembic(pathlib.Path(os.devnull), "heads").splitlines() if "(head)" in l]
    assert len(heads) == 1 and heads[0].startswith(HEAD)


def test_clean_database_upgrades_to_head(tmp_path):
    db = tmp_path / "clean.db"
    alembic(db, "upgrade", "head")
    assert HEAD in alembic(db, "current")
    c = cols(db, "oauth_states")
    assert "initiated_by_user_id" in c and c["initiated_by_user_id"][3] == 0   # nullable
    with sqlite3.connect(db) as con:
        fks = list(con.execute("pragma foreign_key_list(oauth_states)"))
    assert any(fk[2] == "users" and fk[3] == "initiated_by_user_id" and fk[6] == "SET NULL" for fk in fks), fks


def test_existing_database_with_oauth_states_keeps_its_rows(tmp_path):
    db = tmp_path / "existing.db"
    alembic(db, "upgrade", PREVIOUS)
    assert "initiated_by_user_id" not in cols(db, "oauth_states")

    with sqlite3.connect(db) as con:
        con.execute("insert into companies(id,name,industry,region,employees,is_active) values('t1','Co','x','x',1,1)")
        for i, used in enumerate((0, 1)):
            con.execute(
                "insert into oauth_states(id,state_token,tenant_id,integration_id,provider_type,expires_at,used,created_at) "
                "values (?,?,?,?,?,?,?,?)",
                (f"id-{i}", f"legacy-state-{i}", "t1", "int-1", "google_search_console",
                 "2099-01-01 00:00:00", used, "2026-10-01 00:00:00"))
        con.commit()

    alembic(db, "upgrade", "head")

    with sqlite3.connect(db) as con:
        rows = list(con.execute("select state_token, tenant_id, used, initiated_by_user_id from oauth_states order by id"))
        assert rows == [("legacy-state-0", "t1", 0, None), ("legacy-state-1", "t1", 1, None)]
        # the table rebuild (SQLite batch mode) must not lose the uniqueness of state tokens
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("insert into oauth_states(id,state_token,tenant_id,integration_id,provider_type,expires_at,used,created_at)"
                        " values ('dup','legacy-state-0','t1','x','p','2099-01-01',0,'2026-10-01')")


def test_downgrade_then_upgrade_round_trip_preserves_rows(tmp_path):
    db = tmp_path / "roundtrip.db"
    alembic(db, "upgrade", "head")
    with sqlite3.connect(db) as con:
        con.execute("insert into companies(id,name,industry,region,employees,is_active) values('t1','Co','x','x',1,1)")
        con.execute("insert into users(id,tenant_id,email,name,hashed_password,role,status,is_active) "
                    "values('u1','t1','a@x.test','A','h','Company Admin','Active',1)")
        con.execute("insert into oauth_states(id,state_token,tenant_id,initiated_by_user_id,integration_id,provider_type,expires_at,used,created_at) "
                    "values ('i','s1','t1','u1','int','p','2099-01-01',0,'2026-10-01')")
        con.commit()
    alembic(db, "downgrade", PREVIOUS)
    assert "initiated_by_user_id" not in cols(db, "oauth_states")
    with sqlite3.connect(db) as con:
        assert con.execute("select state_token from oauth_states").fetchall() == [("s1",)]
    alembic(db, "upgrade", "head")
    assert "initiated_by_user_id" in cols(db, "oauth_states")


def test_pending_tasks_migration_up_down_up(tmp_path):
    """The pending_tasks table is created, removed on downgrade, and recreated."""
    db = tmp_path / "pending.db"
    alembic(db, "upgrade", "head")
    c = cols(db, "pending_tasks")
    assert {"tenant_id", "user_id", "role_key", "prompt", "status", "requirement_json"} <= set(c)
    assert c["tenant_id"][3] == 1 and c["user_id"][3] == 1  # NOT NULL
    alembic(db, "downgrade", "v9w3x48y0z16")
    assert cols(db, "pending_tasks") == {}
    alembic(db, "upgrade", "head")
    assert "prompt" in cols(db, "pending_tasks")


def test_workflow_runs_migration_is_additive_and_reversible(tmp_path):
    """Run history table + new workflow columns: existing workflow rows survive up and down."""
    import sqlite3
    db = tmp_path / "wfruns.db"
    alembic(db, "upgrade", "w0x4y59z1a17")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO companies (id, name, industry, region, employees, is_active) VALUES ('t','T','x','x',1,1)")
    con.execute("INSERT INTO workflows (id, tenant_id, name, description, trigger, steps_json, is_enabled, status, created_by) "
                "VALUES ('w1','t','Weekly','', 'manual','[]',1,'idle','admin')")
    con.commit(); con.close()
    alembic(db, "upgrade", "head")
    wf_cols = cols(db, "workflows")
    assert {"role_name", "run_as_user_id", "timezone", "max_retries", "retry_delay_minutes"} <= set(wf_cols)
    run_cols = cols(db, "workflow_runs")
    assert {"workflow_id", "slot", "attempt", "status", "not_before", "plan_id"} <= set(run_cols)
    con = sqlite3.connect(db)
    assert con.execute("SELECT name, timezone, max_retries FROM workflows WHERE id='w1'").fetchone() == ("Weekly", "UTC", 0)
    # the unique (workflow, slot) constraint is what prevents duplicate runs
    con.execute("INSERT INTO workflow_runs (id, tenant_id, workflow_id, slot) VALUES ('r1','t','w1','2026-10-21T09:00')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO workflow_runs (id, tenant_id, workflow_id, slot) VALUES ('r2','t','w1','2026-10-21T09:00')")
    con.close()
    alembic(db, "downgrade", "w0x4y59z1a17")
    assert cols(db, "workflow_runs") == {}
    assert "role_name" not in cols(db, "workflows")
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM workflows WHERE id='w1'").fetchone() == ("Weekly",)
    con.close()


def test_meeting_room_migration_is_additive_and_reversible(tmp_path):
    """Three new tables; existing data (including workflows) survives up and down."""
    import sqlite3
    db = tmp_path / "meetings.db"
    alembic(db, "upgrade", "x1y5z60a2b18")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO companies (id, name, industry, region, employees, is_active) VALUES ('t','T','x','x',1,1)")
    con.execute("INSERT INTO workflows (id, tenant_id, name, description, trigger, steps_json, is_enabled, status, created_by) "
                "VALUES ('w1','t','Weekly','', 'manual','[]',1,'idle','admin')")
    con.commit(); con.close()
    alembic(db, "upgrade", "head")
    assert {"tenant_id", "objective", "status", "created_by"} <= set(cols(db, "meetings"))
    assert {"meeting_id", "role_key", "depends_on_json", "status", "result"} <= set(cols(db, "meeting_tasks"))
    assert {"meeting_id", "seq", "sender_kind", "content"} <= set(cols(db, "meeting_messages"))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO meetings (id, tenant_id, objective, created_by) VALUES ('m1','t','o','u')")
    con.execute("INSERT INTO meeting_tasks (id, meeting_id, tenant_id, role_key, role_name) VALUES ('k1','m1','t','R','R')")
    con.commit()
    assert con.execute("SELECT status FROM meetings WHERE id='m1'").fetchone() == ("planning",)
    con.close()
    alembic(db, "downgrade", "x1y5z60a2b18")
    assert cols(db, "meetings") == {} and cols(db, "meeting_tasks") == {} and cols(db, "meeting_messages") == {}
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM workflows WHERE id='w1'").fetchone() == ("Weekly",)
    con.close()


def test_employee_versions_migration_is_additive_and_reversible(tmp_path):
    import sqlite3
    db = tmp_path / "empver.db"
    alembic(db, "upgrade", "y2z6a71b3c19")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO companies (id, name, industry, region, employees, is_active) VALUES ('t','T','x','x',1,1)")
    con.execute("INSERT INTO ai_employees (id, tenant_id, role_key, name, status, is_active) VALUES ('e1','t','R','Emp','ACTIVE',1)")
    con.commit(); con.close()
    alembic(db, "upgrade", "head")
    assert {"ai_employee_id", "version", "status", "snapshot_json", "change_summary"} <= set(cols(db, "employee_versions"))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO employee_versions (id, tenant_id, ai_employee_id, version) VALUES ('v1','t','e1',1)")
    with pytest.raises(sqlite3.IntegrityError):                      # one row per (employee, version number)
        con.execute("INSERT INTO employee_versions (id, tenant_id, ai_employee_id, version) VALUES ('v2','t','e1',1)")
    con.close()
    alembic(db, "downgrade", "y2z6a71b3c19")
    assert cols(db, "employee_versions") == {}
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM ai_employees WHERE id='e1'").fetchone() == ("Emp",)
    con.close()


def test_datasets_migration_is_additive_and_reversible(tmp_path):
    import sqlite3
    db = tmp_path / "datasets.db"
    alembic(db, "upgrade", "z3a7b82c4d20")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO companies (id, name, industry, region, employees, is_active) VALUES ('t','T','x','x',1,1)")
    con.commit(); con.close()
    alembic(db, "upgrade", "head")
    assert {"tenant_id", "name", "content_csv", "columns_json", "row_count", "is_restricted"} <= set(cols(db, "datasets"))
    assert {"dataset_id", "spec_json", "result_json", "narrative", "narrative_source", "is_restricted"} <= set(cols(db, "analysis_reports"))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO datasets (id, tenant_id, name) VALUES ('d1','t','Sales')")
    con.commit(); con.close()
    alembic(db, "downgrade", "z3a7b82c4d20")
    assert cols(db, "datasets") == {} and cols(db, "analysis_reports") == {}
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM companies WHERE id='t'").fetchone() == ("T",)
    con.close()


def test_clerk_migration_is_additive_and_reversible(tmp_path):
    import sqlite3
    db = tmp_path / "clerk.db"
    alembic(db, "upgrade", "a4b8c93d5e21")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO companies (id, name, industry, region, employees, is_active) VALUES ('t','T','x','x',1,1)")
    con.commit(); con.close()
    alembic(db, "upgrade", "head")
    assert {"request_type", "status", "requester_id", "assignee_id", "decision_note"} <= set(cols(db, "service_requests"))
    assert {"request_id", "kind", "internal"} <= set(cols(db, "service_request_events"))
    assert {"serial", "status", "template_key", "fields_json"} <= set(cols(db, "issued_documents"))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO issued_documents (id, tenant_id, serial) VALUES ('d1','t','ACME-2026-00001')")
    with pytest.raises(sqlite3.IntegrityError):                      # serials are unique per company
        con.execute("INSERT INTO issued_documents (id, tenant_id, serial) VALUES ('d2','t','ACME-2026-00001')")
    con.execute("INSERT INTO issued_documents (id, tenant_id) VALUES ('d3','t')")       # drafts: no serial, many allowed
    con.execute("INSERT INTO issued_documents (id, tenant_id) VALUES ('d4','t')")
    con.commit(); con.close()
    alembic(db, "downgrade", "a4b8c93d5e21")
    assert cols(db, "service_requests") == {} and cols(db, "issued_documents") == {} and cols(db, "service_request_events") == {}
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM companies WHERE id='t'").fetchone() == ("T",)
    con.close()


def test_appointments_migration_is_additive_and_reversible(tmp_path):
    import sqlite3
    db = tmp_path / "appt.db"
    alembic(db, "upgrade", "b5c9d04e6f22")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO companies (id, name, industry, region, employees, is_active) VALUES ('t','T','x','x',1,1)")
    con.commit(); con.close()
    alembic(db, "upgrade", "head")
    assert {"patient_id", "reason", "status", "red_flag", "red_flags_json", "intake_json", "notes_json"} <= set(cols(db, "appointments"))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO appointments (id, tenant_id) VALUES ('a1','t')")
    con.commit(); con.close()
    alembic(db, "downgrade", "b5c9d04e6f22")
    assert cols(db, "appointments") == {}
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM companies WHERE id='t'").fetchone() == ("T",)
    con.close()
