import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()


class AcceptOffer(BaseModel):
    booking_version: int


class ReassignRequest(BaseModel):
    provider_id: str | None = None
    reason: str


@router.get("/offers")
def provider_offers(_: Principal = Depends(require_roles(Role.PROVIDER))):
    return {"offers": []}


@router.post("/offers/{offer_id}/accept")
def accept_offer(
    offer_id: str,
    payload: AcceptOffer,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
):
    return {
        "offer_id": offer_id,
        "assignment_id": str(uuid.uuid4()),
        "provider": principal.subject,
        "status": "ASSIGNED",
        "booking_version": payload.booking_version + 1,
    }


@router.post("/offers/{offer_id}/decline")
def decline_offer(
    offer_id: str,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
):
    return {"offer_id": offer_id, "provider": principal.subject, "status": "DECLINED"}


@router.get("/ops/board")
def board(_: Principal = Depends(require_roles(Role.DISPATCHER, Role.SUPPORT))):
    return {"unassigned": [], "late_risk": [], "active": [], "recovery": []}


@router.post("/ops/bookings/{booking_id}/reassign")
def reassign(
    booking_id: str,
    payload: ReassignRequest,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.DISPATCHER)),
):
    return {
        "booking_id": booking_id,
        "status": "MATCHING",
        "requested_provider": payload.provider_id,
        "reason": payload.reason,
        "actor": principal.subject,
    }
