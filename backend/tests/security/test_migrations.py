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
HEAD = "w0x4y59z1a17"


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
