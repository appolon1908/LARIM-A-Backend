from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()

class LedgerAdjustment(BaseModel):
    debit_account: str
    credit_account: str
    amount_minor: int = Field(gt=0)
    currency: str
    reason: str

@router.get("/reconciliation-breaks")
def reconciliation(_: Principal = Depends(require_roles(Role.FINANCE))):
    return {"breaks": []}

@router.post("/ledger-adjustments", status_code=201)
def adjustment(payload: LedgerAdjustment, _: str = Depends(require_idempotency_key), principal: Principal = Depends(require_roles(Role.FINANCE))):
    return {"status": "PENDING_SECOND_APPROVAL", "actor": principal.subject, **payload.model_dump()}

@router.get("/payout-batches")
def payout_batches(_: Principal = Depends(require_roles(Role.FINANCE))):
    return {"batches": []}
