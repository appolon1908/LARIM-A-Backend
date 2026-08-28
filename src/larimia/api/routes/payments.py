import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from larimia.adapters.payment_registry import (
    PaymentConfigurationError,
    payment_provider,
    public_payment_configuration,
)
from larimia.bookings.domain.enums import BookingStatus
from larimia.bookings.infrastructure.models import Booking
from larimia.marketplace.models import PaymentIntent
from larimia.payments.errors import PaymentProviderError
from larimia.payments.models import (
    PaymentCheckoutSession,
    PaymentOperation,
    PaymentProviderReference,
    PaymentRefund,
)
from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.authorization import customer_for_principal, require_market
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_models import IdempotencyRecord
from larimia.shared.idempotency_service import complete, fail, reserve


router = APIRouter(dependencies=[Depends(require_capability(Capability.PAYMENTS))])


class Authorize(BaseModel):
    booking_id: uuid.UUID
    provider_code: str | None = Field(default=None, pattern=r"^(stripe|paypal|sandbox)$")
    payment_method_token: str | None = Field(default=None, min_length=1, max_length=2048)
    provider_order_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_provider_input(self):
        if self.provider_code == "paypal":
            if not self.provider_order_id or self.payment_method_token:
                raise ValueError("PayPal authorization requires only provider_order_id")
        elif not self.payment_method_token or self.provider_order_id:
            raise ValueError("Card authorization requires only payment_method_token")
        return self


class PayPalOrderRequest(BaseModel):
    booking_id: uuid.UUID


class CaptureRequest(BaseModel):
    amount_minor: int | None = Field(default=None, gt=0)


class RefundRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=255)


def _serialize(intent: PaymentIntent, reference: PaymentProviderReference | None = None) -> dict:
    result = {
        "id": str(intent.id),
        "booking_id": str(intent.booking_id),
        "provider_code": intent.provider_code,
        "status": intent.status,
        "amount_minor": intent.amount_minor,
        "currency": intent.currency,
        "updated_at": intent.updated_at.isoformat(),
    }
    if reference is not None:
        result["provider_order_id"] = reference.provider_order_id
        result["raw_status"] = reference.raw_status
        if reference.client_action:
            result["client_action"] = reference.client_action
    return result


def _booking_for_customer(db: Session, principal: Principal, booking_id: uuid.UUID) -> tuple[Booking, object]:
    customer = customer_for_principal(db, principal)
    booking = db.get(Booking, booking_id)
    if booking is None or booking.customer_id != customer.id:
        raise HTTPException(404, detail={"code": "BOOKING_NOT_FOUND"})
    return booking, customer


def _gateway_error(exc: Exception, default_code: str) -> HTTPException:
    if isinstance(exc, PaymentProviderError):
        status = 503 if exc.retryable else 502
        return HTTPException(status, detail={"code": exc.code, "retryable": exc.retryable})
    if isinstance(exc, PaymentConfigurationError):
        return HTTPException(503, detail={"code": "PAYMENT_PROVIDER_NOT_CONFIGURED"})
    return HTTPException(502, detail={"code": default_code, "retryable": True})


@router.get("/providers")
def providers():
    return public_payment_configuration()


@router.post("/paypal/orders", status_code=201)
async def create_paypal_order(
    payload: PayPalOrderRequest,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    booking, customer = _booking_for_customer(db, principal, payload.booking_id)
    if booking.status != BookingStatus.QUOTED:
        raise HTTPException(409, detail={"code": "BOOKING_NOT_PAYABLE"})
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="payment.paypal_order.create",
        key=key,
        payload={"booking_id": str(booking.id)},
    )
    if replay is not None:
        return replay
    now = datetime.now(UTC)
    session = PaymentCheckoutSession(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_code="paypal",
        external_order_id=None,
        idempotency_key=key,
        status="CREATE_PENDING",
        approve_url=None,
        expires_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.flush()
    session_id = session.id
    idem_id = idem.id
    db.commit()
    try:
        result = await payment_provider("paypal").create_checkout(
            amount_minor=booking.customer_total_minor,
            currency=booking.currency,
            idempotency_key=key,
            reference={"booking_id": str(booking.id), "booking_number": booking.booking_number},
        )
    except Exception as exc:
        db.rollback()
        stored = db.get(PaymentCheckoutSession, session_id, with_for_update=True)
        stored_idem = db.get(IdempotencyRecord, idem_id, with_for_update=True)
        if stored:
            stored.status = "CREATE_FAILED"
            stored.updated_at = datetime.now(UTC)
        if stored_idem:
            fail(db, stored_idem, {"code": "PAYPAL_ORDER_CREATE_FAILED"})
        db.commit()
        raise _gateway_error(exc, "PAYPAL_ORDER_CREATE_FAILED") from exc
    stored = db.get(PaymentCheckoutSession, session_id, with_for_update=True)
    stored_idem = db.get(IdempotencyRecord, idem_id, with_for_update=True)
    if stored is None or stored_idem is None:
        raise HTTPException(500, detail={"code": "PAYMENT_COMMAND_STATE_LOST"})
    stored.external_order_id = str(result["external_order_id"])
    stored.approve_url = str(result["approve_url"])
    stored.status = str(result.get("status", "CREATED"))
    stored.updated_at = datetime.now(UTC)
    response = {
        "id": str(stored.id),
        "provider_code": "paypal",
        "provider_order_id": stored.external_order_id,
        "status": stored.status,
        "approve_url": stored.approve_url,
    }
    complete(db, stored_idem, response)
    db.commit()
    return response


@router.post("/authorize", status_code=201)
async def authorize(
    payload: Authorize,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    booking, customer = _booking_for_customer(db, principal, payload.booking_id)
    if booking.status != BookingStatus.QUOTED:
        raise HTTPException(409, detail={"code": "BOOKING_NOT_PAYABLE"})
    if booking.customer_total_minor <= 0 or len(booking.currency) != 3:
        raise HTTPException(409, detail={"code": "INVALID_BOOKING_AMOUNT"})
    try:
        gateway = payment_provider(payload.provider_code)
    except Exception as exc:
        raise _gateway_error(exc, "PAYMENT_PROVIDER_NOT_CONFIGURED") from exc
    token = payload.provider_order_id if gateway.code == "paypal" else payload.payment_method_token
    if not token:
        raise HTTPException(422, detail={"code": "PAYMENT_PROVIDER_REFERENCE_REQUIRED"})
    if gateway.code == "paypal":
        checkout = db.scalar(
            select(PaymentCheckoutSession).where(
                PaymentCheckoutSession.external_order_id == token,
                PaymentCheckoutSession.booking_id == booking.id,
                PaymentCheckoutSession.customer_id == customer.id,
                PaymentCheckoutSession.provider_code == "paypal",
            )
        )
        if checkout is None or checkout.status in {"CREATE_FAILED", "CANCELLED"}:
            raise HTTPException(409, detail={"code": "PAYPAL_ORDER_INVALID"})

    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="payment.authorize",
        key=key,
        payload={
            "booking_id": str(booking.id),
            "provider_code": gateway.code,
            "provider_reference_fingerprint": fingerprint,
        },
    )
    if replay is not None:
        return replay

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
    reference = PaymentProviderReference(
        payment_intent_id=intent.id,
        provider_code=gateway.code,
        provider_order_id=payload.provider_order_id,
        provider_authorization_id=None,
        provider_capture_id=None,
        provider_customer_id=None,
        provider_payment_method_id=None,
        raw_status="AUTHORIZATION_PENDING",
        client_action=None,
        created_at=now,
        updated_at=now,
    )
    operation = PaymentOperation(
        payment_intent_id=intent.id,
        provider_code=gateway.code,
        operation_type="AUTHORIZE",
        idempotency_key=key,
        status="PENDING",
        amount_minor=intent.amount_minor,
        currency=intent.currency,
        external_id=None,
        created_at=now,
    )
    db.add_all([reference, operation])
    db.flush()
    intent_id, operation_id, idem_id = intent.id, operation.id, idem.id
    db.commit()

    try:
        provider_result = await gateway.authorize(
            token=token,
            amount_minor=booking.customer_total_minor,
            currency=booking.currency,
            idempotency_key=key,
            reference={"booking_id": str(booking.id), "booking_number": booking.booking_number},
        )
        external_id = provider_result.get("external_id")
        provider_status = provider_result.get("status")
        if not external_id or provider_status not in {
            "AUTHORIZED",
            "REQUIRES_CAPTURE",
            "REQUIRES_ACTION",
            "PROCESSING",
            "CAPTURED",
        }:
            raise PaymentProviderError("PAYMENT_PROVIDER_RESPONSE_INVALID")
    except Exception as exc:
        db.rollback()
        stored_intent = db.get(PaymentIntent, intent_id, with_for_update=True)
        stored_operation = db.get(PaymentOperation, operation_id, with_for_update=True)
        stored_idem = db.get(IdempotencyRecord, idem_id, with_for_update=True)
        if stored_intent:
            stored_intent.status = "AUTHORIZATION_UNKNOWN" if isinstance(exc, PaymentProviderError) and exc.retryable else "AUTHORIZATION_FAILED"
            stored_intent.updated_at = datetime.now(UTC)
        if stored_operation:
            stored_operation.status = "UNKNOWN" if isinstance(exc, PaymentProviderError) and exc.retryable else "FAILED"
            stored_operation.error_code = exc.code if isinstance(exc, PaymentProviderError) else "PAYMENT_AUTHORIZATION_FAILED"
            stored_operation.completed_at = datetime.now(UTC)
        if stored_idem:
            fail(db, stored_idem, {"code": "PAYMENT_AUTHORIZATION_FAILED"})
        db.commit()
        raise _gateway_error(exc, "PAYMENT_AUTHORIZATION_FAILED") from exc

    stored_intent = db.get(PaymentIntent, intent_id, with_for_update=True)
    stored_ref = db.get(PaymentProviderReference, intent_id, with_for_update=True)
    stored_operation = db.get(PaymentOperation, operation_id, with_for_update=True)
    stored_idem = db.get(IdempotencyRecord, idem_id, with_for_update=True)
    if any(value is None for value in (stored_intent, stored_ref, stored_operation, stored_idem)):
        raise HTTPException(500, detail={"code": "PAYMENT_COMMAND_STATE_LOST"})
    stored_intent.external_id = str(external_id)
    stored_intent.status = str(provider_status)
    stored_intent.updated_at = datetime.now(UTC)
    stored_ref.provider_order_id = provider_result.get("provider_order_id") or stored_ref.provider_order_id
    stored_ref.provider_authorization_id = provider_result.get("provider_authorization_id") or str(external_id)
    stored_ref.provider_capture_id = provider_result.get("provider_capture_id")
    stored_ref.provider_customer_id = provider_result.get("provider_customer_id")
    stored_ref.provider_payment_method_id = provider_result.get("provider_payment_method_id")
    stored_ref.raw_status = provider_result.get("raw_status")
    action = provider_result.get("client_action")
    stored_ref.client_action = {"type": action.get("type")} if isinstance(action, dict) else None
    stored_ref.updated_at = datetime.now(UTC)
    stored_operation.status = "SUCCEEDED"
    stored_operation.external_id = str(external_id)
    stored_operation.completed_at = datetime.now(UTC)
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
    result = _serialize(stored_intent, stored_ref)
    if isinstance(action, dict):
        result["client_action"] = action
    complete(db, stored_idem, result)
    db.commit()
    return result


def _staff_intent(db: Session, principal: Principal, payment_intent_id: uuid.UUID) -> tuple[PaymentIntent, Booking, PaymentProviderReference]:
    intent = db.get(PaymentIntent, payment_intent_id)
    if intent is None:
        raise HTTPException(404, detail={"code": "PAYMENT_NOT_FOUND"})
    booking = db.get(Booking, intent.booking_id)
    if booking is None:
        raise HTTPException(409, detail={"code": "PAYMENT_BOOKING_MISSING"})
    require_market(principal, booking.market_code)
    reference = db.get(PaymentProviderReference, intent.id)
    if reference is None:
        raise HTTPException(409, detail={"code": "PAYMENT_PROVIDER_REFERENCE_MISSING"})
    return intent, booking, reference


@router.post("/{payment_intent_id}/capture")
async def capture_payment(
    payment_intent_id: uuid.UUID,
    payload: CaptureRequest,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.FINANCE, Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    intent, booking, reference = _staff_intent(db, principal, payment_intent_id)
    if booking.status not in {BookingStatus.COMPLETED, BookingStatus.SETTLING, BookingStatus.SETTLED}:
        raise HTTPException(409, detail={"code": "SERVICE_COMPLETION_REQUIRED"})
    if intent.status not in {"AUTHORIZED", "REQUIRES_CAPTURE"}:
        raise HTTPException(409, detail={"code": "PAYMENT_NOT_CAPTURABLE"})
    amount = payload.amount_minor or intent.amount_minor
    if amount > intent.amount_minor:
        raise HTTPException(422, detail={"code": "CAPTURE_AMOUNT_EXCEEDS_AUTHORIZATION"})
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="payment.capture",
        key=key,
        payload={"payment_intent_id": str(intent.id), "amount_minor": amount},
    )
    if replay is not None:
        return replay
    operation = PaymentOperation(
        payment_intent_id=intent.id,
        provider_code=intent.provider_code,
        operation_type="CAPTURE",
        idempotency_key=key,
        status="PENDING",
        amount_minor=amount,
        currency=intent.currency,
        created_at=datetime.now(UTC),
    )
    db.add(operation)
    intent.status = "CAPTURE_PENDING"
    intent.updated_at = datetime.now(UTC)
    db.flush()
    operation_id, idem_id = operation.id, idem.id
    external_id = reference.provider_authorization_id or intent.external_id
    db.commit()
    try:
        result = await payment_provider(intent.provider_code).capture(
            external_id=str(external_id),
            amount_minor=amount,
            currency=intent.currency,
            idempotency_key=key,
        )
    except Exception as exc:
        db.rollback()
        stored = db.get(PaymentIntent, intent.id, with_for_update=True)
        op = db.get(PaymentOperation, operation_id, with_for_update=True)
        idem_row = db.get(IdempotencyRecord, idem_id, with_for_update=True)
        if stored:
            stored.status = "CAPTURE_UNKNOWN" if isinstance(exc, PaymentProviderError) and exc.retryable else "CAPTURE_FAILED"
            stored.updated_at = datetime.now(UTC)
        if op:
            op.status = "UNKNOWN" if isinstance(exc, PaymentProviderError) and exc.retryable else "FAILED"
            op.error_code = exc.code if isinstance(exc, PaymentProviderError) else "PAYMENT_CAPTURE_FAILED"
            op.completed_at = datetime.now(UTC)
        if idem_row:
            fail(db, idem_row, {"code": "PAYMENT_CAPTURE_FAILED"})
        db.commit()
        raise _gateway_error(exc, "PAYMENT_CAPTURE_FAILED") from exc
    stored = db.get(PaymentIntent, intent.id, with_for_update=True)
    ref = db.get(PaymentProviderReference, intent.id, with_for_update=True)
    op = db.get(PaymentOperation, operation_id, with_for_update=True)
    idem_row = db.get(IdempotencyRecord, idem_id, with_for_update=True)
    if any(value is None for value in (stored, ref, op, idem_row)):
        raise HTTPException(500, detail={"code": "PAYMENT_COMMAND_STATE_LOST"})
    stored.status = str(result.get("status", "CAPTURE_PENDING"))
    stored.updated_at = datetime.now(UTC)
    ref.provider_capture_id = result.get("provider_capture_id") or ref.provider_capture_id
    ref.raw_status = result.get("raw_status")
    ref.updated_at = datetime.now(UTC)
    op.status = "SUCCEEDED" if stored.status == "CAPTURED" else "PENDING"
    op.external_id = ref.provider_capture_id
    op.completed_at = datetime.now(UTC) if op.status == "SUCCEEDED" else None
    emit(db, aggregate_type="payment_intent", aggregate_id=str(stored.id), event_type="payment.capture_recorded.v1", payload={"payment_intent_id": str(stored.id), "status": stored.status, "amount_minor": amount})
    response = _serialize(stored, ref)
    complete(db, idem_row, response)
    db.commit()
    return response


@router.post("/{payment_intent_id}/void")
async def void_payment(
    payment_intent_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.FINANCE, Role.SUPPORT, Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    intent, _, reference = _staff_intent(db, principal, payment_intent_id)
    if intent.status not in {"AUTHORIZED", "REQUIRES_CAPTURE", "AUTHORIZATION_UNKNOWN"}:
        raise HTTPException(409, detail={"code": "PAYMENT_NOT_VOIDABLE"})
    idem, replay = reserve(db, actor_subject=principal.subject, operation="payment.void", key=key, payload={"payment_intent_id": str(intent.id)})
    if replay is not None:
        return replay
    operation = PaymentOperation(payment_intent_id=intent.id, provider_code=intent.provider_code, operation_type="VOID", idempotency_key=key, status="PENDING", amount_minor=intent.amount_minor, currency=intent.currency, created_at=datetime.now(UTC))
    db.add(operation)
    intent.status = "VOID_PENDING"
    intent.updated_at = datetime.now(UTC)
    db.flush()
    operation_id, idem_id = operation.id, idem.id
    external_id = reference.provider_authorization_id or intent.external_id
    db.commit()
    try:
        result = await payment_provider(intent.provider_code).void(external_id=str(external_id), idempotency_key=key)
    except Exception as exc:
        db.rollback()
        stored = db.get(PaymentIntent, intent.id, with_for_update=True)
        op = db.get(PaymentOperation, operation_id, with_for_update=True)
        idem_row = db.get(IdempotencyRecord, idem_id, with_for_update=True)
        if stored:
            stored.status = "VOID_UNKNOWN" if isinstance(exc, PaymentProviderError) and exc.retryable else "VOID_FAILED"
            stored.updated_at = datetime.now(UTC)
        if op:
            op.status = "UNKNOWN" if isinstance(exc, PaymentProviderError) and exc.retryable else "FAILED"
            op.error_code = exc.code if isinstance(exc, PaymentProviderError) else "PAYMENT_VOID_FAILED"
            op.completed_at = datetime.now(UTC)
        if idem_row:
            fail(db, idem_row, {"code": "PAYMENT_VOID_FAILED"})
        db.commit()
        raise _gateway_error(exc, "PAYMENT_VOID_FAILED") from exc
    stored = db.get(PaymentIntent, intent.id, with_for_update=True)
    ref = db.get(PaymentProviderReference, intent.id, with_for_update=True)
    op = db.get(PaymentOperation, operation_id, with_for_update=True)
    idem_row = db.get(IdempotencyRecord, idem_id, with_for_update=True)
    if any(value is None for value in (stored, ref, op, idem_row)):
        raise HTTPException(500, detail={"code": "PAYMENT_COMMAND_STATE_LOST"})
    stored.status = str(result.get("status", "VOIDED"))
    stored.updated_at = datetime.now(UTC)
    ref.raw_status = result.get("raw_status")
    ref.updated_at = datetime.now(UTC)
    op.status = "SUCCEEDED"
    op.completed_at = datetime.now(UTC)
    response = _serialize(stored, ref)
    complete(db, idem_row, response)
    db.commit()
    return response


@router.post("/{payment_intent_id}/refunds", status_code=201)
async def create_refund(
    payment_intent_id: uuid.UUID,
    payload: RefundRequest,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.FINANCE, Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    intent, booking, reference = _staff_intent(db, principal, payment_intent_id)
    if intent.status not in {"CAPTURED", "PARTIALLY_REFUNDED", "DISPUTED"}:
        raise HTTPException(409, detail={"code": "PAYMENT_NOT_REFUNDABLE"})
    committed = db.scalar(select(func.coalesce(func.sum(PaymentRefund.amount_minor), 0)).where(PaymentRefund.payment_intent_id == intent.id, PaymentRefund.status.in_(["PENDING", "SUCCEEDED"]))) or 0
    if int(committed) + payload.amount_minor > intent.amount_minor:
        raise HTTPException(422, detail={"code": "REFUND_AMOUNT_EXCEEDS_AVAILABLE"})
    idem, replay = reserve(db, actor_subject=principal.subject, operation="payment.refund", key=key, payload={"payment_intent_id": str(intent.id), **payload.model_dump()})
    if replay is not None:
        return replay
    now = datetime.now(UTC)
    refund = PaymentRefund(payment_intent_id=intent.id, booking_id=booking.id, provider_code=intent.provider_code, external_id=None, idempotency_key=key, status="PENDING", amount_minor=payload.amount_minor, currency=intent.currency, reason=payload.reason, requested_by_subject=principal.subject, created_at=now, updated_at=now)
    operation = PaymentOperation(payment_intent_id=intent.id, provider_code=intent.provider_code, operation_type="REFUND", idempotency_key=key, status="PENDING", amount_minor=payload.amount_minor, currency=intent.currency, created_at=now)
    db.add_all([refund, operation])
    db.flush()
    refund_id, operation_id, idem_id = refund.id, operation.id, idem.id
    provider_external_id = reference.provider_capture_id if intent.provider_code == "paypal" else intent.external_id
    if not provider_external_id:
        raise HTTPException(409, detail={"code": "PROVIDER_CAPTURE_REFERENCE_REQUIRED"})
    db.commit()
    try:
        result = await payment_provider(intent.provider_code).refund(external_id=str(provider_external_id), amount_minor=payload.amount_minor, currency=intent.currency, reason=payload.reason, idempotency_key=key)
    except Exception as exc:
        db.rollback()
        stored_refund = db.get(PaymentRefund, refund_id, with_for_update=True)
        op = db.get(PaymentOperation, operation_id, with_for_update=True)
        idem_row = db.get(IdempotencyRecord, idem_id, with_for_update=True)
        if stored_refund:
            stored_refund.status = "UNKNOWN" if isinstance(exc, PaymentProviderError) and exc.retryable else "FAILED"
            stored_refund.error_code = exc.code if isinstance(exc, PaymentProviderError) else "PAYMENT_REFUND_FAILED"
            stored_refund.updated_at = datetime.now(UTC)
        if op:
            op.status = stored_refund.status if stored_refund else "FAILED"
            op.error_code = stored_refund.error_code if stored_refund else "PAYMENT_REFUND_FAILED"
            op.completed_at = datetime.now(UTC)
        if idem_row:
            fail(db, idem_row, {"code": "PAYMENT_REFUND_FAILED"})
        db.commit()
        raise _gateway_error(exc, "PAYMENT_REFUND_FAILED") from exc
    stored_refund = db.get(PaymentRefund, refund_id, with_for_update=True)
    stored_intent = db.get(PaymentIntent, intent.id, with_for_update=True)
    op = db.get(PaymentOperation, operation_id, with_for_update=True)
    idem_row = db.get(IdempotencyRecord, idem_id, with_for_update=True)
    if any(value is None for value in (stored_refund, stored_intent, op, idem_row)):
        raise HTTPException(500, detail={"code": "PAYMENT_COMMAND_STATE_LOST"})
    stored_refund.external_id = result.get("external_id")
    stored_refund.status = str(result.get("status", "PENDING"))
    stored_refund.updated_at = datetime.now(UTC)
    op.external_id = stored_refund.external_id
    op.status = "SUCCEEDED" if stored_refund.status == "SUCCEEDED" else "PENDING"
    op.completed_at = datetime.now(UTC) if op.status == "SUCCEEDED" else None
    total_after = int(committed) + payload.amount_minor
    if stored_refund.status == "SUCCEEDED":
        stored_intent.status = "REFUNDED" if total_after == stored_intent.amount_minor else "PARTIALLY_REFUNDED"
        stored_intent.updated_at = datetime.now(UTC)
    response = {"id": str(stored_refund.id), "status": stored_refund.status, "amount_minor": stored_refund.amount_minor, "currency": stored_refund.currency}
    complete(db, idem_row, response)
    db.commit()
    return response


@router.get("/{payment_intent_id}/refunds")
def list_refunds(
    payment_intent_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    intent = db.get(PaymentIntent, payment_intent_id)
    if intent is None:
        raise HTTPException(404, detail={"code": "PAYMENT_NOT_FOUND"})
    if not principal.roles.intersection({Role.FINANCE, Role.SUPPORT, Role.PLATFORM_ADMIN}):
        customer = customer_for_principal(db, principal)
        if intent.customer_id != customer.id:
            raise HTTPException(404, detail={"code": "PAYMENT_NOT_FOUND"})
    rows = list(db.scalars(select(PaymentRefund).where(PaymentRefund.payment_intent_id == intent.id).order_by(PaymentRefund.created_at.desc())))
    return {"items": [{"id": str(row.id), "status": row.status, "amount_minor": row.amount_minor, "currency": row.currency, "reason": row.reason, "created_at": row.created_at.isoformat()} for row in rows]}


@router.get("/{payment_intent_id}")
def get_payment_intent(
    payment_intent_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    intent = db.get(PaymentIntent, payment_intent_id)
    if intent is None:
        raise HTTPException(404, detail={"code": "PAYMENT_NOT_FOUND"})
    if not principal.roles.intersection({Role.FINANCE, Role.SUPPORT, Role.PLATFORM_ADMIN}):
        customer = customer_for_principal(db, principal)
        if intent.customer_id != customer.id:
            raise HTTPException(404, detail={"code": "PAYMENT_NOT_FOUND"})
    reference = db.get(PaymentProviderReference, intent.id)
    return _serialize(intent, reference)
