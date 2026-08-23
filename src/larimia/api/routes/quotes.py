import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()

BASE_PRICES = {
    "MASSAGE_60": 450000,
    "HAIRCUT": 250000,
    "MAKEUP": 400000,
    "TRAINING_60": 300000,
}

class QuoteRequest(BaseModel):
    market_code: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    service_code: str
    address_id: str
    scheduled_start: datetime
    add_ons: list[str] = []

@router.post("", status_code=201)
def create_quote(payload: QuoteRequest, _: str = Depends(require_idempotency_key)):
    base = BASE_PRICES.get(payload.service_code, 300000)
    travel = 50000
    subtotal = base + travel
    tax = 0
    total = subtotal + tax
    return {
        "id": str(uuid.uuid4()),
        "market_code": payload.market_code,
        "currency": payload.currency,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "lines": [
            {"type": "SERVICE", "amount_minor": base},
            {"type": "TRAVEL", "amount_minor": travel},
        ],
        "subtotal_minor": subtotal,
        "tax_minor": tax,
        "total_minor": total,
        "pricing_policy_version": 1,
    }
