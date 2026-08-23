import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.idempotency import require_idempotency_key

router = APIRouter()

class MembershipSubscribe(BaseModel):
    plan_code: str
    payment_method_token: str

@router.get("/plans")
def plans():
    return {"plans": [
        {"code": "LARIMIA_PLUS", "name": "LARIMÍA Plus", "monthly_credits": 1},
        {"code": "LARIMIA_PREMIER", "name": "LARIMÍA Premier", "monthly_credits": 2},
    ]}

@router.post("/subscriptions", status_code=201)
def subscribe(payload: MembershipSubscribe, _: str = Depends(require_idempotency_key)):
    return {"subscription_id": str(uuid.uuid4()), "plan_code": payload.plan_code, "status": "ACTIVE"}
