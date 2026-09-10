"""durable inbox and outbox leasing

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "outbox_events",
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
    )
    op.add_column("outbox_events", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("outbox_events", sa.Column("locked_until", sa.DateTime(timezone=True)))
    op.add_column("outbox_events", sa.Column("lock_token", sa.String(64)))
    op.add_column("outbox_events", sa.Column("last_error", sa.Text()))
    op.create_index(
        "ix_outbox_delivery_ready",
        "outbox_events",
        ["status", "next_attempt_at", "created_at"],
    )

    op.add_column("inbox_receipts", sa.Column("body_sha256", sa.String(64)))
    op.add_column(
        "inbox_receipts",
        sa.Column("status", sa.String(24), nullable=False, server_default="RECEIVED"),
    )
    op.add_column(
        "inbox_receipts",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("inbox_receipts", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("inbox_receipts", sa.Column("locked_until", sa.DateTime(timezone=True)))
    op.add_column("inbox_receipts", sa.Column("lock_token", sa.String(64)))
    op.add_column("inbox_receipts", sa.Column("last_error", sa.Text()))
    op.create_index(
        "ix_inbox_processing_ready",
        "inbox_receipts",
        ["status", "next_attempt_at", "received_at"],
    )


def downgrade():
    op.drop_index("ix_inbox_processing_ready", table_name="inbox_receipts")
    for column in [
        "last_error",
        "lock_token",
        "locked_until",
        "next_attempt_at",
        "attempts",
        "status",
        "body_sha256",
    ]:
        op.drop_column("inbox_receipts", column)

    op.drop_index("ix_outbox_delivery_ready", table_name="outbox_events")
    for column in [
        "last_error",
        "lock_token",
        "locked_until",
        "next_attempt_at",
        "status",
    ]:
        op.drop_column("outbox_events", column)
