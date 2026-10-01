"""
EAAWP DMM Data Context Service

Builds the data-awareness context injected into the DMM system prompt.
This tells the LLM which semantic concepts are available, what they map to,
and the precise rules for using the query_company_data tool.

Security invariants
-------------------
- Only concept names and field names are exposed to the LLM.
- Connection credentials, host/port, raw SQL are NEVER included.
- Only concepts that map to is_allowed entities are surfaced.
- If no mappings exist, a clear "no company data configured" message is returned.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataConnection, SchemaEntity, SemanticMapping

logger = logging.getLogger(__name__)


async def build_data_context_block(
    tenant_id: str,
    db: AsyncSession,
) -> str:
    """
    Returns a system-prompt block describing available company data concepts.
    Only concepts that point to is_allowed entities are included.
    Returns an empty string if no company data is configured.
    """
    try:
        # Load all semantic mappings for this tenant
        mapping_result = await db.execute(
            select(SemanticMapping).where(
                SemanticMapping.tenant_id == tenant_id,
            ).order_by(SemanticMapping.semantic_concept, SemanticMapping.field_name)
        )
        mappings = mapping_result.scalars().all()

        if not mappings:
            return ""

        # Load entity allow-list to filter to only permitted entities
        entity_ids = list({m.entity_id for m in mappings})
        entity_result = await db.execute(
            select(SchemaEntity.id, SchemaEntity.entity_name, SchemaEntity.is_allowed)
            .where(
                SchemaEntity.id.in_(entity_ids),
                SchemaEntity.tenant_id == tenant_id,
                SchemaEntity.is_allowed == True,  # noqa: E712
            )
        )
        allowed_entity_ids = {r.id for r in entity_result.fetchall()}
        allowed_entity_names = {}
        if allowed_entity_ids:
            en_result = await db.execute(
                select(SchemaEntity.id, SchemaEntity.entity_name)
                .where(SchemaEntity.id.in_(allowed_entity_ids))
            )
            allowed_entity_names = {r.id: r.entity_name for r in en_result.fetchall()}

        # Filter to only mappings with allowed entities
        allowed_mappings = [m for m in mappings if m.entity_id in allowed_entity_ids]
        if not allowed_mappings:
            return ""

        # Group by concept
        concepts: dict[str, dict] = {}
        for m in allowed_mappings:
            if m.semantic_concept not in concepts:
                concepts[m.semantic_concept] = {
                    "entity": allowed_entity_names.get(m.entity_id, m.entity_id[:8]),
                    "fields": [],
                }
            label = m.display_label or m.field_name
            concepts[m.semantic_concept]["fields"].append(
                f"{m.field_name}" + (f" ({label})" if m.display_label else "")
            )

        lines = [
            "",
            "## Available Company Data (READ-ONLY)",
            "You have access to the following authorized company data through the query_company_data tool.",
            "Use this tool when the user's question requires real company data.",
            "NEVER construct raw SQL. NEVER guess table names. Only use the concepts listed below.",
            "",
            "Available semantic concepts:",
        ]
        for concept, meta in concepts.items():
            field_list = ", ".join(meta["fields"][:10])
            lines.append(f'  - "{concept}" → entity: {meta["entity"]} | fields: {field_list}')

        lines += [
            "",
            "How to use query_company_data:",
            '  Call: query_company_data(\'{"semantic_concept": "<concept_name>", "limit": 50}\')',
            "  To filter: add \"filters\": [{\"field\": \"<field>\", \"operator\": \"=\", \"value\": \"<value>\"}]",
            "  To sort: add \"sort\": [{\"field\": \"<field>\", \"direction\": \"DESC\"}]",
            "  To select specific fields: add \"fields\": [\"field1\", \"field2\"]",
            "",
            "Important rules:",
            "  - If a concept is not listed above, DO NOT guess. Tell the user the data is not configured.",
            "  - If you receive [AUTHORIZATION DENIED], explain the entity is not authorized — do not retry.",
            "  - If you receive [ERROR] No semantic mapping found, tell the user to configure the mapping.",
            "  - If you receive 0 rows, report that no data was found — do not fabricate results.",
            "  - Never expose connection IDs, credentials, or internal field mappings to the user.",
            "  - When reporting results, cite the concept name and entity as the source.",
        ]

        return "\n".join(lines)

    except Exception as exc:
        logger.warning("Failed to build data context block: %s", exc)
        return ""


def build_data_source_metadata(tool_result: str) -> list[str]:
    """
    Parse the query_company_data tool result text and extract safe source labels.
    Returns a list of source strings suitable for AgentExecutionResponse.sources.
    """
    sources: list[str] = []
    for line in tool_result.splitlines():
        if line.startswith("Source: "):
            src = line.removeprefix("Source: ").strip()
            if src:
                sources.append(f"Company data · {src}")
        elif line.startswith("Entity: "):
            entity = line.removeprefix("Entity: ").strip()
            if entity and not any(entity in s for s in sources):
                sources.append(f"Company data · {entity}")
    return sources


COMPANY_DATA_TOOL_KEY = "query_company_data"
