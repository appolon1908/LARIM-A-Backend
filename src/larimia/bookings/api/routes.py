import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import BookingLine, Quote
from larimia.shared.audit import record_audit
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.authorization import customer_for_principal, require_booking_customer
from larimia.shared.db import get_db
from larimia.shared.errors import ConflictError
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter()


def serialize(b: Booking) -> dict:
    return {
        "id": str(b.id),
        "booking_number": b.booking_number,
        "customer_id": str(b.customer_id),
        "market_code": b.market_code,
        "status": b.status.value,
        "currency": b.currency,
        "customer_total_minor": b.customer_total_minor,
        "version": b.version,
        "scheduled_start": b.scheduled_start.isoformat(),
        "scheduled_end": b.scheduled_end.isoformat(),
    }


def load_owned(db: Session, p: Principal, bid: uuid.UUID) -> Booking:
    b = db.get(Booking, bid)
    if not b:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    if not p.roles.intersection({Role.DISPATCHER, Role.SUPPORT, Role.PLATFORM_ADMIN}):
        require_booking_customer(db, p, b)
    return b


def cas(db: Session, b: Booking, expected: int, target: BookingStatus) -> Booking:
    r = db.execute(
        update(Booking)
        .where(Booking.id == b.id, Booking.version == expected)
        .values(status=target, version=expected + 1)
    )
    if r.rowcount != 1:
        raise ConflictError("VERSION_CONFLICT", "Booking changed; reload and retry")
    db.flush()
    db.refresh(b)
    return b


@router.get("")
def list_bookings(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    c = customer_for_principal(db, principal)
    rows = list(
        db.scalars(
            select(Booking)
            .where(Booking.customer_id == c.id)
            .order_by(Booking.created_at.desc())
            .limit(100)
        )
    )
    return {"items": [serialize(x) for x in rows]}


@router.post("/from-quote/{quote_id}", status_code=201)
def from_quote(
    quote_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    c = customer_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.from_quote",
        key=key,
        payload={"quote_id": str(quote_id)},
    )
    if replay is not None:
        return replay
    q = db.scalar(select(Quote).where(Quote.id == quote_id).with_for_update())
    if not q or q.customer_id != c.id:
        raise HTTPException(404, detail={"code": "QUOTE_NOT_FOUND"})
    if q.status != "ACTIVE" or q.expires_at <= datetime.now(UTC):
        raise HTTPException(409, detail={"code": "QUOTE_EXPIRED"})
    b = Booking(
        booking_number=f"LRM-{secrets.token_hex(5).upper()}",
        customer_id=c.id,
        market_code=q.market_code,
        status=BookingStatus.QUOTED,
        currency=q.currency,
        customer_total_minor=q.total_minor,
        version=1,
        scheduled_start=q.scheduled_start,
        scheduled_end=q.scheduled_end,
    )
    db.add(b)
    db.flush()
    db.add(
        BookingLine(
            booking_id=b.id,
            service_id=q.service_id,
            service_snapshot=q.snapshot["service"],
            amount_minor=q.subtotal_minor,
        )
    )
    q.status = "CONSUMED"
    record_audit(
        db,
        actor=principal.subject,
        action="booking.create_from_quote",
        resource_type="booking",
        resource_id=str(b.id),
        metadata={"quote_id": str(q.id)},
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(b.id),
        event_type="booking.created_from_quote.v1",
        payload={"booking_id": str(b.id), "quote_id": str(q.id)},
    )
    result = serialize(b)
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
    b = load_owned(db, principal, booking_id)
    from larimia.shared.audit import AuditEvent

    rows = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource_type == "booking", AuditEvent.resource_id == str(b.id))
            .order_by(AuditEvent.created_at)
        )
    )
    return {
        "items": [
            {"action": x.action, "at": x.created_at.isoformat(), "metadata": x.metadata_json}
            for x in rows
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
    b = load_owned(db, principal, booking_id)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.confirm",
        key=key,
        payload={"booking_id": str(booking_id), "version": if_match},
    )
    if replay is not None:
        return replay
    if b.status != BookingStatus.QUOTED:
        raise HTTPException(409, detail={"code": "INVALID_BOOKING_STATE"})
    cas(db, b, if_match, BookingStatus.CONFIRMED)
    record_audit(
        db,
        actor=principal.subject,
        action="booking.confirm",
        resource_type="booking",
        resource_id=str(b.id),
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(b.id),
        event_type="booking.confirmed.v1",
        payload={"booking_id": str(b.id), "version": b.version},
    )
    result = serialize(b)
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
    b = load_owned(db, principal, booking_id)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.start_matching",
        key=key,
        payload={"booking_id": str(booking_id), "version": if_match},
    )
    if replay is not None:
        return replay
    if b.status != BookingStatus.CONFIRMED:
        raise HTTPException(409, detail={"code": "INVALID_BOOKING_STATE"})
    cas(db, b, if_match, BookingStatus.MATCHING)
    record_audit(
        db,
        actor=principal.subject,
        action="booking.start_matching",
        resource_type="booking",
        resource_id=str(b.id),
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(b.id),
        event_type="booking.matching_started.v1",
        payload={"booking_id": str(b.id), "version": b.version},
    )
    result = serialize(b)
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/{booking_id}/cancel")
def cancel(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match"),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    b = load_owned(db, principal, booking_id)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="booking.cancel",
        key=key,
        payload={"booking_id": str(booking_id), "version": if_match},
    )
    if replay is not None:
        return replay
    if b.status in {BookingStatus.COMPLETED, BookingStatus.SETTLED, BookingStatus.CANCELLED}:
        raise HTTPException(409, detail={"code": "INVALID_BOOKING_STATE"})
    cas(db, b, if_match, BookingStatus.CANCELLED)
    record_audit(
        db,
        actor=principal.subject,
        action="booking.cancel",
        resource_type="booking",
        resource_id=str(b.id),
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(b.id),
        event_type="booking.cancelled.v1",
        payload={"booking_id": str(b.id), "version": b.version},
    )
    result = serialize(b)
    complete(db, idem, result)
    db.commit()
    return result
