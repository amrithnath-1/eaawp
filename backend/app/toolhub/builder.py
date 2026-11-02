"""
Tool Builder: create a reusable internal tool when no existing tool or combination can do the job.

1. assess()  – search every tool this company has (built-in, actions, internet, integrations, MCP, generated) for the
               capability; strong matches are returned for reuse instead of building a duplicate.
2. build()   – ask the model for a tool specification (name, purpose, input/output schemas, code, tests), then:
3. validate()– structure → schemas → static security checks → dependency allowlist → every test in the sandbox
               (inputs validated, outputs validated against the output schema and compared with the expected
               result) → resource use. A failing spec gets at most MAX_CORRECTIONS bounded correction rounds.
4. register  – only a fully validated version is stored and activated; it is granted to the requesting AI employee
               role only (least privilege). Every step is in the tool audit trail. Rejected attempts are kept with
               their validation report.
5. run()     – executes a granted, active generated tool in the sandbox with input and output validation.

Generated tools only compute over the inputs they are given: no files, network, database, secrets or other tenants
(enforced by sandbox.check_code and the isolated process, not by trusting the model).
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.toolhub_models import ToolEvent, ToolGrant, ToolRecord, ToolVersion
from app.toolhub import metrics, sandbox, schema as jschema

logger = logging.getLogger(__name__)

MAX_CORRECTIONS = 2
MIN_TESTS = 2
REUSE_SCORE = 0.6
MAX_TEST_MS = 4000

_STOP = {"a", "an", "the", "of", "for", "to", "and", "or", "in", "on", "by", "with", "from", "into", "that", "this",
         "it", "is", "are", "be", "as", "at", "our", "my", "your", "per", "each", "all", "any", "tool", "data", "get",
         "using", "use", "based", "which", "what", "how", "list", "show", "give", "me", "please", "new"}


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "").lower()):
        if w in _STOP or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def similarity(need: str, tool_text: str) -> float:
    """How well a tool's name/description covers what is needed: mostly the share of the need's words the tool
    covers (a long description must not dilute a good match), a little overlap in the other direction."""
    wa, wb = _words(need), _words(tool_text)
    if not wa or not wb:
        return 0.0
    covered = len(wa & wb) / len(wa)
    return 0.75 * covered + 0.25 * len(wa & wb) / len(wa | wb)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:40] or "tool"
    return s if s.startswith("gen_") else f"gen_{s}"


# ── 1. capability assessment ─────────────────────────────────────────────────

async def catalogue(db: AsyncSession, tenant_id: str, role_key: str) -> list[dict]:
    """Every tool this company has: [{key, name, description, source, granted}] (granted = usable by this role)."""
    from app.actions.registry import ACTION_REGISTRY
    from app.tools.registry import MASTER_TOOL_REGISTRY
    from app.tools.web_tools import WEB_TOOLS

    out: list[dict] = []
    for k, t in MASTER_TOOL_REGISTRY.items():
        out.append({"key": k, "name": k, "description": str(getattr(t, "description", ""))[:400],
                    "source": "builtin", "granted": None})
    for k, a in ACTION_REGISTRY.items():
        if k not in MASTER_TOOL_REGISTRY:
            out.append({"key": k, "name": a.meta.display_name, "description": a.meta.description[:400],
                        "source": "action", "granted": None})
    for k, t in WEB_TOOLS.items():
        out.append({"key": k, "name": k, "description": str(t.description)[:400], "source": "internet",
                    "granted": role_key != "MEDICAL_ASSISTANT"})
    rows = (await db.execute(select(ToolRecord).where(
        ToolRecord.tenant_id == tenant_id, ToolRecord.status == "active"))).scalars().all()
    grants = {g.tool_id for g in (await db.execute(select(ToolGrant).where(
        ToolGrant.tenant_id == tenant_id, ToolGrant.role_key == role_key))).scalars()}
    mcp_granted = await _mcp_granted(db, tenant_id, role_key)
    for r in rows:
        out.append({"key": r.key, "name": r.name, "description": r.description[:400], "source": r.source,
                    "integration_id": r.integration_id, "risk_class": r.risk_class,
                    "granted": (r.id in grants) if r.source == "generated" else
                    ((r.integration_id, r.key) in mcp_granted)})
    return out


async def _mcp_granted(db: AsyncSession, tenant_id: str, role_key: str) -> set[tuple[str, str]]:
    from app.db.integration_models import CapabilityGrant
    rows = (await db.execute(select(CapabilityGrant).where(
        CapabilityGrant.tenant_id == tenant_id, CapabilityGrant.role_key == role_key,
        CapabilityGrant.is_granted == True,  # noqa: E712
        CapabilityGrant.capability_key.like("mcp_tool:%")))).scalars().all()
    return {(g.integration_id, g.capability_key[len("mcp_tool:"):]) for g in rows}


async def assess(db: AsyncSession, tenant_id: str, role_key: str, need: str, limit: int = 5) -> dict:
    """Existing tools that may already provide `need`, best first, and whether building is justified."""
    scored = []
    for t in await catalogue(db, tenant_id, role_key):
        sc = similarity(need, f"{t['name']} {t['description']}")
        if sc > 0.12:
            scored.append({**t, "score": round(sc, 3)})
    scored.sort(key=lambda t: t["score"], reverse=True)
    top = scored[:limit]
    strong = [t for t in top if t["score"] >= REUSE_SCORE]
    return {"candidates": top, "decision": "reuse" if strong else "build", "reuse": strong}


# ── 2/3. generation and validation ───────────────────────────────────────────

_GEN_SYSTEM = f"""You write small, safe, reusable Python tools for an enterprise AI platform.
Return ONLY JSON:
{{"name": "short_snake_case_name", "description": "what it does, one sentence", "purpose": "why it is needed",
  "input_schema": {{JSON schema, type object}}, "output_schema": {{JSON schema}},
  "code": "python source", "dependencies": ["module", ...],
  "tests": [{{"inputs": {{...}}, "expected": ...}}, ...]}}
Rules for the code:
- Define run(inputs) that takes the input object and returns a JSON-serialisable result matching output_schema.
- Pure computation over the inputs only. Allowed imports: {", ".join(sorted(sandbox.ALLOWED_MODULES))}.
- No files, network, environment, subprocesses, eval/exec, getattr, format()/str.format, classes, names starting
  with "_" or text containing "__". Validate inputs and raise ValueError with a clear message on bad input.
- Give at least {MIN_TESTS} tests with exact expected outputs (include an edge case). Round floats in the output."""


@dataclass
class BuildResult:
    status: str                     # registered | reused | rejected | unavailable
    message: str
    tool_key: str | None = None
    version: int | None = None
    report: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


def _close(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-9)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    return a == b


async def validate(spec: dict) -> tuple[bool, list[dict]]:
    """Run every check; returns (passed, report)."""
    report: list[dict] = []

    def step(name: str, ok: bool, detail: str = "") -> bool:
        report.append({"check": name, "passed": ok, "detail": detail[:600]})
        return ok

    need = ("name", "description", "input_schema", "output_schema", "code", "tests")
    missing = [k for k in need if not spec.get(k)]
    if not step("structure", not missing, f"missing: {missing}" if missing else "all fields present"):
        return False, report
    name_ok = bool(re.fullmatch(r"[a-z][a-z0-9_]{2,40}", slug(spec["name"])[4:] or ""))
    if not step("name", name_ok, spec["name"][:60]):
        return False, report
    errs = jschema.check_schema(spec["input_schema"], "input_schema") + \
        jschema.check_schema(spec["output_schema"], "output_schema")
    if spec["input_schema"].get("type") != "object":
        errs.append("input_schema.type must be object")
    if not step("schemas", not errs, "; ".join(errs) or "valid JSON schemas"):
        return False, report
    sec = sandbox.check_code(spec["code"])
    if not step("security", not sec, "; ".join(sec) or "static checks passed"):
        return False, report
    deps = [str(d) for d in spec.get("dependencies") or []]
    bad = [d for d in deps if d.split(".")[0] not in sandbox.ALLOWED_MODULES]
    if not step("dependencies", not bad, f"not allowed: {bad}" if bad else f"allowed: {deps or 'none'}"):
        return False, report
    tests = spec["tests"] if isinstance(spec["tests"], list) else []
    if not step("test count", len(tests) >= MIN_TESTS, f"{len(tests)} test(s)"):
        return False, report
    slowest = 0
    for i, t in enumerate(tests[:10], 1):
        inputs, expected = (t or {}).get("inputs"), (t or {}).get("expected")
        ierr = jschema.validate(inputs, spec["input_schema"])
        if ierr:
            step(f"test {i} inputs", False, "; ".join(ierr))
            return False, report
        res = await sandbox.run(spec["code"], inputs)
        slowest = max(slowest, res.duration_ms)
        if not res.ok:
            step(f"test {i} run", False, res.error)
            return False, report
        oerr = jschema.validate(res.output, spec["output_schema"])
        if oerr:
            step(f"test {i} output schema", False, "; ".join(oerr))
            return False, report
        if not _close(res.output, expected):
            step(f"test {i} result", False, f"expected {json.dumps(expected)[:200]}, got {json.dumps(res.output, default=str)[:200]}")
            return False, report
        step(f"test {i}", True, f"{res.duration_ms} ms")
    step("resources", slowest <= MAX_TEST_MS, f"slowest test {slowest} ms (limit {MAX_TEST_MS} ms)")
    step("isolation", True, "no file, network, database or secret access (static checks + empty sandbox env)")
    return all(r["passed"] for r in report), report


def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.S)
    try:
        return json.loads(m.group(0) if m else t)
    except ValueError:
        return {}


def _text(resp: Any) -> str:
    c = getattr(resp, "content", resp)
    if isinstance(c, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)
    return str(c or "")


async def _ask_model(prompt: str) -> dict:
    from app.llm import get_llm_gateway
    model = get_llm_gateway().get_chat_model(temperature=0)
    resp = await model.ainvoke([SystemMessage(content=_GEN_SYSTEM), HumanMessage(content=prompt)])
    return _parse_json(_text(resp))


async def build(db: AsyncSession, tenant_id: str, role_key: str, need: str, details: str = "",
                example_inputs: Any = None, actor: str = "agent", force: bool = False) -> BuildResult:
    """Assess, then (only if justified) generate, validate, correct within bounds and register a tool."""
    need = " ".join(str(need or "").split())[:500]
    if not need:
        return BuildResult("rejected", "Say what the tool must do.")
    found = await assess(db, tenant_id, role_key, f"{need} {details}")
    db.add(ToolEvent(tenant_id=tenant_id, kind="capability_request", actor=actor[:128],
                     detail=json.dumps({"need": need, "role": role_key, "decision": found["decision"],
                                        "candidates": [c["key"] for c in found["candidates"]]})[:2000]))
    if found["decision"] == "reuse" and not force:
        await db.flush()
        names = ", ".join(f"{c['key']} ({c['source']}{'' if c['granted'] in (True, None) else ', not granted to you'})"
                          for c in found["reuse"])
        return BuildResult("reused", f"Existing tools already cover this: {names}. Use them instead of a new tool.",
                           candidates=found["reuse"])

    prompt = (f"Capability needed: {need}\nDetails: {details[:1500]}\n"
              f"Example input: {json.dumps(example_inputs, default=str)[:1500] if example_inputs is not None else 'none'}")
    attempts: list[dict] = []
    spec: dict = {}
    for attempt in range(MAX_CORRECTIONS + 1):
        try:
            spec = await _ask_model(prompt if attempt == 0 else
                                    f"{prompt}\n\nYour previous tool failed validation:\n"
                                    f"{json.dumps([r for r in attempts[-1]['report'] if not r['passed']])[:2000]}\n"
                                    f"Previous code:\n{str(spec.get('code', ''))[:6000]}\nReturn a corrected JSON.")
        except Exception as exc:  # noqa: BLE001
            return BuildResult("unavailable", f"The AI model could not write the tool: {type(exc).__name__}.")
        ok, report = await validate(spec)
        attempts.append({"attempt": attempt + 1, "passed": ok, "report": report})
        if ok:
            break
    key = slug(spec.get("name") or need)
    record = (await db.execute(select(ToolRecord).where(
        ToolRecord.tenant_id == tenant_id, ToolRecord.source == "generated", ToolRecord.key == key))).scalar_one_or_none()
    if not ok:
        if record is None:
            record = ToolRecord(tenant_id=tenant_id, source="generated", key=key, name=str(spec.get("name") or key)[:160],
                                description=str(spec.get("description") or need)[:2000], status="rejected",
                                current_version=0, risk_class="internal_compute", created_by=actor[:128])
            db.add(record)
            await db.flush()
        await _store_version(db, tenant_id, record, spec, attempts, "rejected", actor)
        failed = next((r for r in attempts[-1]["report"] if not r["passed"]), {})
        db.add(ToolEvent(tenant_id=tenant_id, tool_id=record.id, kind="rejected", actor=actor[:128],
                         detail=f"Validation failed after {len(attempts)} attempt(s): {failed.get('check')}: "
                                f"{failed.get('detail', '')}"[:1000]))
        await db.flush()
        return BuildResult("rejected", f"The tool failed validation ({failed.get('check')}: "
                                       f"{failed.get('detail', '')[:300]}) after {len(attempts)} attempt(s); "
                                       "nothing was registered.", report=attempts[-1]["report"])
    return await _register(db, tenant_id, role_key, record, key, spec, attempts, actor)


async def _store_version(db, tenant_id, record, spec, attempts, status, actor) -> ToolVersion:
    last = (await db.execute(select(ToolVersion).where(
        ToolVersion.tenant_id == tenant_id, ToolVersion.tool_id == record.id)
        .order_by(ToolVersion.version.desc()).limit(1))).scalar_one_or_none()
    v = ToolVersion(tenant_id=tenant_id, tool_id=record.id, version=(last.version + 1) if last else 1,
                    purpose=str(spec.get("purpose") or "")[:2000], code=str(spec.get("code") or "")[:sandbox.MAX_CODE_CHARS],
                    input_schema_json=json.dumps(spec.get("input_schema") or {})[:20000],
                    output_schema_json=json.dumps(spec.get("output_schema") or {})[:20000],
                    tests_json=json.dumps(spec.get("tests") or [], default=str)[:20000],
                    dependencies_json=json.dumps(spec.get("dependencies") or []),
                    validation_json=json.dumps(attempts, default=str)[:50000], status=status, created_by=actor[:128])
    db.add(v)
    await db.flush()
    return v


async def _register(db, tenant_id, role_key, record, key, spec, attempts, actor) -> BuildResult:
    now = datetime.now(timezone.utc)
    if record is None:
        record = ToolRecord(tenant_id=tenant_id, source="generated", key=key, name=str(spec["name"])[:160],
                            description=str(spec["description"])[:2000], status="active", current_version=0,
                            risk_class="internal_compute", created_by=actor[:128])
        db.add(record)
        await db.flush()
    current = (await db.execute(select(ToolVersion).where(
        ToolVersion.tenant_id == tenant_id, ToolVersion.tool_id == record.id,
        ToolVersion.status == "active"))).scalars().all()
    for old in current:
        old.status = "superseded"
    v = await _store_version(db, tenant_id, record, spec, attempts, "active", actor)
    record.status, record.current_version, record.updated_at = "active", v.version, now
    record.name, record.description = str(spec["name"])[:160], str(spec["description"])[:2000]
    record.input_schema_json, record.output_schema_json = v.input_schema_json, v.output_schema_json
    record.schema_hash = str(abs(hash(v.code)))[:64]
    await grant(db, tenant_id, record.id, role_key, actor)
    for kind in ("generated", "validated", "registered"):
        db.add(ToolEvent(tenant_id=tenant_id, tool_id=record.id, kind=kind, actor=actor[:128],
                         detail=f"{record.key} v{v.version}: {record.description[:300]}"))
    await db.flush()
    final = attempts[-1]["report"]
    passed = sum(1 for r in final if re.fullmatch(r"test \d+", r["check"]))
    return BuildResult("registered", f"Tool {record.key} v{v.version} is validated ({passed} tests passed in the "
                                     f"sandbox) and ready for {role_key}.",
                       tool_key=record.key, version=v.version, report=final)


# ── management: grants, deactivation, rollback ───────────────────────────────

async def _tool(db: AsyncSession, tenant_id: str, tool_id: str) -> ToolRecord | None:
    return (await db.execute(select(ToolRecord).where(ToolRecord.tenant_id == tenant_id,
                                                      ToolRecord.id == tool_id))).scalar_one_or_none()


async def grant(db: AsyncSession, tenant_id: str, tool_id: str, role_key: str, actor: str) -> None:
    exists = (await db.execute(select(ToolGrant).where(ToolGrant.tenant_id == tenant_id, ToolGrant.tool_id == tool_id,
                                                       ToolGrant.role_key == role_key))).scalar_one_or_none()
    if exists is None:
        db.add(ToolGrant(tenant_id=tenant_id, tool_id=tool_id, role_key=role_key, granted_by=actor[:128]))
        db.add(ToolEvent(tenant_id=tenant_id, tool_id=tool_id, kind="granted", actor=actor[:128],
                         detail=f"granted to {role_key}"))
        await db.flush()


async def revoke(db: AsyncSession, tenant_id: str, tool_id: str, role_key: str, actor: str) -> bool:
    g = (await db.execute(select(ToolGrant).where(ToolGrant.tenant_id == tenant_id, ToolGrant.tool_id == tool_id,
                                                  ToolGrant.role_key == role_key))).scalar_one_or_none()
    if g is None:
        return False
    await db.delete(g)
    db.add(ToolEvent(tenant_id=tenant_id, tool_id=tool_id, kind="revoked", actor=actor[:128],
                     detail=f"revoked from {role_key}"))
    await db.flush()
    return True


async def set_active(db: AsyncSession, tenant_id: str, tool_id: str, active: bool, actor: str) -> ToolRecord | None:
    r = await _tool(db, tenant_id, tool_id)
    if r is None or r.source != "generated" or r.current_version < 1:
        return None
    r.status = "active" if active else "deactivated"
    db.add(ToolEvent(tenant_id=tenant_id, tool_id=r.id, kind="activated" if active else "deactivated",
                     actor=actor[:128], detail=r.key))
    await db.flush()
    return r


async def rollback(db: AsyncSession, tenant_id: str, tool_id: str, to_version: int, actor: str) -> ToolRecord | None:
    """Make an earlier validated version current again (the unsafe/bad current one is marked rolled_back)."""
    r = await _tool(db, tenant_id, tool_id)
    if r is None:
        return None
    rows = (await db.execute(select(ToolVersion).where(
        ToolVersion.tenant_id == tenant_id, ToolVersion.tool_id == tool_id))).scalars().all()
    versions = {v.version: v for v in rows}
    target = versions.get(to_version)
    if target is None or target.status not in ("superseded", "active", "rolled_back") or not target.code:
        return None
    for v in versions.values():
        if v.status == "active" and v.version != to_version:
            v.status = "rolled_back"
    target.status = "active"
    r.current_version, r.input_schema_json, r.output_schema_json = target.version, target.input_schema_json, \
        target.output_schema_json
    db.add(ToolEvent(tenant_id=tenant_id, tool_id=r.id, kind="rolled_back", actor=actor[:128],
                     detail=f"{r.key} back to v{target.version}"))
    await db.flush()
    return r


# ── 5. execution ─────────────────────────────────────────────────────────────

async def usable(db: AsyncSession, tenant_id: str, role_key: str) -> list[ToolRecord]:
    """Active generated tools granted to this role in this company."""
    granted = select(ToolGrant.tool_id).where(ToolGrant.tenant_id == tenant_id, ToolGrant.role_key == role_key)
    return list((await db.execute(select(ToolRecord).where(
        ToolRecord.tenant_id == tenant_id, ToolRecord.source == "generated", ToolRecord.status == "active",
        ToolRecord.id.in_(granted)))).scalars())


async def run(db: AsyncSession, tenant_id: str, role_key: str, key: str, inputs: Any,
              plan_id: str | None = None) -> str:
    """Execute a generated tool for this role; returns text for the model (data or a [TOOL ERROR] message)."""
    t0 = time.monotonic()
    rec = next((r for r in await usable(db, tenant_id, role_key) if r.key == key), None)

    async def done(status: str, text: str, cat: str | None = None, out: Any = "") -> str:
        await metrics.record(db, tenant_id=tenant_id, tool_key=key, tool_label=key, tool_source="generated",
                             role_key=role_key, plan_id=plan_id, status=status, error_category=cat,
                             error_message=text if status != "success" else None, input_value=inputs,
                             output_value=out, duration_ms=int((time.monotonic() - t0) * 1000))
        return text
    if rec is None:
        return await done("blocked", f"[PERMISSION DENIED] {key}: not an active tool granted to you.", "permission")
    ver = (await db.execute(select(ToolVersion).where(
        ToolVersion.tenant_id == tenant_id, ToolVersion.tool_id == rec.id,
        ToolVersion.version == rec.current_version))).scalar_one_or_none()
    if ver is None or ver.status != "active":
        return await done("failed", f"[TOOL ERROR] {key}: no active validated version.", "not_found")
    in_schema = json.loads(ver.input_schema_json or "{}")
    errs = jschema.validate(inputs, in_schema)
    if errs:
        return await done("failed", f"[VALIDATION ERROR] {key}: {'; '.join(errs[:5])}. Expected inputs: "
                                    f"{json.dumps(in_schema.get('properties', {}))[:600]}", "invalid_args")
    res = await sandbox.run(ver.code, inputs)
    if not res.ok:
        return await done("failed", f"[TOOL ERROR] {key}: {res.error}", "timeout" if res.timed_out else "execution_error")
    oerr = jschema.validate(res.output, json.loads(ver.output_schema_json or "{}"))
    if oerr:
        return await done("failed", f"[TOOL ERROR] {key}: output did not match its schema ({'; '.join(oerr[:3])}).",
                          "malformed_output")
    text = json.dumps(res.output, ensure_ascii=False, default=str)[:20000]
    return await done("success", f"{text}\nSource: generated tool {key} v{ver.version} (computed from the inputs given)",
                      out=res.output)
