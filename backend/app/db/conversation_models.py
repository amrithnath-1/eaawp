"""
Persistent AI employee conversations (the History tab) and the company's approved profile.

Conversations are private to the person who had them: no other user, administrators included, can list or read them
through the API. Each conversation belongs to one AI employee role; it can only be continued while that role is the
person's selected workspace, and only its own messages are given back to the model as context.

Only user-visible text is stored: the person's message, the AI employee's answer, and a small display summary (plan
status, step descriptions, public source names). No system prompts, tool payloads, credentials or reasoning.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_conversations_owner_recent", "tenant_id", "user_id", "updated_at"),)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sender: Mapped[str] = mapped_column(String(16), nullable=False)          # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Display summary only: {"sources": [...], "plan_status": ..., "step_summaries": [...], "requires_approval": bool,
    # "pending_task_id": ..., "integration_action": {...}, "error": bool}
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_conversation_messages_conv_created", "conversation_id", "created_at"),)


class CompanyProfile(Base):
    """Administrator-approved facts about the company that every AI employee may rely on (one row per company)."""
    __tablename__ = "company_profiles"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
