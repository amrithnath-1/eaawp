"""
EAAWP Action Tool Base Abstraction

Defines the interface every action tool must implement.
Action tools are distinct from read-only query tools:
- They modify state or affect external systems.
- They must always go through the governance pipeline.
- They have risk levels and approval requirements.
- They are never allowed to receive or emit credentials.
- They never accept raw SQL, shell commands, or arbitrary HTTP.

Governance pipeline for every action:
  validate() → check permissions → determine approval → [await approval] → execute() → audit
"""

from __future__ import annotations

import abc
from typing import Any, Literal

from pydantic import BaseModel

RiskLevel = Literal["low", "medium", "high"]


class ActionToolMeta(BaseModel):
    """Metadata describing an action tool's capabilities and requirements."""
    tool_name: str
    display_name: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool    # default approval requirement
    target_integration: str    # "internal" | "external_crm" | etc.
    allowed_roles: list[str]   # role keys that may invoke this action


class BaseActionTool(abc.ABC):
    """
    Abstract base class for all EAAWP action tools.

    Subclasses must implement:
    - meta (property)       — ActionToolMeta describing the tool
    - validate(arguments)   — validate and parse structured arguments
    - execute(arguments, tenant_id, role_key, db) — perform the action

    Subclasses must NOT:
    - Accept raw SQL in any argument
    - Accept or emit credentials
    - Execute arbitrary shell commands or HTTP requests
    - Bypass the approval pipeline
    """

    @property
    @abc.abstractmethod
    def meta(self) -> ActionToolMeta:
        """Return the tool's metadata."""

    @abc.abstractmethod
    def validate(self, arguments: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        """
        Validate and normalise the action arguments.

        Returns:
            (is_valid, error_message, normalised_arguments)
        """

    @abc.abstractmethod
    async def execute(
        self,
        arguments: dict[str, Any],
        tenant_id: str,
        role_key: str,
        db: Any,   # AsyncSession
    ) -> dict[str, Any]:
        """
        Execute the action after approval.
        Must return a dict with at least {"success": bool, "message": str}.
        Never returns credentials or raw SQL.
        """
