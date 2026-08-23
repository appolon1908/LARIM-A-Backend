import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.services import VisitService
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.authorization import provider_for_principal
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter()


class Start(BaseModel):
    pin: str = Field(min_length=4, max_length=8)


def run(action, bid, key, p, db, pin=None):
    provider = provider_for_principal(db, p)
    idem, replay = reserve(
        db,
        actor_subject=p.subject,
        operation=f"visit.{action}",
        key=key,
        payload={"booking_id": str(bid), "pin": pin},
    )
    if replay is not None:
        return replay
    b = db.get(Booking, bid)
    if not b:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    v = VisitService.transition(db, booking=b, provider=provider, action=action, pin=pin)
    result = {
        "booking_id": str(b.id),
        "visit_id": str(v.id),
        "status": v.status,
        "version": b.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/{booking_id}/en-route")
def enroute(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return run("en-route", booking_id, key, p, db)


@router.post("/{booking_id}/arrive")
def arrive(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return run("arrive", booking_id, key, p, db)


@router.post("/{booking_id}/start")
def start(
    booking_id: uuid.UUID,
    payload: Start,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return run("start", booking_id, key, p, db, payload.pin)


@router.post("/{booking_id}/complete")
def done(
    booking_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(require_roles(Role.PROVIDER)),
    db: Session = Depends(get_db),
):
    return run("complete", booking_id, key, p, db)
