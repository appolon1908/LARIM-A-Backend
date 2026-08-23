"""initial marketplace baseline

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

booking_status = postgresql.ENUM(
    "DRAFT","QUOTED","CONFIRMED","MATCHING","ASSIGNED","EN_ROUTE","ARRIVED",
    "IN_SERVICE","COMPLETED","SETTLING","SETTLED","CANCELLED","DISPUTED",
    name="booking_status", create_type=False
)

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    booking_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_number", sa.String(32), nullable=False, unique=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_code", sa.String(16), nullable=False),
        sa.Column("status", booking_status, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("customer_total_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_bookings_customer_id", "bookings", ["customer_id"])
    op.create_index("ix_bookings_market_code", "bookings", ["market_code"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "inbox_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("provider", "external_event_id", name="uq_inbox_provider_event"),
    )

    op.create_table(
        "ledger_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(120), nullable=False, unique=True),
        sa.Column("account_type", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
    )
    op.create_table(
        "ledger_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference_type", sa.String(80), nullable=False),
        sa.Column("reference_id", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
    )

def downgrade():
    for table in ["ledger_entries","ledger_transactions","ledger_accounts","inbox_receipts","outbox_events","audit_events","bookings"]:
        op.drop_table(table)
    booking_status.drop(op.get_bind(), checkfirst=True)
