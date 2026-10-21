"""
Static + dynamic guards for cross-tenant leakage at the data-access layer.

1. Every ``select/update/delete`` on a tenant-scoped model must mention the
   tenant in its statement, unless that exact (file, model) pair is on the
   REVIEWED allowlist below with the reason it is safe.  A NEW unscoped query
   therefore fails CI and needs a conscious decision.
2. Agent tool context (tenant / role / db) is a ContextVar: concurrent agent
   runs for different tenants must never see each other's identity.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# (relative path, model) -> why an unscoped statement is safe.
REVIEWED: dict[tuple[str, str], str] = {
    ("services/document_processor.py", "KnowledgeDocument"): "Internal; called only after knowledge.py verified tenant ownership of doc_id.",
    ("services/document_processor.py", "DocumentChunk"): "Child rows of the document above, by document_id.",
    ("services/dmm_context.py", "SchemaEntity"): "Second lookup by ids that the preceding tenant-scoped query returned.",
    ("services/admin_customization_service.py", "AgentConfiguration"): "By ai_employee_id of an employee selected with tenant_id.",
    ("services/monitoring_scheduler.py", "MonitoringRule"): "Cross-tenant by design: returns (rule_id, tenant_id) pairs and each rule is then run under ITS OWN tenant.",
    ("services/workflow_runner.py", "Workflow"): "Cross-tenant by design (system scheduler): lists scheduled workflows; every run is then executed under its OWN tenant, re-validated, with tenant-scoped lookups.",
    ("services/workflow_runner.py", "WorkflowRun"): "Cross-tenant by design (system scheduler): recovery/approval-reconcile/queued scans act on one run at a time and only touch that run's own workflow.",
    ("services/meeting_service.py", "Meeting"): "System paths acting on ONE meeting id handed over by the API after its tenant/owner check (claim), and startup recovery of stale meetings; every child-row query then filters by that meeting's own tenant_id.",
    ("integrations/manager.py", "CapabilityGrant"): "Upsert after _get_integration_or_raise(integration_id, tenant_id).",
    ("db/seed.py", "AgentConfiguration"): "Seed script for the demo employee.",
    ("core/auth.py", "RefreshToken"): "Looked up by unguessable jti from a verified signed refresh JWT; user_id is cross-checked.",
    ("core/auth.py", "User"): "By user id taken from a verified signed access JWT.",
    ("api/routers/auth.py", "User"): "By user id from a validated refresh token.",
    ("api/routers/execution.py", "PlanStep"): "Child rows of an ExecutionPlan fetched with tenant_id in the preceding statement.",
    ("api/routers/integrations.py", "SchemaEntity"): "Child rows of a DataConnection already verified for this tenant.",
    ("api/routers/oauth_router.py", "OAuthState"): "By 256-bit single-use state token; tenant is read FROM the row and re-validated against the initiating user.",
    ("services/team_service.py", "Invitation"): "Invitee has no session/tenant yet: looked up by the SHA-256 of a 256-bit single-use secret token; tenant is read FROM the row.",
    ("api/routers/planning.py", "PlanStep"): "Child rows of an ExecutionPlan already fetched/verified for this tenant.",
}


def _tenant_models() -> set[str]:
    src = "".join(p.read_text(encoding="utf-8") for p in (APP / "db").glob("*.py"))
    models, cur = set(), None
    for line in src.splitlines():
        m = re.match(r"class (\w+)\(", line)
        if m:
            cur = m.group(1)
        if cur and re.search(r"\btenant_id\b.*mapped_column|tenant_id\s*:\s*Mapped", line):
            models.add(cur)
    return models


def _unscoped() -> set[tuple[str, str]]:
    tm = _tenant_models()
    found: set[tuple[str, str]] = set()
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel.startswith("db/") and "models" in path.name:
            continue
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("select", "update", "delete") and node.args):
                continue
            used = {n.id for n in ast.walk(node.args[0]) if isinstance(n, ast.Name)} & tm
            if not used:
                continue
            st = node
            while parents.get(st) is not None and not isinstance(parents[st], ast.stmt):
                st = parents[st]
            st = parents.get(st, st)
            seg = (ast.get_source_segment(text, node)
                   if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For, ast.With, ast.Try))
                   else ast.get_source_segment(text, st)) or ""
            if "tenant" not in seg.lower():
                found.update((rel, m) for m in used)
    return found


def test_tenant_models_were_discovered():
    assert len(_tenant_models()) >= 30


def test_no_new_unscoped_query_on_a_tenant_model():
    new = sorted(k for k in _unscoped() if k not in REVIEWED)
    assert not new, (
        "Queries on tenant-scoped models without a tenant filter. Add the filter, or review and add "
        "to REVIEWED with a reason:\n  " + "\n  ".join(f"{f} :: {m}" for f, m in new)
    )


def test_reviewed_allowlist_has_no_stale_entries():
    stale = sorted(k for k in REVIEWED if k not in _unscoped())
    assert not stale, f"REVIEWED entries that no longer match an unscoped query (remove): {stale}"


def test_tool_context_is_isolated_between_concurrent_agent_runs():
    from app.tools import registry

    get_tenant = registry._tenant_id_ctx.get

    async def run(tenant: str, delay: float):
        registry.set_tool_context(db_session=None, tenant_id=tenant, role_key="R")
        await asyncio.sleep(delay)              # let the other run interleave
        seen = get_tenant()
        registry.clear_tool_context()
        return tenant, seen

    async def main():
        return await asyncio.gather(*(run(f"tenant-{i}", 0.01 * (5 - i % 5)) for i in range(20)))

    for tenant, seen in asyncio.new_event_loop().run_until_complete(main()):
        assert seen == tenant, f"{tenant} observed {seen}"
