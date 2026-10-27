"""
customize_eaawp — change EAAWP itself from the chat (administrators only, always approval-gated).

Flow:
  1. The AI employee proposes the change with {"instruction": "<what the administrator asked>"}.
  2. prepare() turns the instruction into concrete, validated operations with the existing Admin AI Customization
     planner (company profile, AI employee settings, capability grants, workflows, approval policies, ...).
  3. Governance stores those exact operations and creates an approval request: the administrator sees the proposed
     changes BEFORE anything is saved.
  4. On approval the stored operations are re-validated and executed by the existing customization service; the
     result says which changes were saved, skipped or failed.

Credentials never pass through here: credential-like parameters are rejected by the plan schema, and connecting a
service that needs a secret still goes through the secure setup forms.
"""
from __future__ import annotations

from typing import Any

from app.actions.base import ActionToolMeta, BaseActionTool

TOOL_NAME = "customize_eaawp"


def _describe(ops: list[dict]) -> str:
    lines = []
    for i, op in enumerate(ops, 1):
        params = {k: v for k, v in (op.get("params") or {}).items() if v not in ("", None, [], {})}
        lines.append(f"{i}. {op.get('description') or op.get('type')} — {op.get('type')} {params}")
    return "\n".join(lines)


class CustomizeEaawpAction(BaseActionTool):
    @property
    def meta(self) -> ActionToolMeta:
        return ActionToolMeta(
            tool_name=TOOL_NAME,
            display_name="Customize EAAWP",
            description=(
                "Change EAAWP's own configuration on an administrator's request: the approved company profile, "
                "AI employee settings, integration access grants, workflows and approval policies. Arguments: "
                '{"instruction": "<the administrator\'s requested change, complete, in their words>"}. '
                "The concrete changes are shown for approval before anything is saved."
            ),
            risk_level="medium", requires_approval=True,
            target_integration="internal",
            allowed_roles=["DIGITAL_MARKETING_MANAGER", "DATA_INTELLIGENCE_ANALYST", "INSTITUTIONAL_CLERK",
                           "MEDICAL_ASSISTANT"],
        )

    async def prepare(self, arguments: dict[str, Any], tenant_id: str, db: Any) -> dict[str, Any]:
        """Instruction -> concrete operations (runs once, when the change is proposed)."""
        if arguments.get("operations"):
            return arguments
        instruction = str(arguments.get("instruction") or "").strip()
        if not instruction:
            raise ValueError("Say what should be changed.")
        from app.services.admin_customization_service import generate_customization_plan
        try:
            plan = await generate_customization_plan(instruction[:3000], tenant_id, "chat", db)
        except RuntimeError as exc:
            raise ValueError(f"The change could not be planned: {exc}") from exc
        ops = [op.model_dump() for op in plan.operations]
        if not ops:
            missing = "; ".join(plan.missing_information) or "the request did not describe a concrete change"
            raise ValueError(f"Nothing to change yet: {missing}.")
        return {
            "instruction": instruction[:3000],
            "summary": plan.summary,
            "changes": _describe(ops),
            "operations": ops,
            "missing_information": plan.missing_information,
        }

    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        from app.schemas.admin_customization import CustomizationPlan
        ops = arguments.get("operations")
        if not isinstance(ops, list) or not ops:
            return False, "No concrete changes were prepared.", {}
        try:
            plan = CustomizationPlan(summary=str(arguments.get("summary") or "Customization")[:1000],
                                     operations=ops,
                                     missing_information=[str(m)[:200] for m in arguments.get("missing_information") or []][:10])
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:300], {}
        dumped = [op.model_dump() for op in plan.operations]
        return True, "", {
            "instruction": str(arguments.get("instruction") or "")[:3000],
            "summary": plan.summary,
            "changes": _describe(dumped),
            "operations": dumped,
            "missing_information": plan.missing_information,
        }

    async def execute(self, arguments: dict[str, Any], tenant_id: str, role_key: str, db: Any) -> dict[str, Any]:
        from app.schemas.admin_customization import CustomizationPlan
        from app.services.admin_customization_service import execute_customization_plan
        plan = CustomizationPlan(summary=arguments.get("summary") or "Customization",
                                 operations=arguments["operations"])
        result = await execute_customization_plan(plan, tenant_id, "approved administrator (chat)", db, commit=False)
        lines = [f"- {r.description}: {r.status.upper()} — {r.detail}" for r in result.results]
        ok = result.operations_failed == 0
        return {
            "success": ok,
            "message": (f"Customization applied: {result.operations_succeeded} saved, "
                        f"{result.operations_failed} failed, "
                        f"{result.operations_total - result.operations_succeeded - result.operations_failed} skipped.\n"
                        + "\n".join(lines)),
        }
