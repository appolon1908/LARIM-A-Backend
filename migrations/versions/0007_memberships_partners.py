"""membership billing and partner commerce

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "membership_plans",
        sa.Column("code", sa.String(80), primary_key=True),
        sa.Column("name_es", sa.String(160), nullable=False),
        sa.Column("name_en", sa.String(160), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("credits_per_period", sa.Integer(), nullable=False),
        sa.Column("billing_interval", sa.String(24), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("billing_interval IN ('MONTH','YEAR')", name="ck_membership_plans_billing_interval"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price_minor >= 0", name="ck_membership_plans_membership_plan_price_nonnegative"),
        sa.CheckConstraint("credits_per_period >= 0", name="ck_membership_plans_membership_plan_credits_nonnegative"),
    )
    op.execute(
        """
        INSERT INTO membership_plans
          (code, name_es, name_en, currency, price_minor, credits_per_period,
           billing_interval, active, created_at)
        VALUES
          ('LARIMIA_PLUS', 'LARIMÍA Plus', 'LARIMÍA Plus', 'DOP', 149900, 1, 'MONTH', true, now()),
          ('LARIMIA_PREMIER', 'LARIMÍA Premier', 'LARIMÍA Premier', 'DOP', 249900, 2, 'MONTH', true, now())
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.add_column("memberships", sa.Column("external_subscription_id", sa.String(255)))
    op.add_column("memberships", sa.Column("current_period_start", sa.DateTime(timezone=True)))
    op.add_column("memberships", sa.Column("current_period_end", sa.DateTime(timezone=True)))
    op.add_column("memberships", sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("memberships", sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"))
    op.add_column("memberships", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("memberships", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_unique_constraint("uq_memberships_external_subscription_id", "memberships", ["external_subscription_id"])
    op.create_foreign_key("fk_memberships_plan_code_membership_plans", "memberships", "membership_plans", ["plan_code"], ["code"])
    op.create_check_constraint("ck_memberships_status", "memberships", "status IN ('PENDING_PAYMENT','ACTIVE','PAST_DUE','CANCELLED','EXPIRED')")
    op.create_index("uq_memberships_one_live_customer", "memberships", ["customer_id"], unique=True, postgresql_where=sa.text("status IN ('PENDING_PAYMENT','ACTIVE','PAST_DUE')"))

    op.create_table(
        "membership_credits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memberships.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("credit_type", sa.String(48), nullable=False),
        sa.Column("granted_quantity", sa.Integer(), nullable=False),
        sa.Column("consumed_quantity", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("granted_quantity > 0", name="ck_membership_credits_membership_credit_granted_positive"),
        sa.CheckConstraint("consumed_quantity >= 0 AND consumed_quantity <= granted_quantity", name="ck_membership_credits_membership_credit_consumption_valid"),
    )
    op.create_index("ix_membership_credits_customer_id", "membership_credits", ["customer_id"])
    op.create_index("ix_membership_credits_membership_id", "membership_credits", ["membership_id"])

    op.create_table(
        "membership_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memberships.id", ondelete="SET NULL")),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_code", "external_event_id", name="uq_membership_provider_event"),
    )
    op.create_index("ix_membership_events_membership_id", "membership_events", ["membership_id"])

    op.create_table(
        "partner_organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("market_code", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("billing_currency", sa.String(3), nullable=False),
        sa.Column("credit_limit_minor", sa.BigInteger(), nullable=False),
        sa.Column("outstanding_minor", sa.BigInteger(), nullable=False),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING_REVIEW','ACTIVE','SUSPENDED','CLOSED')", name="ck_partner_organizations_status"),
        sa.CheckConstraint("credit_limit_minor >= 0", name="ck_partner_organizations_partner_credit_limit_nonnegative"),
        sa.CheckConstraint("outstanding_minor >= 0", name="ck_partner_organizations_partner_outstanding_nonnegative"),
        sa.CheckConstraint("payment_terms_days >= 0", name="ck_partner_organizations_partner_terms_nonnegative"),
    )
    op.create_index("ix_partner_organizations_market_code", "partner_organizations", ["market_code"])

    op.create_table(
        "partner_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_issuer", sa.String(255), nullable=False),
        sa.Column("identity_subject", sa.String(255), nullable=False),
        sa.Column("role_code", sa.String(48), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("identity_issuer", "identity_subject", name="uq_partner_identity"),
    )
    op.create_index("ix_partner_memberships_organization_id", "partner_memberships", ["organization_id"])

    op.create_table(
        "partner_properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("address_line_1", sa.String(255), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_partner_property_code"),
    )
    op.create_index("ix_partner_properties_organization_id", "partner_properties", ["organization_id"])

    op.create_table(
        "partner_booking_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_organizations.id"), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_properties.id"), nullable=False),
        sa.Column("requested_by_subject", sa.String(255), nullable=False),
        sa.Column("guest_name", sa.String(160), nullable=False),
        sa.Column("guest_reference", sa.String(120)),
        sa.Column("room_or_villa", sa.String(80)),
        sa.Column("service_code", sa.String(80), nullable=False),
        sa.Column("market_code", sa.String(16), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quotes.id")),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id")),
        sa.Column("approved_credit_minor", sa.BigInteger()),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING_QUOTE','QUOTED','CREDIT_APPROVED','BOOKED','REJECTED','CANCELLED')", name="ck_partner_booking_requests_status"),
        sa.CheckConstraint("approved_credit_minor IS NULL OR approved_credit_minor >= 0", name="ck_partner_booking_requests_partner_booking_credit_nonnegative"),
    )
    op.create_index("ix_partner_booking_requests_organization_id", "partner_booking_requests", ["organization_id"])
    op.create_index("ix_partner_booking_requests_property_id", "partner_booking_requests", ["property_id"])
    op.create_index("ix_partner_booking_requests_market_code", "partner_booking_requests", ["market_code"])

    op.create_table(
        "partner_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_organizations.id"), nullable=False),
        sa.Column("invoice_number", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','ISSUED','PAID','VOID','OVERDUE')", name="ck_partner_invoices_status"),
        sa.CheckConstraint("subtotal_minor >= 0 AND tax_minor >= 0 AND total_minor >= 0", name="ck_partner_invoices_partner_invoice_amounts_nonnegative"),
    )
    op.create_index("ix_partner_invoices_organization_id", "partner_invoices", ["organization_id"])

    op.create_table(
        "partner_invoice_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("booking_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_booking_requests.id")),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_partner_invoice_lines_partner_invoice_line_quantity_positive"),
        sa.CheckConstraint("unit_amount_minor >= 0 AND total_minor >= 0", name="ck_partner_invoice_lines_partner_invoice_line_amounts_nonnegative"),
    )
    op.create_index("ix_partner_invoice_lines_invoice_id", "partner_invoice_lines", ["invoice_id"])


def downgrade():
    for table in [
        "partner_invoice_lines",
        "partner_invoices",
        "partner_booking_requests",
        "partner_properties",
        "partner_memberships",
        "partner_organizations",
        "membership_events",
        "membership_credits",
    ]:
        op.drop_table(table)

    op.drop_index("uq_memberships_one_live_customer", table_name="memberships")
    op.drop_constraint("ck_memberships_status", "memberships", type_="check")
    op.drop_constraint("fk_memberships_plan_code_membership_plans", "memberships", type_="foreignkey")
    op.drop_constraint("uq_memberships_external_subscription_id", "memberships", type_="unique")
    for column in [
        "updated_at",
        "created_at",
        "version",
        "cancel_at_period_end",
        "current_period_end",
        "current_period_start",
        "external_subscription_id",
    ]:
        op.drop_column("memberships", column)
    op.drop_table("membership_plans")
