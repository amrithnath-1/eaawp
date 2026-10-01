"""
EAAWP Database Seed

Creates the first real company and Digital Marketing Manager AI employee.
Safe to run multiple times — checks for existing records before inserting.

Run with:
    cd backend
    .venv\\Scripts\\python -m app.db.seed
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentConfiguration, AIEmployee, Company, LLMModel, User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ── Seed data ─────────────────────────────────────────────────────────────────

DEMO_COMPANY = {
    "id": "demo-company-001",
    "name": "EAAWP Demo Company",
    "industry": "Technology",
    "region": "UK · London",
    "employees": 120,
}

DEMO_USER = {
    "id": "demo-user-001",
    "tenant_id": "demo-company-001",
    "email": "admin@demo.eaawp.io",
    "name": "Demo Admin",
    # bcrypt hash of "demo1234" — never use real passwords here
    "hashed_password": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TiGTt5V4SaEBXjHjSHMgFfDL3X.a",
    "role": "Company Admin",
    "status": "Active",
}

GPT4O_MINI = {
    "id": "llm-gpt4o-mini-001",
    "provider": "openai",
    "model_name": "gpt-4o-mini",
    "display_name": "GPT-4o Mini",
    "context_window": 128000,
    "is_active": True,
}

DMM_AI_EMPLOYEE = {
    "id": "ai-dmm-001",
    "tenant_id": "demo-company-001",
    "llm_model_id": "llm-gpt4o-mini-001",
    "role_key": "DIGITAL_MARKETING_MANAGER",
    "name": "Marketing Intelligence Agent",
    "status": "IDLE",
    "is_active": True,
}

DMM_SYSTEM_PERSONA = (
    "You are the Marketing Intelligence Agent for this company. "
    "Your role is to support the Digital Marketing Manager by continuously monitoring "
    "campaign performance, analysing audience engagement metrics, surfacing content "
    "opportunities, and preparing data-driven marketing reports. "
    "You have access to campaign analytics, CRM contact data, content scheduling tools, "
    "and the company knowledge base. "
    "You operate under strict data governance: you never send external communications "
    "without explicit human approval, and you always cite the data sources behind your "
    "insights. Your communication style is concise and data-first. "
    "Every action you take is logged in the audit trail."
)

DMM_TOOL_SCOPES = [
    {"name": "Query Campaign Analytics", "toolKey": "query_campaign_analytics",
     "governance": "enabled", "description": "Read-only access to campaign performance metrics"},
    {"name": "Fetch Knowledge Base", "toolKey": "fetch_knowledge_base",
     "governance": "enabled", "description": "Vector search across indexed marketing documents"},
    {"name": "Read CRM Contacts", "toolKey": "read_crm_contacts",
     "governance": "enabled", "description": "Read audience segmentation and contact lists"},
    {"name": "Generate Report", "toolKey": "generate_report",
     "governance": "enabled", "description": "Produce structured marketing performance documents"},
    {"name": "Schedule Social Post", "toolKey": "schedule_social_post",
     "governance": "requires_approval", "description": "Queue social media posts — requires manager approval"},
    {"name": "Send Campaign Email", "toolKey": "send_campaign_email",
     "governance": "requires_approval", "description": "Send email campaigns — always requires human approval"},
    {"name": "Update CRM Records", "toolKey": "update_crm_records",
     "governance": "requires_approval", "description": "CRM mutations need manager sign-off"},
    {"name": "Access Financial Data", "toolKey": "query_finance_erp",
     "governance": "disabled", "description": "Finance ERP is outside this role's scope"},
    {"name": "HR Records Access", "toolKey": "read_hr_records",
     "governance": "disabled", "description": "HR data is outside this role's scope"},
]

DMM_CAPABILITIES = {
    "Campaign analytics": True,
    "Content generation": True,
    "Competitor research": True,
    "Email drafting": True,
    "Report writing": True,
    "Social media scheduling": True,
    "SEO analysis": True,
    "A/B test suggestions": True,
    "Budget tracking": False,
    "Direct ad spend": False,
}

DMM_PERMISSIONS = [
    {"action": "Read campaign data", "mode": "auto"},
    {"action": "Query knowledge base", "mode": "auto"},
    {"action": "Generate reports", "mode": "auto"},
    {"action": "Schedule social posts", "mode": "approval"},
    {"action": "Send campaign emails", "mode": "approval"},
    {"action": "Update CRM records", "mode": "approval"},
    {"action": "Access financial data", "mode": "restricted"},
    {"action": "Access HR records", "mode": "restricted"},
]


async def seed(db: AsyncSession) -> None:
    # ── Company ───────────────────────────────────────────────────────────────
    existing = await db.get(Company, DEMO_COMPANY["id"])
    if not existing:
        db.add(Company(**DEMO_COMPANY))
        logger.info("Seeded company: %s", DEMO_COMPANY["name"])
    else:
        logger.info("Company already exists — skipping")

    # ── User ──────────────────────────────────────────────────────────────────
    existing_user = await db.get(User, DEMO_USER["id"])
    if not existing_user:
        db.add(User(**DEMO_USER))
        logger.info("Seeded user: %s", DEMO_USER["email"])
    else:
        logger.info("User already exists — skipping")

    # ── LLM Model ─────────────────────────────────────────────────────────────
    existing_llm = await db.get(LLMModel, GPT4O_MINI["id"])
    if not existing_llm:
        db.add(LLMModel(**GPT4O_MINI))
        logger.info("Seeded LLM model: %s", GPT4O_MINI["display_name"])
    else:
        logger.info("LLM model already exists — skipping")

    await db.flush()  # ensure FKs are resolvable before AI employee insert

    # ── AI Employee ───────────────────────────────────────────────────────────
    existing_ai = await db.get(AIEmployee, DMM_AI_EMPLOYEE["id"])
    if not existing_ai:
        db.add(AIEmployee(**DMM_AI_EMPLOYEE))
        logger.info("Seeded AI employee: %s", DMM_AI_EMPLOYEE["name"])
    else:
        logger.info("AI employee already exists — skipping")

    await db.flush()

    # ── Agent Configuration ───────────────────────────────────────────────────
    stmt = select(AgentConfiguration).where(
        AgentConfiguration.ai_employee_id == DMM_AI_EMPLOYEE["id"]
    )
    result = await db.execute(stmt)
    existing_cfg = result.scalar_one_or_none()

    if not existing_cfg:
        db.add(
            AgentConfiguration(
                tenant_id="demo-company-001",
                ai_employee_id=DMM_AI_EMPLOYEE["id"],
                system_persona=DMM_SYSTEM_PERSONA,
                tone="Concise",
                autonomy_level=3,
                capabilities_json=json.dumps(DMM_CAPABILITIES),
                tools_json=json.dumps({}),
                tool_scopes_json=json.dumps(DMM_TOOL_SCOPES),
                permissions_json=json.dumps(DMM_PERMISSIONS),
            )
        )
        logger.info("Seeded agent configuration for Digital Marketing Manager")
    else:
        logger.info("Agent configuration already exists — skipping")

    await db.commit()
    logger.info("Seed complete.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    async with AsyncSessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())


async def seed_demo_data() -> None:
    """
    Seed safe demo data for presentation purposes.
    Demo data is clearly labelled and separate from production data.
    Run only in development/demo environments.
    Never seeds real credentials or sensitive company data.
    """
    from app.db.session import AsyncSessionLocal
    from app.db.models import Company, AIEmployee, LLMModel
    import uuid, logging
    from sqlalchemy import select
    logger = logging.getLogger(__name__)

    async with AsyncSessionLocal() as db:
        # Check if demo company already exists
        result = await db.execute(
            select(Company).where(Company.name == "EAAWP Demo Company")
        )
        if result.scalar_one_or_none():
            logger.info("Demo data already seeded — skipping.")
            return

        # Create demo company
        demo_company = Company(
            id=str(uuid.uuid4()),
            name="EAAWP Demo Company",
            industry="Marketing & Technology",
            region="UK",
            employees=50,
            is_active=True,
        )
        db.add(demo_company)
        await db.flush()
        logger.info("Demo company created: %s", demo_company.id)
        await db.commit()
        logger.info("Demo data seeded successfully.")
