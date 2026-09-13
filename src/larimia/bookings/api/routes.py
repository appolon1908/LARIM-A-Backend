import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from larimia.bookings.api.schemas import BookingCreate, BookingRead
from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.domain.state_machine import ensure_transition
from larimia.bookings.infrastructure.models import Booking
from larimia.shared.audit import record_audit
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()


def transition_booking(
    db: Session, booking: Booking, target: BookingStatus, actor: str, action: str
) -> Booking:
    try:
        ensure_transition(booking.status, target)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "INVALID_BOOKING_TRANSITION", "message": str(exc)}
        ) from exc
    old = booking.status
    booking.status = target
    booking.version += 1
    record_audit(
        db,
        actor=actor,
        action=action,
        resource_type="booking",
        resource_id=str(booking.id),
        metadata={"from": old.value, "to": target.value},
    )
    emit(
        db,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type=f"Booking{target.value.title().replace('_', '')}",
        payload={"booking_id": str(booking.id), "status": target.value, "version": booking.version},
    )
    db.commit()
    db.refresh(booking)
    return booking


@router.post("", response_model=BookingRead, status_code=201)
def create_booking(
    payload: BookingCreate,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Booking:
    if payload.scheduled_end <= payload.scheduled_start:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SERVICE_WINDOW"})
    booking = Booking(
        booking_number=f"LRM-{secrets.token_hex(5).upper()}",
        **payload.model_dump(),
    )
    db.add(booking)
    record_audit(
        db,
        actor=principal.subject,
        action="booking.create",
        resource_type="booking",
        resource_id=str(booking.id),
    )
    db.commit()
    db.refresh(booking)
    return booking


@router.get("/{booking_id}", response_model=BookingRead)
def get_booking(
    booking_id: uuid.UUID, _: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail={"code": "BOOKING_NOT_FOUND"})
    return booking


@router.post("/{booking_id}/quote", response_model=BookingRead)
def mark_quoted(
    booking_id: uuid.UUID,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    return transition_booking(db, booking, BookingStatus.QUOTED, principal.subject, "booking.quote")


@router.post("/{booking_id}/confirm", response_model=BookingRead)
def confirm(
    booking_id: uuid.UUID,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    return transition_booking(
        db, booking, BookingStatus.CONFIRMED, principal.subject, "booking.confirm"
    )


@router.post("/{booking_id}/start-matching", response_model=BookingRead)
def start_matching(
    booking_id: uuid.UUID,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.DISPATCHER)),
    db: Session = Depends(get_db),
):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    return transition_booking(
        db, booking, BookingStatus.MATCHING, principal.subject, "booking.start_matching"
    )


@router.post("/{booking_id}/cancel", response_model=BookingRead)
def cancel(
    booking_id: uuid.UUID,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    return transition_booking(
        db, booking, BookingStatus.CANCELLED, principal.subject, "booking.cancel"
    )
