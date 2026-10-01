"""GET /api/v1/companies  — list all companies (admin use)."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Company
from app.schemas.api import CompanyOut, CompanyCreate
import uuid, datetime

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])

@router.get("", response_model=list[CompanyOut])
async def list_companies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Company).where(Company.is_active == True))
    return result.scalars().all()

@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(company_id: str, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException
    company = await db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company

@router.post("", response_model=CompanyOut, status_code=201)
async def create_company(body: CompanyCreate, db: AsyncSession = Depends(get_db)):
    company = Company(id=str(uuid.uuid4()), **body.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company
