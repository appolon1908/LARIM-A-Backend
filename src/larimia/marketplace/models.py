import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from larimia.shared.db import Base


def now() -> datetime:
    return datetime.now(UTC)


class Entity:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class User(Entity, Base):
    __tablename__ = "marketplace_users"
    subject: Mapped[str] = mapped_column(String(255), unique=True)
    issuer: Mapped[str] = mapped_column(String(255), default="larimia-local")
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["customer"])
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Address(Entity, Base):
    __tablename__ = "customer_addresses"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    market_code: Mapped[str] = mapped_column(String(16))


class Provider(Entity, Base):
    __tablename__ = "provider_profiles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    market_code: Mapped[str] = mapped_column(String(16), default="DO-SDQ")
    services: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    availability: Mapped[list[dict]] = mapped_column(JSON, default=list)
    latitude: Mapped[float] = mapped_column(Float, default=18.4861)
    longitude: Mapped[float] = mapped_column(Float, default=-69.9312)
    radius_km: Mapped[float] = mapped_column(Float, default=20)
    rating: Mapped[float] = mapped_column(Float, default=5)
    completion_rate: Mapped[float] = mapped_column(Float, default=1)
    workload: Mapped[int] = mapped_column(Integer, default=0)


class Service(Entity, Base):
    __tablename__ = "catalog_services"
    code: Mapped[str] = mapped_column(String(80), unique=True)
    category: Mapped[str] = mapped_column(String(80))
    name: Mapped[dict[str, str]] = mapped_column(JSON)
    market_code: Mapped[str] = mapped_column(String(16), default="DO-SDQ", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="DOP")
    duration_minutes: Mapped[int] = mapped_column(Integer)
    base_minor: Mapped[int] = mapped_column(BigInteger)
    travel_minor: Mapped[int] = mapped_column(BigInteger, default=50000)
    tax_bps: Mapped[int] = mapped_column(Integer, default=0)
    fee_bps: Mapped[int] = mapped_column(Integer, default=2000)
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Quote(Entity, Base):
    __tablename__ = "marketplace_quotes"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog_services.id"))
    address_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_addresses.id"))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)


class MarketplaceBooking(Entity, Base):
    __tablename__ = "marketplace_bookings"
    quote_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_quotes.id"), unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_profiles.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="QUOTED", index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    address: Mapped[dict[str, Any]] = mapped_column(JSON)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class StatusHistory(Entity, Base):
    __tablename__ = "booking_status_history"
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_bookings.id"), index=True)
    actor: Mapped[str] = mapped_column(String(255))
    previous: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))


class Offer(Entity, Base):
    __tablename__ = "dispatch_offers"
    __table_args__ = (UniqueConstraint("booking_id", "provider_id", "attempt"),)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_bookings.id"), index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_profiles.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    rank_score: Mapped[float] = mapped_column(Float)
    attempt: Mapped[int] = mapped_column(Integer, default=1)


class Payment(Entity, Base):
    __tablename__ = "marketplace_payments"
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_bookings.id"), unique=True
    )
    status: Mapped[str] = mapped_column(String(32))
    external_reference: Mapped[str] = mapped_column(String(255), unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    refunded_minor: Mapped[int] = mapped_column(BigInteger, default=0)


class Refund(Entity, Base):
    __tablename__ = "marketplace_refunds"
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_payments.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(500))
    external_reference: Mapped[str] = mapped_column(String(255), unique=True)


class Earning(Entity, Base):
    __tablename__ = "provider_earnings"
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_bookings.id"), unique=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_profiles.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)


class Review(Entity, Base):
    __tablename__ = "marketplace_reviews"
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_bookings.id"), unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"))
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_profiles.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(String(2000), default="")


class Case(Entity, Base):
    __tablename__ = "marketplace_cases"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("marketplace_bookings.id"))
    kind: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    body: Mapped[str] = mapped_column(String(4000))
    resolution: Mapped[str | None] = mapped_column(String(4000))


class Notification(Entity, Base):
    __tablename__ = "marketplace_notifications"
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outbox_events.id"), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="DELIVERED")


class Block(Entity, Base):
    __tablename__ = "blocked_relationships"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_profiles.id"), index=True)
    __table_args__ = (UniqueConstraint("customer_id", "provider_id"),)


class Payout(Entity, Base):
    __tablename__ = "marketplace_payouts"
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_profiles.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="SCHEDULED", index=True)
    earning_ids: Mapped[list[str]] = mapped_column(JSON)
    approved_by: Mapped[str] = mapped_column(String(255))
    external_reference: Mapped[str | None] = mapped_column(String(255), unique=True)


class Conversation(Entity, Base):
    __tablename__ = "marketplace_conversations"
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_bookings.id"), unique=True
    )


class Message(Entity, Base):
    __tablename__ = "conversation_messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_conversations.id"), index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"))
    body: Mapped[str] = mapped_column(String(4000))


class Document(Entity, Base):
    __tablename__ = "private_documents"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketplace_bookings.id"), index=True
    )
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="QUARANTINED")


class Promotion(Entity, Base):
    __tablename__ = "marketplace_promotions"
    code: Mapped[str] = mapped_column(String(80), unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RefreshSession(Entity, Base):
    __tablename__ = "refresh_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("marketplace_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class DispatchSession(Entity, Base):
    __tablename__ = "dispatch_sessions"
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_bookings.id"), unique=True
    )
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)


class EventDelivery(Entity, Base):
    __tablename__ = "integration_event_deliveries"
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outbox_events.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    last_error: Mapped[str | None] = mapped_column(String(120))
