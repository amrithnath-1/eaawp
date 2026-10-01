"""add_email_integration_tables

Revision ID: i6f0d15g7e43
Revises: h5e9c04f6d32
Create Date: 2026-09-12 12:00:00.000000

Creates:
  - external_integrations  (SMTP provider config, credentials encrypted)
  - email_audit_logs       (safe send-attempt metadata, no credentials)

Security notes
--------------
- encrypted_password stores Fernet-encrypted credentials — never plain text.
- email_audit_logs stores safe metadata only: counts, domains, lengths.
  No SMTP password, no full email body, no authentication tokens.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i6f0d15g7e43"
down_revision: Union[str, None] = "h5e9c04f6d32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── external_integrations ─────────────────────────────────────────────────
    op.create_table(
        "external_integrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False, server_default="smtp"),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("smtp_host", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("username", sa.String(length=255), nullable=False, server_default=""),
        # encrypted_password — never stored plain, never returned in responses
        sa.Column("encrypted_password", sa.Text(), nullable=False, server_default=""),
        sa.Column("tls_mode", sa.String(length=16), nullable=False, server_default="starttls"),
        sa.Column("sender_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("sender_display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="not_tested"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False, server_default="admin"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("external_integrations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_external_integrations_tenant_id"), ["tenant_id"], unique=False
        )

    # ── email_audit_logs ──────────────────────────────────────────────────────
    op.create_table(
        "email_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=128), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=True),
        sa.Column("approval_request_id", sa.String(length=36), nullable=True),
        # Safe metadata only — no credentials, no full body
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipient_domains", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("subject_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("body_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("email_audit_logs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_email_audit_logs_tenant_id"), ["tenant_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_email_audit_logs_attempted_at"), ["attempted_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("email_audit_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_email_audit_logs_attempted_at"))
        batch_op.drop_index(batch_op.f("ix_email_audit_logs_tenant_id"))
    op.drop_table("email_audit_logs")

    with op.batch_alter_table("external_integrations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_external_integrations_tenant_id"))
    op.drop_table("external_integrations")
