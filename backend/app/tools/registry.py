"""
EAAWP Master Tool Registry

MASTER_TOOL_REGISTRY is the single source of truth for every callable tool
in the platform. It maps string keys → LangChain @tool-decorated functions.

Security contract
-----------------
- No tool may be called unless its key is present in this dictionary.
- The DynamicAgentEngine resolves tool names against this registry ONLY.
- Arbitrary string execution is structurally impossible: resolve_tools()
  raises ValueError for any unrecognised key.

Adding a new tool
-----------------
1. Define a @tool-decorated function below.
2. Add its key to MASTER_TOOL_REGISTRY.
3. Add its key to the relevant RoleConfig.toolScopes in role-config.ts (frontend).
   The frontend governance badge and backend registry key must match.
"""

from __future__ import annotations

from langchain_core.tools import tool


# ── Starter tools ─────────────────────────────────────────────────────────────


@tool
def query_sales_db(region: str) -> str:
    """
    Query the sales database for performance metrics in a given region.

    Args:
        region: The sales region to query (e.g. "Region A", "EMEA").

    Returns:
        A string summary of sales performance for the region.
    """
    # TODO: Replace with a real database query via SQLAlchemy / async pg driver.
    return (
        f"[STUB] Sales data for {region}: "
        "Revenue £2.4M (–18.4% vs forecast). "
        "Top SKU: Industrial Controller v4. "
        "Fulfilment delay at Hub 2 identified as root cause."
    )


@tool
def fetch_knowledge_base(query: str) -> str:
    """
    Search the company knowledge base using semantic vector search.

    Args:
        query: Natural-language query to search the indexed document store.

    Returns:
        Relevant text chunks from the knowledge base.
    """
    # TODO: Replace with a real vector store lookup (e.g. pgvector / Chroma / Pinecone).
    return (
        f"[STUB] Vector search for '{query}': "
        "Found 2 relevant chunks. "
        "Source 1: Company Sales Policy.pdf §4.2 — Regional targets reviewed quarterly. "
        "Source 2: Logistics SOP v3 — Hub escalation process defined in §7."
    )


@tool
def send_email(recipient: str, body: str) -> str:
    """
    Send an email on behalf of the agent. This tool is guarded — it must be
    approved by a human before execution in production.

    Args:
        recipient: Email address or distribution list name.
        body: The full body text of the email to send.

    Returns:
        Confirmation string if the email was queued successfully.
    """
    # TODO: Replace with a real email service (SMTP / SendGrid / Microsoft Graph).
    return (
        f"[STUB] Email queued for {recipient}. "
        "Body preview: "
        f"{body[:120]}{'...' if len(body) > 120 else ''}. "
        "Awaiting human approval before dispatch."
    )


@tool
def query_campaign_analytics(channel: str = "all") -> str:
    """
    Query marketing campaign analytics for the Digital Marketing Manager role.

    Args:
        channel: The marketing channel to query
                 (e.g. "email", "social", "paid_search", "all").

    Returns:
        A string summary of campaign performance metrics.
    """
    # TODO: Replace with a real analytics platform API (Google Analytics / HubSpot).
    return (
        f"[STUB] Campaign analytics for channel='{channel}': "
        "Email open rate 24.3% (+2.1% WoW). "
        "Social impressions 142K (–8% WoW). "
        "Paid search CTR 3.8%. "
        "Top performing campaign: 'Autumn Product Launch'."
    )


@tool
def generate_report(report_type: str, period: str = "current_month") -> str:
    """
    Generate a structured performance report document.

    Args:
        report_type: The type of report (e.g. "marketing_summary", "sales_performance").
        period: The time period covered (e.g. "current_month", "Q3_2026").

    Returns:
        A string confirmation that the report was generated and where it was saved.
    """
    # TODO: Replace with a real document generation pipeline.
    return (
        f"[STUB] {report_type} report for {period} generated. "
        "Document saved to: Library / Reports / {report_type}_{period}.pdf. "
        "Awaiting distribution approval."
    )


# ── Master registry ───────────────────────────────────────────────────────────

MASTER_TOOL_REGISTRY: dict[str, object] = {
    "query_sales_db": query_sales_db,
    "fetch_knowledge_base": fetch_knowledge_base,
    "send_email": send_email,
    "query_campaign_analytics": query_campaign_analytics,
    "generate_report": generate_report,
}


def resolve_tools(tool_names: list[str]) -> list[object]:
    """
    Resolve a list of tool name strings to their @tool-decorated callables.

    Raises:
        ValueError: If any name in tool_names is not present in MASTER_TOOL_REGISTRY.
                    The error message includes the offending tool name.

    Returns:
        Ordered list of resolved @tool callables corresponding to tool_names.
    """
    resolved = []
    for name in tool_names:
        if name not in MASTER_TOOL_REGISTRY:
            raise ValueError(
                f"Tool '{name}' is not registered in MASTER_TOOL_REGISTRY. "
                f"Registered tools: {sorted(MASTER_TOOL_REGISTRY.keys())}"
            )
        resolved.append(MASTER_TOOL_REGISTRY[name])
    return resolved
