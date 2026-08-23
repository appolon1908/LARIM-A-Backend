import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from larimia.marketplace.services import QuoteService
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal, require_market
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.QUOTES))],
)


class QuoteRequest(BaseModel):
    market_code: str
    service_code: str
    address_id: uuid.UUID
    scheduled_start: datetime


@router.post("", status_code=201)
def create_quote(
    payload: QuoteRequest,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    customer = customer_for_principal(db, principal)
    require_market(principal, payload.market_code)

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="quote.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay

    quote = QuoteService.create(
        db,
        customer=customer,
        **payload.model_dump(),
    )
    result = {
        "id": str(quote.id),
        "status": quote.status,
        "market_code": quote.market_code,
        "currency": quote.currency,
        "subtotal_minor": quote.subtotal_minor,
        "tax_minor": quote.tax_minor,
        "total_minor": quote.total_minor,
        "scheduled_start": quote.scheduled_start.isoformat(),
        "scheduled_end": quote.scheduled_end.isoformat(),
        "expires_at": quote.expires_at.isoformat(),
        "price_policy_version": quote.price_policy_version,
    }
    complete(db, idem, result)
    db.commit()
    return result
