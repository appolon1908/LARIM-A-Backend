import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import PaymentIntent
from larimia.marketplace.services import PaymentService
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, fail, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.PAYMENTS))],
)


class Authorize(BaseModel):
    booking_id: uuid.UUID
    payment_method_token: str = Field(min_length=1, max_length=2048)


@router.post("/authorize", status_code=201)
async def authorize(
    payload: Authorize,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    booking = db.scalar(
        select(Booking)
        .where(Booking.id == payload.booking_id)
        .with_for_update()
    )
    if booking is None or booking.customer_id != customer.id:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})

    token_fingerprint = hashlib.sha256(
        payload.payment_method_token.encode("utf-8")
    ).hexdigest()
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="payment.authorize",
        key=key,
        payload={
            "booking_id": str(booking.id),
            "payment_method_fingerprint": token_fingerprint,
        },
    )
    if replay is not None:
        return replay

    try:
        intent = await PaymentService.authorize(
            db,
            booking=booking,
            customer=customer,
            token=payload.payment_method_token,
            key=key,
        )
        result = {
            "id": str(intent.id),
            "status": intent.status,
            "amount_minor": intent.amount_minor,
            "currency": intent.currency,
        }
        complete(db, idem, result)
        db.commit()
        return result
    except Exception:
        db.rollback()
        # The reservation may have been rolled back with the business transaction.
        # Re-reserve it in a clean transaction and persist a retryable failure marker.
        idem, replay = reserve(
            db,
            actor_subject=principal.subject,
            operation="payment.authorize",
            key=key,
            payload={
                "booking_id": str(booking.id),
                "payment_method_fingerprint": token_fingerprint,
            },
        )
        if replay is None:
            fail(db, idem, {"code": "PAYMENT_AUTHORIZATION_FAILED"})
            db.commit()
        raise


@router.get("/{payment_intent_id}")
def get_payment_intent(
    payment_intent_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    intent = db.get(PaymentIntent, payment_intent_id)
    if intent is None or intent.customer_id != customer.id:
        raise HTTPException(404, detail={"code": "PAYMENT_NOT_FOUND"})
    return {
        "id": str(intent.id),
        "status": intent.status,
        "amount_minor": intent.amount_minor,
        "currency": intent.currency,
    }
