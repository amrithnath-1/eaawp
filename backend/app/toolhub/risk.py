"""
Capability-based risk classes and the execution policy for each.

  read_only           reads approved data                         → runs automatically when the role is authorised
  internal_compute    calculates over data it is given            → runs automatically
  internal_modify     changes EAAWP records                       → existing governance (approval where configured)
  external_comm       sends / publishes outside the company       → approval required
  financial           money or irreversible external effect       → explicit approval; never automatic
  security_sensitive  credentials, permissions, admin operations  → never run by an AI employee

Nothing here widens existing permissions: a tool still needs its role grant, and actions still go through governance.
"""
from __future__ import annotations

import re

RISK_CLASSES = ("read_only", "internal_compute", "internal_modify", "external_comm", "financial", "security_sensitive")

POLICY = {
    "read_only": "automatic",
    "internal_compute": "automatic",
    "internal_modify": "governed",
    "external_comm": "approval",
    "financial": "explicit_approval",
    "security_sensitive": "blocked",
}

_SECURITY = {"admin", "sudo", "override", "credential", "credentials", "password", "token", "secret", "permission",
             "permissions", "grant", "revoke", "role", "roles", "auth", "login", "key", "keys"}
_FINANCIAL = {"pay", "payment", "payments", "charge", "refund", "invoice", "transfer", "purchase", "buy", "order",
              "bill", "billing", "subscribe", "checkout", "wire", "payout"}
_EXTERNAL = {"send", "publish", "post", "email", "tweet", "message", "notify", "sms", "share", "deploy", "submit",
             "reply", "comment", "upload"}
_MODIFY = {"create", "update", "upsert", "insert", "add", "write", "modify", "patch", "set", "put", "delete",
           "remove", "destroy", "drop", "truncate", "wipe", "move", "rename", "archive", "edit"}
_COMPUTE = {"calculate", "compute", "convert", "transform", "format", "parse", "validate", "compare", "aggregate",
            "summarise", "summarize", "score", "rank", "analyse", "analyze", "chart", "report"}


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", name or "").lower()) if t]


def classify(name: str, *, generated: bool = False) -> str:
    """Risk class from every word of the tool name (a server controls its own names, so the worst word wins)."""
    toks = set(_tokens(name))
    if generated:
        return "internal_compute"     # generated tools only compute over their inputs (enforced by the sandbox)
    if toks & _SECURITY:
        return "security_sensitive"
    if toks & _FINANCIAL:
        return "financial"
    if toks & _EXTERNAL:
        return "external_comm"
    if toks & _MODIFY:
        return "internal_modify"
    if toks & _COMPUTE:
        return "internal_compute"
    return "read_only"


def runs_automatically(risk_class: str) -> bool:
    return POLICY.get(risk_class) == "automatic"
