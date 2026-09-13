"""Leased external delivery allows network I/O outside database transactions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integration_event_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbox_events.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("last_error", sa.String(120)),
    )
    op.create_index(
        "ix_integration_event_deliveries_status", "integration_event_deliveries", ["status"]
    )
    op.create_index(
        "ix_integration_event_deliveries_created_at", "integration_event_deliveries", ["created_at"]
    )
    op.create_index(
        "ix_delivery_pending", "integration_event_deliveries", ["status", "available_at"]
    )


def downgrade():
    raise RuntimeError("Drain or export the event queue before reviewed rollback")
