import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import PaymentIntent
from larimia.marketplace.services import PaymentService
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve

router = APIRouter()


class Authorize(BaseModel):
    booking_id: uuid.UUID
    payment_method_token: str


@router.post("/authorize", status_code=201)
async def authorize(
    payload: Authorize,
    key: str = Depends(require_idempotency_key),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    c = customer_for_principal(db, p)
    b = db.scalar(select(Booking).where(Booking.id == payload.booking_id).with_for_update())
    if not b or b.customer_id != c.id:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    idem, replay = reserve(
        db,
        actor_subject=p.subject,
        operation="payment.authorize",
        key=key,
        payload={"booking_id": str(b.id), "payment_method_token": "[redacted]"},
    )
    if replay is not None:
        return replay
    pi = await PaymentService.authorize(
        db, booking=b, customer=c, token=payload.payment_method_token, key=key
    )
    result = {
        "id": str(pi.id),
        "status": pi.status,
        "amount_minor": pi.amount_minor,
        "currency": pi.currency,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/{payment_intent_id}")
def get(
    payment_intent_id: uuid.UUID,
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    c = customer_for_principal(db, p)
    pi = db.get(PaymentIntent, payment_intent_id)
    if not pi or pi.customer_id != c.id:
        raise HTTPException(404, detail={"code": "PAYMENT_NOT_FOUND"})
    return {
        "id": str(pi.id),
        "status": pi.status,
        "amount_minor": pi.amount_minor,
        "currency": pi.currency,
    }
