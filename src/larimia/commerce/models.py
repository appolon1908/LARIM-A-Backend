import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from larimia.shared.db import Base


class MembershipPlan(Base):
    __tablename__ = "membership_plans"

    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    name_es: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credits_per_period: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    billing_interval: Mapped[str] = mapped_column(String(24), nullable=False, default="MONTH")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="membership_plan_price_nonnegative"),
        CheckConstraint("credits_per_period >= 0", name="membership_plan_credits_nonnegative"),
    )


class MembershipCredit(Base):
    __tablename__ = "membership_credits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    credit_type: Mapped[str] = mapped_column(String(48), nullable=False, default="SERVICE")
    granted_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("granted_quantity > 0", name="membership_credit_granted_positive"),
        CheckConstraint(
            "consumed_quantity >= 0 AND consumed_quantity <= granted_quantity",
            name="membership_credit_consumption_valid",
        ),
    )


class MembershipEvent(Base):
    __tablename__ = "membership_events"
    __table_args__ = (
        UniqueConstraint("provider_code", "external_event_id", name="uq_membership_provider_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL"), index=True
    )
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PartnerOrganization(Base):
    __tablename__ = "partner_organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    market_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_REVIEW")
    billing_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="DOP")
    credit_limit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    outstanding_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("credit_limit_minor >= 0", name="partner_credit_limit_nonnegative"),
        CheckConstraint("outstanding_minor >= 0", name="partner_outstanding_nonnegative"),
        CheckConstraint("payment_terms_days >= 0", name="partner_terms_nonnegative"),
    )


class PartnerMembership(Base):
    __tablename__ = "partner_memberships"
    __table_args__ = (
        UniqueConstraint("identity_issuer", "identity_subject", name="uq_partner_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    role_code: Mapped[str] = mapped_column(String(48), nullable=False, default="BOOKER")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PartnerProperty(Base):
    __tablename__ = "partner_properties"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_partner_property_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PartnerBookingRequest(Base):
    __tablename__ = "partner_booking_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_organizations.id"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_properties.id"), nullable=False, index=True
    )
    requested_by_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    guest_name: Mapped[str] = mapped_column(String(160), nullable=False)
    guest_reference: Mapped[str | None] = mapped_column(String(120))
    room_or_villa: Mapped[str | None] = mapped_column(String(80))
    service_code: Mapped[str] = mapped_column(String(80), nullable=False)
    market_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_QUOTE")
    quote_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quotes.id"))
    booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    approved_credit_minor: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "approved_credit_minor IS NULL OR approved_credit_minor >= 0",
            name="partner_booking_credit_nonnegative",
        ),
    )


class PartnerInvoice(Base):
    __tablename__ = "partner_invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_organizations.id"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "subtotal_minor >= 0 AND tax_minor >= 0 AND total_minor >= 0",
            name="partner_invoice_amounts_nonnegative",
        ),
    )


class PartnerInvoiceLine(Base):
    __tablename__ = "partner_invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    booking_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_booking_requests.id")
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="partner_invoice_line_quantity_positive"),
        CheckConstraint(
            "unit_amount_minor >= 0 AND total_minor >= 0",
            name="partner_invoice_line_amounts_nonnegative",
        ),
    )


# Keep one ORM identity for the existing memberships table while this bounded
# context owns the billing lifecycle fields added by migration 0007.
from larimia.marketplace.models import Membership

Membership.external_subscription_id = mapped_column(String(255), unique=True)
Membership.current_period_start = mapped_column(DateTime(timezone=True))
Membership.current_period_end = mapped_column(DateTime(timezone=True))
Membership.cancel_at_period_end = mapped_column(Boolean, default=False, nullable=False)
Membership.version = mapped_column(BigInteger, default=1, nullable=False)
Membership.created_at = mapped_column(DateTime(timezone=True), nullable=False)
Membership.updated_at = mapped_column(DateTime(timezone=True), nullable=False)
