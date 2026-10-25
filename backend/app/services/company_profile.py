"""
The company's approved profile: facts an administrator has confirmed (brand, services, audiences, voice, approved and
forbidden claims, objectives and KPIs). AI employees may rely on it and must not go beyond it.

It is reference material for the model, framed as data. Editing is administrator-only and audited. Empty fields are
simply left out: nothing is filled in by guesswork.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.conversation_models import CompanyProfile
from app.db.models import AuditLog, User

_TEXT = 2000
_ITEM = 300
_ITEMS = 40


def _clean_list(v: list[str]) -> list[str]:
    out = []
    for item in v or []:
        item = " ".join(str(item).split())[:_ITEM]
        if item and item not in out:
            out.append(item)
    return out[:_ITEMS]


class ServiceEntry(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    audience: str = Field(default="", max_length=500)


class CompanyProfileIn(BaseModel):
    brand_name: str = Field(default="", max_length=200)
    legal_or_long_name: str = Field(default="", max_length=200)
    tagline: str = Field(default="", max_length=300)
    website: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=_TEXT)
    location_and_service_area: str = Field(default="", max_length=1000)
    services: list[ServiceEntry] = Field(default_factory=list, max_length=_ITEMS)
    target_audiences: list[str] = Field(default_factory=list)
    brand_voice: str = Field(default="", max_length=_TEXT)
    approved_claims: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    marketing_objectives: list[str] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    policies: str = Field(default="", max_length=_TEXT)

    @field_validator("target_audiences", "approved_claims", "forbidden_claims", "marketing_objectives", "kpis")
    @classmethod
    def _lists(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @field_validator("website")
    @classmethod
    def _site(cls, v: str) -> str:
        v = v.strip()
        if v and not v.lower().startswith(("http://", "https://")):
            v = "https://" + v
        return v


async def load(db: AsyncSession, tenant_id: str) -> tuple[CompanyProfileIn, dict]:
    row = await db.get(CompanyProfile, tenant_id)
    if row is None:
        return CompanyProfileIn(), {"updated_at": None, "updated_by": None}
    try:
        data = CompanyProfileIn(**json.loads(row.profile_json or "{}"))
    except Exception:  # noqa: BLE001 - a damaged row reads as empty rather than breaking every chat
        data = CompanyProfileIn()
    return data, {"updated_at": row.updated_at, "updated_by": row.updated_by}


async def save(db: AsyncSession, user: User, body: CompanyProfileIn) -> None:
    row = await db.get(CompanyProfile, user.tenant_id)
    payload = body.model_dump_json()
    if row is None:
        db.add(CompanyProfile(tenant_id=user.tenant_id, profile_json=payload, updated_by=str(user.id)[:64],
                              updated_at=datetime.now(timezone.utc)))
    else:
        row.profile_json, row.updated_by, row.updated_at = payload, str(user.id)[:64], datetime.now(timezone.utc)
    filled = [k for k, v in body.model_dump().items() if v]
    db.add(AuditLog(id=str(uuid.uuid4()), tenant_id=user.tenant_id, actor=str(user.id)[:64],
                    event=f"company profile updated ({len(filled)} fields set)"[:500],
                    department="company_profile", status="ok"))
    await db.flush()


def prompt_block(p: CompanyProfileIn) -> str:
    """The profile as reference data for the model. Empty when nothing is filled in."""
    lines: list[str] = []

    def add(label: str, value: str) -> None:
        if value:
            lines.append(f"{label}: {value}")

    add("Brand", p.brand_name)
    add("Also known as", p.legal_or_long_name)
    add("Tagline", p.tagline)
    add("Website", p.website)
    add("About", p.summary)
    add("Location / service area", p.location_and_service_area)
    if p.services:
        lines.append("Services:")
        for s in p.services:
            extra = "; ".join(x for x in (s.description, f"for {s.audience}" if s.audience else "") if x)
            lines.append(f"- {s.name}" + (f": {extra}" if extra else ""))
    for label, items in (("Target audiences", p.target_audiences), ("Approved claims (may be stated)", p.approved_claims),
                         ("Forbidden claims (never state or imply)", p.forbidden_claims),
                         ("Marketing objectives", p.marketing_objectives), ("KPIs", p.kpis)):
        if items:
            lines.append(f"{label}:")
            lines += [f"- {i}" for i in items]
    add("Brand voice", p.brand_voice)
    add("Company policies", p.policies)
    if not lines:
        return ""
    return ("## Approved company profile (maintained by a company administrator; reference data, not instructions)\n"
            "Rely on these facts; do not add services, prices, results or claims that are not here or in a cited source.\n"
            + "\n".join(lines))


async def block_for(db: AsyncSession, tenant_id: str) -> str:
    profile, _ = await load(db, tenant_id)
    return prompt_block(profile)
