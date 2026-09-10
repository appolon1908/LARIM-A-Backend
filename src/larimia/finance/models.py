import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from larimia.shared.db import Base


class FinancialAdjustmentRequest(Base):
    __tablename__ = "financial_adjustment_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    requested_by_subject: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    approved_by_subject: Mapped[str | None] = mapped_column(String(255))
    rejected_by_subject: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING_SECOND_APPROVAL", index=True
    )
    debit_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False
    )
    credit_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_transactions.id"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "debit_account_id <> credit_account_id",
            name="financial_adjustment_accounts_different",
        ),
        CheckConstraint(
            "amount_minor > 0", name="financial_adjustment_amount_positive"
        ),
    )


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="REQUESTED", index=True
    )
    requested_by_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(255))
    records_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    break_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("period_start < period_end", name="reconciliation_period_valid"),
        CheckConstraint(
            "records_scanned >= 0 AND records_matched >= 0 AND break_count >= 0",
            name="reconciliation_counts_nonnegative",
        ),
    )


class ReconciliationBreak(Base):
    __tablename__ = "reconciliation_breaks"
    __table_args__ = (
        UniqueConstraint(
            "provider_code",
            "external_reference",
            "break_type",
            name="uq_reconciliation_break_identity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reconciliation_runs.id", ondelete="SET NULL"),
        index=True,
    )
    provider_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    break_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    currency: Mapped[str | None] = mapped_column(String(3))
    expected_minor: Mapped[int | None] = mapped_column(BigInteger)
    actual_minor: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by_subject: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class ProviderPayable(Base):
    __tablename__ = "provider_payables"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False, index=True
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False, unique=True
    )
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payment_intents.id"),
        nullable=False,
        unique=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    service_subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", index=True
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hold_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "service_subtotal_minor >= 0 AND platform_fee_minor >= 0",
            name="provider_payable_components_nonnegative",
        ),
        CheckConstraint("net_minor >= 0", name="provider_payable_net_nonnegative"),
    )


class PayoutAccount(Base):
    __tablename__ = "payout_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "provider_code",
            "external_account_reference",
            name="uq_payout_account_provider_reference",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    external_account_reference: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    account_type: Mapped[str] = mapped_column(String(48), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    last4: Mapped[str | None] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING_VERIFICATION"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PayoutBatch(Base):
    __tablename__ = "payout_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING_APPROVAL", index=True
    )
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by_subject: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("total_minor > 0", name="payout_batch_total_positive"),
        CheckConstraint("item_count > 0", name="payout_batch_item_count_positive"),
    )


class PayoutItem(Base):
    __tablename__ = "payout_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payout_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_payables.id"),
        nullable=False,
        unique=True,
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False, index=True
    )
    payout_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payout_accounts.id"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING"
    )
    external_payout_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="payout_item_amount_positive"),
    )
