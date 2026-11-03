"""
Execution records and per-tool performance, computed from real execution history (no estimates).

record() writes one ToolExecution in its own savepoint so a metrics problem never breaks the user's request.
stats() aggregates success rate, latency, timeouts, retries, last success/failure and error categories.
hints() turns recent history into short notes for tool selection (e.g. "unreliable lately: 4 of the last 5 failed").
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.toolhub_models import ToolExecution

logger = logging.getLogger(__name__)

_SECRETISH = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\W{0,6}(?:bearer\s+)?[\w\-\.]{6,}")


def summarise(value: Any, limit: int = 300) -> str:
    """Short, secret-scrubbed summary of tool input/output for the execution monitor."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = _SECRETISH.sub(lambda m: m.group(1) + "=***", " ".join(str(text).split()))
    return text[:limit] + ("…" if len(text) > limit else "")


async def record(db: AsyncSession, *, tenant_id: str, tool_key: str, role_key: str, status: str,
                 duration_ms: int, tool_label: str = "", tool_source: str = "builtin", plan_id: str | None = None,
                 error_category: str | None = None, error_message: str | None = None, retries: int = 0,
                 recovery: str | None = None, input_value: Any = "", output_value: Any = "") -> None:
    try:
        async with db.begin_nested():
            db.add(ToolExecution(
                tenant_id=tenant_id, tool_key=tool_key[:255], tool_label=(tool_label or tool_key)[:200],
                tool_source=tool_source[:16], role_key=role_key[:128], plan_id=plan_id, status=status,
                error_category=error_category, error_message=summarise(error_message, 500) if error_message else None,
                duration_ms=max(0, int(duration_ms)), retries=retries, recovery=(recovery or None),
                input_summary=summarise(input_value), output_summary=summarise(output_value),
            ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tool execution record failed (non-fatal): %s", exc)


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def stats(db: AsyncSession, tenant_id: str, *, since_days: int = 30, tool_key: str | None = None) -> list[dict]:
    """Per-tool performance over the last `since_days` days, worst success rate first."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    stmt = select(ToolExecution).where(ToolExecution.tenant_id == tenant_id, ToolExecution.started_at >= since)
    if tool_key:
        stmt = stmt.where(ToolExecution.tool_key == tool_key)
    rows = (await db.execute(stmt.order_by(ToolExecution.started_at).limit(20000))).scalars().all()
    by: dict[str, dict] = {}
    for r in rows:
        s = by.setdefault(r.tool_key, {"tool_key": r.tool_key, "label": r.tool_label, "source": r.tool_source,
                                       "total": 0, "success": 0, "failed": 0, "blocked": 0, "timeouts": 0,
                                       "retries": 0, "duration_total": 0, "last_success": None,
                                       "last_failure": None, "last_error": None, "errors": {}, "recent": []})
        s["total"] += 1
        s["duration_total"] += r.duration_ms
        s["retries"] += r.retries
        s["recent"] = (s["recent"] + [r.status])[-5:]
        if r.status == "success":
            s["success"] += 1
            s["last_success"] = _aware(r.started_at)
        else:
            s["failed" if r.status == "failed" else "blocked"] += 1
            s["last_failure"] = _aware(r.started_at)
            s["last_error"] = r.error_message
            cat = r.error_category or "execution_error"
            s["errors"][cat] = s["errors"].get(cat, 0) + 1
            if cat == "timeout":
                s["timeouts"] += 1
    out = []
    for s in by.values():
        s["success_rate"] = round(s["success"] / s["total"], 3) if s["total"] else None
        s["avg_ms"] = round(s.pop("duration_total") / s["total"]) if s["total"] else 0
        s["degraded"] = len(s["recent"]) >= 3 and all(x != "success" for x in s["recent"][-3:])
        for k in ("last_success", "last_failure"):
            s[k] = s[k].isoformat() if s[k] else None
        out.append(s)
    return sorted(out, key=lambda s: (s["success_rate"] if s["success_rate"] is not None else 1, -s["total"]))


async def hints(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    """tool_key → a short note for the model when a tool has a meaningful record (used in tool selection)."""
    notes: dict[str, str] = {}
    for s in await stats(db, tenant_id, since_days=7):
        if s["total"] < 3:
            continue
        if s["degraded"]:
            notes[s["tool_key"]] = (f"Unreliable lately: the last {len(s['recent'])} calls mostly failed "
                                    f"({', '.join(sorted(s['errors']))}); prefer an equivalent tool if one exists.")
        elif s["success_rate"] is not None and s["success_rate"] >= 0.9:
            notes[s["tool_key"]] = f"Reliable: {round(s['success_rate'] * 100)}% success, about {s['avg_ms']} ms."
        elif s["avg_ms"] > 15000:
            notes[s["tool_key"]] = f"Slow: about {round(s['avg_ms'] / 1000)} s per call."
    return notes
