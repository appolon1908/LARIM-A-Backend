import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.services import VisitService
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.authorization import provider_for_principal
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.PROVIDER_SELF_SERVICE))],
)


class StartVisit(BaseModel):
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


def _run_transition(
    *,
    action: str,
    booking_id: uuid.UUID,
    key: str,
    principal: Principal,
    db: Session,
    pin: str | None = None,
):
    provider = provider_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation=f"visit.{action}",
        key=key,
        payload={"booking_id": str(booking_id), "has_pin": pin is not None},
    )
    if replay is not None:
        return replay

    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})

    visit = VisitService.transition(
        db,
        booking=booking,
        provider=provider,
        action=action,
        pin=pin,
    )
    result = {
        "booking_id": str(booking.id),
        "visit_id": str(visit.id),
        "status": visit.status,
        "version": booking.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/{booking_id}/en-route")
def en_route(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return _run_transition(
        action="en-route",
        booking_id=booking_id,
        key=key,
        principal=principal,
        db=db,
    )


@router.post("/{booking_id}/arrive")
def arrive(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return _run_transition(
        action="arrive",
        booking_id=booking_id,
        key=key,
        principal=principal,
        db=db,
    )


@router.post("/{booking_id}/start")
def start(
    booking_id: uuid.UUID,
    payload: StartVisit,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return _run_transition(
        action="start",
        booking_id=booking_id,
        key=key,
        principal=principal,
        db=db,
        pin=payload.pin,
    )


@router.post("/{booking_id}/complete")
def complete_visit(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return _run_transition(
        action="complete",
        booking_id=booking_id,
        key=key,
        principal=principal,
        db=db,
    )
