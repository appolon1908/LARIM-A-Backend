import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from larimia.adapters.payment_registry import payment_provider
from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import PaymentIntent
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_models import IdempotencyRecord
from larimia.shared.idempotency_service import complete, fail, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.PAYMENTS))],
)


class Authorize(BaseModel):
    booking_id: uuid.UUID
    payment_method_token: str = Field(min_length=1, max_length=2048)


def _serialize(intent: PaymentIntent) -> dict:
    return {
        "id": str(intent.id),
        "status": intent.status,
        "amount_minor": intent.amount_minor,
        "currency": intent.currency,
    }


@router.post("/authorize", status_code=201)
async def authorize(
    payload: Authorize,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    booking = db.get(Booking, payload.booking_id)
    if booking is None or booking.customer_id != customer.id:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    if booking.status != BookingStatus.QUOTED:
        raise HTTPException(409, detail={"code": "BOOKING_NOT_PAYABLE"})
    if booking.customer_total_minor <= 0 or len(booking.currency) != 3:
        raise HTTPException(409, detail={"code": "INVALID_BOOKING_AMOUNT"})

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

    gateway = payment_provider()
    now = datetime.now(UTC)
    intent = PaymentIntent(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_code=gateway.code,
        external_id=None,
        status="AUTHORIZATION_PENDING",
        amount_minor=booking.customer_total_minor,
        currency=booking.currency,
        created_at=now,
        updated_at=now,
    )
    db.add(intent)
    db.flush()
    intent_id = intent.id
    idem_id = idem.id

    # Persist the command before making an external call. No database row lock is
    # held across provider latency, and reconciliation can recover an unknown outcome.
    db.commit()

    try:
        provider_result = await gateway.authorize(
            token=payload.payment_method_token,
            amount_minor=booking.customer_total_minor,
            currency=booking.currency,
            idempotency_key=key,
        )
        external_id = provider_result.get("external_id")
        provider_status = provider_result.get("status")
        if not external_id or provider_status not in {
            "AUTHORIZED",
            "REQUIRES_CAPTURE",
            "CAPTURED",
        }:
            raise ValueError("Payment provider returned an invalid authorization")
    except Exception as exc:
        db.rollback()
        stored_intent = db.get(PaymentIntent, intent_id, with_for_update=True)
        stored_idem = db.get(IdempotencyRecord, idem_id, with_for_update=True)
        if stored_intent is not None:
            stored_intent.status = "AUTHORIZATION_FAILED"
            stored_intent.updated_at = datetime.now(UTC)
        if stored_idem is not None:
            fail(db, stored_idem, {"code": "PAYMENT_AUTHORIZATION_FAILED"})
        db.commit()
        raise HTTPException(
            status_code=502,
            detail={"code": "PAYMENT_AUTHORIZATION_FAILED"},
        ) from exc

    stored_intent = db.get(PaymentIntent, intent_id, with_for_update=True)
    stored_idem = db.get(IdempotencyRecord, idem_id, with_for_update=True)
    if stored_intent is None or stored_idem is None:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "PAYMENT_COMMAND_STATE_LOST"},
        )

    stored_intent.external_id = str(external_id)
    stored_intent.status = str(provider_status)
    stored_intent.updated_at = datetime.now(UTC)
    emit(
        db,
        aggregate_type="payment_intent",
        aggregate_id=str(stored_intent.id),
        event_type="payment.authorization_recorded.v1",
        payload={
            "booking_id": str(booking.id),
            "payment_intent_id": str(stored_intent.id),
            "provider_code": gateway.code,
            "status": stored_intent.status,
        },
    )
    result = _serialize(stored_intent)
    complete(db, stored_idem, result)
    db.commit()
    return result


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
    return _serialize(intent)
