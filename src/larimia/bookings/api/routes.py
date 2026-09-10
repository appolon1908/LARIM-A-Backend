import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.domain.state_machine import ensure_transition
from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.capacity import CapacityService
from larimia.marketplace.models import BookingLine, PaymentIntent, Quote
from larimia.shared.audit import AuditEvent, record_audit
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.authorization import (
    customer_for_principal,
    require_booking_customer,
    require_market,
)
from larimia.shared.capabilities import Capability, ensure_capability
from larimia.shared.db import get_db
from larimia.shared.errors import ConflictError
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter()


class CancelRequest(BaseModel):
    reason: str = Field(default="CUSTOMER_REQUEST", min_length=1, max_length=255)


def serialize(booking: Booking) -> dict:
    return {
        "id": str(booking.id),
        "booking_number": booking.booking_number,
        "customer_id": str(booking.customer_id),
        "market_code": booking.market_code,
        "status": booking.status.value,
        "currency": booking.currency,
        "customer_total_minor": booking.customer_total_minor,
        "version": booking.version,
        "scheduled_start": booking.scheduled_start.isoformat(),
        "scheduled_end": booking.scheduled_end.isoformat(),
        "quote_id": str(booking.quote_id) if booking.quote_id else None,
        "capacity_hold_id": (
            str(booking.capacity_hold_id) if booking.capacity_hold_id else None
        ),
        "payment_intent_id": (
            str(booking.payment_intent_id) if booking.payment_intent_id else None
        ),
        "confirmed_at": (
            booking.confirmed_at.isoformat() if booking.confirmed_at else None
        ),
        "cancelled_at": (
            booking.cancelled_at.isoformat() if booking.cancelled_at else None
        ),
        "cancellation_reason": booking.cancellation_reason,
    }


def load_owned(
    db: Session,
    principal: Principal,
    booking_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Booking:
    statement = select(Booking).where(Booking.id == booking_id)
    if lock:
        statement = statement.with_for_update()
    booking = db.scalar(statement)
    if booking is None:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})

    staff_roles = {
        Role.DISPATCHER,
        Role.SUPPORT,
        Role.SAFETY,
        Role.FINANCE,
        Role.PLATFORM_ADMIN,
    }
    if principal.roles.intersection(staff_roles):
        require_market(principal, booking.market_code)
    else:
        require_booking_customer(db, principal, booking)
    return booking


def cas(
    db: Session,
    booking: Booking,
    expected: int,
    target: BookingStatus,
) -> Booking:
    ensure_transition(booking.status, target)
    result = db.execute(
        update(Booking)
        .where(
            Booking.id == booking.id,
            Booking.version == expected,
            Booking.status == booking.status,
        )
        .values(status=target, version=expected + 1)
    )
    if result.rowcount != 1:
        raise ConflictError(
            "VERSION_CONFLICT",
            "Booking changed; reload and retry",
        )
    db.flush()
    db.refresh(booking)
    return booking


@router.get("")
def list_bookings(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    rows = list(
        db.scalars(
            select(Booking)
            .where(Booking.customer_id == customer.id)
            .order_by(Booking.created_at.desc())
            .limit(100)
        )
    )
    return {"items": [serialize(row) for row in rows]}


@router.post("/from-quote/{quote_id}", status_code=201)
def from_quote(
    quote_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.from_quote",
        key=key,
        payload={"quote_id": str(quote_id)},
    )
    if replay is not None:
        return replay

    quote = db.scalar(
        select(Quote).where(Quote.id == quote_id).with_for_update()
    )
    if quote is None or quote.customer_id != customer.id:
        raise HTTPException(404, detail={"code": "QUOTE_NOT_FOUND"})
    if quote.status != "ACTIVE" or quote.expires_at <= datetime.now(UTC):
        raise HTTPException(409, detail={"code": "QUOTE_EXPIRED"})

    existing = db.scalar(
        select(Booking).where(Booking.quote_id == quote.id).with_for_update()
    )
    if existing is not None:
        raise HTTPException(409, detail={"code": "QUOTE_ALREADY_USED"})

    hold = CapacityService.active_hold_for_quote(
        db,
        quote.id,
        lock=True,
    )
    booking = Booking(
        booking_number=f"LRM-{secrets.token_hex(5).upper()}",
        customer_id=customer.id,
        market_code=quote.market_code,
        status=BookingStatus.QUOTED,
        currency=quote.currency,
        customer_total_minor=quote.total_minor,
        version=1,
        scheduled_start=quote.scheduled_start,
        scheduled_end=quote.scheduled_end,
        quote_id=quote.id,
        capacity_hold_id=hold.id,
    )
    db.add(booking)
    db.flush()
    db.add(
        BookingLine(
            booking_id=booking.id,
            service_id=quote.service_id,
            service_snapshot=quote.snapshot["service"],
            amount_minor=quote.subtotal_minor,
        )
    )
    record_audit(
        db,
        actor=principal.subject,
        action="booking.create_from_quote",
        resource_type="booking",
        resource_id=str(booking.id),
        metadata={
            "quote_id": str(quote.id),
            "capacity_hold_id": str(hold.id),
        },
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type="booking.created_from_quote.v1",
        payload={
            "booking_id": str(booking.id),
            "quote_id": str(quote.id),
            "capacity_hold_id": str(hold.id),
        },
    )
    result = serialize(booking)
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/{booking_id}")
def get_booking(
    booking_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    return serialize(load_owned(db, principal, booking_id))


@router.get("/{booking_id}/timeline")
def timeline(
    booking_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    booking = load_owned(db, principal, booking_id)
    rows = list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == "booking",
                AuditEvent.resource_id == str(booking.id),
            )
            .order_by(AuditEvent.created_at)
        )
    )
    return {
        "items": [
            {
                "action": row.action,
                "at": row.created_at.isoformat(),
                "metadata": row.metadata_json,
            }
            for row in rows
        ]
    }


@router.post("/{booking_id}/confirm")
def confirm(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match"),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    ensure_capability(Capability.PAYMENTS)
    booking = load_owned(db, principal, booking_id, lock=True)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.confirm",
        key=key,
        payload={"booking_id": str(booking_id), "version": if_match},
    )
    if replay is not None:
        return replay
    if booking.quote_id is None or booking.capacity_hold_id is None:
        raise HTTPException(409, detail={"code": "BOOKING_FUNDING_CONTEXT_MISSING"})

    quote = db.scalar(
        select(Quote).where(Quote.id == booking.quote_id).with_for_update()
    )
    if quote is None or quote.status != "ACTIVE" or quote.expires_at <= datetime.now(UTC):
        raise HTTPException(409, detail={"code": "QUOTE_EXPIRED"})

    hold = CapacityService.active_hold_for_quote(
        db,
        quote.id,
        lock=True,
    )
    payment = db.scalar(
        select(PaymentIntent)
        .where(
            PaymentIntent.booking_id == booking.id,
            PaymentIntent.customer_id == booking.customer_id,
            PaymentIntent.amount_minor == booking.customer_total_minor,
            PaymentIntent.currency == booking.currency,
            PaymentIntent.status.in_(
                ["AUTHORIZED", "REQUIRES_CAPTURE", "CAPTURED"]
            ),
        )
        .order_by(PaymentIntent.updated_at.desc())
        .with_for_update()
    )
    if payment is None:
        raise HTTPException(
            409,
            detail={"code": "PAYMENT_AUTHORIZATION_REQUIRED"},
        )

    cas(db, booking, if_match, BookingStatus.CONFIRMED)
    booking.payment_intent_id = payment.id
    booking.confirmed_at = datetime.now(UTC)
    quote.status = "CONSUMED"
    CapacityService.consume(db, hold=hold, booking=booking)
    record_audit(
        db,
        actor=principal.subject,
        action="booking.confirm",
        resource_type="booking",
        resource_id=str(booking.id),
        metadata={
            "payment_intent_id": str(payment.id),
            "capacity_hold_id": str(hold.id),
        },
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type="booking.confirmed.v1",
        payload={
            "booking_id": str(booking.id),
            "version": booking.version,
            "payment_intent_id": str(payment.id),
            "capacity_hold_id": str(hold.id),
        },
    )
    result = serialize(booking)
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/{booking_id}/start-matching")
def start_matching(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match"),
    principal: Principal = Depends(require_roles(Role.DISPATCHER)),
    db: Session = Depends(get_db),
):
    ensure_capability(Capability.MATCHING)
    booking = load_owned(db, principal, booking_id, lock=True)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.start_matching",
        key=key,
        payload={"booking_id": str(booking_id), "version": if_match},
    )
    if replay is not None:
        return replay

    cas(db, booking, if_match, BookingStatus.MATCHING)
    record_audit(
        db,
        actor=principal.subject,
        action="booking.start_matching",
        resource_type="booking",
        resource_id=str(booking.id),
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type="booking.matching_started.v1",
        payload={
            "booking_id": str(booking.id),
            "version": booking.version,
        },
    )
    result = serialize(booking)
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/{booking_id}/cancel")
def cancel(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match"),
    payload: CancelRequest | None = Body(default=None),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    booking = load_owned(db, principal, booking_id, lock=True)
    payload = payload or CancelRequest()
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.cancel",
        key=key,
        payload={
            "booking_id": str(booking_id),
            "version": if_match,
            "reason": payload.reason,
        },
    )
    if replay is not None:
        return replay

    cas(db, booking, if_match, BookingStatus.CANCELLED)
    booking.cancelled_at = datetime.now(UTC)
    booking.cancellation_reason = payload.reason
    CapacityService.release_for_booking(db, booking)

    if booking.quote_id is not None:
        quote = db.get(Quote, booking.quote_id, with_for_update=True)
        if quote is not None and quote.status == "ACTIVE":
            quote.status = "CANCELLED"

    payment = None
    if booking.payment_intent_id is not None:
        payment = db.get(
            PaymentIntent,
            booking.payment_intent_id,
            with_for_update=True,
        )
    else:
        payment = db.scalar(
            select(PaymentIntent)
            .where(
                PaymentIntent.booking_id == booking.id,
                PaymentIntent.status.in_(["AUTHORIZED", "REQUIRES_CAPTURE"]),
            )
            .order_by(PaymentIntent.updated_at.desc())
            .with_for_update()
        )
    if payment is not None and payment.status in {
        "AUTHORIZED",
        "REQUIRES_CAPTURE",
    }:
        payment.status = "RELEASE_REQUESTED"
        payment.updated_at = datetime.now(UTC)
        emit(
            db,
            aggregate_type="payment_intent",
            aggregate_id=str(payment.id),
            event_type="payment.authorization_release_requested.v1",
            payload={
                "booking_id": str(booking.id),
                "payment_intent_id": str(payment.id),
            },
        )

    record_audit(
        db,
        actor=principal.subject,
        action="booking.cancel",
        resource_type="booking",
        resource_id=str(booking.id),
        metadata={"reason": payload.reason},
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type="booking.cancelled.v1",
        payload={
            "booking_id": str(booking.id),
            "version": booking.version,
            "reason": payload.reason,
        },
    )
    result = serialize(booking)
    complete(db, idem, result)
    db.commit()
    return result
