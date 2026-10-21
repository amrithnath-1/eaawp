"""
Is the database at the schema revision this code expects?

A database that is behind the code (a new table or column added by a later
migration is missing) otherwise surfaces as an opaque 500 on whichever page
first touches the new table.  These helpers let startup, /health and the error
handler say what is actually wrong and how to fix it - without ever running a
migration automatically.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

MIGRATE_HINT = "Back up the database file, then run:  python -m alembic upgrade head   (from the backend folder)."

# Messages SQLite / PostgreSQL / MySQL produce for a missing table or column.
_SCHEMA_ERROR = re.compile(
    r"no such (table|column)|undefined ?(table|column)|does not exist|unknown column|doesn't exist"
    r"|has no column named",
    re.I,
)


def expected_head() -> str:
    """Latest revision in the migration scripts shipped with this code."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head() or ""


async def current_revision(engine) -> str | None:
    """The revision recorded in the database, or None if it was never stamped."""
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).first()
            return row[0] if row else None
    except SQLAlchemyError:
        return None


async def schema_status(engine) -> dict[str, object]:
    head = expected_head()
    current = await current_revision(engine)
    return {"current": current, "expected": head, "up_to_date": current == head}


def is_schema_error(exc: BaseException) -> bool:
    """True when a DB exception means 'a table/column this code needs is missing'."""
    orig = getattr(exc, "orig", None)
    return bool(_SCHEMA_ERROR.search(str(orig if orig is not None else exc)))


def safe_db_error_text(exc: BaseException) -> str:
    """Driver message only - never the SQL parameters SQLAlchemy appends to str(exc)."""
    orig = getattr(exc, "orig", None)
    return (str(orig) if orig is not None else type(exc).__name__)[:300]
