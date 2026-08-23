import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()

class CaseCreate(BaseModel):
    booking_id: str | None = None
    category: str
    subject: str
    message: str

class CaseAction(BaseModel):
    status: str
    note: str

@router.post("/cases", status_code=201)
def create_case(payload: CaseCreate, _: str = Depends(require_idempotency_key)):
    return {"case_id": str(uuid.uuid4()), "status": "OPEN", **payload.model_dump()}

@router.get("/ops/cases")
def list_cases(_: Principal = Depends(require_roles(Role.SUPPORT))):
    return {"cases": []}

@router.post("/ops/cases/{case_id}/actions")
def act(case_id: str, payload: CaseAction, principal: Principal = Depends(require_roles(Role.SUPPORT))):
    return {"case_id": case_id, "status": payload.status, "note": payload.note, "actor": principal.subject}
