import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()


class PartnerBooking(BaseModel):
    guest_name: str
    property_name: str
    room_or_villa: str | None = None
    service_code: str
    scheduled_start: str
    market_code: str


@router.post("/bookings", status_code=201)
def create_partner_booking(
    payload: PartnerBooking,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PARTNER_BOOKER)),
):
    return {
        "booking_id": str(uuid.uuid4()),
        "status": "CONFIRMED",
        "partner_actor": principal.subject,
        **payload.model_dump(),
    }


@router.get("/bookings")
def list_partner_bookings(_: Principal = Depends(require_roles(Role.PARTNER_BOOKER))):
    return {"bookings": []}


@router.get("/invoices")
def invoices(_: Principal = Depends(require_roles(Role.PARTNER_BOOKER, Role.FINANCE))):
    return {"invoices": []}
