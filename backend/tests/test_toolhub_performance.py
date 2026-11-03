"""
Suite I — performance of the tool hub with real components (sandbox processes, SQLite database, registry sync).
Limits are generous (CI machines vary); the measured times are printed with -s.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

from app.db.toolhub_models import ToolExecution
from app.toolhub import mcp_sync, metrics, sandbox
from tests.conftest import _run

CODE = "import statistics\ndef run(i):\n    return {'mean': statistics.mean(i['xs'])}\n"


def test_concurrent_sandbox_executions():
    async def go():
        t0 = time.monotonic()
        res = await asyncio.gather(*(sandbox.run(CODE, {"xs": list(range(n, n + 1000))}) for n in range(12)))
        return res, time.monotonic() - t0
    res, took = _run(go())
    assert all(r.ok for r in res) and [r.output["mean"] for r in res] == [n + 499.5 for n in range(12)]
    print(f"12 concurrent sandbox runs: {took:.2f}s")
    assert took < 20


def test_large_registry_sync_and_change_detection(world):
    tools = [{"name": f"tool_{i}", "description": f"does thing {i}",
              "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}} for i in range(500)]

    async def go():
        async with world.maker() as db:
            t0 = time.monotonic()
            first = await mcp_sync.sync(db, world.tenant_a, "11111111-1111-1111-1111-111111111111", tools)
            t1 = time.monotonic()
            changed = [dict(t, description="changed") if i % 10 == 0 else t for i, t in enumerate(tools[:-20])]
            second = await mcp_sync.sync(db, world.tenant_a, "11111111-1111-1111-1111-111111111111", changed)
            t2 = time.monotonic()
            await db.commit()
            return first, second, t1 - t0, t2 - t1
    first, second, a, b = _run(go())
    print(f"sync 500 tools: {a:.2f}s; re-sync with 48 changed / 20 removed: {b:.2f}s")
    assert len(first["added"]) == 500 and len(second["changed"]) == 48 and len(second["removed"]) == 20
    assert a < 10 and b < 10


def test_metrics_over_thousands_of_executions(world):
    async def go():
        async with world.maker() as db:
            now = datetime.now(timezone.utc)
            for i in range(3000):
                db.add(ToolExecution(tenant_id=world.tenant_a, tool_key=f"t{i % 40}", role_key="DIGITAL_MARKETING_MANAGER",
                                     status="success" if i % 7 else "failed", error_category=None if i % 7 else "timeout",
                                     duration_ms=100 + i % 50, started_at=now - timedelta(minutes=i)))
            await db.commit()
            t0 = time.monotonic()
            s = await metrics.stats(db, world.tenant_a)
            h = await metrics.hints(db, world.tenant_a)
            return s, h, time.monotonic() - t0
    s, h, took = _run(go())
    print(f"stats + hints over 3000 executions: {took:.2f}s")
    assert len(s) == 40 and sum(x["total"] for x in s) == 3000 and took < 5
