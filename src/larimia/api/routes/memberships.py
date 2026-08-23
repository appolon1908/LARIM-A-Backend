from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.marketplace.models import Membership
from larimia.shared.auth import Principal, get_principal
from larimia.shared.authorization import customer_for_principal
from larimia.shared.capabilities import Capability, require_capability
from larimia.shared.db import get_db
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter(
    dependencies=[Depends(require_capability(Capability.MEMBERSHIPS))],
)

PLANS = {
    "LARIMIA_PLUS": {"monthly_credits": 1},
    "LARIMIA_PREMIER": {"monthly_credits": 2},
}


class Subscribe(BaseModel):
    plan_code: str = Field(min_length=1, max_length=80)


@router.get("/plans")
def plans():
    return {
        "items": [
            {"code": code, **details}
            for code, details in sorted(PLANS.items())
        ]
    }


@router.post("/subscriptions", status_code=201)
def subscribe(
    payload: Subscribe,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    if payload.plan_code not in PLANS:
        raise HTTPException(422, detail={"code": "MEMBERSHIP_PLAN_INVALID"})

    customer = customer_for_principal(db, principal)
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="membership.subscribe",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay

    membership = db.scalar(
        select(Membership)
        .where(
            Membership.customer_id == customer.id,
            Membership.status == "ACTIVE",
        )
        .with_for_update()
    )
    if membership is None:
        membership = Membership(
            customer_id=customer.id,
            plan_code=payload.plan_code,
            status="ACTIVE",
            started_at=datetime.now(UTC),
        )
        db.add(membership)
        db.flush()
    elif membership.plan_code != payload.plan_code:
        raise HTTPException(409, detail={"code": "MEMBERSHIP_ALREADY_ACTIVE"})

    result = {
        "id": str(membership.id),
        "plan_code": membership.plan_code,
        "status": membership.status,
    }
    complete(db, idem, result)
    db.commit()
    return result
