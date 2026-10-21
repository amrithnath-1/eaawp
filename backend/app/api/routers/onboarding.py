"""
EAAWP Company Onboarding Router

Handles fresh-company creation with proper tenant isolation.
Auto-initialises the DMM role configuration using existing defaults.
Creates an admin user for the new tenant.
No data from other tenants is exposed.
"""
from __future__ import annotations
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import get_current_tenant_id, hash_password, require_admin
from app.core.rate_limit import client_ip, limiter, too_many
from app.db.models import Company, User, AIEmployee
from app.db.session import get_db
from app.schemas.api import CompanyOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


# ── Abuse protection for public self-service registration ───────────────────

async def registration_guard(request: Request) -> None:
    """Close sign-up on demand, and cap sign-ups per client IP and per day."""
    if not settings.registration_enabled:
        raise HTTPException(status_code=403, detail="Self-service registration is disabled.")
    if not settings.rate_limit_enabled:
        return
    retry = limiter.check(
        f"register:{client_ip(request)}",
        settings.registration_rate_limit,
        settings.registration_rate_window_seconds,
    )
    if retry:
        raise too_many(retry, "registration attempts")
    retry = limiter.check("register:global", settings.registration_daily_cap, 86400)
    if retry:
        raise too_many(retry, "registrations today")


# ── Request schemas ───────────────────────────────────────────────────────────

class OnboardCompanyRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    industry: str = Field(default="", max_length=128)
    region: str = Field(default="", max_length=128)
    employees: int = Field(default=0, ge=0)
    website: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=1000)
    # Admin user
    admin_name: str = Field(..., min_length=1, max_length=255)
    admin_email: str = Field(..., min_length=3, max_length=255)
    admin_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("admin_email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email address.")
        return v.strip().lower()

    @field_validator("admin_password")
    @classmethod
    def password_fits_bcrypt(cls, v: str) -> str:
        # bcrypt only uses the first 72 bytes and rejects longer input.
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes.")
        return v

    @field_validator("company_name")
    @classmethod
    def safe_name(cls, v: str) -> str:
        for bad in (";", "--", "exec(", "eval("):
            if bad.lower() in v.lower():
                raise ValueError("Company name contains forbidden characters.")
        return v.strip()


class OnboardCompanyResponse(BaseModel):
    company_id: str
    company_name: str
    tenant_id: str
    admin_user_id: str
    dmm_initialized: bool
    message: str


class DMMStatusResponse(BaseModel):
    tenant_id: str
    has_company: bool
    has_dmm_config: bool
    has_ai_employee: bool
    has_knowledge: bool
    has_data_connection: bool
    has_channel: bool
    status: str  # "not_configured" | "configuring" | "ready_for_test" | "active" | "paused"
    checklist: dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/company",
    response_model=OnboardCompanyResponse,
    status_code=201,
    dependencies=[Depends(registration_guard)],
)
async def onboard_new_company(
    body: OnboardCompanyRequest,
    db: AsyncSession = Depends(get_db),
) -> OnboardCompanyResponse:
    """
    Create a new tenant company + admin user + DMM role config.
    Completely isolated — no data from other tenants.
    """
    company_id = str(uuid.uuid4())

    # Create company record
    company = Company(
        id=company_id,
        name=body.company_name,
        industry=body.industry,
        region=body.region,
        employees=body.employees,
        is_active=True,
    )
    db.add(company)

    # Create admin user (tenant-scoped)
    admin_id = str(uuid.uuid4())
    admin_user = User(
        id=admin_id,
        tenant_id=company_id,
        email=body.admin_email,
        name=body.admin_name,
        hashed_password=hash_password(body.admin_password),
        role="Company Admin",
        status="Active",
        is_active=True,
    )
    db.add(admin_user)

    # Auto-initialize DMM role configuration using existing defaults
    dmm_initialized = False
    try:
        from app.api.routers.role_config import _get_or_seed
        await db.flush()  # ensure company + user exist
        await _get_or_seed("DIGITAL_MARKETING_MANAGER", company_id, db)
        dmm_initialized = True
    except Exception as exc:
        logger.warning("DMM auto-init failed for %s: %s", company_id, exc)

    await db.flush()

    logger.info("New company onboarded: %s (%s)", body.company_name, company_id)

    return OnboardCompanyResponse(
        company_id=company_id,
        company_name=body.company_name,
        tenant_id=company_id,
        admin_user_id=admin_id,
        dmm_initialized=dmm_initialized,
        message=(
            f"Company '{body.company_name}' created successfully. "
            f"DMM configuration {'initialized' if dmm_initialized else 'pending'}. "
            "You can now log in and configure your AI workforce."
        ),
    )


@router.get("/status/{tenant_id}", response_model=DMMStatusResponse)
async def get_onboarding_status(
    tenant_id: str,
    auth_tenant_id: str = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DMMStatusResponse:
    """
    Return the onboarding/readiness status for the caller's own tenant.
    Used by the DMM checklist UI.

    The tenant in the URL must match the authenticated tenant.  A different
    tenant answers 404 so that tenant IDs cannot be probed.
    """
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=404, detail="Company not found.")
    # Company
    company_result = await db.execute(
        select(Company).where(Company.id == tenant_id, Company.is_active == True)
    )
    has_company = company_result.scalar_one_or_none() is not None

    # DMM role config
    from app.db.models import RoleConfiguration
    dmm_result = await db.execute(
        select(RoleConfiguration).where(
            RoleConfiguration.tenant_id == tenant_id,
            RoleConfiguration.role_key == "DIGITAL_MARKETING_MANAGER",
        )
    )
    has_dmm = dmm_result.scalar_one_or_none() is not None

    # AI Employee record
    emp_result = await db.execute(
        select(AIEmployee).where(
            AIEmployee.tenant_id == tenant_id,
            AIEmployee.role_key == "DIGITAL_MARKETING_MANAGER",
            AIEmployee.is_active == True,
        )
    )
    has_ai_employee = emp_result.scalar_one_or_none() is not None

    # Knowledge documents
    from app.db.models import KnowledgeDocument
    doc_result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.status == "indexed",
        ).limit(1)
    )
    has_knowledge = doc_result.scalar_one_or_none() is not None

    # Data connection
    from app.db.models import DataConnection
    conn_result = await db.execute(
        select(DataConnection).where(
            DataConnection.tenant_id == tenant_id,
            DataConnection.status == "connected",
        ).limit(1)
    )
    has_data = conn_result.scalar_one_or_none() is not None

    # Marketing channel
    from app.db.channel_models import MarketingChannelIntegration
    chan_result = await db.execute(
        select(MarketingChannelIntegration).where(
            MarketingChannelIntegration.tenant_id == tenant_id,
            MarketingChannelIntegration.is_enabled == True,
        ).limit(1)
    )
    has_channel = chan_result.scalar_one_or_none() is not None

    # Determine status
    if not has_company:
        status = "not_configured"
    elif not has_dmm:
        status = "not_configured"
    elif not has_ai_employee:
        status = "configuring"
    else:
        status = "active" if has_ai_employee else "ready_for_test"

    checklist = {
        "company_profile": has_company,
        "dmm_role_selected": has_dmm,
        "dmm_ai_employee": has_ai_employee,
        "knowledge_uploaded": has_knowledge,
        "data_connected": has_data,
        "channel_configured": has_channel,
    }

    return DMMStatusResponse(
        tenant_id=tenant_id,
        has_company=has_company,
        has_dmm_config=has_dmm,
        has_ai_employee=has_ai_employee,
        has_knowledge=has_knowledge,
        has_data_connection=has_data,
        has_channel=has_channel,
        status=status,
        checklist=checklist,
    )


@router.post("/activate-dmm", response_model=dict)
async def activate_dmm(
    body: dict,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Activate the DMM AI employee for the admin's own tenant.
    Validates configuration before activation.

    The tenant always comes from the authenticated admin.  A ``tenant_id`` in
    the body is accepted only for backward compatibility and must match.
    """
    tenant_id = admin_user.tenant_id
    requested = body.get("tenant_id")
    if requested and requested != tenant_id:
        raise HTTPException(404, "Company not found.")

    # Verify company
    company_result = await db.execute(
        select(Company).where(Company.id == tenant_id, Company.is_active == True)
    )
    if not company_result.scalar_one_or_none():
        raise HTTPException(404, "Company not found.")

    # Verify DMM role config
    from app.db.models import RoleConfiguration
    dmm_result = await db.execute(
        select(RoleConfiguration).where(
            RoleConfiguration.tenant_id == tenant_id,
            RoleConfiguration.role_key == "DIGITAL_MARKETING_MANAGER",
        )
    )
    role_config = dmm_result.scalar_one_or_none()
    if not role_config:
        raise HTTPException(400, "DMM role configuration not found. Complete configuration first.")

    # Check if AI Employee already exists
    emp_result = await db.execute(
        select(AIEmployee).where(
            AIEmployee.tenant_id == tenant_id,
            AIEmployee.role_key == "DIGITAL_MARKETING_MANAGER",
        )
    )
    existing_emp = emp_result.scalar_one_or_none()

    if existing_emp:
        existing_emp.status = "IDLE"
        existing_emp.is_active = True
        await db.flush()
        return {
            "success": True,
            "ai_employee_id": existing_emp.id,
            "status": "ACTIVE",
            "message": "DMM AI employee activated.",
        }

    # Create AI Employee record
    # Find a default LLM model
    from app.db.models import LLMModel
    llm_result = await db.execute(
        select(LLMModel).where(LLMModel.is_active == True).limit(1)
    )
    llm = llm_result.scalar_one_or_none()

    emp_id = str(uuid.uuid4())
    new_emp = AIEmployee(
        id=emp_id,
        tenant_id=tenant_id,
        llm_model_id=llm.id if llm else None,
        role_key="DIGITAL_MARKETING_MANAGER",
        name=role_config.agent_name or "Marketing Intelligence Agent",
        status="IDLE",
        is_active=True,
    )
    db.add(new_emp)
    await db.flush()

    return {
        "success": True,
        "ai_employee_id": emp_id,
        "status": "ACTIVE",
        "message": "DMM AI employee created and activated.",
    }
