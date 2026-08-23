import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()

class AuthorizePayment(BaseModel):
    booking_id: str
    payment_method_token: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

class RefundRequest(BaseModel):
    charge_id: str
    amount_minor: int = Field(gt=0)
    reason: str

@router.post("/authorize", status_code=201)
def authorize(payload: AuthorizePayment, _: str = Depends(require_idempotency_key)):
    return {"payment_intent_id": str(uuid.uuid4()), "booking_id": payload.booking_id, "status": "AUTHORIZED", "amount_minor": payload.amount_minor, "currency": payload.currency}

@router.post("/{payment_intent_id}/capture")
def capture(payment_intent_id: str, _: str = Depends(require_idempotency_key), principal: Principal = Depends(require_roles(Role.FINANCE, Role.PLATFORM_ADMIN))):
    return {"payment_intent_id": payment_intent_id, "status": "CAPTURED", "actor": principal.subject}

@router.post("/refunds", status_code=201)
def refund(payload: RefundRequest, _: str = Depends(require_idempotency_key), principal: Principal = Depends(require_roles(Role.FINANCE, Role.SUPPORT))):
    return {"refund_id": str(uuid.uuid4()), "charge_id": payload.charge_id, "amount_minor": payload.amount_minor, "status": "PENDING", "actor": principal.subject}
