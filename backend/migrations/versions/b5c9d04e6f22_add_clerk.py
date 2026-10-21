"""add_institutional_clerk_tables

Revision ID: b5c9d04e6f22
Revises: a4b8c93d5e21
Create Date: 2026-10-21 22:00:00.000000

Institutional Clerk: service requests, their timeline and issued documents. Additive only.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5c9d04e6f22"
down_revision: Union[str, None] = "a4b8c93d5e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    now = sa.text("(CURRENT_TIMESTAMP)")
    op.create_table(
        "service_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("request_type", sa.String(32), nullable=False, server_default="general"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("fields_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column("priority", sa.String(8), nullable=False, server_default="normal"),
        sa.Column("requester_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("requester_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("assignee_id", sa.String(36), nullable=True),
        sa.Column("assignee_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("due_date", sa.String(10), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_service_requests_tenant_id", "service_requests", ["tenant_id"])
    op.create_index("ix_service_requests_tenant_status", "service_requests", ["tenant_id", "status"])

    op.create_table(
        "service_request_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="comment"),
        sa.Column("actor", sa.String(64), nullable=False, server_default=""),
        sa.Column("actor_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["service_requests.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_service_request_events_tenant_id", "service_request_events", ["tenant_id"])
    op.create_index("ix_service_request_events_request_id", "service_request_events", ["request_id"])

    op.create_table(
        "issued_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("template_key", sa.String(32), nullable=False, server_default=""),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("fields_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("serial", sa.String(40), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("issued_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["service_requests.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "serial", name="uq_issued_documents_tenant_serial"),
    )
    op.create_index("ix_issued_documents_tenant_id", "issued_documents", ["tenant_id"])
    op.create_index("ix_issued_documents_request_id", "issued_documents", ["request_id"])


def downgrade() -> None:
    op.drop_table("issued_documents")
    op.drop_table("service_request_events")
    op.drop_table("service_requests")
