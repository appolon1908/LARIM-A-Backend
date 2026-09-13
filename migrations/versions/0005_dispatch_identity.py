"""Persist dispatch recovery and bind identities to verified issuers."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "marketplace_users",
        sa.Column("issuer", sa.String(255), nullable=False, server_default="larimia-local"),
    )
    op.create_table(
        "dispatch_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "booking_id",
            UUID(as_uuid=True),
            sa.ForeignKey("marketplace_bookings.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
    )
    op.create_index("ix_dispatch_sessions_status", "dispatch_sessions", ["status"])
    op.create_index("ix_dispatch_sessions_created_at", "dispatch_sessions", ["created_at"])


def downgrade():
    raise RuntimeError("Issuer binding and dispatch recovery require forward-only rollback")
