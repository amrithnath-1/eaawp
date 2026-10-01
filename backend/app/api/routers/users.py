"""Users router — authenticated, admin-only writes."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import get_current_user, require_admin, hash_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.api import UserOut, UserCreate

router = APIRouter(prefix="/api/v1/users", tags=["users"])

# Roles that an admin is permitted to assign.  "superadmin" intentionally
# excluded — only granted by direct DB access.
_ASSIGNABLE_ROLES = {"Employee", "Manager", "Company Admin", "AI Administrator"}

@router.get("", response_model=list[UserOut])
async def list_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List active users for the authenticated user's tenant."""
    result = await db.execute(
        select(User).where(User.tenant_id == current_user.tenant_id, User.is_active == True)
    )
    return result.scalars().all()

@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user in the admin's tenant.  Requires admin role.
    The role field is validated against an allowlist — only designated
    roles may be assigned; escalation to superadmin is not permitted here.
    """
    tenant_id = admin_user.tenant_id

    # Validate the requested role against the allowlist.
    if body.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Role '{body.role}' cannot be assigned here. "
                   f"Allowed: {sorted(_ASSIGNABLE_ROLES)}",
        )

    existing = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.email == body.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered in this tenant")

    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=body.email,
        name=body.name,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
