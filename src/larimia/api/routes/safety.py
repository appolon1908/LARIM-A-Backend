import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from larimia.shared.auth import Principal, Role, get_principal, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()


class IncidentCreate(BaseModel):
    booking_id: str | None = None
    severity: str = Field(pattern=r"^S[1-4]$")
    category: str
    description: str


class IncidentAction(BaseModel):
    action: str
    notes: str


@router.post("/incidents", status_code=201)
def create_incident(
    payload: IncidentCreate,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
):
    return {
        "incident_id": str(uuid.uuid4()),
        "status": "OPEN",
        "reporter": getattr(principal, "subject", "anonymous"),
        **payload.model_dump(),
    }


@router.get("/ops/incidents")
def list_incidents(_: Principal = Depends(require_roles(Role.SAFETY, Role.SUPPORT))):
    return {"incidents": []}


@router.post("/ops/incidents/{incident_id}/actions")
def action(
    incident_id: str,
    payload: IncidentAction,
    _: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.SAFETY)),
):
    return {
        "incident_id": incident_id,
        "action": payload.action,
        "notes": payload.notes,
        "actor": principal.subject,
    }
