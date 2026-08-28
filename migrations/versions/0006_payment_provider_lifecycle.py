"""payment provider lifecycle and native webhooks

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_provider_references",
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_intents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("provider_order_id", sa.String(255), unique=True),
        sa.Column("provider_authorization_id", sa.String(255), unique=True),
        sa.Column("provider_capture_id", sa.String(255), unique=True),
        sa.Column("provider_customer_id", sa.String(255)),
        sa.Column("provider_payment_method_id", sa.String(255)),
        sa.Column("raw_status", sa.String(80)),
        sa.Column("client_action", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_provider_references_provider_code", "payment_provider_references", ["provider_code"])

    op.create_table(
        "payment_checkout_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("external_order_id", sa.String(255), unique=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("approve_url", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("booking_id", "provider_code", "idempotency_key", name="uq_payment_checkout_command"),
    )
    op.create_index("ix_payment_checkout_sessions_booking_id", "payment_checkout_sessions", ["booking_id"])
    op.create_index("ix_payment_checkout_sessions_customer_id", "payment_checkout_sessions", ["customer_id"])

    op.create_table(
        "payment_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_minor > 0", name="ck_payment_operations_payment_operation_amount_positive"),
        sa.UniqueConstraint("provider_code", "idempotency_key", name="uq_payment_operation_provider_key"),
    )
    op.create_index("ix_payment_operations_payment_intent_id", "payment_operations", ["payment_intent_id"])

    op.create_table(
        "payment_refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("requested_by_subject", sa.String(255), nullable=False),
        sa.Column("error_code", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_payment_refunds_payment_refund_amount_positive"),
        sa.UniqueConstraint("payment_intent_id", "idempotency_key", name="uq_payment_refund_command"),
        sa.UniqueConstraint("provider_code", "external_id", name="uq_payment_refund_provider_external"),
    )
    op.create_index("ix_payment_refunds_payment_intent_id", "payment_refunds", ["payment_intent_id"])
    op.create_index("ix_payment_refunds_booking_id", "payment_refunds", ["booking_id"])


def downgrade() -> None:
    op.drop_table("payment_refunds")
    op.drop_table("payment_operations")
    op.drop_table("payment_checkout_sessions")
    op.drop_table("payment_provider_references")
