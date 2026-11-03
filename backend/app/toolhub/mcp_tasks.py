"""
Long-running MCP operations (jobs): recognised, recorded, followed, finished — for any server.

Some MCP tools do not return their result: they start a job and return its identifier ("This call returns only a job
ID … read it with <x>_status"). Following such a job reliably needs facts, not guesses:

* Recognising a job: the result carries an identifier (id / jobId / taskId / operationId …) AND a non-terminal
  status, or the tool's own description says it returns a job ID; MCP-native tasks (result.task) are recognised too.
* The status mechanism: the server's own status tool, found among its tools by name (e.g. firecrawl_agent →
  firecrawl_agent_status, firecrawl_crawl → firecrawl_check_crawl_status) and by schema: its required id-like input
  tells which field of the start result to send. A thread id, conversation id or session id is never used as the
  job id unless the status tool itself asks for that field. MCP-native tasks use tasks/get and tasks/result.
* Lifecycle: CREATED → QUEUED / RUNNING → COMPLETED | FAILED | CANCELLED | TIMED_OUT | EXPIRED.
    - TIMED_OUT: our deadline (mcp_task_max_duration_s) passed; we stop polling, the job may still finish remotely.
    - EXPIRED:   the server no longer knows the id (404 / not found / unknown / expired): never polled again.
    - a failed STATUS CHECK (timeout, 5xx) is a polling failure, counted on the task; it is not a job failure.
    - FAILED:    the job itself reported failure.
* Polling: the server's pollInterval if given, else mcp_task_poll_initial_s, growing ×1.6 up to mcp_task_poll_max_s;
  one chat answer waits at most mcp_task_turn_wait_s, then reports the job as running. The background poller
  (start_poller) continues — also after a restart, because tasks and their next poll time are in the database.
* No duplicates: the same tool with the same inputs while a job is active (or finished within
  mcp_task_dedupe_window_s) returns the existing job instead of starting it again.
* Cancel: through the server's cancel tool when it has one (or tasks/cancel), never by guessing.
* Permissions: polling uses the status tool, which the role must also be granted (no bypass).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.toolhub_models import McpTask

logger = logging.getLogger(__name__)

ACTIVE = ("CREATED", "QUEUED", "RUNNING")
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "EXPIRED")
_ID_FIELDS = ("id", "jobId", "job_id", "taskId", "task_id", "operationId", "operation_id", "runId", "run_id",
              "crawlId", "batchId", "requestId")
_NOT_JOB_IDS = {"threadid", "thread_id", "conversationid", "sessionid", "session_id", "scrapeid", "requestid"}
_RUNNING = {"processing", "pending", "queued", "running", "started", "scraping", "in_progress", "in-progress",
            "working", "created", "accepted", "submitted", "active", "waiting"}
_DONE = {"completed", "complete", "done", "succeeded", "success", "finished"}
_FAILED = {"failed", "error", "errored"}
_CANCELLED = {"cancelled", "canceled", "aborted", "stopped"}
_EXPIRED_TEXT = re.compile(r"\b404\b|not found|no such (job|task)|unknown (job|task|id)|expired|does not exist|"
                           r"invalid (job|task) id", re.I)
_JOB_DESC = re.compile(r"returns? (only )?(a|the) (job|task|operation|run) id|asynchronous|async job|"
                       r"check (its|the) status|poll", re.I)
RESULT_CHARS = 12_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def args_hash(tool: str, args: dict) -> str:
    return hashlib.sha256(json.dumps({"t": tool, "a": args}, sort_keys=True, default=str).encode()).hexdigest()


def _parse(text: str) -> Any:
    t = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except ValueError:
        start = t.find("{")
        if start >= 0:
            try:
                return json.loads(t[start:t.rfind("}") + 1])
            except ValueError:
                return None
    return None


def _status_of(obj: dict) -> str | None:
    for k in ("status", "state", "jobStatus", "job_status"):
        v = obj.get(k)
        if isinstance(v, str):
            return v.strip().lower()
    return None


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


# ── Recognising a job and its status mechanism ────────────────────────────────

async def _server_tools(db: AsyncSession, tenant_id: str, integration_id: str) -> dict[str, dict]:
    from app.db.toolhub_models import ToolRecord
    res = await db.execute(select(ToolRecord).where(
        ToolRecord.tenant_id == tenant_id, ToolRecord.integration_id == integration_id, ToolRecord.source == "mcp",
        ToolRecord.status == "active"))
    return {r.key: {"schema": json.loads(r.input_schema_json or "{}"), "description": r.description or ""}
            for r in res.scalars()}


def _sibling(start: str, tools: dict[str, dict], word: str) -> str | None:
    """The tool named like the start tool plus `word` (status / cancel), e.g. x_agent → x_agent_status."""
    st = set(_tokens(start))
    best, score = None, 0.0
    for name in tools:
        toks = _tokens(name)
        if name == start or word not in toks:
            continue
        rest = [t for t in toks if t not in (word, "check", "get")]
        if not rest:
            continue
        overlap = len(st & set(rest)) / max(len(set(rest)), 1)
        if overlap > score:
            best, score = name, overlap
    return best if score >= 0.99 else None


def _id_param(schema: dict) -> str | None:
    from app.toolhub import mcp_schema
    req = mcp_schema.required_of(schema)
    props = (mcp_schema.resolved(schema).get("properties") or {})
    cands = req or list(props)
    for p in cands:
        if p.lower() in {f.lower() for f in _ID_FIELDS} or p.lower().endswith("id"):
            return p
    return cands[0] if len(cands) == 1 else None


def recognise(start_tool: str, description: str, text: str, tools: dict[str, dict]) -> dict | None:
    """If `text` (a tool result) is a started job, how to follow it; else None."""
    obj = _parse(text)
    if not isinstance(obj, dict):
        return None
    inner = obj.get("data") if isinstance(obj.get("data"), dict) and not _status_of(obj) and not any(
        k in obj for k in _ID_FIELDS) else obj
    task = inner.get("task") if isinstance(inner.get("task"), dict) else None
    if task and isinstance(task.get("taskId"), str):          # MCP-native task
        return {"mechanism": "mcp_tasks", "remote_id": task["taskId"], "field": "taskId",
                "remote_status": str(task.get("status") or "working").lower(),
                "poll_s": (task.get("pollInterval") or 0) / 1000 or None, "status_tool": None, "param": None,
                "cancel_tool": None}
    status = _status_of(inner)
    if status in _DONE | _FAILED:
        return None
    status_tool = _sibling(start_tool, tools, "status")
    if not status_tool:
        return None
    # A job: a non-terminal status, the tool says it returns a job id, or — with a sibling status tool — a small
    # acknowledgement carrying an id and no content.
    has_id = any(isinstance(inner.get(k), (str, int)) for k in _ID_FIELDS if k.lower() not in _NOT_JOB_IDS)
    small_ack = has_id and len(inner) <= 8 and not any(
        k in inner for k in ("markdown", "content", "results", "data", "html", "items", "pages"))
    if not (status in _RUNNING or _JOB_DESC.search(description or "") or small_ack):
        return None
    param = _id_param(tools[status_tool]["schema"])
    if not param:
        return None
    # The value the status tool asks for: the field of the same name, else the start result's own job id.
    value, field = None, None
    for k, v in inner.items():
        if k.lower() == param.lower() and isinstance(v, (str, int)):
            value, field = str(v), k
    if value is None and param.lower() not in _NOT_JOB_IDS:
        for k in _ID_FIELDS:
            if k.lower() in _NOT_JOB_IDS:
                continue
            if isinstance(inner.get(k), (str, int)):
                value, field = str(inner[k]), k
                break
    if value is None:
        return None
    return {"mechanism": "tool", "remote_id": value, "field": field, "remote_status": status or "started",
            "poll_s": None, "status_tool": status_tool, "param": param,
            "cancel_tool": _sibling(start_tool, tools, "cancel")}


# ── Records ───────────────────────────────────────────────────────────────────

async def find_duplicate(db: AsyncSession, tenant_id: str, integration_id: str, tool: str, args: dict
                         ) -> McpTask | None:
    h = args_hash(tool, args)
    since = _now() - timedelta(seconds=settings.mcp_task_dedupe_window_s)
    rows = (await db.execute(select(McpTask).where(
        McpTask.tenant_id == tenant_id, McpTask.integration_id == integration_id, McpTask.start_tool == tool,
        McpTask.args_hash == h).order_by(McpTask.created_at.desc()).limit(1))).scalars().all()
    for t in rows:
        if t.state in ACTIVE or (t.state == "COMPLETED" and (_aware(t.completed_at) or _now()) >= since):
            return t
    return None


def describe(t: McpTask) -> str:
    head = f"[TASK {t.state}] job {t.remote_id} from {t.start_tool} (EAAWP task {t.id})"
    if t.state == "COMPLETED":
        return f"{head}. Result:\n{(t.result_text or '')[:RESULT_CHARS]}"
    if t.state in ACTIVE:
        return (f"{head} is still running on the server (status '{t.remote_status or 'started'}', checked "
                f"{t.poll_count} time(s)). EAAWP keeps checking; the result is kept when it finishes. Tell the "
                f"person it is running; they can ask again later.")
    reason = {"FAILED": "the job reported a failure", "CANCELLED": "the job was cancelled",
              "TIMED_OUT": f"it did not finish within {settings.mcp_task_max_duration_s} s, so EAAWP stopped "
                           "checking (it may still finish on the server)",
              "EXPIRED": "the server no longer knows this job id (expired or not found); it will not be checked "
                         "again"}[t.state]
    return f"{head}: {reason}." + (f" Detail: {t.error[:400]}" if t.error else "")


async def report_existing(db: AsyncSession, t: McpTask) -> str:
    if t.state in ACTIVE:
        await poll_once(db, t)
    return ("[DUPLICATE PREVENTED] The same request was already started; nothing was started again.\n"
            + describe(t))


async def after_call(db: AsyncSession, tenant_id: str, role_key: str, plan_id: str | None, p: Any,
                     text: str) -> str:
    """A tool result: plain data, or a started job (recorded, then followed for up to the per-answer wait)."""
    tools = await _server_tools(db, tenant_id, p.integration_id)
    how = recognise(p.tool_name, p.description, text, tools)
    if how is None:
        return text
    now = _now()
    t = McpTask(tenant_id=tenant_id, integration_id=p.integration_id, role_key=role_key, plan_id=plan_id,
                start_tool=p.tool_name, args_hash=args_hash(p.tool_name, p.args),
                args_summary=json.dumps(p.args, ensure_ascii=False, default=str)[:500], mechanism=how["mechanism"],
                status_tool=how["status_tool"], status_param=how["param"], cancel_tool=how["cancel_tool"],
                remote_id=how["remote_id"][:255], remote_id_field=how["field"] or "id", state="RUNNING",
                remote_status=how["remote_status"][:64], deadline_at=now + timedelta(
                    seconds=settings.mcp_task_max_duration_s),
                next_poll_at=now + timedelta(seconds=how["poll_s"] or settings.mcp_task_poll_initial_s))
    db.add(t)
    await db.flush()
    logger.info("MCP job started: task=%s tool=%s remote_field=%s status_tool=%s", t.id, t.start_tool,
                t.remote_id_field, t.status_tool or t.mechanism)
    await wait(db, t, settings.mcp_task_turn_wait_s, first_delay=how["poll_s"])
    return describe(t)


# ── Polling ───────────────────────────────────────────────────────────────────

def _next_delay(t: McpTask, base: float | None = None) -> float:
    d = (base or settings.mcp_task_poll_initial_s) * (1.6 ** min(t.poll_count, 8))
    return min(d, settings.mcp_task_poll_max_s)


def _apply(t: McpTask, status: str | None, text: str) -> None:
    t.remote_status = (status or t.remote_status or "")[:64]
    if status in _DONE:
        t.state, t.result_text, t.completed_at = "COMPLETED", text[:RESULT_CHARS * 4], _now()
    elif status in _FAILED:
        t.state, t.error, t.completed_at = "FAILED", text[:2000], _now()
    elif status in _CANCELLED:
        t.state, t.error, t.completed_at = "CANCELLED", text[:500], _now()
    else:
        t.state = "QUEUED" if status in ("queued", "pending", "waiting", "submitted") else "RUNNING"


async def _credentials(db: AsyncSession, t: McpTask) -> tuple[dict | None, str | None]:
    from app.db.integration_models import Integration
    from app.integrations.manager import MCP_TOOL_PREFIX, _decrypt_credentials, has_capability_grant
    row = (await db.execute(select(Integration).where(
        Integration.id == t.integration_id, Integration.tenant_id == t.tenant_id))).scalar_one_or_none()
    if row is None or row.status != "connected" or not row.is_enabled:
        return None, "the MCP server is no longer connected"
    if t.mechanism == "tool":
        for cap in ("call_tool", f"{MCP_TOOL_PREFIX}{t.status_tool}"):
            if not await has_capability_grant(integration_id=row.id, role_key=t.role_key, capability_key=cap,
                                              tenant_id=t.tenant_id, db=db):
                return None, (f"this AI employee has not been granted the status tool '{t.status_tool}', so the "
                              "job cannot be checked; an administrator can grant it")
    return _decrypt_credentials(row.encrypted_credentials), None


async def poll_once(db: AsyncSession, t: McpTask) -> McpTask:
    """One status check. Terminal tasks are never checked again."""
    if t.state in TERMINAL:
        return t
    now = _now()
    if now >= _aware(t.deadline_at):
        t.state, t.completed_at, t.updated_at = "TIMED_OUT", now, now
        t.error = t.error or f"no final status within {settings.mcp_task_max_duration_s} s"
        await db.flush()
        return t
    creds, why = await _credentials(db, t)
    if creds is None:
        t.last_poll_error, t.updated_at = why, now
        t.poll_failures += 1
        t.next_poll_at = now + timedelta(seconds=settings.mcp_task_poll_max_s)
        await db.flush()
        return t
    from app.integrations.providers.mcp_provider import MCPError, MCPIntegrationProvider, result_text_of
    provider = MCPIntegrationProvider()
    t.poll_count += 1
    try:
        if t.mechanism == "mcp_tasks":
            got = await provider.request(creds, "tasks/get", {"taskId": t.remote_id})
            status = str(got.get("status") or "").lower()
            text = json.dumps(got, ensure_ascii=False, default=str)
            if status in _DONE:
                res = await provider.request(creds, "tasks/result", {"taskId": t.remote_id})
                text, is_err = result_text_of(res)
                status = "failed" if is_err else "completed"
        else:
            res = await provider.request(creds, "tools/call", {"name": t.status_tool,
                                                               "arguments": {t.status_param: t.remote_id}})
            text, is_err = result_text_of(res)
            if is_err:
                raise MCPError(text or "status tool reported an error")
            obj = _parse(text)
            # The status is on the envelope ({"status": …, "data": {…}}) or inside data ({"data": {"status": …}}).
            status = None
            if isinstance(obj, dict):
                status = _status_of(obj) or (_status_of(obj["data"]) if isinstance(obj.get("data"), dict) else None)
                if obj.get("success") is False and not status:
                    status = "failed"
        _apply(t, status, text)
        t.poll_failures, t.last_poll_error = 0, None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:500]
        if _EXPIRED_TEXT.search(msg):
            t.state, t.error, t.completed_at = "EXPIRED", msg, now
            logger.info("MCP job expired / unknown: task=%s (%s)", t.id, msg[:120])
        else:
            t.poll_failures += 1
            t.last_poll_error = msg                         # a polling failure, not a job failure
            logger.info("MCP job status check failed: task=%s failures=%s (%s)", t.id, t.poll_failures, msg[:120])
    finally:
        creds.clear()
    t.updated_at = _now()
    t.next_poll_at = None if t.state in TERMINAL else _now() + timedelta(seconds=_next_delay(t))
    await db.flush()
    return t


async def wait(db: AsyncSession, t: McpTask, seconds: float, first_delay: float | None = None) -> McpTask:
    """Follow a job for at most `seconds` (one chat answer)."""
    end = asyncio.get_running_loop().time() + max(0.0, seconds)
    delay = first_delay or settings.mcp_task_poll_initial_s
    while t.state in ACTIVE:
        left = end - asyncio.get_running_loop().time()
        if left <= 0:
            break
        await asyncio.sleep(min(delay, left))
        await poll_once(db, t)
        delay = _next_delay(t, first_delay)
    return t


async def cancel(db: AsyncSession, t: McpTask) -> tuple[bool, str]:
    if t.state in TERMINAL:
        return False, f"The job is already {t.state}."
    creds, why = await _credentials(db, t)
    if creds is None:
        return False, why or "cannot reach the server"
    from app.integrations.providers.mcp_provider import MCPIntegrationProvider
    provider = MCPIntegrationProvider()
    try:
        if t.mechanism == "mcp_tasks":
            await provider.request(creds, "tasks/cancel", {"taskId": t.remote_id})
        elif t.cancel_tool:
            await provider.request(creds, "tools/call", {"name": t.cancel_tool,
                                                         "arguments": {t.status_param or "id": t.remote_id}})
        else:
            return False, "This server offers no way to cancel the job."
    except Exception as exc:  # noqa: BLE001
        return False, f"The server refused to cancel it: {str(exc)[:200]}"
    finally:
        creds.clear()
    t.state, t.completed_at, t.updated_at, t.next_poll_at = "CANCELLED", _now(), _now(), None
    await db.flush()
    return True, "Cancelled."


def summary(t: McpTask) -> dict:
    return {"id": t.id, "integration_id": t.integration_id, "role_key": t.role_key, "start_tool": t.start_tool,
            "status_tool": t.status_tool, "mechanism": t.mechanism, "remote_id": t.remote_id,
            "remote_id_field": t.remote_id_field, "state": t.state, "remote_status": t.remote_status,
            "poll_count": t.poll_count, "poll_failures": t.poll_failures, "last_poll_error": t.last_poll_error,
            "error": t.error, "has_result": bool(t.result_text), "can_cancel": t.state in ACTIVE and bool(
                t.cancel_tool or t.mechanism == "mcp_tasks"),
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "deadline_at": t.deadline_at.isoformat() if t.deadline_at else None}


# ── Background poller (also resumes after a restart) ──────────────────────────

async def poll_due(maker) -> int:
    """Check every active task whose next poll time has come. Returns how many were checked."""
    n = 0
    async with maker() as db:
        due = (await db.execute(select(McpTask).where(McpTask.state.in_(ACTIVE)).order_by(
            McpTask.next_poll_at).limit(50))).scalars().all()
        for t in due:
            if t.next_poll_at is None or _aware(t.next_poll_at) <= _now():
                await poll_once(db, t)
                n += 1
        await db.commit()
    return n


_poller: asyncio.Task | None = None


def start_poller(maker) -> None:
    global _poller
    if not settings.mcp_task_poller_enabled or (_poller and not _poller.done()):
        return

    async def loop():
        while True:
            try:
                await poll_due(maker)
            except Exception:  # noqa: BLE001
                logger.warning("MCP task poller round failed", exc_info=True)
            await asyncio.sleep(settings.mcp_task_poller_interval_s)
    _poller = asyncio.get_running_loop().create_task(loop())


def stop_poller() -> None:
    global _poller
    if _poller and not _poller.done():
        _poller.cancel()
    _poller = None
