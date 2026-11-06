"""
Project Manager AI employee (ported from Vyuham): storage.

  pm_state      one row per company: the working records (team roster, projects, tasks, approvals, decisions,
                assignments, deliverables, weights, specifications, plans, budgets, change requests, skill reviews,
                room messages) and the hash-chained audit ledger, as one JSON document with a version counter.
                Every request loads it under a row lock and writes it back once, so two requests can never
                double-assign a task (the same guarantee Vyuham's single lock gave).
  pm_documents  project documents (metadata + status); the file text lives in pm_chunks.
  pm_chunks     extracted, chunked text used for analysis and search, flagged when it looks like an injected instruction.
All rows are tenant-scoped.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class PmState(Base):
    __tablename__ = "pm_state"

    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PmDocument(Base):
    __tablename__ = "pm_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ext: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploaded")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suspicious_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_pm_documents_tenant_project", "tenant_id", "project_id"),)


class PmChunk(Base):
    __tablename__ = "pm_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("pm_documents.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(40), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_pm_chunks_tenant_project", "tenant_id", "project_id"),
                      Index("ix_pm_chunks_document", "document_id", "seq"))
