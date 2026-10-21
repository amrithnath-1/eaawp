"""
Datasets and saved analysis reports (Data Analyst role).

A dataset is a table the company uploaded (CSV/XLSX), stored as normalised CSV text with a
typed schema. Reports store the spec that was run and the computed result, so a report is
reproducible and never contains figures the engine did not compute.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content_csv: Mapped[str] = mapped_column(Text, nullable=False, default="")
    columns_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Restricted datasets are visible/analysable by company administrators only (and never offered to agents).
    is_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_datasets_tenant_name", "tenant_id", "name"),)


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    spec_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    narrative_source: Mapped[str] = mapped_column(String(16), nullable=False, default="template")
    is_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
