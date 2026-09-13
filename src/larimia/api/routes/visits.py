from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()


class Location(BaseModel):
    lat: float
    lng: float


class Arrival(BaseModel):
    location: Location


class StartService(BaseModel):
    pin: str = Field(min_length=4, max_length=8)


class CompleteService(BaseModel):
    notes: str | None = None


@router.post("/{booking_id}/en-route")
def en_route(
    booking_id: str,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
):
    return {"booking_id": booking_id, "status": "EN_ROUTE", "provider": principal.subject}


@router.post("/{booking_id}/arrive")
def arrive(
    booking_id: str,
    payload: Arrival,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
):
    return {
        "booking_id": booking_id,
        "status": "ARRIVED",
        "geofence": "PENDING_VERIFICATION",
        "provider": principal.subject,
        "location": payload.location.model_dump(),
    }


@router.post("/{booking_id}/start")
def start(
    booking_id: str,
    payload: StartService,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
):
    return {
        "booking_id": booking_id,
        "status": "IN_SERVICE",
        "pin_verified": True,
        "provider": principal.subject,
    }


@router.post("/{booking_id}/complete")
def complete(
    booking_id: str,
    payload: CompleteService,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.PROVIDER)),
):
    return {
        "booking_id": booking_id,
        "status": "COMPLETED",
        "provider": principal.subject,
        "notes": payload.notes,
    }
