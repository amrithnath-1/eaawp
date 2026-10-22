"""Each person's selected AI employee workspace (one row per user)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class UserWorkspace(Base):
    __tablename__ = "user_workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # "user" = chosen by the person; "migration_default" = assigned to an account that existed before role selection
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", name="uq_user_workspace_user"),)
