from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from larimia.config import get_settings
from larimia.ledger.infrastructure_models import LedgerAccount, LedgerEntry, LedgerTransaction
from larimia.shared.audit import record_audit
from larimia.shared.events import emit

from . import domain
from .models import (
    Address,
    Block,
    Earning,
    Offer,
    Payment,
    Provider,
    Quote,
    Refund,
    Review,
    Service,
    StatusHistory,
    User,
    now,
)
from .models import MarketplaceBooking as Booking
from .payments import MockGateway
from .security import allowed


def get(db: Session, model, identity, lock=False):
    row = (
        db.scalar(select(model).where(model.id == identity).with_for_update())
        if lock
        else db.get(model, identity)
    )
    if row is None:
        raise HTTPException(404, "Resource not found")
    return row


def serialize(row) -> dict:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in {"password_hash"}
    }


def provider_for(db: Session, user: User, lock=False) -> Provider:
    query = select(Provider).where(Provider.user_id == user.id)
    provider = db.scalar(query.with_for_update() if lock else query)
    if not provider:
        raise HTTPException(404, "Provider profile not found")
    return provider


def booking_for(db: Session, user: User, booking_id: UUID, lock=False) -> Booking:
    booking = get(db, Booking, booking_id, lock)
    provider = db.get(Provider, booking.provider_id) if booking.provider_id else None
    if (
        booking.customer_id != user.id
        and not (provider and provider.user_id == user.id)
        and not allowed(user, "booking.read")
    ):
        raise HTTPException(404, "Booking not found")
    return booking


def booking_view(booking: Booking) -> dict:
    data = serialize(booking)
    data.update(
        bookingNumber="LRM-" + str(booking.id)[:8].upper(),
        scheduledStart=booking.scheduled_start,
        total={
            "amountMinor": booking.snapshot["total_minor"],
            "currency": booking.snapshot["currency"],
        },
    )
    return data


def event(db: Session, user: User, name: str, booking: Booking) -> None:
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type=name,
        payload={
            "booking_id": str(booking.id),
            "user_id": str(booking.customer_id),
            "status": booking.status,
            "version": booking.version,
        },
    )
    record_audit(
        db, actor=user.subject, action=name, resource_type="booking", resource_id=str(booking.id)
    )


def change(db: Session, user: User, booking: Booking, target: str, name: str) -> None:
    try:
        domain.transition(booking.status, target)
    except ValueError as exc:
        raise HTTPException(409, {"code": "BOOKING_INVALID_STATE", "message": str(exc)}) from exc
    db.add(
        StatusHistory(
            booking_id=booking.id, actor=user.subject, previous=booking.status, status=target
        )
    )
    booking.status = target
    booking.version += 1
    event(db, user, name, booking)


def create_quote(db: Session, user: User, payload) -> dict:
    address = get(db, Address, payload.address_id)
    if address.customer_id != user.id:
        raise HTTPException(404, "Address not found")
    service = db.scalar(
        select(Service).where(Service.code == payload.service_code, Service.active.is_(True))
    )
    if (
        not service
        or service.market_code != payload.market_code
        or service.currency != payload.currency
        or address.market_code != payload.market_code
    ):
        raise HTTPException(422, "Service unavailable in requested market/currency")
    if payload.scheduled_start <= now():
        raise HTTPException(422, "Service must be scheduled in the future")
    discount = 0
    if payload.promotion_code:
        from .models import Promotion

        promotion = db.scalar(
            select(Promotion).where(
                Promotion.code == payload.promotion_code, Promotion.active.is_(True)
            )
        )
        if not promotion or promotion.expires_at <= now() or promotion.currency != service.currency:
            raise HTTPException(422, "Promotion unavailable")
        discount = promotion.amount_minor
    try:
        snapshot = domain.price(
            service.base_minor, service.travel_minor, service.tax_bps, service.fee_bps, discount
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    snapshot.update(
        service_code=service.code,
        required_skills=service.required_skills,
        currency=service.currency,
        market_code=service.market_code,
        pricing_policy_version=service.version,
    )
    from .models import ServiceJobPolicy

    policy = db.scalar(select(ServiceJobPolicy).where(ServiceJobPolicy.service_id == service.id))
    if policy:
        snapshot["job_policy"] = {**policy.requirements, "version": policy.version}
    quote = Quote(
        customer_id=user.id,
        service_id=service.id,
        address_id=address.id,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_start + timedelta(minutes=service.duration_minutes),
        expires_at=now() + timedelta(minutes=10),
        snapshot=snapshot,
    )
    db.add(quote)
    db.flush()
    emit(
        db,
        aggregate_type="quote",
        aggregate_id=str(quote.id),
        event_type="QuoteCreated",
        payload={"quote_id": str(quote.id), "user_id": str(user.id)},
    )
    return {**serialize(quote), **snapshot}


def create_booking(db: Session, user: User, quote_id: UUID) -> dict:
    quote = get(db, Quote, quote_id, True)
    if quote.customer_id != user.id:
        raise HTTPException(404, "Quote not found")
    if quote.expires_at <= now():
        raise HTTPException(409, "Quote expired")
    if quote.accepted:
        raise HTTPException(409, "Quote already accepted")
    quote.accepted = True
    address = get(db, Address, quote.address_id)
    booking = Booking(
        quote_id=quote.id,
        customer_id=user.id,
        snapshot=quote.snapshot,
        address={
            "latitude": address.latitude,
            "longitude": address.longitude,
            "market_code": address.market_code,
            "label": address.label,
        },
        scheduled_start=quote.scheduled_start,
        scheduled_end=quote.scheduled_end,
    )
    db.add(booking)
    db.flush()
    event(db, user, "QuoteAccepted", booking)
    event(db, user, "BookingCreated", booking)
    return booking_view(booking)


def authorize(db: Session, user: User, payload) -> dict:
    booking = booking_for(db, user, payload.booking_id, True)
    if booking.customer_id != user.id:
        raise HTTPException(403, "Only the customer may authorize payment")
    existing = db.scalar(select(Payment).where(Payment.booking_id == booking.id))
    if existing:
        return serialize(existing)
    if booking.status != "QUOTED":
        raise HTTPException(409, "Booking is not awaiting payment")
    try:
        reference = MockGateway().authorize(
            str(booking.id),
            booking.snapshot["total_minor"],
            booking.snapshot["currency"],
            payload.payment_method_token,
        )
    except ValueError as exc:
        raise HTTPException(422, "Payment authorization failed") from exc
    payment = Payment(
        booking_id=booking.id,
        status="AUTHORIZED",
        external_reference=reference,
        amount_minor=booking.snapshot["total_minor"],
        currency=booking.snapshot["currency"],
    )
    db.add(payment)
    change(db, user, booking, "PAYMENT_AUTHORIZED", "PaymentAuthorized")
    db.flush()
    return serialize(payment)


def eligible(
    db: Session, provider: Provider, booking: Booking, blocked_provider_ids: set[UUID] | None = None
) -> bool:
    if provider.status != "APPROVED" or not provider.online or provider.workload > 0:
        return False
    if (
        booking.snapshot["service_code"] not in provider.services
        or provider.market_code != booking.snapshot["market_code"]
    ):
        return False
    if not set(booking.snapshot["required_skills"]).issubset(provider.skills):
        return False
    blocked = (
        provider.id in blocked_provider_ids
        if blocked_provider_ids is not None
        else db.scalar(
            select(Block.id).where(
                Block.provider_id == provider.id, Block.customer_id == booking.customer_id
            )
        )
        is not None
    )
    if blocked:
        return False
    windows = provider.availability
    if not any(
        datetime.fromisoformat(w["start"]) <= booking.scheduled_start
        and datetime.fromisoformat(w["end"]) >= booking.scheduled_end
        for w in windows
    ):
        return False
    return (
        domain.distance_km(
            provider.latitude,
            provider.longitude,
            booking.address["latitude"],
            booking.address["longitude"],
        )
        <= provider.radius_km
    )


def dispatch(db: Session, user: User, booking_id: UUID) -> dict:
    booking = booking_for(db, user, booking_id, True)
    from .models import DispatchSession

    change(db, user, booking, "SEARCHING", "DispatchStarted")
    session = DispatchSession(booking_id=booking.id)
    db.add(session)
    from .dispatch_ranking import rank_candidates

    ranked = rank_candidates(db, booking)
    if not ranked:
        change(db, user, booking, "NO_PROVIDER_FOUND", "NoProviderFound")
        session.status = "EXHAUSTED"
        payment = db.scalar(
            select(Payment).where(Payment.booking_id == booking.id).with_for_update()
        )
        if payment and payment.status == "AUTHORIZED":
            MockGateway().cancel(payment.external_reference)
            payment.status = "CANCELLED"
    else:
        change(db, user, booking, "OFFERED", "DispatchOfferCreated")
        for rank, provider, details in ranked[: get_settings().dispatch_batch_size]:
            offer = Offer(
                booking_id=booking.id,
                provider_id=provider.id,
                rank_score=rank,
                ranking_details=details,
                expires_at=now() + timedelta(seconds=get_settings().dispatch_offer_seconds),
            )
            db.add(offer)
            db.flush()
            emit(
                db,
                aggregate_type="offer",
                aggregate_id=str(offer.id),
                event_type="DispatchOfferCreated",
                payload={
                    "offer_id": str(offer.id),
                    "booking_id": str(booking.id),
                    "user_id": str(provider.user_id),
                },
            )
    return booking_view(booking)


def accept(db: Session, user: User, offer_id: UUID, version: int) -> dict:
    # Lock booking first for every contender, then provider, then offer. Same order as job writes.
    initial = get(db, Offer, offer_id)
    provider = provider_for(db, user)
    if initial.provider_id != provider.id:
        raise HTTPException(404, "Offer not found")
    booking = get(db, Booking, initial.booking_id, True)
    provider = get(db, Provider, provider.id, True)
    offer = get(db, Offer, offer_id, True)
    if booking.status != "OFFERED" or booking.provider_id or booking.version != version:
        raise HTTPException(409, "Booking is already assigned or version is stale")
    if (
        offer.status != "PENDING"
        or offer.expires_at <= now()
        or not eligible(db, provider, booking)
    ):
        raise HTTPException(409, "Offer is expired or provider is no longer eligible")
    booking.provider_id = provider.id
    provider.workload += 1
    offer.status = "ACCEPTED"
    for other in db.scalars(
        select(Offer).where(Offer.booking_id == booking.id, Offer.id != offer.id)
    ):
        other.status = "CANCELLED"
    change(db, user, booking, "ASSIGNED", "ProviderAssigned")
    from .models import DispatchSession

    session = db.scalar(select(DispatchSession).where(DispatchSession.booking_id == booking.id))
    if session:
        session.status = "ASSIGNED"
    event(db, user, "DispatchOfferAccepted", booking)
    return booking_view(booking)


def journal(
    db: Session,
    reference_type: str,
    reference_id: str,
    currency: str,
    entries: list[tuple[str, str, int]],
) -> None:
    domain.balanced(entries)
    transaction = LedgerTransaction(
        reference_type=reference_type, reference_id=reference_id, description=reference_type
    )
    db.add(transaction)
    db.flush()
    for account_code, direction, amount in entries:
        # Accounts are deterministic; PostgreSQL conflict handling supports concurrent captures.
        from sqlalchemy.dialects.postgresql import insert

        account_id = uuid4()
        db.execute(
            insert(LedgerAccount)
            .values(
                id=account_id,
                code=account_code + ":" + currency,
                account_type="CONTROL",
                currency=currency,
            )
            .on_conflict_do_nothing(index_elements=["code"])
        )
        account = db.scalar(
            select(LedgerAccount).where(LedgerAccount.code == account_code + ":" + currency)
        )
        if account is None:
            raise RuntimeError("Journal account was not persisted")
        db.add(
            LedgerEntry(
                transaction_id=transaction.id,
                account_id=account.id,
                direction=direction,
                amount_minor=amount,
                currency=currency,
            )
        )


def capture(db: Session, user: User, booking: Booking) -> dict:
    payment = db.scalar(select(Payment).where(Payment.booking_id == booking.id).with_for_update())
    if not payment or payment.status != "AUTHORIZED" or booking.status != "COMPLETED":
        raise HTTPException(409, "Capture requires completed work and an authorization")
    MockGateway().capture(payment.external_reference, payment.amount_minor)
    earning = booking.snapshot["provider_earning_minor"]
    entries = [
        ("processor", "DEBIT", payment.amount_minor),
        ("provider:" + str(booking.provider_id), "CREDIT", earning),
    ]
    remainder = payment.amount_minor - earning
    if remainder:
        entries.append(("platform_and_tax", "CREDIT", remainder))
    journal(db, "capture", str(payment.id), payment.currency, entries)
    payment.status = "CAPTURED"
    db.add(
        Earning(
            booking_id=booking.id,
            provider_id=booking.provider_id,
            amount_minor=earning,
            currency=payment.currency,
        )
    )
    change(db, user, booking, "PAYMENT_CAPTURED", "PaymentCaptured")
    event(db, user, "ProviderEarningCreated", booking)
    return booking_view(booking)


def job_action(db: Session, user: User, booking_id: UUID, action: str) -> dict:
    booking = booking_for(db, user, booking_id, True)
    provider = provider_for(db, user, True)
    if booking.provider_id != provider.id or provider.status != "APPROVED":
        raise HTTPException(403, "Assigned approved provider required")
    actions = {
        "en-route": ("PROVIDER_EN_ROUTE", "ProviderEnRoute"),
        "arrive": ("ARRIVED", "ProviderArrived"),
        "start": ("IN_PROGRESS", "JobStarted"),
        "complete": ("COMPLETED", "JobCompleted"),
    }
    if action not in actions:
        raise HTTPException(404, "Unknown job action")
    if action == "complete":
        from .jobs import validate_completion

        validate_completion(db, booking)
    target, name = actions[action]
    change(db, user, booking, target, name)
    if action == "complete":
        provider.workload = max(0, provider.workload - 1)
        return capture(db, user, booking)
    return booking_view(booking)


def refund(db: Session, user: User, payload, key: str) -> dict:
    initial = get(db, Payment, payload.payment_id)
    booking = get(db, Booking, initial.booking_id, True)
    payment = get(db, Payment, payload.payment_id, True)
    if (
        payment.status != "CAPTURED"
        or payload.amount_minor > payment.amount_minor - payment.refunded_minor
    ):
        raise HTTPException(409, "Refund exceeds captured available amount")
    earning = db.scalar(select(Earning).where(Earning.booking_id == booking.id).with_for_update())
    if not earning or earning.status != "PENDING":
        raise HTTPException(409, "Paid earnings require finance adjustment before refund")
    previous_refund = payment.refunded_minor
    payment.refunded_minor += payload.amount_minor
    original_earning = booking.snapshot["provider_earning_minor"]
    provider_reversal = (
        original_earning * payment.refunded_minor // payment.amount_minor
        - original_earning * previous_refund // payment.amount_minor
    )
    entries = [("processor", "CREDIT", payload.amount_minor)]
    if provider_reversal:
        entries.append(("provider:" + str(booking.provider_id), "DEBIT", provider_reversal))
    remainder = payload.amount_minor - provider_reversal
    if remainder:
        entries.append(("platform_and_tax", "DEBIT", remainder))
    refund = Refund(
        payment_id=payment.id,
        amount_minor=payload.amount_minor,
        reason=payload.reason,
        external_reference=MockGateway().refund(str(payment.id) + ":" + key, payload.amount_minor),
    )
    db.add(refund)
    db.flush()
    journal(db, "refund", str(refund.id), payment.currency, entries)
    earning.amount_minor -= provider_reversal
    target = "REFUNDED" if payment.refunded_minor == payment.amount_minor else "PARTIALLY_REFUNDED"
    change(db, user, booking, target, "RefundIssued")
    return serialize(refund)


def review(db: Session, user: User, payload) -> dict:
    booking = booking_for(db, user, payload.booking_id, True)
    if booking.customer_id != user.id or booking.status not in {"PAYMENT_CAPTURED", "SETTLED"}:
        raise HTTPException(409, "Only customer of a completed paid booking can review")
    if db.scalar(select(Review).where(Review.booking_id == booking.id)):
        raise HTTPException(409, "Booking already reviewed")
    provider = get(db, Provider, booking.provider_id, True)
    row = Review(
        booking_id=booking.id,
        customer_id=user.id,
        provider_id=provider.id,
        rating=payload.rating,
        body=payload.body,
    )
    db.add(row)
    db.flush()
    provider.rating = float(
        db.scalar(
            select(func.coalesce(func.avg(Review.rating), 0)).where(
                Review.provider_id == provider.id
            )
        )
    )
    event(db, user, "ReviewSubmitted", booking)
    return serialize(row)
