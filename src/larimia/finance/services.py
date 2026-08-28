from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.infrastructure.models import Booking
from larimia.config import get_settings
from larimia.finance.models import (
    FinancialAdjustmentRequest,
    ProviderPayable,
    ReconciliationBreak,
)
from larimia.ledger.infrastructure_models import (
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from larimia.marketplace.models import Assignment, PaymentIntent, Quote
from larimia.shared.events import emit


class FinancialInvariantError(ValueError):
    pass


@dataclass(frozen=True)
class JournalLine:
    account_code: str
    direction: str
    amount_minor: int
    currency: str


def post_journal(
    db: Session,
    *,
    reference_type: str,
    reference_id: str,
    description: str,
    lines: list[JournalLine],
    metadata: dict | None = None,
) -> LedgerTransaction:
    """Post one immutable, balanced journal transaction."""
    existing = db.scalar(
        select(LedgerTransaction).where(
            LedgerTransaction.reference_type == reference_type,
            LedgerTransaction.reference_id == reference_id,
        )
    )
    if existing is not None:
        return existing
    if not lines:
        raise FinancialInvariantError("A journal must contain entries")

    balances: dict[str, int] = {}
    normalized: list[tuple[LedgerAccount, JournalLine]] = []
    for line in lines:
        if line.direction not in {"DEBIT", "CREDIT"}:
            raise FinancialInvariantError(
                "Journal direction must be DEBIT or CREDIT"
            )
        if line.amount_minor <= 0:
            raise FinancialInvariantError("Journal amounts must be positive")
        currency = line.currency.upper()
        account = db.scalar(
            select(LedgerAccount).where(
                LedgerAccount.code == line.account_code,
                LedgerAccount.currency == currency,
                LedgerAccount.active.is_(True),
            )
        )
        if account is None:
            raise FinancialInvariantError(
                f"Active ledger account {line.account_code!r} is not configured"
            )
        signed = (
            line.amount_minor
            if line.direction == "DEBIT"
            else -line.amount_minor
        )
        balances[currency] = balances.get(currency, 0) + signed
        normalized.append(
            (
                account,
                JournalLine(
                    line.account_code,
                    line.direction,
                    line.amount_minor,
                    currency,
                ),
            )
        )

    unbalanced = {
        currency: amount for currency, amount in balances.items() if amount
    }
    if unbalanced:
        raise FinancialInvariantError(
            f"Journal is not balanced: {unbalanced}"
        )

    now = datetime.now(UTC)
    transaction = LedgerTransaction(
        reference_type=reference_type,
        reference_id=reference_id,
        description=description[:500],
        status="POSTED",
        metadata_json=metadata or {},
        created_at=now,
        posted_at=now,
    )
    db.add(transaction)
    db.flush()
    for account, line in normalized:
        db.add(
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=account.id,
                direction=line.direction,
                amount_minor=line.amount_minor,
                currency=line.currency,
            )
        )
    db.flush()
    return transaction


def open_reconciliation_break(
    db: Session,
    *,
    provider_code: str,
    external_reference: str,
    break_type: str,
    details: str,
    currency: str | None = None,
    expected_minor: int | None = None,
    actual_minor: int | None = None,
    run_id=None,
) -> ReconciliationBreak:
    existing = db.scalar(
        select(ReconciliationBreak).where(
            ReconciliationBreak.provider_code == provider_code,
            ReconciliationBreak.external_reference == external_reference,
            ReconciliationBreak.break_type == break_type,
        )
    )
    if existing is not None:
        return existing
    row = ReconciliationBreak(
        run_id=run_id,
        provider_code=provider_code,
        external_reference=external_reference,
        break_type=break_type,
        status="OPEN",
        currency=currency,
        expected_minor=expected_minor,
        actual_minor=actual_minor,
        details=details[:4000],
        resolution=None,
        resolved_by_subject=None,
        created_at=datetime.now(UTC),
        resolved_at=None,
        version=1,
    )
    db.add(row)
    db.flush()
    emit(
        db,
        aggregate_type="reconciliation_break",
        aggregate_id=str(row.id),
        event_type="finance.reconciliation_break_opened.v1",
        payload={
            "break_id": str(row.id),
            "provider_code": provider_code,
            "break_type": break_type,
            "external_reference": external_reference,
        },
    )
    return row


def record_captured_payment(
    db: Session,
    intent: PaymentIntent,
) -> ProviderPayable | None:
    """Create a payable and balanced capture journal exactly once."""
    existing = db.scalar(
        select(ProviderPayable).where(
            ProviderPayable.payment_intent_id == intent.id
        )
    )
    if existing is not None:
        return existing

    booking = db.get(Booking, intent.booking_id, with_for_update=True)
    if booking is None:
        open_reconciliation_break(
            db,
            provider_code=intent.provider_code,
            external_reference=str(intent.id),
            break_type="CAPTURE_WITHOUT_BOOKING",
            details="Captured payment references a missing booking",
            currency=intent.currency,
            actual_minor=intent.amount_minor,
        )
        return None
    if booking.status not in {
        BookingStatus.COMPLETED,
        BookingStatus.SETTLING,
        BookingStatus.SETTLED,
    }:
        open_reconciliation_break(
            db,
            provider_code=intent.provider_code,
            external_reference=str(intent.id),
            break_type="CAPTURE_BEFORE_SERVICE_COMPLETION",
            details=f"Booking status is {booking.status.value}",
            currency=intent.currency,
            actual_minor=intent.amount_minor,
        )
        return None

    assignment = db.scalar(
        select(Assignment).where(Assignment.booking_id == booking.id)
    )
    quote = db.get(Quote, booking.quote_id) if booking.quote_id else None
    if assignment is None or quote is None:
        open_reconciliation_break(
            db,
            provider_code=intent.provider_code,
            external_reference=str(intent.id),
            break_type="CAPTURE_CONTEXT_INCOMPLETE",
            details="Assignment or authoritative quote is missing",
            currency=intent.currency,
            actual_minor=intent.amount_minor,
        )
        return None
    if quote.currency != intent.currency or quote.total_minor != intent.amount_minor:
        open_reconciliation_break(
            db,
            provider_code=intent.provider_code,
            external_reference=str(intent.id),
            break_type="CAPTURE_AMOUNT_MISMATCH",
            details=(
                "Captured amount/currency differs from authoritative quote"
            ),
            currency=intent.currency,
            expected_minor=quote.total_minor,
            actual_minor=intent.amount_minor,
        )
        return None

    settings = get_settings()
    platform_fee = (
        quote.subtotal_minor * settings.platform_fee_bps + 5_000
    ) // 10_000
    platform_fee = min(platform_fee, quote.subtotal_minor)
    provider_net = quote.subtotal_minor - platform_fee
    now = datetime.now(UTC)
    available_at = now + timedelta(
        hours=settings.provider_payable_hold_hours
    )
    status = "AVAILABLE" if available_at <= now else "PENDING"

    journal_lines = [
        JournalLine(
            f"PROCESSOR_CLEARING:{intent.currency}",
            "DEBIT",
            intent.amount_minor,
            intent.currency,
        )
    ]
    if provider_net:
        journal_lines.append(
            JournalLine(
                f"PROVIDER_PAYABLE:{intent.currency}",
                "CREDIT",
                provider_net,
                intent.currency,
            )
        )
    if platform_fee:
        journal_lines.append(
            JournalLine(
                f"PLATFORM_REVENUE:{intent.currency}",
                "CREDIT",
                platform_fee,
                intent.currency,
            )
        )
    if quote.tax_minor:
        journal_lines.append(
            JournalLine(
                f"TAX_PAYABLE:{intent.currency}",
                "CREDIT",
                quote.tax_minor,
                intent.currency,
            )
        )

    try:
        transaction = post_journal(
            db,
            reference_type="PAYMENT_CAPTURE",
            reference_id=str(intent.id),
            description=f"Capture for booking {booking.booking_number}",
            metadata={
                "booking_id": str(booking.id),
                "provider_id": str(assignment.provider_id),
                "payment_provider": intent.provider_code,
            },
            lines=journal_lines,
        )
    except FinancialInvariantError as exc:
        open_reconciliation_break(
            db,
            provider_code=intent.provider_code,
            external_reference=str(intent.id),
            break_type="CAPTURE_JOURNAL_FAILED",
            details=str(exc),
            currency=intent.currency,
            expected_minor=quote.total_minor,
            actual_minor=intent.amount_minor,
        )
        return None

    payable = ProviderPayable(
        provider_id=assignment.provider_id,
        booking_id=booking.id,
        payment_intent_id=intent.id,
        currency=intent.currency,
        service_subtotal_minor=quote.subtotal_minor,
        platform_fee_minor=platform_fee,
        adjustment_minor=0,
        net_minor=provider_net,
        status=status,
        available_at=available_at,
        hold_reason=None,
        created_at=now,
        updated_at=now,
    )
    db.add(payable)
    if booking.status == BookingStatus.COMPLETED:
        booking.status = BookingStatus.SETTLING
        booking.version += 1
    db.flush()
    emit(
        db,
        aggregate_type="provider_payable",
        aggregate_id=str(payable.id),
        event_type="finance.provider_payable_created.v1",
        payload={
            "payable_id": str(payable.id),
            "provider_id": str(payable.provider_id),
            "booking_id": str(booking.id),
            "net_minor": payable.net_minor,
            "currency": payable.currency,
            "status": payable.status,
            "ledger_transaction_id": str(transaction.id),
        },
    )
    return payable


def hold_payable_for_payment(
    db: Session,
    intent: PaymentIntent,
    *,
    reason: str,
    amount_minor: int | None = None,
) -> ProviderPayable | None:
    payable = db.scalar(
        select(ProviderPayable)
        .where(ProviderPayable.payment_intent_id == intent.id)
        .with_for_update()
    )
    if payable is not None and payable.status in {
        "PENDING",
        "AVAILABLE",
        "RESERVED",
    }:
        payable.status = "HELD"
        payable.hold_reason = reason[:255]
        payable.updated_at = datetime.now(UTC)
        emit(
            db,
            aggregate_type="provider_payable",
            aggregate_id=str(payable.id),
            event_type="finance.provider_payable_held.v1",
            payload={"payable_id": str(payable.id), "reason": reason},
        )
    open_reconciliation_break(
        db,
        provider_code=intent.provider_code,
        external_reference=str(intent.id),
        break_type="REFUND_OR_DISPUTE_REVIEW",
        details=reason,
        currency=intent.currency,
        expected_minor=intent.amount_minor,
        actual_minor=amount_minor,
    )
    return payable


def approve_adjustment(
    db: Session,
    request: FinancialAdjustmentRequest,
    *,
    approver_subject: str,
) -> LedgerTransaction:
    if request.status != "PENDING_SECOND_APPROVAL":
        raise FinancialInvariantError("Adjustment is not pending approval")
    if request.requested_by_subject == approver_subject:
        raise FinancialInvariantError(
            "Requester cannot approve their own adjustment"
        )
    debit = db.get(LedgerAccount, request.debit_account_id)
    credit = db.get(LedgerAccount, request.credit_account_id)
    if debit is None or credit is None or not debit.active or not credit.active:
        raise FinancialInvariantError("Adjustment accounts are not active")
    if debit.currency != request.currency or credit.currency != request.currency:
        raise FinancialInvariantError(
            "Adjustment currency must match both accounts"
        )

    transaction = post_journal(
        db,
        reference_type="MANUAL_ADJUSTMENT",
        reference_id=str(request.id),
        description=request.reason,
        metadata={
            "requested_by": request.requested_by_subject,
            "approved_by": approver_subject,
        },
        lines=[
            JournalLine(
                debit.code,
                "DEBIT",
                request.amount_minor,
                request.currency,
            ),
            JournalLine(
                credit.code,
                "CREDIT",
                request.amount_minor,
                request.currency,
            ),
        ],
    )
    now = datetime.now(UTC)
    request.status = "POSTED"
    request.approved_by_subject = approver_subject
    request.ledger_transaction_id = transaction.id
    request.decided_at = now
    request.updated_at = now
    request.version += 1
    emit(
        db,
        aggregate_type="financial_adjustment",
        aggregate_id=str(request.id),
        event_type="finance.adjustment_posted.v1",
        payload={
            "adjustment_id": str(request.id),
            "ledger_transaction_id": str(transaction.id),
            "approved_by": approver_subject,
        },
    )
    db.flush()
    return transaction


def release_due_payables(db: Session, *, limit: int = 500) -> int:
    now = datetime.now(UTC)
    rows = list(
        db.scalars(
            select(ProviderPayable)
            .where(
                ProviderPayable.status == "PENDING",
                ProviderPayable.available_at <= now,
            )
            .order_by(ProviderPayable.available_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.status = "AVAILABLE"
        row.updated_at = now
        emit(
            db,
            aggregate_type="provider_payable",
            aggregate_id=str(row.id),
            event_type="finance.provider_payable_available.v1",
            payload={"payable_id": str(row.id)},
        )
    return len(rows)
