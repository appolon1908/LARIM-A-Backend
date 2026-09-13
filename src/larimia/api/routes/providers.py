import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()


class ProviderApplication(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str
    market_code: str
    requested_services: list[str]


class AvailabilityRule(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_local: str
    end_local: str
    timezone: str


class ProviderStatusUpdate(BaseModel):
    status: str
    reason: str


@router.post("/applications", status_code=201)
def apply(payload: ProviderApplication, _: str = Depends(require_idempotency_key)):
    return {
        "application_id": str(uuid.uuid4()),
        "status": "PENDING_IDENTITY",
        **payload.model_dump(),
    }


@router.get("/me")
def me(principal: Principal = Depends(require_roles(Role.PROVIDER))):
    return {"subject": principal.subject, "status": "ACTIVE", "rating": None, "completed_jobs": 0}


@router.put("/me/availability")
def set_availability(
    rules: list[AvailabilityRule], principal: Principal = Depends(require_roles(Role.PROVIDER))
):
    return {
        "provider": principal.subject,
        "rules": [r.model_dump() for r in rules],
        "updated": True,
    }


@router.get("/me/earnings")
def earnings(principal: Principal = Depends(require_roles(Role.PROVIDER))):
    return {
        "provider": principal.subject,
        "currency": "DOP",
        "available_minor": 0,
        "pending_minor": 0,
    }


@router.get("/me/payouts")
def payouts(principal: Principal = Depends(require_roles(Role.PROVIDER))):
    return {"provider": principal.subject, "items": []}


@router.post("/{provider_id}/status")
def update_status(
    provider_id: str,
    payload: ProviderStatusUpdate,
    principal: Principal = Depends(require_roles(Role.COMPLIANCE, Role.QUALITY)),
):
    return {
        "provider_id": provider_id,
        "status": payload.status,
        "reason": payload.reason,
        "actor": principal.subject,
    }
