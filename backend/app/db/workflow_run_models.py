"""
Workflow runs: one row per attempt to execute a workflow.

Why a table: the previous scheduler only remembered "last run minute" on the
workflow row, so a restart could repeat a run, a crash left the workflow stuck
as ``running`` forever, and there was no history.  The UNIQUE(workflow_id, slot)
constraint is what prevents duplicate scheduled runs, across ticks, processes
and restarts.  Rows hold no credentials and no tool output - only status and a
short sanitised reason.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # manual | scheduled | retry
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    # Scheduled: the UTC minute the run belongs to ("2026-10-21T09:00"); retries add "#rN";
    # manual runs use a unique "manual:<uuid>".  Unique per workflow.
    slot: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # queued | running | completed | failed | awaiting_approval | waiting_setup | skipped | cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pending_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("workflow_id", "slot", name="uq_workflow_run_slot"),
        Index("ix_workflow_runs_tenant_status", "tenant_id", "status"),
    )
