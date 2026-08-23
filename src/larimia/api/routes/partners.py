from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.idempotency import require_idempotency_key


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.PARTNERS))],
)


class PartnerBooking(BaseModel):
    guest_name: str = Field(min_length=1, max_length=160)
    property_name: str = Field(min_length=1, max_length=160)
    room_or_villa: str | None = Field(default=None, max_length=80)
    service_code: str = Field(min_length=1, max_length=80)
    scheduled_start: str
    market_code: str = Field(min_length=1, max_length=16)


def _not_implemented() -> None:
    # The old route fabricated confirmed bookings and UUIDs. Keeping a visible
    # fail-closed endpoint is safer than pretending the partner workflow exists.
    raise HTTPException(
        status_code=503,
        detail={"code": "PARTNER_WORKFLOW_NOT_READY"},
    )


@router.post("/bookings", status_code=201)
def create_partner_booking(
    _: PartnerBooking,
    __: str = Depends(require_idempotency_key),
    ___: Principal = Depends(require_roles(Role.PARTNER_BOOKER)),
):
    _not_implemented()


@router.get("/bookings")
def list_partner_bookings(
    _: Principal = Depends(require_roles(Role.PARTNER_BOOKER)),
):
    _not_implemented()


@router.get("/invoices")
def invoices(
    _: Principal = Depends(require_roles(Role.PARTNER_BOOKER, Role.FINANCE)),
):
    _not_implemented()
